"""Tests for resource-schema introspection (`schema_to.generate.resource`)."""

from typing import Any

import pytest
from tests.support.docs import json_schema_doc

from schema_to.cst.json_schema import BooleanSchema, ObjectSchema, is_object_schema
from schema_to.generate.fastapi.resource import json_properties, property_names
from schema_to.parse.json_schema import JsonSchemaParser
from schema_to.result import Ok


def _object_schema(data: dict[str, Any]) -> ObjectSchema:
    doc = json_schema_doc(data, "t:///s")
    result = JsonSchemaParser().apply(doc)
    assert isinstance(result, Ok)
    root = result.value.root
    assert isinstance(root, ObjectSchema)
    return root


def test_json_properties_detects_object_and_array() -> None:
    schema = _object_schema(
        {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "meta": {"type": "object"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        }
    )
    assert set(json_properties(schema)) == {"meta", "tags"}
    assert set(property_names(schema)) == {"id", "name", "meta", "tags"}


def test_empty_for_none() -> None:
    assert json_properties(None) == ()
    assert property_names(None) == ()


@pytest.mark.parametrize("schema", [{"type": "object"}])
def test_no_properties(schema: dict[str, Any]) -> None:
    obj = _object_schema(schema)
    assert json_properties(obj) == ()
    assert property_names(obj) == ()


def test_is_object_schema() -> None:
    assert is_object_schema(_object_schema({"type": "object"}))
    # No explicit type but properties present is treated as an object.
    assert is_object_schema(_object_schema({"properties": {"a": {"type": "string"}}}))
    # `object` among a type union still counts.
    assert is_object_schema(_object_schema({"type": ["object", "null"]}))
    assert not is_object_schema(_object_schema({"type": "string"}))
    assert not is_object_schema(BooleanSchema(value=True))
