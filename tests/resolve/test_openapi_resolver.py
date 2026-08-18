"""Tests for the OpenAPI Reference Object resolver."""

import json

import pytest

from schema_to.cst.json_schema import ObjectSchema
from schema_to.cst.openapi import (
    Example,
    Header,
    Link,
    OpenApiDocument,
    Operation,
    Parameter,
    PathItem,
    RequestBody,
    Response,
    SecurityScheme,
)
from schema_to.errors import ResolutionError
from schema_to.io.media_type import MediaTypes
from schema_to.io.source import OpenApiRawDoc
from schema_to.parse.openapi import OpenApiParser
from schema_to.resolve.openapi import OpenApiRefResolver
from schema_to.result import Err, Ok

_RESOLVER_INPUT = "3.1.0"


def _document(doc: dict, doc_id: str = "d") -> OpenApiDocument:
    raw = OpenApiRawDoc(doc_id=doc_id, content=json.dumps(doc).encode(), media_type=MediaTypes.json)
    parsed = OpenApiParser().apply(raw)
    assert isinstance(parsed, Ok), [e.message for e in getattr(parsed, "errors", ())]
    return parsed.value


def _resolve(doc: dict, doc_id: str = "d") -> Ok[OpenApiDocument] | Err:
    return OpenApiRefResolver().apply(_document(doc, doc_id))


def _minimal(**extra: object) -> dict:
    return {"openapi": _RESOLVER_INPUT, "info": {"title": "T", "version": "1"}, **extra}


def _operation(doc: OpenApiDocument, path: str = "/x") -> Operation:
    """Return the GET operation of `path`, asserting it is there."""
    operation = doc.paths[path].get
    assert operation is not None
    return operation


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_a_referenced_parameter_is_replaced_by_its_target() -> None:
    result = _resolve(
        _minimal(
            paths={"/x": {"get": {"parameters": [{"$ref": "#/components/parameters/Id"}]}}},
            components={"parameters": {"Id": {"name": "id", "in": "path", "required": True}}},
        )
    )
    assert isinstance(result, Ok), result
    parameter = _operation(result.value).parameters[0]
    assert isinstance(parameter, Parameter)
    assert parameter.name == "id"


@pytest.mark.parametrize(
    ("section", "name", "target", "expected"),
    [
        ("responses", "Ok", {"description": "ok"}, Response),
        ("requestBodies", "Body", {"content": {}}, RequestBody),
        ("headers", "X", {"description": "h"}, Header),
        ("links", "Next", {"operationId": "op"}, Link),
        ("examples", "One", {"value": 1}, Example),
        ("securitySchemes", "Key", {"type": "apiKey"}, SecurityScheme),
        ("pathItems", "Shared", {"summary": "s"}, PathItem),
    ],
)
def test_every_component_section_resolves(
    section: str, name: str, target: dict, expected: type
) -> None:
    """A reference from the components map into itself resolves for every section."""
    result = _resolve(
        _minimal(
            components={
                section: {name: target, "Alias": {"$ref": f"#/components/{section}/{name}"}}
            }
        )
    )
    assert isinstance(result, Ok), [e.message for e in getattr(result, "errors", ())]
    resolved = getattr(result.value.components, _FIELD[section])["Alias"]
    assert isinstance(resolved, expected)


_FIELD = {
    "responses": "responses",
    "requestBodies": "request_bodies",
    "headers": "headers",
    "links": "links",
    "examples": "examples",
    "securitySchemes": "security_schemes",
    "pathItems": "path_items",
}


def test_resolution_reaches_nested_positions() -> None:
    """A header inside a referenced response is itself resolved."""
    result = _resolve(
        _minimal(
            paths={"/x": {"get": {"responses": {"200": {"$ref": "#/components/responses/Ok"}}}}},
            components={
                "responses": {
                    "Ok": {
                        "description": "ok",
                        "headers": {"X": {"$ref": "#/components/headers/X"}},
                    }
                },
                "headers": {"X": {"description": "rate limit"}},
            },
        )
    )
    assert isinstance(result, Ok), result
    response = _operation(result.value).responses["200"]
    assert isinstance(response, Response)
    header = response.headers["X"]
    assert isinstance(header, Header)
    assert header.description == "rate limit"


def test_a_chain_of_references_is_followed_through() -> None:
    result = _resolve(
        _minimal(
            paths={"/x": {"get": {"parameters": [{"$ref": "#/components/parameters/A"}]}}},
            components={
                "parameters": {
                    "A": {"$ref": "#/components/parameters/B"},
                    "B": {"name": "id", "in": "query"},
                }
            },
        )
    )
    assert isinstance(result, Ok), result
    parameter = _operation(result.value).parameters[0]
    assert isinstance(parameter, Parameter)
    assert parameter.name == "id"


def test_a_schema_ref_is_left_for_the_json_schema_resolver() -> None:
    result = _resolve(
        _minimal(
            components={"schemas": {"Thing": {"$ref": "#/components/schemas/Other"}, "Other": {}}}
        )
    )
    assert isinstance(result, Ok), result
    thing = result.value.components.schemas["Thing"]
    assert isinstance(thing, ObjectSchema)
    assert thing.ref == "#/components/schemas/Other"


def test_a_document_without_references_is_returned_unchanged() -> None:
    document = _document(
        _minimal(paths={"/x": {"get": {"responses": {"200": {"description": "k"}}}}})
    )
    result = OpenApiRefResolver().apply(document)
    assert isinstance(result, Ok)
    assert result.value is document


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def test_a_reference_overrides_the_target_description() -> None:
    result = _resolve(
        _minimal(
            paths={
                "/x": {
                    "get": {
                        "parameters": [
                            {
                                "$ref": "#/components/parameters/Id",
                                "description": "at the point of use",
                            }
                        ]
                    }
                }
            },
            components={
                "parameters": {"Id": {"name": "id", "in": "path", "description": "shared"}}
            },
        )
    )
    assert isinstance(result, Ok), result
    parameter = _operation(result.value).parameters[0]
    assert isinstance(parameter, Parameter)
    assert parameter.description == "at the point of use"
    # The shared definition keeps its own wording.
    shared = result.value.components.parameters["Id"]
    assert isinstance(shared, Parameter)
    assert shared.description == "shared"


def test_an_override_the_target_cannot_hold_warns_rather_than_failing() -> None:
    """A Parameter has no `summary`, so a reference overriding one loses it."""
    result = _resolve(
        _minimal(
            paths={
                "/x": {
                    "get": {
                        "parameters": [{"$ref": "#/components/parameters/Id", "summary": "ignored"}]
                    }
                }
            },
            components={"parameters": {"Id": {"name": "id", "in": "path"}}},
        )
    )
    assert isinstance(result, Ok), result
    assert len(result.warnings) == 1
    assert result.warnings[0].code == "unhonoured-override"
    assert "summary" in result.warnings[0].message


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------


def test_an_unresolvable_reference_is_an_error() -> None:
    result = _resolve(
        _minimal(paths={"/x": {"get": {"parameters": [{"$ref": "#/components/parameters/Nope"}]}}})
    )
    assert isinstance(result, Err)
    assert all(isinstance(e, ResolutionError) for e in result.errors)
    assert "Cannot resolve" in result.errors[0].message


def test_an_unresolvable_reference_reports_where_it_was_written() -> None:
    result = _resolve(_minimal(paths={"/x": {"get": {"parameters": [{"$ref": "#/nowhere"}]}}}))
    assert isinstance(result, Err)
    location = result.errors[0].location
    assert location is not None
    assert location.json_pointer == "/paths/~1x/get/parameters/0"


def test_errors_accumulate_across_the_document() -> None:
    result = _resolve(
        _minimal(
            paths={
                "/x": {"get": {"parameters": [{"$ref": "#/a"}, {"$ref": "#/b"}]}},
                "/y": {"get": {"parameters": [{"$ref": "#/c"}]}},
            }
        )
    )
    assert isinstance(result, Err)
    assert len(result.errors) == 3


def test_a_reference_to_the_wrong_kind_of_node_is_an_error() -> None:
    result = _resolve(
        _minimal(
            paths={"/x": {"get": {"parameters": [{"$ref": "#/components/responses/Ok"}]}}},
            components={"responses": {"Ok": {"description": "ok"}}},
        )
    )
    assert isinstance(result, Err)
    assert "resolves to a Response" in result.errors[0].message
    assert "Parameter is required" in result.errors[0].message


def test_a_reference_cycle_is_reported_rather_than_recursed() -> None:
    result = _resolve(
        _minimal(
            components={
                "parameters": {
                    "A": {"$ref": "#/components/parameters/B"},
                    "B": {"$ref": "#/components/parameters/A"},
                }
            }
        )
    )
    assert isinstance(result, Err)
    assert any("cycle" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# Cross-document
# ---------------------------------------------------------------------------


def test_a_reference_into_a_registered_document_resolves() -> None:
    shared = _document(
        _minimal(components={"parameters": {"Id": {"name": "id", "in": "path"}}}),
        doc_id="shared.yaml",
    )
    main = _document(
        _minimal(
            paths={
                "/x": {"get": {"parameters": [{"$ref": "shared.yaml#/components/parameters/Id"}]}}
            }
        ),
        doc_id="main.yaml",
    )
    resolver = OpenApiRefResolver()
    resolver.register(shared)
    result = resolver.apply(main)
    assert isinstance(result, Ok), [e.message for e in getattr(result, "errors", ())]
    parameter = _operation(result.value).parameters[0]
    assert isinstance(parameter, Parameter)
    assert parameter.name == "id"


def test_a_reference_into_an_unregistered_document_is_an_error() -> None:
    result = _resolve(
        _minimal(
            paths={
                "/x": {
                    "get": {"parameters": [{"$ref": "elsewhere.yaml#/components/parameters/Id"}]}
                }
            }
        ),
        doc_id="main.yaml",
    )
    assert isinstance(result, Err)
    assert "elsewhere.yaml" in result.errors[0].message
