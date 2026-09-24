"""Parsing an OpenAPI document into its CST.

A missing required field, an unknown enum member, and a mistyped flag are all errors,
and they accumulate rather than stopping at the first one.
"""

from tests.support.stages import minimal_openapi, openapi_result, operation_at

from schema_to.cst.openapi import (
    Example,
    Header,
    Link,
    Parameter,
    ParameterLocation,
    PathItem,
    Reference,
    RequestBody,
    Response,
)
from schema_to.result import Err, Ok
from schema_to.serialize.openapi import OpenApiSerializer


def test_ref_in_a_parameter_position_becomes_a_reference() -> None:
    result = openapi_result(
        minimal_openapi(
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
    parameter = operation_at(result.value, "/x").parameters[0]
    assert isinstance(parameter, Reference)
    assert parameter.ref == "#/components/parameters/Id"


def test_a_concrete_parameter_still_parses_as_a_parameter() -> None:
    result = openapi_result(
        minimal_openapi(
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
    parameter = operation_at(result.value, "/x").parameters[0]
    assert isinstance(parameter, Parameter)
    assert (parameter.name, parameter.in_) == ("id", ParameterLocation.PATH)


def test_links_headers_and_encodings_are_parsed() -> None:
    result = openapi_result(
        minimal_openapi(
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
    operation = operation_at(result.value, "/x", "post")
    body = operation.request_body
    assert isinstance(body, RequestBody)
    assert body.content["multipart/form-data"].encoding["file"].content_type == "image/png"
    response = operation.responses["200"]
    assert isinstance(response, Response)
    assert isinstance(response.headers["X-Rate"], Header)
    assert isinstance(response.links["next"], Link)
    assert response.links["next"].operation_id == "getX"


def test_component_path_items_and_examples_are_parsed() -> None:
    result = openapi_result(
        minimal_openapi(
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
    result = openapi_result(minimal_openapi(servers=[{"description": "no url here"}]))
    assert isinstance(result, Err)
    assert any("url is required" in e.message for e in result.errors)
    assert any(e.location and e.location.json_pointer == "/servers/0/url" for e in result.errors)


def test_a_response_without_a_description_is_an_error() -> None:
    result = openapi_result(minimal_openapi(paths={"/x": {"get": {"responses": {"200": {}}}}}))
    assert isinstance(result, Err)
    assert any("description is required" in e.message for e in result.errors)


def test_an_unknown_security_scheme_type_is_an_error_not_a_silent_drop() -> None:
    result = openapi_result(
        minimal_openapi(components={"securitySchemes": {"s": {"type": "magic"}}})
    )
    assert isinstance(result, Err)
    assert any("type" in e.message for e in result.errors)


def test_a_non_boolean_flag_is_rejected_rather_than_coerced() -> None:
    result = openapi_result(
        minimal_openapi(
            paths={"/x": {"get": {"deprecated": "no", "responses": {"200": {"description": "k"}}}}}
        )
    )
    assert isinstance(result, Err)
    assert any("deprecated must be a boolean" in e.message for e in result.errors)


def test_errors_accumulate_across_the_whole_document() -> None:
    result = openapi_result(
        minimal_openapi(
            servers=[{"description": "a"}, {"description": "b"}], tags=[{"description": "c"}]
        )
    )
    assert isinstance(result, Err)
    assert len(result.errors) == 3


def test_a_non_three_version_is_rejected() -> None:
    result = openapi_result({"openapi": "2.0", "info": {"title": "T", "version": "1"}})
    assert isinstance(result, Err)
    assert any("3.x" in e.message for e in result.errors)


def test_json_schema_dialect_round_trips() -> None:
    dialect = "https://json-schema.org/draft/2020-12/schema"
    result = openapi_result(minimal_openapi(jsonSchemaDialect=dialect))
    assert isinstance(result, Ok), result
    assert result.value.json_schema_dialect == dialect
    assert OpenApiSerializer().serialize(result.value)["jsonSchemaDialect"] == dialect


def test_references_survive_a_round_trip() -> None:
    document = minimal_openapi(
        paths={
            "/x": {
                "get": {
                    "parameters": [{"$ref": "#/components/parameters/Id"}],
                    "responses": {"200": {"$ref": "#/components/responses/Ok"}},
                }
            }
        }
    )
    result = openapi_result(document)
    assert isinstance(result, Ok), result
    assert OpenApiSerializer().serialize(result.value) == document
