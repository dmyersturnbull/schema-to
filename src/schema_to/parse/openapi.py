"""OpenAPI 3.1 document parser.

Converts a `RawDocument` (JSON or YAML bytes) into an `OpenApiDocument` CST.
Like the JSON Schema parser, this is **non-resolving**: `$ref` values are stored
as raw strings for a later `RefResolver` stage.

Errors are accumulated across all object builders so a single parse call yields
the complete diagnostic set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from schema_to.parse._utils import extract, loc, ptr

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
from schema_to.errors import ParseError, SchemaValidationError, TranspilationError
from schema_to.parse.json_schema import JsonSchemaParser
from schema_to.pipeline import DocumentParser
from schema_to.result import Err, Ok, Result

if TYPE_CHECKING:
    from schema_to.io.source import RawDocument

__all__ = ["OpenApiParser"]

_SUPPORTED_ESSENCES = frozenset({"application/json", "application/yaml", "text/yaml"})

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


class OpenApiParser(DocumentParser[OpenApiDocument]):
    """Parses JSON or YAML bytes into an `OpenApiDocument` CST.

    Accepts documents whose root object contains an `"openapi"` field starting
    with `"3."`.  JSON Schema embedded in `schema` fields is parsed via the
    same logic used by `JsonSchemaParser`.
    """

    def __init__(self) -> None:
        self.js = JsonSchemaParser()

    def supports(self, document: RawDocument) -> bool:
        return document.media_type.essence in _SUPPORTED_ESSENCES

    def apply(self, input: RawDocument) -> Result[OpenApiDocument]:
        try:
            data = self.js._decode(input)
        except TranspilationError as exc:
            return Err((exc,))
        if not isinstance(data, dict):
            return Err(
                (
                    ParseError(
                        "OpenAPI document must be a JSON object.", location=loc(input.source_id, "")
                    ),
                )
            )
        return self._build_document(data, source_id=input.source_id, display_name=input.display_name)

    # -- Document root -------------------------------------------------------

    def _build_document(
        self, data: dict[str, Any], *, source_id: str, display_name: str | None
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
                self._build_info(data["info"], source_id=source_id, pointer="/info"), errors
            )

        if errors:
            return Err(tuple(errors))

        paths: dict[str, PathItem] = {}
        if isinstance(data.get("paths"), dict):
            for path, pi_data in data["paths"].items():
                pi_ptr = ptr("", "paths", path)
                if isinstance(pi_data, dict):
                    pi = extract(
                        self._build_path_item(pi_data, source_id=source_id, pointer=pi_ptr), errors
                    )
                    if pi is not None:
                        paths[path] = pi
                else:
                    errors.append(
                        ParseError(
                            f"Path item for {path!r} must be an object.",
                            location=loc(source_id, pi_ptr),
                        )
                    )

        webhooks: dict[str, PathItem] = {}
        if isinstance(data.get("webhooks"), dict):
            for name, pi_data in data["webhooks"].items():
                wh_ptr = ptr("", "webhooks", name)
                if isinstance(pi_data, dict):
                    pi = extract(
                        self._build_path_item(pi_data, source_id=source_id, pointer=wh_ptr), errors
                    )
                    if pi is not None:
                        webhooks[name] = pi

        components = extract(
            self._build_components(
                data.get("components", {}), source_id=source_id, pointer="/components"
            ),
            errors,
        )

        servers = self._build_server_list(data, source_id=source_id, pointer="", errors=errors)
        tags = self._build_tags(data, source_id=source_id, pointer="", errors=errors)

        security: list[dict] = []
        if isinstance(data.get("security"), list):
            for item in data["security"]:
                if isinstance(item, dict):
                    security.append(
                        {k: list(v) if isinstance(v, list) else v for k, v in item.items()}
                    )

        external_docs: ExternalDocumentation | None = None
        if isinstance(data.get("externalDocs"), dict):
            external_docs = extract(
                self._build_external_docs(
                    data["externalDocs"], source_id=source_id, pointer="/externalDocs"
                ),
                errors,
            )

        extensions = {k: v for k, v in data.items() if k.startswith("x-")}

        if errors:
            return Err(tuple(errors))

        return Ok(
            OpenApiDocument(
                openapi=openapi_ver,  # type: ignore[arg-type]
                info=info,  # type: ignore[arg-type]
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

    # -- Info ----------------------------------------------------------------

    def _build_info(self, data: dict[str, Any], *, source_id: str, pointer: str) -> Result[Info]:
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
            c = data["contact"]
            contact = Contact(
                name=c.get("name") if isinstance(c.get("name"), str) else None,
                url=c.get("url") if isinstance(c.get("url"), str) else None,
                email=c.get("email") if isinstance(c.get("email"), str) else None,
                extensions={k: v for k, v in c.items() if k.startswith("x-")},
            )

        license_: License | None = None
        if isinstance(data.get("license"), dict):
            lic = data["license"]
            lic_name = lic.get("name", "")
            license_ = License(
                name=lic_name if isinstance(lic_name, str) else "",
                identifier=lic.get("identifier")
                if isinstance(lic.get("identifier"), str)
                else None,
                url=lic.get("url") if isinstance(lic.get("url"), str) else None,
                extensions={k: v for k, v in lic.items() if k.startswith("x-")},
            )

        return Ok(
            Info(
                title=title,  # type: ignore[arg-type]
                version=version,  # type: ignore[arg-type]
                summary=data.get("summary") if isinstance(data.get("summary"), str) else None,
                description=data.get("description")
                if isinstance(data.get("description"), str)
                else None,
                terms_of_service=data.get("termsOfService")
                if isinstance(data.get("termsOfService"), str)
                else None,
                contact=contact,
                license_=license_,
                extensions={k: v for k, v in data.items() if k.startswith("x-")},
            )
        )

    # -- Servers / tags / external docs -------------------------------------

    def _build_server_list(
        self,
        data: dict[str, Any],
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> list[Server]:
        servers: list[Server] = []
        raw = data.get("servers")
        if not isinstance(raw, list):
            return servers
        for i, s in enumerate(raw):
            if not isinstance(s, dict):
                continue
            url = s.get("url", "")
            variables: dict[str, ServerVariable] = {}
            if isinstance(s.get("variables"), dict):
                for vname, vdata in s["variables"].items():
                    if isinstance(vdata, dict):
                        variables[vname] = ServerVariable(
                            default=vdata.get("default", "")
                            if isinstance(vdata.get("default"), str)
                            else "",
                            enum=list(vdata["enum"])
                            if isinstance(vdata.get("enum"), list)
                            else None,
                            description=vdata.get("description")
                            if isinstance(vdata.get("description"), str)
                            else None,
                            extensions={k: v for k, v in vdata.items() if k.startswith("x-")},
                        )
            servers.append(
                Server(
                    url=url,
                    description=s.get("description")
                    if isinstance(s.get("description"), str)
                    else None,
                    variables=variables,
                    extensions={k: v for k, v in s.items() if k.startswith("x-")},
                )
            )
        return servers

    def _build_tags(
        self,
        data: dict[str, Any],
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> list[Tag]:
        tags: list[Tag] = []
        raw = data.get("tags")
        if not isinstance(raw, list):
            return tags
        for t in raw:
            if not isinstance(t, dict):
                continue
            name = t.get("name", "")
            ext_docs: ExternalDocumentation | None = None
            if isinstance(t.get("externalDocs"), dict):
                ed = t["externalDocs"]
                ext_docs = ExternalDocumentation(
                    url=ed.get("url", ""),
                    description=ed.get("description")
                    if isinstance(ed.get("description"), str)
                    else None,
                    extensions={k: v for k, v in ed.items() if k.startswith("x-")},
                )
            tags.append(
                Tag(
                    name=name,
                    description=t.get("description")
                    if isinstance(t.get("description"), str)
                    else None,
                    external_docs=ext_docs,
                    extensions={k: v for k, v in t.items() if k.startswith("x-")},
                )
            )
        return tags

    def _build_external_docs(
        self, data: dict[str, Any], *, source_id: str, pointer: str
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
                description=data.get("description")
                if isinstance(data.get("description"), str)
                else None,
                extensions={k: v for k, v in data.items() if k.startswith("x-")},
            )
        )

    # -- Paths / operations --------------------------------------------------

    def _build_path_item(
        self, data: dict[str, Any], *, source_id: str, pointer: str
    ) -> Result[PathItem]:
        errors: list[TranspilationError] = []
        method_ops: dict[str, Operation] = {}
        for method_str in _HTTP_METHODS:
            if method_str in data and isinstance(data[method_str], dict):
                op = extract(
                    self._build_operation(
                        data[method_str], source_id=source_id, pointer=ptr(pointer, method_str)
                    ),
                    errors,
                )
                if op is not None:
                    method_ops[method_str] = op

        parameters = self._build_parameter_list(
            data, source_id=source_id, pointer=pointer, errors=errors
        )
        servers = self._build_server_list(data, source_id=source_id, pointer=pointer, errors=errors)

        if errors:
            return Err(tuple(errors))

        return Ok(
            PathItem(
                summary=data.get("summary") if isinstance(data.get("summary"), str) else None,
                description=data.get("description")
                if isinstance(data.get("description"), str)
                else None,
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
        self, data: dict[str, Any], *, source_id: str, pointer: str
    ) -> Result[Operation]:
        errors: list[TranspilationError] = []

        responses_raw = data.get("responses", {})
        responses: dict[str, Response] = {}
        if isinstance(responses_raw, dict):
            for status, resp_data in responses_raw.items():
                if isinstance(resp_data, dict):
                    rptr = ptr(pointer, "responses", status)
                    resp = extract(
                        self._build_response(resp_data, source_id=source_id, pointer=rptr), errors
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
                    data["requestBody"], source_id=source_id, pointer=ptr(pointer, "requestBody")
                ),
                errors,
            )

        external_docs: ExternalDocumentation | None = None
        if isinstance(data.get("externalDocs"), dict):
            external_docs = extract(
                self._build_external_docs(
                    data["externalDocs"], source_id=source_id, pointer=ptr(pointer, "externalDocs")
                ),
                errors,
            )

        servers = self._build_server_list(data, source_id=source_id, pointer=pointer, errors=errors)

        security: list[dict] | None = None
        if isinstance(data.get("security"), list):
            security = [dict(req) for req in data["security"] if isinstance(req, dict)]

        tags: list[str] = []
        if isinstance(data.get("tags"), list):
            tags = [t for t in data["tags"] if isinstance(t, str)]

        if errors:
            return Err(tuple(errors))

        return Ok(
            Operation(
                responses=responses,
                tags=tags,
                summary=data.get("summary") if isinstance(data.get("summary"), str) else None,
                description=data.get("description")
                if isinstance(data.get("description"), str)
                else None,
                external_docs=external_docs,
                operation_id=data.get("operationId")
                if isinstance(data.get("operationId"), str)
                else None,
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
        data: dict[str, Any],
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> list[Parameter]:
        parameters: list[Parameter] = []
        raw = data.get("parameters")
        if not isinstance(raw, list):
            return parameters
        for i, p_data in enumerate(raw):
            if not isinstance(p_data, dict):
                continue
            pptr = ptr(pointer, "parameters", i)
            p = extract(self._build_parameter(p_data, source_id=source_id, pointer=pptr), errors)
            if p is not None:
                parameters.append(p)
        return parameters

    def _build_parameter(
        self, data: dict[str, Any], *, source_id: str, pointer: str
    ) -> Result[Parameter]:
        errors: list[TranspilationError] = []
        name = data.get("name")
        in_ = data.get("in")
        if not isinstance(name, str):
            errors.append(
                SchemaValidationError(
                    "parameter.name must be a string.",
                    location=loc(source_id, ptr(pointer, "name")),
                )
            )
        try:
            in_loc = ParameterLocation(in_) if isinstance(in_, str) else None
        except ValueError:
            in_loc = None
        if in_loc is None:
            errors.append(
                SchemaValidationError(
                    f"parameter.in must be one of query/header/path/cookie, got {in_!r}.",
                    location=loc(source_id, ptr(pointer, "in")),
                )
            )
        if errors:
            return Err(tuple(errors))

        schema = None
        if isinstance(data.get("schema"), dict):
            schema = extract(
                self.js._build_schema(
                    data["schema"], source_id=source_id, pointer=ptr(pointer, "schema")
                ),
                errors,
            )

        return Ok(
            Parameter(
                name=name,  # type: ignore[arg-type]
                in_=in_loc,  # type: ignore[arg-type]
                schema=schema,
                description=data.get("description")
                if isinstance(data.get("description"), str)
                else None,
                required=bool(data.get("required")),
                deprecated=bool(data.get("deprecated")),
                allow_empty_value=bool(data.get("allowEmptyValue")),
                style=data.get("style") if isinstance(data.get("style"), str) else None,
                explode=data.get("explode") if isinstance(data.get("explode"), bool) else None,
                extensions={k: v for k, v in data.items() if k.startswith("x-")},
                source_ref=SourceRef(source_id, pointer),
            )
        )

    def _build_request_body(
        self, data: dict[str, Any], *, source_id: str, pointer: str
    ) -> Result[RequestBody]:
        errors: list[TranspilationError] = []
        content_raw = data.get("content", {})
        content: dict[str, Any] = {}
        if isinstance(content_raw, dict):
            for media_type_str, mt_data in content_raw.items():
                if isinstance(mt_data, dict):
                    mt = extract(
                        self._build_media_type_obj(
                            mt_data,
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
                description=data.get("description")
                if isinstance(data.get("description"), str)
                else None,
                required=bool(data.get("required")),
                extensions={k: v for k, v in data.items() if k.startswith("x-")},
                source_ref=SourceRef(source_id, pointer),
            )
        )

    def _build_response(
        self, data: dict[str, Any], *, source_id: str, pointer: str
    ) -> Result[Response]:
        errors: list[TranspilationError] = []
        description = data.get("description", "")
        if not isinstance(description, str):
            description = ""

        headers: dict[str, Any] = {}
        if isinstance(data.get("headers"), dict):
            for hname, hdata in data["headers"].items():
                if isinstance(hdata, dict):
                    h = extract(
                        self._build_header(
                            hdata, source_id=source_id, pointer=ptr(pointer, "headers", hname)
                        ),
                        errors,
                    )
                    if h is not None:
                        headers[hname] = h

        content: dict[str, Any] = {}
        if isinstance(data.get("content"), dict):
            for media_type_str, mt_data in data["content"].items():
                if isinstance(mt_data, dict):
                    mt = extract(
                        self._build_media_type_obj(
                            mt_data,
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
        self, data: dict[str, Any], *, source_id: str, pointer: str
    ) -> Result[Header]:
        errors: list[TranspilationError] = []
        schema = None
        if isinstance(data.get("schema"), dict):
            schema = extract(
                self.js._build_schema(
                    data["schema"], source_id=source_id, pointer=ptr(pointer, "schema")
                ),
                errors,
            )
        if errors:
            return Err(tuple(errors))
        return Ok(
            Header(
                schema=schema,
                description=data.get("description")
                if isinstance(data.get("description"), str)
                else None,
                required=bool(data.get("required")),
                deprecated=bool(data.get("deprecated")),
                extensions={k: v for k, v in data.items() if k.startswith("x-")},
            )
        )

    def _build_media_type_obj(
        self, data: dict[str, Any], *, source_id: str, pointer: str
    ) -> Result[MediaTypeObject]:
        errors: list[TranspilationError] = []
        schema = None
        if isinstance(data.get("schema"), dict):
            schema = extract(
                self.js._build_schema(
                    data["schema"], source_id=source_id, pointer=ptr(pointer, "schema")
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
                examples=dict(examples_raw) if isinstance(examples_raw, dict) else {},
                extensions={k: v for k, v in data.items() if k.startswith("x-")},
            )
        )

    # -- Components ----------------------------------------------------------

    def _build_components(
        self, data: dict[str, Any], *, source_id: str, pointer: str
    ) -> Result[Components]:
        if not isinstance(data, dict):
            return Ok(Components())

        errors: list[TranspilationError] = []

        schemas: dict[str, Any] = {}
        if isinstance(data.get("schemas"), dict):
            for name, s_data in data["schemas"].items():
                s = extract(
                    self.js._build_schema(
                        s_data, source_id=source_id, pointer=ptr(pointer, "schemas", name)
                    ),
                    errors,
                )
                if s is not None:
                    schemas[name] = s

        parameters: dict[str, Any] = {}
        if isinstance(data.get("parameters"), dict):
            for name, p_data in data["parameters"].items():
                if isinstance(p_data, dict):
                    p = extract(
                        self._build_parameter(
                            p_data, source_id=source_id, pointer=ptr(pointer, "parameters", name)
                        ),
                        errors,
                    )
                    if p is not None:
                        parameters[name] = p

        responses: dict[str, Any] = {}
        if isinstance(data.get("responses"), dict):
            for name, r_data in data["responses"].items():
                if isinstance(r_data, dict):
                    r = extract(
                        self._build_response(
                            r_data, source_id=source_id, pointer=ptr(pointer, "responses", name)
                        ),
                        errors,
                    )
                    if r is not None:
                        responses[name] = r

        request_bodies: dict[str, Any] = {}
        if isinstance(data.get("requestBodies"), dict):
            for name, rb_data in data["requestBodies"].items():
                if isinstance(rb_data, dict):
                    rb = extract(
                        self._build_request_body(
                            rb_data,
                            source_id=source_id,
                            pointer=ptr(pointer, "requestBodies", name),
                        ),
                        errors,
                    )
                    if rb is not None:
                        request_bodies[name] = rb

        headers: dict[str, Any] = {}
        if isinstance(data.get("headers"), dict):
            for name, h_data in data["headers"].items():
                if isinstance(h_data, dict):
                    h = extract(
                        self._build_header(
                            h_data, source_id=source_id, pointer=ptr(pointer, "headers", name)
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
