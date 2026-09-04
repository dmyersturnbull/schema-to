"""Which schemas become tables, and what each `x-pg-*` keyword does to the DDL.

A keyword here is addressed to this generator,
so a malformed value raises rather than being quietly dropped.
"""

from tests.support.docs import schema_map_doc
from tests.support.drive import POSTGRES_TABLE_SET
from tests.support.stages import table_set_source

_THING = {"type": "object", "x-pg-table": "thing", "properties": {"id": {"type": "string"}}}


def test_primary_key_defaults_to_id() -> None:
    """Almost every resource is keyed by `id`; requiring the keyword on each would be noise."""
    assert "id text PRIMARY KEY" in table_set_source({"thing": _THING})


def test_table_without_id_or_declared_key_warns() -> None:
    docs = schema_map_doc(
        {
            "thing": {
                "type": "object",
                "x-pg-table": "thing",
                "properties": {"n": {"type": "string"}},
            }
        }
    )
    assert "no-primary-key" in POSTGRES_TABLE_SET.warnings(docs)


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def test_only_marked_schemas_become_tables() -> None:
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc({"thing-data": _THING, "thing-patch": {"type": "object"}})
    )
    assert "CREATE TABLE IF NOT EXISTS thing (" in sql
    assert "thing_patch" not in sql


def test_table_name_comes_from_the_keyword() -> None:
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc({"run-version-data": {**_THING, "x-pg-table": "run_version"}})
    )
    assert "CREATE TABLE IF NOT EXISTS run_version (" in sql


def test_schema_name_is_the_fallback_table_name() -> None:
    """`x-pg-table: true` is not valid; the keyword always names the table."""
    assert (
        "must be a non-empty string"
        in POSTGRES_TABLE_SET.errors(schema_map_doc({"thing": {**_THING, "x-pg-table": ""}}))[0]
    )


def test_two_schemas_cannot_declare_one_table() -> None:
    docs = schema_map_doc({"a-data": _THING, "b-data": _THING})
    assert "Two schemas both declare table 'thing'" in POSTGRES_TABLE_SET.errors(docs)[0]


def test_non_object_schema_marked_as_a_table_is_an_error() -> None:
    docs = schema_map_doc({"thing": {"type": "string", "x-pg-table": "thing"}})
    assert "not an object schema" in POSTGRES_TABLE_SET.errors(docs)[0]


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------


def test_primary_key_on_a_property() -> None:
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
            {
                "thing": {
                    "type": "object",
                    "x-pg-table": "thing",
                    "required": ["id"],
                    "properties": {"id": {"type": "string", "x-pg-primary-key": True}},
                }
            }
        )
    )
    assert "id text PRIMARY KEY" in sql
    # PRIMARY KEY already implies NOT NULL.
    assert "NOT NULL PRIMARY KEY" not in sql


def test_composite_primary_key_becomes_a_table_constraint() -> None:
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
            {
                "thing": {
                    "type": "object",
                    "x-pg-table": "thing",
                    "x-pg-primary-key": ["run", "alias"],
                    "properties": {"run": {"type": "string"}, "alias": {"type": "integer"}},
                }
            }
        )
    )
    assert "CONSTRAINT thing_pkey PRIMARY KEY (run, alias)" in sql


def test_foreign_key_from_a_table_name() -> None:
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
            {
                "other": {"type": "object", "x-pg-table": "other"},
                "thing": {
                    "type": "object",
                    "x-pg-table": "thing",
                    "properties": {"ref": {"type": "string", "x-pg-refs": "other"}},
                },
            }
        )
    )
    assert "ref text REFERENCES other" in sql


def test_foreign_key_with_actions() -> None:
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
            {
                "other": {"type": "object", "x-pg-table": "other"},
                "thing": {
                    "type": "object",
                    "x-pg-table": "thing",
                    "properties": {
                        "ref": {
                            "type": "string",
                            "x-pg-refs": {"table": "other", "column": "id", "on-delete": "cascade"},
                        }
                    },
                },
            }
        )
    )
    assert "REFERENCES other(id) ON DELETE CASCADE" in sql


def test_index_on_a_property() -> None:
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
            {
                "thing": {
                    "type": "object",
                    "x-pg-table": "thing",
                    "properties": {"ns": {"type": "string", "x-pg-index": True}},
                }
            }
        )
    )
    # `IF NOT EXISTS` precedes the name; PostgreSQL rejects the other order.
    assert "CREATE INDEX IF NOT EXISTS thing_ns_idx ON thing USING BTREE (ns);" in sql


def test_composite_index_from_the_schema() -> None:
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
            {
                "thing": {
                    "type": "object",
                    "x-pg-table": "thing",
                    "x-pg-indexes": [{"columns": ["a", "b"], "unique": True, "method": "btree"}],
                    "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
                }
            }
        )
    )
    assert "CREATE UNIQUE INDEX IF NOT EXISTS thing_a_b_idx ON thing USING BTREE (a, b);" in sql


def test_overflow_column() -> None:
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc({"thing": {**_THING, "x-pg-overflow": "unmodelled"}})
    )
    assert "unmodelled jsonb NOT NULL DEFAULT '{}'::jsonb" in sql


def test_column_rename() -> None:
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
            {
                "thing": {
                    "type": "object",
                    "x-pg-table": "thing",
                    "properties": {"end": {"type": "string", "x-pg-column": "end_time"}},
                }
            }
        )
    )
    assert "end_time text" in sql


def test_skip_omits_the_column() -> None:
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
            {
                "thing": {
                    "type": "object",
                    "x-pg-table": "thing",
                    "properties": {
                        "keep": {"type": "string"},
                        "drop": {"type": "string", "x-pg-skip": True},
                    },
                }
            }
        )
    )
    assert "keep text" in sql
    assert "drop" not in sql


def test_json_type_override_is_recognised_structurally() -> None:
    """`x-pg-type: jsonb` names a type the generator also understands, not an opaque string."""
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
            {
                "thing": {
                    "type": "object",
                    "x-pg-table": "thing",
                    "properties": {"payload": {"type": "string", "x-pg-type": "jsonb"}},
                }
            }
        )
    )
    assert "payload jsonb" in sql


def test_sql_type_override() -> None:
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
            {
                "thing": {
                    "type": "object",
                    "x-pg-table": "thing",
                    "properties": {"loc": {"type": "string", "x-pg-type": "geometry(Point,4326)"}},
                }
            }
        )
    )
    assert "loc geometry(Point,4326)" in sql
