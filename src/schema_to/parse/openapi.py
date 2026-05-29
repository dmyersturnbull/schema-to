"""OpenAPI 3.1 document parser.

Converts a `RawDoc` (JSON or YAML bytes) into an `OpenApiDocument` CST.
Like the JSON Schema parser, this is **non-resolving**: `$ref` values are stored
as raw strings for a later `RefResolver` stage.

Errors are accumulated across all object builders so a single parse call yields
the complete diagnostic set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from schema_to import OpenApiRawDoc
from schema_to.cst.base import SourceRef
from schema_to.cst.openapi import (
    Components,
    Contact,
    ExternalDocumentation,
    Header,
    Info,
    License,
    MediaTypeObject,
    OpenApiDocument,
    Operation,
    Parameter,
    ParameterLocation,
    PathItem,
    RequestBody,
    Response,
    Server,
    ServerVariable,
    Tag,
)
from schema_to.errors import ParseError, SchemaValidationError, SourceLocation, TranspilationError
from schema_to.parse._utils import (
    as_json_dict,
    as_json_list,
    bool_field,
    decode_raw_doc,
    extract,
    ptr,
    str_field,
    str_or,
)
from schema_to.parse.json_schema import JsonSchemaParser
from schema_to.pipeline import DocParser
from schema_to.result import Err, Ok, Result

if TYPE_CHECKING:
    from schema_to.core import JsonValue
    from schema_to.cst.json_schema import JsonSchema

__all__ = ["OpenApiParser"]

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
loc = SourceLocation


class OpenApiParser(DocParser[OpenApiRawDoc, OpenApiDocument]):
    """Parses JSON or YAML bytes into an `OpenApiDocument` CST.

    Accepts documents whose root object contains an `"openapi"` field starting
    with `"3."`.  JSON Schema embedded in `schema` fields is parsed via the
    same logic used by `JsonSchemaParser`.
    """

    def __init__(self) -> None:
        self.js = JsonSchemaParser()

    def accepts(self, doc: OpenApiRawDoc) -> bool:
        return isinstance(doc, OpenApiRawDoc)

    def apply(self, input: OpenApiRawDoc) -> Result[OpenApiDocument]:
        try:
            data = decode_raw_doc(input)
        except TranspilationError as exc:
            return Err((exc,))
        if not isinstance(data, dict):
            return Err.of(
                ParseError(
                    "OpenAPI document must be a JSON object.", location=loc(input.source_id, "")
                )
            )
        return self._build_document(
            cast("dict[str, JsonValue]", data),  # narrowed by isinstance above; ty can't see it
            source_id=input.source_id,
            display_name=input.display_name,
        )

    # -- Document root -------------------------------------------------------

    def _build_document(
        self,
        data: dict[str, JsonValue],
        *,
        source_id: str,
        display_name: str | None,  # noqa: ARG002  # OpenApiDocument derives its name from info.title, not the source; kept for interface symmetry with other parsers
    ) -> Result[OpenApiDocument]:
        errors: list[TranspilationError] = []

        openapi_ver = data.get("openapi")
        if not isinstance(openapi_ver, str) or not openapi_ver.startswith("3."):
            errors.append(
                SchemaValidationError(
                    f"openapi must be a '3.x' version string, got {openapi_ver!r}.",
                    location=loc(source_id, "/openapi"),
                )
            )

        info: Info | None = None
        if not isinstance(data.get("info"), dict):
            errors.append(ParseError("info must be an object.", location=loc(source_id, "/info")))
        else:
            info = extract(
                self._build_info(
                    cast("dict[str, JsonValue]", data["info"]), source_id=source_id, pointer="/info"
                ),
                errors,
            )

        if errors:
            return Err(tuple(errors))

        paths = self._build_path_map(data, "paths", source_id=source_id, errors=errors)
        webhooks = self._build_path_map(data, "webhooks", source_id=source_id, errors=errors)

        components = extract(
            self._build_components(
                cast("dict[str, JsonValue]", data.get("components") or {}),
                source_id=source_id,
                pointer="/components",
            ),
            errors,
        )

        servers = self._build_server_list(data)
        tags = self._build_tags(data)

        security: list[dict] = []
        raw_security = data.get("security")
        if isinstance(raw_security, list):
            security.extend(
                {k: list(cast("list[JsonValue]", v)) if isinstance(v, list) else v for k, v in item.items()}
                for item in as_json_list(raw_security)
                if isinstance(item, dict)
            )

        external_docs: ExternalDocumentation | None = None
        if isinstance(data.get("externalDocs"), dict):
            external_docs = extract(
                self._build_external_docs(
                    cast("dict[str, JsonValue]", data["externalDocs"]),
                    source_id=source_id,
                    pointer="/externalDocs",
                ),
                errors,
            )

        extensions = {k: v for k, v in data.items() if k.startswith("x-")}

        if errors:
            return Err(tuple(errors))

        return Ok(
            OpenApiDocument(
                openapi=cast(
                    "str", openapi_ver
                ),  # validated str above; errors guard prevents reaching here with None
                info=cast("Info", info),  # validated non-None above via extract()
                paths=paths,
                components=components or Components(),
                servers=servers,
                security=security,
                tags=tags,
                external_docs=external_docs,
                webhooks=webhooks,
                extensions=extensions,
                source_id=source_id,
                source_ref=SourceRef(source_id, ""),
            )
        )

    # -- Paths / webhooks helper ---------------------------------------------

    def _build_path_map(
        self,
        data: dict[str, JsonValue],
        key: str,
        *,
        source_id: str,
        errors: list[TranspilationError],
    ) -> dict[str, PathItem]:
        result: dict[str, PathItem] = {}
        raw = data.get(key)
        if not isinstance(raw, dict):
            return result
        for name, pi_data in as_json_dict(raw).items():
            pi_ptr = ptr("", key, name)
            if isinstance(pi_data, dict):
                pi = extract(
                    self._build_path_item(
                        cast("dict[str, JsonValue]", pi_data), source_id=source_id, pointer=pi_ptr
                    ),
                    errors,
                )
                if pi is not None:
                    result[name] = pi
            else:
                errors.append(
                    ParseError(
                        f"Path item for {name!r} must be an object.",
                        location=loc(source_id, pi_ptr),
                    )
                )
        return result

    # -- Info ----------------------------------------------------------------

    def _build_info(
        self, data: dict[str, JsonValue], *, source_id: str, pointer: str
    ) -> Result[Info]:
        errors: list[TranspilationError] = []
        title = data.get("title")
        version = data.get("version")
        if not isinstance(title, str):
            errors.append(
                SchemaValidationError(
                    "info.title must be a string.", location=loc(source_id, ptr(pointer, "title"))
                )
            )
        if not isinstance(version, str):
            errors.append(
                SchemaValidationError(
                    "info.version must be a string.",
                    location=loc(source_id, ptr(pointer, "version")),
                )
            )
        if errors:
            return Err(tuple(errors))

        contact: Contact | None = None
        if isinstance(data.get("contact"), dict):
            c = cast("dict[str, JsonValue]", data["contact"])
            contact = Contact(
                name=str_field(c, "name"),
                url=str_field(c, "url"),
                email=str_field(c, "email"),
                extensions={k: v for k, v in c.items() if k.startswith("x-")},
            )

        license_: License | None = None
        if isinstance(data.get("license"), dict):
            lic = cast("dict[str, JsonValue]", data["license"])
            license_ = License(
                name=str_or(lic, "name"),
                identifier=str_field(lic, "identifier"),
                url=str_field(lic, "url"),
                extensions={k: v for k, v in lic.items() if k.startswith("x-")},
            )

        return Ok(
            Info(
                title=cast(
                    "str", title
                ),  # validated str above; errors guard prevents reaching here with None
                version=cast("str", version),  # same
                summary=str_field(data, "summary"),
                description=str_field(data, "description"),
                terms_of_service=str_field(data, "termsOfService"),
                contact=contact,
                license_=license_,
                extensions={k: v for k, v in data.items() if k.startswith("x-")},
            )
        )

    # -- Servers / tags / external docs -------------------------------------

    def _build_server_list(self, data: dict[str, JsonValue]) -> list[Server]:
        raw = data.get("servers")
        if not isinstance(raw, list):
            return []
        return [
            self._extract_server(cast("dict[str, JsonValue]", s))
            for s in raw
            if isinstance(s, dict)
        ]

    def _extract_server(self, s: dict[str, JsonValue]) -> Server:
        variables: dict[str, ServerVariable] = {}
        if isinstance(s.get("variables"), dict):
            for vname, vdata in cast("dict[str, JsonValue]", s["variables"]).items():
                if isinstance(vdata, dict):
                    vd = cast("dict[str, JsonValue]", vdata)
                    raw_enum = vd.get("enum")
                    variables[vname] = ServerVariable(
                        default=str_or(vd, "default"),
                        enum=[x for x in as_json_list(raw_enum) if isinstance(x, str)]
                        if isinstance(raw_enum, list)
                        else None,
                        description=str_field(vd, "description"),
                        extensions={k: v for k, v in vd.items() if k.startswith("x-")},
                    )
        return Server(
            url=str_or(s, "url"),
            description=str_field(s, "description"),
            variables=variables,
            extensions={k: v for k, v in s.items() if k.startswith("x-")},
        )

    def _build_tags(self, data: dict[str, JsonValue]) -> list[Tag]:
        tags: list[Tag] = []
        raw = data.get("tags")
        if not isinstance(raw, list):
            return tags
        for t in as_json_list(raw):
            if not isinstance(t, dict):
                continue
            td = cast("dict[str, JsonValue]", t)
            ext_docs: ExternalDocumentation | None = None
            if isinstance(td.get("externalDocs"), dict):
                ed = cast("dict[str, JsonValue]", td["externalDocs"])
                ext_docs = ExternalDocumentation(
                    url=str_or(ed, "url"),
                    description=str_field(ed, "description"),
                    extensions={k: v for k, v in ed.items() if k.startswith("x-")},
                )
            tags.append(
                Tag(
                    name=str_or(td, "name"),
                    description=str_field(td, "description"),
                    external_docs=ext_docs,
                    extensions={k: v for k, v in td.items() if k.startswith("x-")},
                )
            )
        return tags

    def _build_external_docs(
        self, data: dict[str, JsonValue], *, source_id: str, pointer: str
    ) -> Result[ExternalDocumentation]:
        url = data.get("url")
        if not isinstance(url, str):
            return Err(
                (
                    SchemaValidationError(
                        "externalDocs.url must be a string.",
                        location=loc(source_id, ptr(pointer, "url")),
                    ),
                )
            )
        return Ok(
            ExternalDocumentation(
                url=url,
                description=str_field(data, "description"),
                extensions={k: v for k, v in data.items() if k.startswith("x-")},
            )
        )

    # -- Paths / operations --------------------------------------------------

    def _build_path_item(
        self, data: dict[str, JsonValue], *, source_id: str, pointer: str
    ) -> Result[PathItem]:
        errors: list[TranspilationError] = []
        method_ops: dict[str, Operation] = {}
        for method_str in _HTTP_METHODS:
            if method_str in data and isinstance(data[method_str], dict):
                op = extract(
                    self._build_operation(
                        cast("dict[str, JsonValue]", data[method_str]),
                        source_id=source_id,
                        pointer=ptr(pointer, method_str),
                    ),
                    errors,
                )
                if op is not None:
                    method_ops[method_str] = op

        parameters = self._build_parameter_list(
            data, source_id=source_id, pointer=pointer, errors=errors
        )
        servers = self._build_server_list(data)

        if errors:
            return Err(tuple(errors))

        return Ok(
            PathItem(
                summary=str_field(data, "summary"),
                description=str_field(data, "description"),
                get=method_ops.get("get"),
                put=method_ops.get("put"),
                post=method_ops.get("post"),
                delete=method_ops.get("delete"),
                options=method_ops.get("options"),
                head=method_ops.get("head"),
                patch=method_ops.get("patch"),
                trace=method_ops.get("trace"),
                parameters=parameters,
                servers=servers,
                extensions={k: v for k, v in data.items() if k.startswith("x-")},
                source_ref=SourceRef(source_id, pointer),
            )
        )

    def _build_operation(
        self, data: dict[str, JsonValue], *, source_id: str, pointer: str
    ) -> Result[Operation]:
        errors: list[TranspilationError] = []

        responses_raw = data.get("responses", {})
        responses: dict[str, Response] = {}
        if isinstance(responses_raw, dict):
            for status, resp_data in as_json_dict(responses_raw).items():
                if isinstance(resp_data, dict):
                    rptr = ptr(pointer, "responses", status)
                    resp = extract(
                        self._build_response(
                            cast("dict[str, JsonValue]", resp_data),
                            source_id=source_id,
                            pointer=rptr,
                        ),
                        errors,
                    )
                    if resp is not None:
                        responses[status] = resp
        else:
            errors.append(
                SchemaValidationError(
                    "responses must be an object.",
                    location=loc(source_id, ptr(pointer, "responses")),
                )
            )

        parameters = self._build_parameter_list(
            data, source_id=source_id, pointer=pointer, errors=errors
        )

        request_body: RequestBody | None = None
        if isinstance(data.get("requestBody"), dict):
            request_body = extract(
                self._build_request_body(
                    cast("dict[str, JsonValue]", data["requestBody"]),
                    source_id=source_id,
                    pointer=ptr(pointer, "requestBody"),
                ),
                errors,
            )

        external_docs: ExternalDocumentation | None = None
        if isinstance(data.get("externalDocs"), dict):
            external_docs = extract(
                self._build_external_docs(
                    cast("dict[str, JsonValue]", data["externalDocs"]),
                    source_id=source_id,
                    pointer=ptr(pointer, "externalDocs"),
                ),
                errors,
            )

        servers = self._build_server_list(data)

        security: list[dict] | None = None
        raw_sec = data.get("security")
        if isinstance(raw_sec, list):
            security = [dict(req) for req in as_json_list(raw_sec) if isinstance(req, dict)]

        tags: list[str] = []
        raw_tags = data.get("tags")
        if isinstance(raw_tags, list):
            tags = [t for t in as_json_list(raw_tags) if isinstance(t, str)]

        if errors:
            return Err(tuple(errors))

        return Ok(
            Operation(
                responses=responses,
                tags=tags,
                summary=str_field(data, "summary"),
                description=str_field(data, "description"),
                external_docs=external_docs,
                operation_id=str_field(data, "operationId"),
                parameters=parameters,
                request_body=request_body,
                deprecated=bool(data.get("deprecated")),
                security=security,
                servers=servers,
                extensions={k: v for k, v in data.items() if k.startswith("x-")},
                source_ref=SourceRef(source_id, pointer),
            )
        )

    # -- Parameters / request body / responses / media types ----------------

    def _build_parameter_list(
        self,
        data: dict[str, JsonValue],
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> list[Parameter]:
        parameters: list[Parameter] = []
        raw = data.get("parameters")
        if not isinstance(raw, list):
            return parameters
        for i, p_data in enumerate(as_json_list(raw)):
            if not isinstance(p_data, dict):
                continue
            pptr = ptr(pointer, "parameters", i)
            p = extract(
                self._build_parameter(
                    cast("dict[str, JsonValue]", p_data), source_id=source_id, pointer=pptr
                ),
                errors,
            )
            if p is not None:
                parameters.append(p)
        return parameters

    def _build_parameter(
        self, data: dict[str, JsonValue], *, source_id: str, pointer: str
    ) -> Result[Parameter]:
        name = data.get("name")
        in_ = data.get("in")

        # Validate required string fields with early returns so the type checker
        # can narrow them without casts below.
        if not isinstance(name, str):
            return Err(
                (
                    SchemaValidationError(
                        "parameter.name must be a string.",
                        location=loc(source_id, ptr(pointer, "name")),
                    ),
                )
            )
        try:
            in_loc = ParameterLocation(in_) if isinstance(in_, str) else None
        except ValueError:
            in_loc = None
        if in_loc is None:
            return Err(
                (
                    SchemaValidationError(
                        f"parameter.in must be one of query/header/path/cookie, got {in_!r}.",
                        location=loc(source_id, ptr(pointer, "in")),
                    ),
                )
            )

        errors: list[TranspilationError] = []
        schema = None
        schema_data = data.get("schema")
        if isinstance(schema_data, dict):
            schema = extract(
                self.js._build_schema(  # noqa: SLF001  # _build_schema is intentionally shared between parsers
                    schema_data, source_id=source_id, pointer=ptr(pointer, "schema")
                ),
                errors,
            )

        if errors:
            return Err(tuple(errors))

        return Ok(
            Parameter(
                name=name,
                in_=in_loc,
                schema=schema,
                description=str_field(data, "description"),
                required=bool(data.get("required")),
                deprecated=bool(data.get("deprecated")),
                allow_empty_value=bool(data.get("allowEmptyValue")),
                style=str_field(data, "style"),
                explode=bool_field(data, "explode"),
                extensions={k: v for k, v in data.items() if k.startswith("x-")},
                source_ref=SourceRef(source_id, pointer),
            )
        )

    def _build_request_body(
        self, data: dict[str, JsonValue], *, source_id: str, pointer: str
    ) -> Result[RequestBody]:
        errors: list[TranspilationError] = []
        content_raw = data.get("content", {})
        content: dict[str, MediaTypeObject] = {}
        if isinstance(content_raw, dict):
            for media_type_str, mt_data in as_json_dict(content_raw).items():
                if isinstance(mt_data, dict):
                    mt = extract(
                        self._build_media_type_obj(
                            cast("dict[str, JsonValue]", mt_data),
                            source_id=source_id,
                            pointer=ptr(pointer, "content", media_type_str),
                        ),
                        errors,
                    )
                    if mt is not None:
                        content[media_type_str] = mt
        if errors:
            return Err(tuple(errors))
        return Ok(
            RequestBody(
                content=content,
                description=str_field(data, "description"),
                required=bool(data.get("required")),
                extensions={k: v for k, v in data.items() if k.startswith("x-")},
                source_ref=SourceRef(source_id, pointer),
            )
        )

    def _build_response(  # noqa: C901
        self, data: dict[str, JsonValue], *, source_id: str, pointer: str
    ) -> Result[Response]:
        errors: list[TranspilationError] = []
        description = data.get("description", "")
        if not isinstance(description, str):
            description = ""

        headers: dict[str, Header] = {}
        if isinstance(data.get("headers"), dict):
            for hname, hdata in cast("dict[str, JsonValue]", data["headers"]).items():
                if isinstance(hdata, dict):
                    h = extract(
                        self._build_header(
                            cast("dict[str, JsonValue]", hdata),
                            source_id=source_id,
                            pointer=ptr(pointer, "headers", hname),
                        ),
                        errors,
                    )
                    if h is not None:
                        headers[hname] = h

        content: dict[str, MediaTypeObject] = {}
        if isinstance(data.get("content"), dict):
            for media_type_str, mt_data in cast("dict[str, JsonValue]", data["content"]).items():
                if isinstance(mt_data, dict):
                    mt = extract(
                        self._build_media_type_obj(
                            cast("dict[str, JsonValue]", mt_data),
                            source_id=source_id,
                            pointer=ptr(pointer, "content", media_type_str),
                        ),
                        errors,
                    )
                    if mt is not None:
                        content[media_type_str] = mt

        if errors:
            return Err(tuple(errors))
        return Ok(
            Response(
                description=description,
                headers=headers,
                content=content,
                extensions={k: v for k, v in data.items() if k.startswith("x-")},
                source_ref=SourceRef(source_id, pointer),
            )
        )

    def _build_header(
        self, data: dict[str, JsonValue], *, source_id: str, pointer: str
    ) -> Result[Header]:
        errors: list[TranspilationError] = []
        schema = None
        schema_data = data.get("schema")
        if isinstance(schema_data, dict):
            schema = extract(
                self.js._build_schema(  # noqa: SLF001  # _build_schema is intentionally shared between parsers
                    schema_data, source_id=source_id, pointer=ptr(pointer, "schema")
                ),
                errors,
            )
        if errors:
            return Err(tuple(errors))
        return Ok(
            Header(
                schema=schema,
                description=str_field(data, "description"),
                required=bool(data.get("required")),
                deprecated=bool(data.get("deprecated")),
                extensions={k: v for k, v in data.items() if k.startswith("x-")},
            )
        )

    def _build_media_type_obj(
        self, data: dict[str, JsonValue], *, source_id: str, pointer: str
    ) -> Result[MediaTypeObject]:
        errors: list[TranspilationError] = []
        schema = None
        schema_data = data.get("schema")
        if isinstance(schema_data, dict):
            schema = extract(
                self.js._build_schema(  # noqa: SLF001  # _build_schema is intentionally shared between parsers
                    schema_data, source_id=source_id, pointer=ptr(pointer, "schema")
                ),
                errors,
            )
        if errors:
            return Err(tuple(errors))
        examples_raw = data.get("examples")
        return Ok(
            MediaTypeObject(
                schema=schema,
                example=data.get("example"),
                examples=dict(as_json_dict(examples_raw)) if isinstance(examples_raw, dict) else {},
                extensions={k: v for k, v in data.items() if k.startswith("x-")},
            )
        )

    # -- Components ----------------------------------------------------------

    def _build_components(  # noqa: C901, PLR0912
        self, data: dict[str, JsonValue], *, source_id: str, pointer: str
    ) -> Result[Components]:
        if not isinstance(data, dict):
            return Ok(Components())

        errors: list[TranspilationError] = []

        schemas: dict[str, JsonSchema] = {}
        if isinstance(data.get("schemas"), dict):
            for name, s_data in cast("dict[str, JsonValue]", data["schemas"]).items():
                s = extract(
                    self.js._build_schema(  # noqa: SLF001  # _build_schema is intentionally shared between parsers
                        s_data, source_id=source_id, pointer=ptr(pointer, "schemas", name)
                    ),
                    errors,
                )
                if s is not None:
                    schemas[name] = s

        parameters: dict[str, Parameter] = {}
        if isinstance(data.get("parameters"), dict):
            for name, p_data in cast("dict[str, JsonValue]", data["parameters"]).items():
                if isinstance(p_data, dict):
                    p = extract(
                        self._build_parameter(
                            cast("dict[str, JsonValue]", p_data),
                            source_id=source_id,
                            pointer=ptr(pointer, "parameters", name),
                        ),
                        errors,
                    )
                    if p is not None:
                        parameters[name] = p

        responses: dict[str, Response] = {}
        if isinstance(data.get("responses"), dict):
            for name, r_data in cast("dict[str, JsonValue]", data["responses"]).items():
                if isinstance(r_data, dict):
                    r = extract(
                        self._build_response(
                            cast("dict[str, JsonValue]", r_data),
                            source_id=source_id,
                            pointer=ptr(pointer, "responses", name),
                        ),
                        errors,
                    )
                    if r is not None:
                        responses[name] = r

        request_bodies: dict[str, RequestBody] = {}
        if isinstance(data.get("requestBodies"), dict):
            for name, rb_data in cast("dict[str, JsonValue]", data["requestBodies"]).items():
                if isinstance(rb_data, dict):
                    rb = extract(
                        self._build_request_body(
                            cast("dict[str, JsonValue]", rb_data),
                            source_id=source_id,
                            pointer=ptr(pointer, "requestBodies", name),
                        ),
                        errors,
                    )
                    if rb is not None:
                        request_bodies[name] = rb

        headers: dict[str, Header] = {}
        if isinstance(data.get("headers"), dict):
            for name, h_data in cast("dict[str, JsonValue]", data["headers"]).items():
                if isinstance(h_data, dict):
                    h = extract(
                        self._build_header(
                            cast("dict[str, JsonValue]", h_data),
                            source_id=source_id,
                            pointer=ptr(pointer, "headers", name),
                        ),
                        errors,
                    )
                    if h is not None:
                        headers[name] = h

        if errors:
            return Err(tuple(errors))

        return Ok(
            Components(
                schemas=schemas,
                responses=responses,
                parameters=parameters,
                request_bodies=request_bodies,
                headers=headers,
                extensions={k: v for k, v in data.items() if k.startswith("x-")},
            )
        )
