"""Fields that survive a parse → serialize round trip.

A field the CST holds but the serializer forgets would be invisible in the parsed document,
so each of these pins the key back in the emitted JSON.
"""

from collections.abc import Mapping

from tests.support.stages import minimal_openapi, openapi_result, operation_at
from tests.support.types import JsonLike

from schema_to.core import JsonObject
from schema_to.cst.openapi import Header, Parameter, PathItem, Reference
from schema_to.parse._plan import plan_for
from schema_to.result import Ok
from schema_to.serialize.openapi import OpenApiSerializer

# ---------------------------------------------------------------------------
# Coverage of the 3.1 fixed fields
# ---------------------------------------------------------------------------


def _round_trip(document: JsonLike) -> JsonObject:
    result = openapi_result(document)
    assert isinstance(result, Ok), [e.message for e in getattr(result, "errors", ())]
    return OpenApiSerializer().serialize(result.value)


def test_parameter_serialization_fields_are_carried() -> None:
    document = minimal_openapi(
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
    document = minimal_openapi(
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
    document = minimal_openapi(
        paths={"/x": {"$ref": "#/components/pathItems/Shared", "summary": "local"}},
        components={"pathItems": {"Shared": {"description": "shared"}}},
    )
    result = openapi_result(document)
    assert isinstance(result, Ok), [e.message for e in getattr(result, "errors", ())]
    path_item = result.value.paths["/x"]
    assert path_item.ref == "#/components/pathItems/Shared"
    assert path_item.summary == "local"
    assert _round_trip(document) == document


def test_callbacks_are_carried_on_operations_and_components() -> None:
    document = minimal_openapi(
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
    result = openapi_result(document)
    assert isinstance(result, Ok), [e.message for e in getattr(result, "errors", ())]
    callbacks = operation_at(result.value, "/x", "post").callbacks
    inline = callbacks["inline"]
    assert isinstance(inline, Mapping), "an inline callback maps expressions to path items"
    assert isinstance(inline["{$request.body#/url}"], PathItem)
    assert isinstance(callbacks["shared"], Reference)
    assert _round_trip(document) == document
