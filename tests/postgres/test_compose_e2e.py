"""End-to-end: `allOf`-composed schemas reaching the Postgres target as tables.

Separate from `test_compose_unit.py`, which exercises the flattener directly.
These go through the whole parse → resolve → generate → reify pipeline.
"""

from tests.support.docs import json_schema_doc
from tests.support.drive import POSTGRES
from tests.support.types import JsonLike


def _transpile(data: JsonLike) -> str:
    return POSTGRES.text(json_schema_doc(data))


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
    [message] = POSTGRES.errors(json_schema_doc({"type": "string"}))
    assert "object" in message
    assert "string" in message
