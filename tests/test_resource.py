"""Tests for resource-schema introspection (`schema_to.generate.resource`)."""

from __future__ import annotations

from typing import Any

import orjson
import pytest

from schema_to import JsonSchemaRawDoc, MediaTypes
from schema_to.cst.json_schema import ObjectSchema
from schema_to.generate.resource import json_properties, property_names
from schema_to.parse.json_schema import JsonSchemaParser
from schema_to.result import Ok


def _object_schema(data: dict[str, Any]) -> ObjectSchema:
    doc = JsonSchemaRawDoc(
        doc_id="t://s", content=orjson.dumps(data), media_type=MediaTypes.json, display_name="s"
    )
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
