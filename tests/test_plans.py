"""Tests for the node plan compiler and the parser behaviours it drives.

The golden snapshot is the safety net for deriving plans from annotations:
A change to the derivation rules, or to a CST field,
shows up as a diff in a checked-in table.
"""

import json
from dataclasses import fields, is_dataclass, replace
from pathlib import Path

import pytest

from schema_to.core import JsonObject
from schema_to.cst.json_schema import ObjectSchema
from schema_to.cst.openapi import (
    Components,
    Contact,
    Encoding,
    Example,
    ExternalDocumentation,
    Header,
    Info,
    License,
    Link,
    MediaTypeObject,
    OAuthFlow,
    OAuthFlows,
    OpenApiDocument,
    Operation,
    Parameter,
    ParameterLocation,
    PathItem,
    Reference,
    RequestBody,
    Response,
    SecurityScheme,
    Server,
    ServerVariable,
    Tag,
)
from schema_to.io.media_type import MediaTypes
from schema_to.io.source import OpenApiRawDoc
from schema_to.parse._plan import (
    EnumSpec,
    FieldPlan,
    ListSpec,
    MapSpec,
    NodeSpec,
    OneOfSpec,
    SchemaSpec,
    SetSpec,
    SpecVersion,
    json_key,
    plan_for,
)
from schema_to.parse.openapi import OpenApiParser
from schema_to.result import Err, Ok
from schema_to.serialize.openapi import OpenApiSerializer

_GOLDEN = Path(__file__).parent / "plans.golden.txt"

# Every node built from a plan. The document envelopes are excluded: a JSON
# Schema document *is* its root schema rather than an object of keywords.
_PLANNED = [
    ObjectSchema,
    OpenApiDocument,
    Components,
    Contact,
    Encoding,
    Example,
    ExternalDocumentation,
    Header,
    Info,
    License,
    Link,
    MediaTypeObject,
    OAuthFlow,
    OAuthFlows,
    Operation,
    Parameter,
    PathItem,
    Reference,
    RequestBody,
    Response,
    SecurityScheme,
    Server,
    ServerVariable,
    Tag,
]


def _render_spec(spec: object) -> str:
    match spec:
        case ListSpec(item=item):
            rendered = f"list[{_render_spec(item)}]"
        case SetSpec(item=item):
            rendered = f"set[{_render_spec(item)}]"
        case MapSpec(value=value):
            rendered = f"map[{_render_spec(value)}]"
        case OneOfSpec(options=options):
            rendered = "one-of[" + " | ".join(_render_spec(o) for o in options) + "]"
        case NodeSpec(node=node):
            rendered = node.__name__
        case EnumSpec(enum=enum):
            rendered = f"enum[{enum.__name__}]"
        case SchemaSpec():
            rendered = "schema"
        case _:
            rendered = type(spec).__name__.removesuffix("Spec").lower() + _render_bound(spec)
    return rendered


def _render_range(entry: FieldPlan) -> str:
    since = entry.since.text if entry.since is not None else ""
    until = entry.until.text if entry.until is not None else ""
    return f"[{since}..{until}]" if since or until else ""


def _render_bound(spec: object) -> str:
    minimum = getattr(spec, "minimum", None)
    return f"(>={minimum})" if minimum is not None else ""


def _render_plans() -> str:
    lines: list[str] = []
    for node in _PLANNED:
        plan = plan_for(node)
        flags = "".join(
            [
                " +extensions" if plan.has_extensions else "",
                " +source_ref" if plan.has_source_ref else "",
            ]
        )
        lines.append(f"{node.__name__}{flags}")
        for entry in plan.entries:
            marks = "".join(["!" if entry.required else " ", "?" if entry.nullable else " "])
            lines.append(
                f"  {marks} {entry.key:<24} {entry.name:<24} "
                f"{_render_range(entry):<10} {_render_spec(entry.spec)}"
            )
        lines.append("")
    return "\n".join(lines)


def test_plans_match_golden_snapshot() -> None:
    rendered = _render_plans()
    if not _GOLDEN.exists():  # pragma: no cover — only on first run
        _GOLDEN.write_text(rendered, encoding="utf-8")
    assert rendered == _GOLDEN.read_text(encoding="utf-8"), (
        "Compiled plans changed. Review the diff; if it is intended, delete "
        f"{_GOLDEN.name} and re-run to regenerate it."
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("in_", "in"),
        ("type_", "type"),
        ("license_", "license"),
        ("terms_of_service", "termsOfService"),
        ("open_id_connect_url", "openIdConnectUrl"),
        ("path_items", "pathItems"),
        ("url", "url"),
    ],
)
def test_json_key_derivation(name: str, expected: str) -> None:
    assert json_key(name) == expected


def test_every_planned_node_is_a_frozen_dataclass() -> None:
    for node in _PLANNED:
        assert is_dataclass(node), node
        assert fields(node), node


def test_requiredness_matches_the_absence_of_a_default() -> None:
    required = {e.key for e in plan_for(Info).entries if e.required}
    assert required == {"title", "version"}
    # OAS 3.1 made `responses` optional, so the CST gives it a default.
    assert not any(e.required for e in plan_for(Operation).entries)


# ---------------------------------------------------------------------------
# Parser behaviour
# ---------------------------------------------------------------------------


def _parse(doc: dict) -> Ok | Err:
    raw = OpenApiRawDoc(doc_id="d", content=json.dumps(doc).encode(), media_type=MediaTypes.json)
    return OpenApiParser().apply(raw)


def _minimal(**extra: object) -> dict:
    return {"openapi": "3.1.0", "info": {"title": "T", "version": "1"}, **extra}


def test_ref_in_a_parameter_position_becomes_a_reference() -> None:
    result = _parse(
        _minimal(
            paths={
                "/x": {
                    "get": {
                        "parameters": [{"$ref": "#/components/parameters/Id"}],
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            }
        )
    )
    assert isinstance(result, Ok), result
    parameter = result.value.paths["/x"].get.parameters[0]
    assert isinstance(parameter, Reference)
    assert parameter.ref == "#/components/parameters/Id"


def test_a_concrete_parameter_still_parses_as_a_parameter() -> None:
    result = _parse(
        _minimal(
            paths={
                "/x": {
                    "get": {
                        "parameters": [{"name": "id", "in": "path", "required": True}],
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            }
        )
    )
    assert isinstance(result, Ok), result
    parameter = result.value.paths["/x"].get.parameters[0]
    assert isinstance(parameter, Parameter)
    assert (parameter.name, parameter.in_) == ("id", ParameterLocation.PATH)


def test_links_headers_and_encodings_are_parsed() -> None:
    result = _parse(
        _minimal(
            paths={
                "/x": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "multipart/form-data": {
                                    "encoding": {"file": {"contentType": "image/png"}}
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "description": "ok",
                                "headers": {"X-Rate": {"description": "limit"}},
                                "links": {"next": {"operationId": "getX"}},
                            }
                        },
                    }
                }
            }
        )
    )
    assert isinstance(result, Ok), result
    operation = result.value.paths["/x"].post
    body = operation.request_body
    assert isinstance(body, RequestBody)
    assert body.content["multipart/form-data"].encoding["file"].content_type == "image/png"
    response = operation.responses["200"]
    assert isinstance(response, Response)
    assert isinstance(response.headers["X-Rate"], Header)
    assert isinstance(response.links["next"], Link)
    assert response.links["next"].operation_id == "getX"


def test_component_path_items_and_examples_are_parsed() -> None:
    result = _parse(
        _minimal(
            components={
                "pathItems": {"Shared": {"summary": "s"}},
                "examples": {"one": {"summary": "first", "value": 1}},
            }
        )
    )
    assert isinstance(result, Ok), result
    components = result.value.components
    assert isinstance(components.path_items["Shared"], PathItem)
    example = components.examples["one"]
    assert isinstance(example, Example)
    assert example.value == 1


def test_a_missing_required_field_is_an_error_not_an_empty_string() -> None:
    result = _parse(_minimal(servers=[{"description": "no url here"}]))
    assert isinstance(result, Err)
    assert any("url is required" in e.message for e in result.errors)
    assert any(e.location and e.location.json_pointer == "/servers/0/url" for e in result.errors)


def test_a_response_without_a_description_is_an_error() -> None:
    result = _parse(_minimal(paths={"/x": {"get": {"responses": {"200": {}}}}}))
    assert isinstance(result, Err)
    assert any("description is required" in e.message for e in result.errors)


def test_an_unknown_security_scheme_type_is_an_error_not_a_silent_drop() -> None:
    result = _parse(_minimal(components={"securitySchemes": {"s": {"type": "magic"}}}))
    assert isinstance(result, Err)
    assert any("type" in e.message for e in result.errors)


def test_a_non_boolean_flag_is_rejected_rather_than_coerced() -> None:
    result = _parse(
        _minimal(
            paths={"/x": {"get": {"deprecated": "no", "responses": {"200": {"description": "k"}}}}}
        )
    )
    assert isinstance(result, Err)
    assert any("deprecated must be a boolean" in e.message for e in result.errors)


def test_errors_accumulate_across_the_whole_document() -> None:
    result = _parse(
        _minimal(servers=[{"description": "a"}, {"description": "b"}], tags=[{"description": "c"}])
    )
    assert isinstance(result, Err)
    assert len(result.errors) == 3


def test_a_non_three_version_is_rejected() -> None:
    result = _parse({"openapi": "2.0", "info": {"title": "T", "version": "1"}})
    assert isinstance(result, Err)
    assert any("3.x" in e.message for e in result.errors)


def test_json_schema_dialect_round_trips() -> None:
    dialect = "https://json-schema.org/draft/2020-12/schema"
    result = _parse(_minimal(jsonSchemaDialect=dialect))
    assert isinstance(result, Ok), result
    assert result.value.json_schema_dialect == dialect
    assert OpenApiSerializer().serialize(result.value)["jsonSchemaDialect"] == dialect


def test_references_survive_a_round_trip() -> None:
    document = _minimal(
        paths={
            "/x": {
                "get": {
                    "parameters": [{"$ref": "#/components/parameters/Id"}],
                    "responses": {"200": {"$ref": "#/components/responses/Ok"}},
                }
            }
        }
    )
    result = _parse(document)
    assert isinstance(result, Ok), result
    assert OpenApiSerializer().serialize(result.value) == document


# ---------------------------------------------------------------------------
# Version gating
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "parts"), [("3.1.0", (3, 1, 0)), ("3.2", (3, 2)), ("3.2.0-rc1", (3, 2, 0))]
)
def test_spec_version_parsing(text: str, parts: tuple[int, ...]) -> None:
    version = SpecVersion.parse(text)
    assert version is not None
    assert version.parts == parts


def _version(text: str) -> SpecVersion:
    parsed = SpecVersion.parse(text)
    assert parsed is not None
    return parsed


def test_spec_version_ignores_trailing_zeroes_when_comparing() -> None:
    v31, v32 = _version("3.1.0"), _version("3.2")
    assert v32.at_least(v31)
    assert not v31.at_least(v32)
    assert v32.at_least(_version("3.2.0"))


def test_a_three_two_key_is_rejected_in_a_three_one_document() -> None:
    result = _parse(_minimal(**{"$self": "https://example.com/api"}))
    assert isinstance(result, Err)
    assert any(
        "$self was introduced in OpenAPI 3.2" in e.message and "declares 3.1.0" in e.message
        for e in result.errors
    ), [e.message for e in result.errors]


def test_the_same_key_is_accepted_in_a_three_two_document() -> None:
    document = {
        "openapi": "3.2.0",
        "info": {"title": "T", "version": "1"},
        "$self": "https://example.com/api",
        "servers": [{"url": "/", "name": "default"}],
    }
    result = _parse(document)
    assert isinstance(result, Ok), [e.message for e in getattr(result, "errors", ())]
    assert result.value.self_ == "https://example.com/api"
    assert result.value.servers[0].name == "default"
    assert OpenApiSerializer().serialize(result.value) == document


def test_gating_reaches_nested_nodes() -> None:
    result = _parse(
        _minimal(
            paths={
                "/x": {"get": {"responses": {"200": {"description": "ok", "summary": "too new"}}}}
            }
        )
    )
    assert isinstance(result, Err)
    assert any("summary was introduced in OpenAPI 3.2" in e.message for e in result.errors)


def test_three_two_path_item_operations_parse() -> None:
    result = _parse(
        {
            "openapi": "3.2.0",
            "info": {"title": "T", "version": "1"},
            "paths": {
                "/x": {
                    "query": {"operationId": "queryX"},
                    "additionalOperations": {"PURGE": {"operationId": "purgeX"}},
                }
            },
        }
    )
    assert isinstance(result, Ok), [e.message for e in getattr(result, "errors", ())]
    path_item = result.value.paths["/x"]
    assert path_item.query is not None
    assert path_item.query.operation_id == "queryX"
    assert path_item.additional_operations["PURGE"].operation_id == "purgeX"


def test_serializing_into_an_older_version_drops_the_gated_key() -> None:
    """A 3.2 field on a CST relabelled 3.1 emits nothing, so the output re-parses."""
    parsed = _parse(
        {
            "openapi": "3.2.0",
            "info": {"title": "T", "version": "1"},
            "$self": "https://example.com/api",
        }
    )
    assert isinstance(parsed, Ok), parsed
    relabelled = replace(parsed.value, openapi="3.1.0")
    emitted = OpenApiSerializer().serialize(relabelled)
    assert "$self" not in emitted


def test_an_unreadable_version_gates_nothing() -> None:
    """A document whose version cannot be read has worse problems to report."""
    result = _parse({"info": {"title": "T", "version": "1"}, "$self": "x"})
    assert isinstance(result, Err)
    messages = [e.message for e in result.errors]
    assert any("openapi is required" in m for m in messages)
    assert not any("introduced in OpenAPI" in m for m in messages)


# ---------------------------------------------------------------------------
# Coverage of the 3.1 fixed fields
# ---------------------------------------------------------------------------


def _round_trip(document: dict) -> JsonObject:
    result = _parse(document)
    assert isinstance(result, Ok), [e.message for e in getattr(result, "errors", ())]
    return OpenApiSerializer().serialize(result.value)


def test_parameter_serialization_fields_are_carried() -> None:
    document = _minimal(
        paths={
            "/x": {
                "get": {
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "allowReserved": True,
                            "example": "a/b",
                            "examples": {"one": {"summary": "s", "value": "a/b"}},
                        }
                    ]
                }
            }
        }
    )
    assert _round_trip(document) == document


def test_header_serialization_fields_are_carried() -> None:
    document = _minimal(
        components={
            "headers": {
                "X-Rate": {
                    "style": "simple",
                    "explode": False,
                    "example": 5,
                    "examples": {"one": {"value": 5}},
                    "schema": {"type": "integer"},
                }
            }
        }
    )
    assert _round_trip(document) == document


def test_a_header_has_no_query_only_traits() -> None:
    """The specification says a header MUST NOT use `allowEmptyValue` or `allowReserved`."""
    keys = plan_for(Header).keys()
    assert "allowEmptyValue" not in keys
    assert "allowReserved" not in keys
    # The Parameter it is otherwise shaped like does have them.
    assert {"allowEmptyValue", "allowReserved"} <= plan_for(Parameter).keys()


def test_a_path_item_ref_is_a_field_beside_the_others() -> None:
    document = _minimal(
        paths={"/x": {"$ref": "#/components/pathItems/Shared", "summary": "local"}},
        components={"pathItems": {"Shared": {"description": "shared"}}},
    )
    result = _parse(document)
    assert isinstance(result, Ok), [e.message for e in getattr(result, "errors", ())]
    path_item = result.value.paths["/x"]
    assert path_item.ref == "#/components/pathItems/Shared"
    assert path_item.summary == "local"
    assert _round_trip(document) == document


def test_callbacks_are_carried_on_operations_and_components() -> None:
    document = _minimal(
        paths={
            "/x": {
                "post": {
                    "callbacks": {
                        "inline": {
                            "{$request.body#/url}": {
                                "post": {"responses": {"200": {"description": "ok"}}}
                            }
                        },
                        "shared": {"$ref": "#/components/callbacks/OnEvent"},
                    }
                }
            }
        },
        components={
            "callbacks": {
                "OnEvent": {
                    "{$request.body#/cb}": {"post": {"responses": {"200": {"description": "k"}}}}
                }
            }
        },
    )
    result = _parse(document)
    assert isinstance(result, Ok), [e.message for e in getattr(result, "errors", ())]
    callbacks = result.value.paths["/x"].post.callbacks
    assert isinstance(callbacks["inline"]["{$request.body#/url}"], PathItem)
    assert isinstance(callbacks["shared"], Reference)
    assert _round_trip(document) == document
