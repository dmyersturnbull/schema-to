"""Tests for the `query-dsl` runtime library (src/extra/query_dsl).

This is the standalone runtime the generated FastAPI bodies depend on. It is
staged under `src/extra/` (added to the test pythonpath) and requires psycopg.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from query_dsl import (
    QueryError,
    build_delete_query,
    build_get_query,
    build_list_query,
    build_merge_patch_query,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from psycopg import sql


def _sql(result: tuple[sql.Composable, Mapping[str, Any]]) -> tuple[str, Mapping[str, Any]]:
    query, params = result
    return query.as_string(), params


def test_list_query_select_sort_paging() -> None:
    text, params = _sql(
        build_list_query(
            schema="public", table="things", select="id,name", sort="-id,name", limit=10, offset=5
        )
    )
    assert 'SELECT "id", "name" FROM "public"."things"' in text
    assert 'ORDER BY "id" DESC, "name" ASC' in text
    assert "LIMIT %(p0)s OFFSET %(p1)s" in text
    assert params == {"p0": 10, "p1": 5}


def test_list_query_default_select_is_star() -> None:
    text, _ = _sql(build_list_query(schema="public", table="t"))
    assert text == 'SELECT * FROM "public"."t"'


def test_where_comparisons_are_parameterised() -> None:
    text, params = _sql(
        build_list_query(schema="s", table="t", where="name eq 'bob' and age ge 18")
    )
    assert '("name" = %(p0)s AND "age" >= %(p1)s)' in text
    assert params == {"p0": "bob", "p1": 18}


def test_where_jsonb_path_and_or_not() -> None:
    text, params = _sql(
        build_list_query(
            schema="s",
            table="t",
            where="not (meta.theme eq 'dark' or active eq true)",
            json_columns=("meta",),
        )
    )
    assert 'NOT (("meta" #>> %(p0)s = %(p1)s OR "active" = %(p2)s))' in text
    assert params == {"p0": ["theme"], "p1": "dark", "p2": True}


def test_where_in_uses_any() -> None:
    text, params = _sql(build_list_query(schema="s", table="t", where="tags in ['a', 'b']"))
    assert '"tags" = ANY(%(p0)s)' in text
    assert params == {"p0": ["a", "b"]}


def test_string_literal_with_quote_is_safe() -> None:
    text, params = _sql(build_list_query(schema="s", table="t", where="name eq 'O''Brien'"))
    assert params == {"p0": "O'Brien"}
    assert "'O'" not in text  # value is bound, never interpolated


def test_addressing_into_non_json_column_is_rejected() -> None:
    with pytest.raises(QueryError, match="non-JSON column"):
        build_list_query(schema="s", table="t", where="name.first eq 'x'")


def test_query_error_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown operator"):
        build_list_query(schema="s", table="t", where="name foo 1")


def test_get_and_delete_queries() -> None:
    text, params = _sql(build_get_query(schema="s", table="t", pk_column="id", pk_value=7))
    assert text == 'SELECT * FROM "s"."t" WHERE "id" = %(p0)s'
    assert params == {"p0": 7}
    dtext, _ = _sql(build_delete_query(schema="s", table="t", pk_column="id", pk_value=7))
    assert dtext == 'DELETE FROM "s"."t" WHERE "id" = %(p0)s'


def test_merge_patch_builds_update() -> None:
    text, params = _sql(
        build_merge_patch_query(
            schema="s", table="t", pk_column="id", pk_value=1, patch={"name": "new"}
        )
    )
    assert 'UPDATE "s"."t" SET "name" = %(p0)s WHERE "id" = %(p1)s RETURNING *' in text
    assert params == {"p0": "new", "p1": 1}
