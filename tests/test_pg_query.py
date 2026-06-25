"""Tests for the PostgreSQL query helpers.

Two layers are covered:

* `pg_query` (transpile-time): detecting which resource columns hold JSON.
* `pg_runtime` (the shipped runtime module): the `where`/`select`/`sort`
  compiler. The runtime module is package *data* (a `.jinja` template), so it is
  loaded and executed here exactly as the generated application would import it.
  This requires `psycopg`, a dev-only dependency.
"""

from __future__ import annotations

from importlib import resources
from typing import TYPE_CHECKING, Any

import orjson
import pytest

from schema_to import JsonSchemaRawDoc, MediaTypes
from schema_to.cst.json_schema import ObjectSchema
from schema_to.generate.pg_query import column_names, json_columns
from schema_to.parse.json_schema import JsonSchemaParser
from schema_to.result import Ok

if TYPE_CHECKING:
    from collections.abc import Mapping


# ---------------------------------------------------------------------------
# pg_query: JSON-column detection
# ---------------------------------------------------------------------------


def _object_schema(data: dict[str, Any]) -> ObjectSchema:
    doc = JsonSchemaRawDoc(
        doc_id="t://s", content=orjson.dumps(data), media_type=MediaTypes.json, display_name="s"
    )
    result = JsonSchemaParser().apply(doc)
    assert isinstance(result, Ok)
    root = result.value.root
    assert isinstance(root, ObjectSchema)
    return root


def test_json_columns_detects_object_array_and_extension() -> None:
    schema = _object_schema(
        {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "meta": {"type": "object"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "blob": {"type": "string", "x-pg-type": "jsonb"},
            },
        }
    )
    assert json_columns(schema) == frozenset({"meta", "tags", "blob"})
    assert set(column_names(schema)) == {"id", "name", "meta", "tags", "blob"}


def test_json_columns_empty_for_none() -> None:
    assert json_columns(None) == frozenset()
    assert column_names(None) == ()


# ---------------------------------------------------------------------------
# pg_runtime: runtime query compilation
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runtime() -> Mapping[str, Any]:
    """Load and execute the shipped `pg_runtime` template as a module namespace."""
    src = (
        resources.files("schema_to.generate") / "templates/postgres/pg_runtime.py.jinja"
    ).read_text()
    namespace: dict[str, Any] = {}
    exec(compile(src, "pg_runtime", "exec"), namespace)  # noqa: S102
    return namespace


def _sql(result: tuple[Any, Mapping[str, Any]]) -> tuple[str, Mapping[str, Any]]:
    """Render a ``(query, params)`` builder result to ``(sql_text, params)``."""
    query, params = result
    return query.as_string(), params


def test_list_query_select_sort_paging(runtime: Mapping[str, Any]) -> None:
    text, params = _sql(
        runtime["build_list_query"](
            schema="public",
            table="things",
            select="id,name",
            sort="-id,name",
            limit=10,
            offset=5,
        )
    )
    assert 'SELECT "id", "name" FROM "public"."things"' in text
    assert 'ORDER BY "id" DESC, "name" ASC' in text
    assert "LIMIT %(p0)s OFFSET %(p1)s" in text
    assert params == {"p0": 10, "p1": 5}


def test_list_query_default_select_is_star(runtime: Mapping[str, Any]) -> None:
    text, _ = _sql(runtime["build_list_query"](schema="public", table="t"))
    assert text == 'SELECT * FROM "public"."t"'


def test_where_comparisons_are_parameterised(runtime: Mapping[str, Any]) -> None:
    text, params = _sql(
        runtime["build_list_query"](schema="s", table="t", where="name eq 'bob' and age ge 18")
    )
    assert '("name" = %(p0)s AND "age" >= %(p1)s)' in text
    assert params == {"p0": "bob", "p1": 18}


def test_where_jsonb_path_and_or_not(runtime: Mapping[str, Any]) -> None:
    text, params = _sql(
        runtime["build_list_query"](
            schema="s",
            table="t",
            where="not (meta.theme eq 'dark' or active eq true)",
            json_columns=("meta",),
        )
    )
    assert 'NOT (("meta" #>> %(p0)s = %(p1)s OR "active" = %(p2)s))' in text
    assert params == {"p0": ["theme"], "p1": "dark", "p2": True}


def test_where_in_uses_any(runtime: Mapping[str, Any]) -> None:
    text, params = _sql(
        runtime["build_list_query"](schema="s", table="t", where="tags in ['a', 'b']")
    )
    assert '"tags" = ANY(%(p0)s)' in text
    assert params == {"p0": ["a", "b"]}


def test_string_literal_with_quote_is_safe(runtime: Mapping[str, Any]) -> None:
    text, params = _sql(
        runtime["build_list_query"](schema="s", table="t", where="name eq 'O''Brien'")
    )
    assert params == {"p0": "O'Brien"}
    assert "'O'" not in text  # value is bound, never interpolated


def test_addressing_into_non_json_column_is_rejected(runtime: Mapping[str, Any]) -> None:
    with pytest.raises(ValueError, match="non-JSON column"):
        runtime["build_list_query"](schema="s", table="t", where="name.first eq 'x'")


def test_get_and_delete_queries(runtime: Mapping[str, Any]) -> None:
    text, params = _sql(
        runtime["build_get_query"](schema="s", table="t", pk_column="id", pk_value=7)
    )
    assert text == 'SELECT * FROM "s"."t" WHERE "id" = %(p0)s'
    assert params == {"p0": 7}
    dtext, _ = _sql(
        runtime["build_delete_query"](schema="s", table="t", pk_column="id", pk_value=7)
    )
    assert dtext == 'DELETE FROM "s"."t" WHERE "id" = %(p0)s'


def test_merge_patch_builds_update(runtime: Mapping[str, Any]) -> None:
    text, params = _sql(
        runtime["build_merge_patch_query"](
            schema="s", table="t", pk_column="id", pk_value=1, patch={"name": "new"}
        )
    )
    assert 'UPDATE "s"."t" SET "name" = %(p0)s WHERE "id" = %(p1)s RETURNING *' in text
    assert params == {"p0": "new", "p1": 1}
