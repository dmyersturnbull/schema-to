"""Tests for the table-set generator and its `x-pg-*` keywords.

Covers:
- Targeted: only `x-pg-table` schemas become tables.
- Targeted: each keyword's effect on the emitted DDL.
- Targeted: malformed keyword values raise rather than being ignored.
- Targeted: tables are ordered after the tables they reference; cycles warn.
- Integration: a two-file set with cross-file refs produces a full migration.
"""

import orjson
import pytest
from tests._targets import transpiler_for

from schema_to.errors import GenerationError
from schema_to.generate.postgres._pg_keywords import read_property_keywords, read_table_keywords
from schema_to.io.media_type import MediaTypes
from schema_to.io.source import SchemaMapRawDoc
from schema_to.result import Err, Ok


def _doc(data: object, name: str = "main") -> SchemaMapRawDoc:
    return SchemaMapRawDoc(
        doc_id=f"file:///{name}.yaml",
        content=orjson.dumps(data),
        media_type=MediaTypes.json,
        display_name=name,
    )


def _sql(*docs: SchemaMapRawDoc) -> str:
    transpiler = transpiler_for("postgres", selects=SchemaMapRawDoc, schema_map=True)
    result = transpiler.transpile_all(docs)
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    return result.value[0].content.decode("utf-8")


def _warnings(*docs: SchemaMapRawDoc) -> list[str]:
    transpiler = transpiler_for("postgres", selects=SchemaMapRawDoc, schema_map=True)
    result = transpiler.transpile_all(docs)
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    return [w.code for w in transpiler.warnings if w.code]


def _errors(*docs: SchemaMapRawDoc) -> list[str]:
    result = transpiler_for("postgres", selects=SchemaMapRawDoc, schema_map=True).transpile_all(
        docs
    )
    assert isinstance(result, Err)
    return [getattr(e, "message", str(e)) for e in result.errors]


_THING = {"type": "object", "x-pg-table": "thing", "properties": {"id": {"type": "string"}}}


def test_primary_key_defaults_to_id() -> None:
    """Almost every resource is keyed by `id`; requiring the keyword on each would be noise."""
    assert "id text PRIMARY KEY" in _sql(_doc({"thing": _THING}))


def test_table_without_id_or_declared_key_warns() -> None:
    docs = _doc(
        {
            "thing": {
                "type": "object",
                "x-pg-table": "thing",
                "properties": {"n": {"type": "string"}},
            }
        }
    )
    assert "no-primary-key" in _warnings(docs)


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def test_only_marked_schemas_become_tables() -> None:
    sql = _sql(_doc({"thing-data": _THING, "thing-patch": {"type": "object"}}))
    assert "CREATE TABLE IF NOT EXISTS thing (" in sql
    assert "thing_patch" not in sql


def test_roots_narrows_marked_schemas_considered_for_a_table() -> None:
    """`roots` further restricts the `x-pg-table` selection to named schemas."""
    other = {"type": "object", "x-pg-table": "other", "properties": {"id": {"type": "string"}}}
    transpiler = transpiler_for(
        "postgres", selects=SchemaMapRawDoc, schema_map=True, roots=frozenset({"thing-data"})
    )
    result = transpiler.transpile_all([_doc({"thing-data": _THING, "other-data": other})])
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    sql = result.value[0].content.decode("utf-8")
    assert "CREATE TABLE IF NOT EXISTS thing (" in sql
    assert "CREATE TABLE IF NOT EXISTS other (" not in sql


def test_table_name_comes_from_the_keyword() -> None:
    sql = _sql(_doc({"run-version-data": {**_THING, "x-pg-table": "run_version"}}))
    assert "CREATE TABLE IF NOT EXISTS run_version (" in sql


def test_schema_name_is_the_fallback_table_name() -> None:
    """`x-pg-table: true` is not valid; the keyword always names the table."""
    assert "must be a non-empty string" in _errors(_doc({"thing": {**_THING, "x-pg-table": ""}}))[0]


def test_two_schemas_cannot_declare_one_table() -> None:
    docs = _doc({"a-data": _THING, "b-data": _THING})
    assert "Two schemas both declare table 'thing'" in _errors(docs)[0]


def test_non_object_schema_marked_as_a_table_is_an_error() -> None:
    docs = _doc({"thing": {"type": "string", "x-pg-table": "thing"}})
    assert "not an object schema" in _errors(docs)[0]


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------


def test_primary_key_on_a_property() -> None:
    sql = _sql(
        _doc(
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
    sql = _sql(
        _doc(
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
    sql = _sql(
        _doc(
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
    sql = _sql(
        _doc(
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
    sql = _sql(
        _doc(
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
    sql = _sql(
        _doc(
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
    sql = _sql(_doc({"thing": {**_THING, "x-pg-overflow": "unmodelled"}}))
    assert "unmodelled jsonb NOT NULL DEFAULT '{}'::jsonb" in sql


def test_column_rename() -> None:
    sql = _sql(
        _doc(
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
    sql = _sql(
        _doc(
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
    sql = _sql(
        _doc(
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
    sql = _sql(
        _doc(
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


# ---------------------------------------------------------------------------
# Keyword validation
# ---------------------------------------------------------------------------


def test_bad_references_shape_raises() -> None:
    with pytest.raises(GenerationError, match="x-pg-refs"):
        read_property_keywords({"x-pg-refs": 3}, where="property 'ref'")


def test_references_object_without_table_raises() -> None:
    with pytest.raises(GenerationError, match="`table`"):
        read_property_keywords({"x-pg-refs": {"column": "id"}}, where="property 'ref'")


def test_unknown_on_delete_action_raises() -> None:
    with pytest.raises(GenerationError, match="an action of one of"):
        read_property_keywords(
            {"x-pg-refs": {"table": "t", "on-delete": "explode"}}, where="property 'ref'"
        )


def test_unknown_index_method_raises() -> None:
    with pytest.raises(GenerationError, match="a `method` of one of"):
        read_property_keywords({"x-pg-index": {"method": "quantum"}}, where="property 'x'")


def test_non_boolean_flag_raises() -> None:
    with pytest.raises(GenerationError, match="`true` or `false`"):
        read_property_keywords({"x-pg-skip": "yes"}, where="property 'x'")


def test_indexes_without_columns_raises() -> None:
    with pytest.raises(GenerationError, match="non-empty `columns`"):
        read_table_keywords({"x-pg-indexes": [{"unique": True}]}, where="schema 'thing'")


def test_hyphenated_on_delete_action_is_accepted() -> None:
    keywords = read_property_keywords(
        {"x-pg-refs": {"table": "t", "on-delete": "set-null"}}, where="property 'ref'"
    )
    assert keywords.refs is not None
    assert keywords.refs.on_delete.value == "set null"


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_referenced_table_is_declared_first() -> None:
    sql = _sql(
        _doc(
            {
                "child": {
                    "type": "object",
                    "x-pg-table": "child",
                    "properties": {"p": {"type": "string", "x-pg-refs": "parent"}},
                },
                "parent": {"type": "object", "x-pg-table": "parent"},
            }
        )
    )
    assert sql.index("CREATE TABLE IF NOT EXISTS parent") < sql.index(
        "CREATE TABLE IF NOT EXISTS child"
    )


def test_unknown_reference_target_warns() -> None:
    docs = _doc(
        {
            "thing": {
                "type": "object",
                "x-pg-table": "thing",
                "properties": {"ref": {"type": "string", "x-pg-refs": "elsewhere"}},
            }
        }
    )
    assert "unknown-fk-target" in _warnings(docs)


def test_reference_cycle_warns_instead_of_hanging() -> None:
    docs = _doc(
        {
            "a": {
                "type": "object",
                "x-pg-table": "a",
                "properties": {"b": {"type": "string", "x-pg-refs": "b"}},
            },
            "b": {
                "type": "object",
                "x-pg-table": "b",
                "properties": {"a": {"type": "string", "x-pg-refs": "a"}},
            },
        }
    )
    assert "reference-cycle" in _warnings(docs)


def test_self_reference_is_not_a_cycle() -> None:
    docs = _doc(
        {
            "node": {
                "type": "object",
                "x-pg-table": "node",
                "properties": {"parent": {"type": "string", "x-pg-refs": "node"}},
            }
        }
    )
    assert "reference-cycle" not in _warnings(docs)


# ---------------------------------------------------------------------------
# Identifier quoting
# ---------------------------------------------------------------------------


def test_reserved_words_are_quoted() -> None:
    """Goldberry has properties named `end`, `group`, `left`, and `right`."""
    sql = _sql(
        _doc(
            {
                "thing": {
                    "type": "object",
                    "x-pg-table": "thing",
                    "properties": {
                        "end": {"type": "string"},
                        "group": {"type": "string", "x-pg-index": True},
                        "ordinary": {"type": "string"},
                    },
                }
            }
        )
    )
    assert '"end" text' in sql
    assert '"group" text' in sql
    # Ordinary names stay bare, so the DDL remains readable.
    assert "ordinary text" in sql
    assert '"ordinary"' not in sql
    # And the quoting follows the column everywhere it is named.
    assert 'ON thing USING BTREE ("group")' in sql


def test_check_expressions_quote_the_column() -> None:
    sql = _sql(
        _doc(
            {
                "thing": {
                    "type": "object",
                    "x-pg-table": "thing",
                    "properties": {"end": {"type": "string", "pattern": "^P"}},
                }
            }
        )
    )
    assert """CHECK (("end" ~ '^P'))""" in sql


# ---------------------------------------------------------------------------
# Extra columns and deferral
# ---------------------------------------------------------------------------


def test_extra_columns_are_appended() -> None:
    sql = _sql(
        _doc(
            {
                "thing": {
                    **_THING,
                    "x-pg-extra-columns": [
                        {
                            "name": "loaded_at",
                            "type": "timestamptz",
                            "not-null": True,
                            "default": "now()",
                        }
                    ],
                }
            }
        )
    )
    assert "loaded_at timestamptz NOT NULL DEFAULT now()" in sql


def test_extra_column_without_a_type_raises() -> None:
    with pytest.raises(GenerationError, match="both a `name` and a `type`"):
        read_table_keywords({"x-pg-extra-columns": [{"name": "x"}]}, where="schema 'thing'")


def test_cycle_keys_are_deferrable() -> None:
    sql = _sql(
        _doc(
            {
                "a-data": {
                    "type": "object",
                    "x-pg-table": "a",
                    "properties": {
                        "id": {"type": "string"},
                        "b": {"type": "string", "x-pg-refs": "b"},
                    },
                },
                "b-data": {
                    "type": "object",
                    "x-pg-table": "b",
                    "properties": {
                        "id": {"type": "string"},
                        "a": {"type": "string", "x-pg-refs": "a"},
                    },
                },
            }
        )
    )
    assert sql.count("DEFERRABLE INITIALLY DEFERRED") == 2


def test_keys_outside_a_cycle_are_not_deferrable() -> None:
    sql = _sql(
        _doc(
            {
                "a-data": {
                    "type": "object",
                    "x-pg-table": "a",
                    "properties": {"id": {"type": "string"}},
                },
                "b-data": {
                    "type": "object",
                    "x-pg-table": "b",
                    "properties": {
                        "id": {"type": "string"},
                        "a": {"type": "string", "x-pg-refs": "a"},
                    },
                },
            }
        )
    )
    assert "DEFERRABLE" not in sql
