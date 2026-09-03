"""Tests for the `pg-jsonschema` target (JSON Schema → PostgreSQL with validation)."""

from tests.support.docs import json_schema_doc
from tests.support.drive import PG_JSONSCHEMA, POSTGRES, Route

_SCHEMA = {
    "type": "object",
    "title": "Thing",
    "properties": {
        "id": {"type": "integer"},
        "name": {"type": "string"},
        "meta": {
            "type": "object",
            "properties": {"theme": {"type": "string"}},
            "required": ["theme"],
        },
    },
    "required": ["id"],
}


def _transpile(route: Route) -> str:
    return route.text(json_schema_doc(_SCHEMA))


def test_pg_jsonschema_emits_extension_preamble() -> None:
    sql = _transpile(PG_JSONSCHEMA)
    assert sql.startswith("CREATE EXTENSION IF NOT EXISTS pg_jsonschema;")


def test_pg_jsonschema_validates_json_column() -> None:
    sql = _transpile(PG_JSONSCHEMA)
    assert "jsonb_matches_schema(" in sql
    assert '"theme"' in sql  # the embedded sub-schema
    assert ", meta)" in sql  # validates the meta column


def test_pg_jsonschema_leaves_scalar_columns_unvalidated() -> None:
    sql = _transpile(PG_JSONSCHEMA)
    # the scalar `name` column gets no jsonb_matches_schema check
    name_line = next(line for line in sql.splitlines() if line.strip().startswith("name "))
    assert "jsonb_matches_schema" not in name_line


def test_plain_postgres_target_has_no_validation() -> None:
    sql = _transpile(POSTGRES)
    assert "jsonb_matches_schema" not in sql
    assert "CREATE EXTENSION" not in sql
