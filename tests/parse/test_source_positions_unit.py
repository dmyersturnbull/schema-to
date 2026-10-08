"""Each CST node knows where in the file it was written."""

from tests.support.asserts import ok

from schema_to.core import Position, SourceRef
from schema_to.cst.json_schema import ObjectSchema
from schema_to.io.media_type import MediaTypes
from schema_to.io.source import JsonSchemaRawDoc, OpenApiRawDoc, SchemaMapRawDoc
from schema_to.parse.json_schema import JsonSchemaMapParser, JsonSchemaParser
from schema_to.parse.openapi import OpenApiParser

_SCHEMA_JSON = b"""{
  "type": "object",
  "properties": {
    "name": {"type": "string"}
  }
}
"""

_SCHEMA_YAML = b"""type: object
properties:
  name:
    type: string
"""


def test_a_json_schema_node_is_located_in_json() -> None:
    doc = ok(
        JsonSchemaParser().apply(
            JsonSchemaRawDoc.original("file:///a.json", _SCHEMA_JSON, MediaTypes.json)
        )
    )
    assert isinstance(doc.root, ObjectSchema)
    assert doc.root.source_ref == SourceRef("file:///a.json", "", Position(1, 1), Position(6, 2))
    name = (doc.root.properties or {})["name"]
    assert name.source_ref == SourceRef(
        "file:///a.json", "/properties/name", Position(4, 13), Position(4, 31)
    )


def test_a_json_schema_node_is_located_in_yaml() -> None:
    doc = ok(
        JsonSchemaParser().apply(
            JsonSchemaRawDoc.original("file:///a.yaml", _SCHEMA_YAML, MediaTypes.yaml)
        )
    )
    assert isinstance(doc.root, ObjectSchema)
    name = (doc.root.properties or {})["name"]
    assert name.source_ref == SourceRef(
        "file:///a.yaml", "/properties/name", Position(4, 5), Position(5, 1)
    )


def test_a_schema_map_entry_is_located() -> None:
    text = b"a:\n  type: string\nb:\n  type: integer\n"
    doc = ok(
        JsonSchemaMapParser().apply(
            SchemaMapRawDoc.original("file:///m.yaml", text, MediaTypes.yaml)
        )
    )
    assert doc.schemas["b"].source_ref == SourceRef(
        "file:///m.yaml", "/b", Position(4, 3), Position(5, 1)
    )


def test_an_openapi_node_is_located() -> None:
    text = b"openapi: 3.1.0\ninfo:\n  title: T\n  version: '1'\npaths: {}\n"
    doc = ok(
        OpenApiParser().apply(OpenApiRawDoc.original("file:///api.yaml", text, MediaTypes.yaml))
    )
    assert doc.info.source_ref == SourceRef(
        "file:///api.yaml", "/info", Position(3, 3), Position(5, 1)
    )


def test_a_parse_error_names_the_line_of_the_offending_node() -> None:
    doc = JsonSchemaRawDoc.original(
        "file:///a.yaml", b"type: object\nminLength: oops\n", MediaTypes.yaml
    )
    result = JsonSchemaParser().apply(doc)
    errors = getattr(result, "errors", ())
    assert [(e.location.json_pointer, e.location.start) for e in errors if e.location] == [
        ("/minLength", Position(2, 12))
    ]
