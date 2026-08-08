"""Integration: `allOf`-composed schemas reaching the Postgres target as tables.

Separate from `test_compose.py`, which exercises the flattener directly.
These go through the whole parse → resolve → generate → reify pipeline.
"""

import orjson

from schema_to.io.media_type import MediaTypes
from schema_to.io.source import JsonSchemaRawDoc
from schema_to.result import Ok
from schema_to.transpile.sql import JsonSchemaToPostgresTranspiler

_SOURCE_ID = "test://schema"


def _transpile(data: object) -> str:
    doc = JsonSchemaRawDoc(
        doc_id=_SOURCE_ID,
        content=orjson.dumps(data),
        media_type=MediaTypes.json,
        display_name="Test",
    )
    result = JsonSchemaToPostgresTranspiler().transpile(doc)
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    return result.value[0].content.decode("utf-8")


def test_all_of_root_produces_a_table_with_every_column() -> None:
    """A root composed only of `allOf` used to be rejected as a non-object schema."""
    sql = _transpile(
        {
            "title": "composed",
            "allOf": [
                {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}},
                {"type": "object", "properties": {"count": {"type": "integer"}}},
            ],
        }
    )
    assert "CREATE TABLE IF NOT EXISTS composed (" in sql
    assert "id text NOT NULL" in sql
    assert "count integer" in sql


def test_non_object_root_names_what_it_found() -> None:
    doc = JsonSchemaRawDoc(
        doc_id=_SOURCE_ID, content=orjson.dumps({"type": "string"}), media_type=MediaTypes.json
    )
    result = JsonSchemaToPostgresTranspiler().transpile(doc)
    assert not isinstance(result, Ok)
    [error] = result.errors
    assert "object" in error.message
    assert "string" in error.message
