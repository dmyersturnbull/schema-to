"""End-to-end: a multi-file schema set producing one complete migration.

Separate from `test_sql_tables_integration.py`, which exercises one keyword at a time.
These assert on whole scripts built from several documents.
"""

from tests.support.docs import schema_map_doc
from tests.support.drive import PG_JSONSCHEMA_TABLE_SET, POSTGRES_TABLE_SET


def test_two_file_set_with_cross_file_refs() -> None:
    """The Goldberry shape: primitives in one file, resources composing them in another."""
    base = schema_map_doc(
        {"timestamp": {"type": "string", "pattern": "^2", "description": "A timestamp."}}, "base"
    )
    main = schema_map_doc(
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
                "x-pg-overflow": "extras",
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
    sql = POSTGRES_TABLE_SET.text(base, main)

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
    docs = schema_map_doc(
        {
            "thing": {
                "type": "object",
                "x-pg-table": "thing",
                "properties": {"x": {"$ref": "./missing.yaml#/nope"}},
            }
        }
    )
    assert any("missing.yaml" in m for m in POSTGRES_TABLE_SET.errors(docs))


def test_pg_jsonschema_check_has_no_unresolved_refs() -> None:
    """Inlining runs before serialization, so the embedded schema is self-contained."""
    base = schema_map_doc({"stamp": {"type": "string", "pattern": "^2"}}, "base")
    main = schema_map_doc(
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
    sql = PG_JSONSCHEMA_TABLE_SET.text(base, main)
    assert "jsonb_matches_schema(" in sql
    # pg_jsonschema cannot fetch a remote ref, so none may survive into the check.
    assert "$ref" not in sql
    assert "^2" in sql


def test_one_schema_name_may_not_be_used_in_two_files() -> None:
    """A set of schema-map files is one namespace, so the merge has to reject a clash."""
    first = schema_map_doc({"thing": {"type": "object", "x-pg-table": "a"}}, "first")
    second = schema_map_doc({"thing": {"type": "object", "x-pg-table": "b"}}, "second")
    [message] = POSTGRES_TABLE_SET.errors(first, second)
    assert "thing" in message
    assert "first.yaml" in message
    assert "second.yaml" in message
