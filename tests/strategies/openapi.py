"""Strategies for OpenAPI 3.1 documents.

[openapi_doc_st][] generates any document [schema_to.cst.openapi.OpenApiDocument][] can hold:
every fixed field, every kind of component, references in the positions that accept one, and `x-*` extension keys.

As in [tests.strategies.json_schema][],
a node carries a bounded subset of its optional fields,
rather than an independent coin flip per field,
so that documents stay small enough for Hypothesis to explore while every field remains reachable.

Deliberately narrowed, because widening would generate documents that are no longer
about the parser:

- A `$ref` is well-formed but does not necessarily resolve.
  Parsing and serializing carry it verbatim; `tests/resolve/` builds the resolvable kind by hand.
- 3.2-only fields are not generated.
  The version is pinned at 3.1.0, and `tests/parse/test_openapi_versioning_unit.py` covers what each version admits.
"""

from collections.abc import Mapping

from hypothesis import strategies as st
from tests.strategies._primitives import (
    identifier,
    json_leaf,
    media_type_str,
    nonempty_text,
    safe_text,
)
from tests.strategies.json_schema import json_schema_st

from schema_to.core import JsonObject, JsonValue

_PARAM_LOCATIONS = ["query", "header", "path", "cookie"]
_METHODS = ["get", "put", "post", "delete", "options", "head", "patch", "trace"]
_STYLES = ["matrix", "label", "form", "simple", "spaceDelimited", "pipeDelimited", "deepObject"]

# OpenAPI 3.1 allows exact codes (100-599), wildcard patterns (1xx-5xx), and "default".
_STATUS_CODES = (
    [str(c) for c in range(100, 600, 100)]
    + ["200", "201", "400", "404", "500"]
    + [f"{d}xx" for d in range(1, 6)]
    + ["default"]
)

_url = st.builds(lambda name: f"https://example.com/{name}", identifier)
_extension_key = st.builds(lambda name: f"x-{name}", identifier)


@st.composite
def _with_optional(
    draw: st.DrawFn, d: JsonObject, choices: Mapping[str, st.SearchStrategy[JsonValue]], most: int
) -> None:
    """Add one to `most` of `choices` to `d`, plus an `x-*` extension key now and then.

    At least one, so that a node's optional fields are actually exercised:
    with an independent coin flip per field the rarer ones almost never appear,
    and a document of nothing but required fields says little about the parser.
    """
    for name in draw(
        st.lists(st.sampled_from(sorted(choices)), min_size=1, max_size=most, unique=True)
    ):
        d[name] = draw(choices[name])
    if draw(st.booleans()):
        d[draw(_extension_key)] = draw(json_leaf)


_SHARED = "Shared"
"""The one component name a generated Reference Object ever points at.

A document is generated with references only when it also carries the components
they name, so every `$ref` resolves.  A target that resolves references — FastAPI —
must succeed on any document this strategy produces, and a dangling `$ref` would
make it fail for a reason that says nothing about the target.
"""


def _or_reference(
    concrete: st.SearchStrategy[JsonObject], target: str, *, refs: bool
) -> st.SearchStrategy[JsonObject]:
    """A concrete node, or — when the document carries shared components — a Reference to one."""
    if not refs:
        return concrete
    return st.one_of(concrete, st.just({"$ref": f"#/components/{target}/{_SHARED}"}))


@st.composite
def _external_docs_st(draw: st.DrawFn) -> JsonObject:
    d: JsonObject = {"url": draw(_url)}
    draw(_with_optional(d, {"description": safe_text}, 1))
    return d


@st.composite
def _server_st(draw: st.DrawFn) -> JsonObject:
    d: JsonObject = {"url": draw(_url)}
    variables: st.SearchStrategy[JsonValue] = st.builds(
        lambda name, default: {name: {"default": default}}, identifier, identifier
    )
    draw(_with_optional(d, {"description": safe_text, "variables": variables}, 2))
    return d


@st.composite
def _examples_st(draw: st.DrawFn) -> JsonObject:
    """An Example Object: a value, or an external one, never both."""
    d: JsonObject = {}
    if draw(st.booleans()):
        d["value"] = draw(json_leaf)
    else:
        d["externalValue"] = draw(_url)
    draw(_with_optional(d, {"summary": safe_text, "description": safe_text}, 2))
    return d


@st.composite
def _media_type_object_st(draw: st.DrawFn, *, refs: bool = False) -> JsonObject:
    d: JsonObject = {}
    named_examples: st.SearchStrategy[JsonValue] = st.builds(
        lambda name, ex: {name: ex},
        identifier,
        _or_reference(_examples_st(), "examples", refs=refs),
    )
    encoding: st.SearchStrategy[JsonValue] = st.builds(
        lambda name, ct: {name: {"contentType": ct}}, identifier, media_type_str
    )
    draw(
        _with_optional(
            d,
            {
                "schema": json_schema_st(),
                "example": json_leaf,
                "examples": named_examples,
                "encoding": encoding,
            },
            3,
        )
    )
    return d


def _content_st(*, refs: bool = False) -> st.SearchStrategy[JsonValue]:
    return st.builds(lambda mt, body: {mt: body}, media_type_str, _media_type_object_st(refs=refs))


@st.composite
def _header_st(draw: st.DrawFn) -> JsonObject:
    d: JsonObject = {}
    draw(
        _with_optional(
            d,
            {
                "description": safe_text,
                "required": st.booleans(),
                "deprecated": st.booleans(),
                "style": st.just("simple"),
                "explode": st.booleans(),
                "schema": json_schema_st(),
                "example": json_leaf,
            },
            3,
        )
    )
    return d


@st.composite
def _parameter_st(draw: st.DrawFn, *, refs: bool = False) -> JsonObject:
    location = draw(st.sampled_from(_PARAM_LOCATIONS))
    d: JsonObject = {"name": draw(identifier), "in": location}
    if location == "path":
        # A path parameter is required by definition, so the parser expects to see it said.
        d["required"] = True
    draw(
        _with_optional(
            d,
            {
                "description": safe_text,
                "deprecated": st.booleans(),
                "allowEmptyValue": st.booleans(),
                "style": st.sampled_from(_STYLES),
                "explode": st.booleans(),
                "allowReserved": st.booleans(),
                "schema": json_schema_st(),
                "example": json_leaf,
                "content": _content_st(refs=refs),
            },
            3,
        )
    )
    return d


@st.composite
def _request_body_st(draw: st.DrawFn, *, refs: bool = False) -> JsonObject:
    d: JsonObject = {"content": draw(_content_st(refs=refs))}
    draw(_with_optional(d, {"description": safe_text, "required": st.booleans()}, 2))
    return d


@st.composite
def _link_st(draw: st.DrawFn) -> JsonObject:
    d: JsonObject = {}
    if draw(st.booleans()):
        d["operationId"] = draw(identifier)
    else:
        d["operationRef"] = draw(_url)
    parameters: st.SearchStrategy[JsonValue] = st.builds(
        lambda name, value: {name: value}, identifier, json_leaf
    )
    draw(
        _with_optional(
            d,
            {
                "description": safe_text,
                "parameters": parameters,
                "requestBody": json_leaf,
                "server": _server_st(),
            },
            3,
        )
    )
    return d


@st.composite
def _response_st(draw: st.DrawFn, *, refs: bool = False) -> JsonObject:
    d: JsonObject = {"description": draw(safe_text)}
    named_headers: st.SearchStrategy[JsonValue] = st.builds(
        lambda name, h: {name: h}, identifier, _or_reference(_header_st(), "headers", refs=refs)
    )
    named_links: st.SearchStrategy[JsonValue] = st.builds(
        lambda name, link: {name: link}, identifier, _or_reference(_link_st(), "links", refs=refs)
    )
    draw(
        _with_optional(
            d,
            {"content": _content_st(refs=refs), "headers": named_headers, "links": named_links},
            2,
        )
    )
    return d


def _security_requirement_st() -> st.SearchStrategy[JsonValue]:
    return st.builds(
        lambda name, scopes: {name: scopes},
        identifier,
        st.lists(identifier, max_size=2, unique=True),
    )


@st.composite
def _operation_st(
    draw: st.DrawFn, *, allow_callbacks: bool = True, refs: bool = False
) -> JsonObject:
    responses: JsonObject = {
        draw(st.sampled_from(_STATUS_CODES)): draw(
            _or_reference(_response_st(refs=refs), "responses", refs=refs)
        )
    }
    d: JsonObject = {"responses": responses}
    choices: dict[str, st.SearchStrategy[JsonValue]] = {
        "summary": safe_text,
        "description": safe_text,
        "operationId": identifier,
        "deprecated": st.booleans(),
        "tags": st.lists(identifier, min_size=1, max_size=3, unique=True),
        "externalDocs": _external_docs_st(),
        "parameters": st.lists(
            _or_reference(_parameter_st(refs=refs), "parameters", refs=refs), min_size=1, max_size=2
        ),
        "requestBody": _or_reference(_request_body_st(refs=refs), "requestBodies", refs=refs),
        "security": st.lists(_security_requirement_st(), max_size=2),
        "servers": st.lists(_server_st(), min_size=1, max_size=2),
    }
    if allow_callbacks:
        # A callback holds path items holding operations; one level is enough to parse.
        choices["callbacks"] = st.builds(
            lambda name, expr, item: {name: {expr: item}},
            identifier,
            st.just("{$request.body#/url}"),
            _path_item_st(allow_callbacks=False, refs=refs),
        )
    draw(_with_optional(d, choices, 4))
    return d


@st.composite
def _path_item_st(
    draw: st.DrawFn, *, allow_callbacks: bool = True, refs: bool = False
) -> JsonObject:
    d: JsonObject = {}
    for method in draw(st.lists(st.sampled_from(_METHODS), min_size=1, max_size=2, unique=True)):
        d[method] = draw(_operation_st(allow_callbacks=allow_callbacks, refs=refs))
    draw(
        _with_optional(
            d,
            {
                "summary": safe_text,
                "description": safe_text,
                "parameters": st.lists(
                    _or_reference(_parameter_st(refs=refs), "parameters", refs=refs),
                    min_size=1,
                    max_size=2,
                ),
                "servers": st.lists(_server_st(), min_size=1, max_size=2),
            },
            2,
        )
    )
    return d


@st.composite
def _oauth_flow_st(draw: st.DrawFn, flow: str) -> JsonObject:
    """An OAuth Flow Object, whose required URLs depend on which flow it is."""
    d: JsonObject = {"scopes": {draw(identifier): draw(safe_text)}}
    if flow in {"implicit", "authorizationCode"}:
        d["authorizationUrl"] = draw(_url)
    if flow in {"password", "clientCredentials", "authorizationCode"}:
        d["tokenUrl"] = draw(_url)
    if draw(st.booleans()):
        d["refreshUrl"] = draw(_url)
    return d


@st.composite
def _security_scheme_st(draw: st.DrawFn) -> JsonObject:
    """A Security Scheme Object, whose required fields depend on its `type`."""
    kind = draw(st.sampled_from(["apiKey", "http", "mutualTLS", "oauth2", "openIdConnect"]))
    d: JsonObject = {"type": kind}
    match kind:
        case "apiKey":
            d["name"] = draw(identifier)
            d["in"] = draw(st.sampled_from(["query", "header", "cookie"]))
        case "http":
            scheme = draw(st.sampled_from(["basic", "bearer", "digest"]))
            d["scheme"] = scheme
            if scheme == "bearer":
                d["bearerFormat"] = draw(identifier)
        case "oauth2":
            # A scheme may declare several flows, and the rarer ones only get
            # exercised if one scheme can carry more than a single flow.
            chosen = draw(
                st.lists(
                    st.sampled_from(
                        ["implicit", "password", "clientCredentials", "authorizationCode"]
                    ),
                    min_size=2,
                    max_size=4,
                    unique=True,
                )
            )
            d["flows"] = {flow: draw(_oauth_flow_st(flow)) for flow in chosen}
        case "openIdConnect":
            d["openIdConnectUrl"] = draw(_url)
        case _:
            pass
    draw(_with_optional(d, {"description": safe_text}, 1))
    return d


@st.composite
def _tag_st(draw: st.DrawFn, name: str) -> JsonObject:
    d: JsonObject = {"name": name}
    draw(_with_optional(d, {"description": safe_text, "externalDocs": _external_docs_st()}, 2))
    return d


@st.composite
def _tags_st(draw: st.DrawFn) -> JsonValue:
    """Tags, whose names a document may not repeat.

    The names are drawn first and the tags built around them,
    rather than filtering afterwards on a key that is already inside the value.
    """
    names = draw(st.lists(identifier, min_size=1, max_size=2, unique=True))
    return [draw(_tag_st(name)) for name in names]


@st.composite
def _info_st(draw: st.DrawFn) -> JsonObject:
    d: JsonObject = {"title": draw(nonempty_text), "version": draw(nonempty_text)}
    contact: st.SearchStrategy[JsonValue] = st.builds(
        lambda name, url, email: {"name": name, "url": url, "email": email},
        identifier,
        _url,
        st.builds(lambda name: f"{name}@example.com", identifier),
    )
    licence: st.SearchStrategy[JsonValue] = st.builds(
        lambda name, identifier_: {"name": name, "identifier": identifier_},
        identifier,
        st.sampled_from(["MIT", "Apache-2.0", "BSD-3-Clause"]),
    )
    draw(
        _with_optional(
            d,
            {
                "summary": safe_text,
                "description": safe_text,
                "termsOfService": _url,
                "contact": contact,
                "license": licence,
            },
            3,
        )
    )
    return d


def _named(entries: st.SearchStrategy[JsonObject]) -> st.SearchStrategy[JsonValue]:
    return st.dictionaries(identifier, entries, max_size=2)


@st.composite
def _object_schema_st(draw: st.DrawFn) -> JsonObject:
    """A JSON Schema in object form, which is what a named component schema must be."""
    schema = draw(json_schema_st())
    assert isinstance(schema, dict), "json_schema_st returns an object at depth 0"
    return schema


@st.composite
def _components_st(draw: st.DrawFn, *, refs: bool = False) -> JsonObject:
    """A Components Object.

    When `refs` is set it also carries one entry named `_SHARED` of every referenceable
    kind, so that every Reference Object elsewhere in the document has a target.
    """
    d: JsonObject = {}
    draw(
        _with_optional(
            d,
            {
                "schemas": _named(_object_schema_st()),
                "responses": _named(_response_st()),
                "parameters": _named(_parameter_st()),
                "examples": _named(_examples_st()),
                "requestBodies": _named(_request_body_st()),
                "headers": _named(_header_st()),
                "securitySchemes": st.dictionaries(
                    identifier, _security_scheme_st(), min_size=1, max_size=2
                ),
                "links": st.dictionaries(identifier, _link_st(), min_size=1, max_size=2),
                "pathItems": _named(_path_item_st()),
            },
            4,
        )
    )
    if refs:
        shared: dict[str, st.SearchStrategy[JsonObject]] = {
            "responses": _response_st(),
            "parameters": _parameter_st(),
            "examples": _examples_st(),
            "requestBodies": _request_body_st(),
            "headers": _header_st(),
            "links": _link_st(),
        }
        for target, entry in shared.items():
            section = d.setdefault(target, {})
            assert isinstance(section, dict)
            section[_SHARED] = draw(entry)
    return d


@st.composite
def openapi_doc_st(draw: st.DrawFn) -> JsonObject:
    """Generate a valid OpenAPI 3.1 document dict."""
    d: JsonObject = {"openapi": "3.1.0", "info": draw(_info_st())}
    # References are generated only alongside the components that back them,
    # so that a target which resolves them succeeds on any document from here.
    refs = draw(st.booleans())
    paths: st.SearchStrategy[JsonValue] = st.dictionaries(
        st.builds(lambda name: f"/{name}", identifier), _path_item_st(refs=refs), max_size=3
    )
    choices: dict[str, st.SearchStrategy[JsonValue]] = {
        "jsonSchemaDialect": st.just("https://json-schema.org/draft/2020-12/schema"),
        "paths": paths,
        "webhooks": _named(_path_item_st(refs=refs)),
        "servers": st.lists(_server_st(), min_size=1, max_size=2),
        "security": st.lists(_security_requirement_st(), max_size=2),
        "tags": _tags_st(),
        "externalDocs": _external_docs_st(),
    }
    draw(_with_optional(d, choices, 4))
    if refs:
        d["components"] = draw(_components_st(refs=True))
    return d
