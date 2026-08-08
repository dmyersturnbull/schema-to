"""Integration: a multi-file schema set producing one complete migration.

Separate from `test_sql_tables.py`, which exercises one keyword at a time.
These assert on whole scripts built from several documents.
"""

import orjson

from schema_to.generate.sql_tables import PostgresTableSetTransformer
from schema_to.io.media_type import MediaTypes
from schema_to.io.source import SchemaMapRawDoc
from schema_to.result import Err, Ok
from schema_to.transpile.sql_tables import SchemaMapSetToPostgresTranspiler


def _doc(data: object, name: str = "main") -> SchemaMapRawDoc:
    return SchemaMapRawDoc(
        doc_id=f"file:///{name}.yaml",
        content=orjson.dumps(data),
        media_type=MediaTypes.json,
        display_name=name,
    )


def _sql(*docs: SchemaMapRawDoc) -> str:
    result = SchemaMapSetToPostgresTranspiler().transpile_all(docs)
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    return result.value[0].content.decode("utf-8")


def test_two_file_set_with_cross_file_refs() -> None:
    """The Goldberry shape: primitives in one file, resources composing them in another."""
    base = _doc(
        {"timestamp": {"type": "string", "pattern": "^2", "description": "A timestamp."}}, "base"
    )
    main = _doc(
        {
            "author-data": {
                "type": "object",
                "x-pg-table": "author",
                "required": ["id"],
                "properties": {"id": {"type": "string"}},
            },
            "run-content": {
                "type": "object",
                "properties": {"author": {"type": "string", "x-pg-refs": "author"}},
            },
            "run-data": {
                "x-pg-table": "run",
                "x-pg-extras": "extras",
                "description": "A run.",
                "allOf": [
                    {
                        "type": "object",
                        "required": ["id"],
                        "properties": {
                            "id": {"type": "string"},
                            "insert-time": {"$ref": "./base.yaml#/timestamp", "x-pg-index": True},
                        },
                    },
                    {"$ref": "#/run-content"},
                ],
            },
        },
        "main",
    )
    sql = _sql(base, main)

    assert sql.index("CREATE TABLE IF NOT EXISTS author") < sql.index(
        "CREATE TABLE IF NOT EXISTS run"
    )
    # The primary key defaults to `id` without either schema saying so.
    assert "id text PRIMARY KEY" in sql
    # The cross-file $ref resolved to a concrete type, with its pattern and description.
    assert "insert_time text CHECK ((insert_time ~ '^2'))" in sql
    assert "COMMENT ON COLUMN run.insert_time IS 'A timestamp.';" in sql
    # The allOf branch contributed its column, and it carries the foreign key.
    assert "author text REFERENCES author" in sql
    assert "extras jsonb NOT NULL DEFAULT '{}'::jsonb" in sql
    assert "CREATE INDEX IF NOT EXISTS run_insert_time_idx ON run USING BTREE (insert_time);" in sql
    assert "COMMENT ON TABLE run IS 'A run.';" in sql


def test_unresolvable_cross_file_ref_is_an_error() -> None:
    docs = _doc(
        {
            "thing": {
                "type": "object",
                "x-pg-table": "thing",
                "properties": {"x": {"$ref": "./missing.yaml#/nope"}},
            }
        }
    )
    result = SchemaMapSetToPostgresTranspiler().transpile_all([docs])
    assert isinstance(result, Err)
    assert any("missing.yaml" in getattr(e, "message", str(e)) for e in result.errors)


def test_pg_jsonschema_check_has_no_unresolved_refs() -> None:
    """Inlining runs before serialization, so the embedded schema is self-contained."""
    base = _doc({"stamp": {"type": "string", "pattern": "^2"}}, "base")
    main = _doc(
        {
            "thing": {
                "type": "object",
                "x-pg-table": "thing",
                "properties": {
                    "payload": {
                        "type": "object",
                        "properties": {"at": {"$ref": "./base.yaml#/stamp"}},
                    }
                },
            }
        },
        "main",
    )
    transpiler = SchemaMapSetToPostgresTranspiler(
        generator=PostgresTableSetTransformer(validate_json=True)
    )
    result = transpiler.transpile_all([base, main])
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    sql = result.value[0].content.decode("utf-8")
    assert "jsonb_matches_schema(" in sql
    # pg_jsonschema cannot fetch a remote ref, so none may survive into the check.
    assert "$ref" not in sql
    assert "^2" in sql
