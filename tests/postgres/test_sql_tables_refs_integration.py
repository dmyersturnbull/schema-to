"""References between tables: foreign keys, declaration order, quoting, and deferral.

A table is declared after the tables it references, and a cycle warns rather than hanging.
"""

import pytest
from tests.support.docs import schema_map_doc
from tests.support.drive import POSTGRES_TABLE_SET

from schema_to.errors import GenerationError
from schema_to.generate.postgres._pg_keywords import read_property_keywords, read_table_keywords

_THING = {"type": "object", "x-pg-table": "thing", "properties": {"id": {"type": "string"}}}


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
# x-pg-pk-for
# ---------------------------------------------------------------------------

_AUTHOR_ID = {"type": "string", "pattern": "^[A-Z][a-z]*$", "x-pg-pk-for": "authors"}


def test_ref_to_a_pk_for_schema_becomes_a_foreign_key() -> None:
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
            {
                "author-id": _AUTHOR_ID,
                "author": {
                    "type": "object",
                    "x-pg-table": "authors",
                    "properties": {"id": {"$ref": "#/author-id"}},
                },
                "book": {
                    "type": "object",
                    "x-pg-table": "books",
                    "properties": {"author": {"$ref": "#/author-id"}, "title": {"type": "string"}},
                },
            }
        )
    )
    assert "REFERENCES authors" in sql


def test_ref_to_a_pk_for_schema_within_its_own_table_is_not_a_foreign_key() -> None:
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
            {
                "author-id": _AUTHOR_ID,
                "author": {
                    "type": "object",
                    "x-pg-table": "authors",
                    "properties": {"id": {"$ref": "#/author-id"}},
                },
            }
        )
    )
    assert "id text PRIMARY KEY CHECK" in sql
    assert "REFERENCES" not in sql


def test_explicit_refs_overrides_pk_for() -> None:
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
            {
                "author-id": _AUTHOR_ID,
                "author": {
                    "type": "object",
                    "x-pg-table": "authors",
                    "properties": {"id": {"$ref": "#/author-id"}},
                },
                "editor": {"type": "object", "x-pg-table": "editors"},
                "book": {
                    "type": "object",
                    "x-pg-table": "books",
                    "properties": {"author": {"$ref": "#/author-id", "x-pg-refs": "editors"}},
                },
            }
        )
    )
    assert "REFERENCES editors" in sql
    assert "REFERENCES authors" not in sql


def test_pk_for_orders_the_referenced_table_first() -> None:
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
            {
                "author-id": _AUTHOR_ID,
                "book": {
                    "type": "object",
                    "x-pg-table": "books",
                    "properties": {"author": {"$ref": "#/author-id"}},
                },
                "author": {
                    "type": "object",
                    "x-pg-table": "authors",
                    "properties": {"id": {"$ref": "#/author-id"}},
                },
            }
        )
    )
    assert sql.index("CREATE TABLE IF NOT EXISTS authors") < sql.index(
        "CREATE TABLE IF NOT EXISTS books"
    )


def test_pk_for_pointing_at_an_undeclared_table_warns() -> None:
    docs = schema_map_doc(
        {
            "author-id": _AUTHOR_ID,
            "book": {
                "type": "object",
                "x-pg-table": "books",
                "properties": {"author": {"$ref": "#/author-id"}},
            },
        }
    )
    assert "unknown-fk-target" in POSTGRES_TABLE_SET.warnings(docs)


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_referenced_table_is_declared_first() -> None:
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
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
    docs = schema_map_doc(
        {
            "thing": {
                "type": "object",
                "x-pg-table": "thing",
                "properties": {"ref": {"type": "string", "x-pg-refs": "elsewhere"}},
            }
        }
    )
    assert "unknown-fk-target" in POSTGRES_TABLE_SET.warnings(docs)


def test_reference_cycle_warns_instead_of_hanging() -> None:
    docs = schema_map_doc(
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
    assert "reference-cycle" in POSTGRES_TABLE_SET.warnings(docs)


def test_self_reference_is_not_a_cycle() -> None:
    docs = schema_map_doc(
        {
            "node": {
                "type": "object",
                "x-pg-table": "node",
                "properties": {"parent": {"type": "string", "x-pg-refs": "node"}},
            }
        }
    )
    assert "reference-cycle" not in POSTGRES_TABLE_SET.warnings(docs)


# ---------------------------------------------------------------------------
# Identifier quoting
# ---------------------------------------------------------------------------


def test_reserved_words_are_quoted() -> None:
    """Goldberry has properties named `end`, `group`, `left`, and `right`."""
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
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
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
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
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
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
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
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
    sql = POSTGRES_TABLE_SET.text(
        schema_map_doc(
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
