"""Parameterised PostgreSQL query builders for REST collection/item operations.

Each builder returns `(query, params)`,
where `query` is a `psycopg.sql` composable and `params` is the bound-parameter mapping,
ready to pass straight to `cursor.execute`.
The list builder interprets the `select`/`where`/`sort`/`limit`/`offset` query strings;
the others act on a primary key.
"""


from typing import TYPE_CHECKING

from psycopg import sql

from query_dsl._compose import Bound, Params, Value, adapt, order_by, select_list
from query_dsl._where import parse_where

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "build_delete_query",
    "build_get_query",
    "build_list_query",
    "build_merge_patch_query",
    "build_replace_query",
]


def build_list_query(
    *,
    schema: str,
    table: str,
    select: str | None = None,
    where: str | None = None,
    sort: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    json_columns: Sequence[str] = (),
) -> tuple[sql.Composable, Mapping[str, Bound]]:
    """Build a parameterised `SELECT` for a list operation."""
    params = Params()
    json_cols = frozenset(json_columns)
    query = sql.SQL("SELECT {} FROM {}.{}").format(
        select_list(select, json_cols, params), sql.Identifier(schema), sql.Identifier(table)
    )
    if where:
        query = query + sql.SQL(" WHERE ") + parse_where(where, json_cols, params)
    if sort:
        query = query + sql.SQL(" ORDER BY ") + order_by(sort, json_cols, params)
    if limit is not None:
        query = query + sql.SQL(" LIMIT ") + params.add(int(limit))
    if offset is not None:
        query = query + sql.SQL(" OFFSET ") + params.add(int(offset))
    return query, params.values


def build_get_query(
    *, schema: str, table: str, pk_column: str, pk_value: Value
) -> tuple[sql.Composable, Mapping[str, Bound]]:
    """Build a parameterised single-row `SELECT` by primary key."""
    params = Params()
    query = sql.SQL("SELECT * FROM {}.{} WHERE {} = {}").format(
        sql.Identifier(schema),
        sql.Identifier(table),
        sql.Identifier(pk_column),
        params.add(pk_value),
    )
    return query, params.values


def build_delete_query(
    *, schema: str, table: str, pk_column: str, pk_value: Value
) -> tuple[sql.Composable, Mapping[str, Bound]]:
    """Build a parameterised `DELETE` by primary key."""
    params = Params()
    query = sql.SQL("DELETE FROM {}.{} WHERE {} = {}").format(
        sql.Identifier(schema),
        sql.Identifier(table),
        sql.Identifier(pk_column),
        params.add(pk_value),
    )
    return query, params.values


def build_replace_query(
    *, schema: str, table: str, pk_column: str, pk_value: Value, data: Mapping[str, Value]
) -> tuple[sql.Composable, Mapping[str, Bound]]:
    """Build a parameterised upsert (`INSERT ... ON CONFLICT DO UPDATE`)."""
    params = Params()
    payload = {**dict(data), pk_column: pk_value}
    columns = list(payload)
    col_ids = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    values = sql.SQL(", ").join(params.add(adapt(payload[c])) for c in columns)
    updates = sql.SQL(", ").join(
        sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(c), sql.Identifier(c))
        for c in columns
        if c != pk_column
    )
    query = sql.SQL(
        "INSERT INTO {}.{} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {} RETURNING *"
    ).format(
        sql.Identifier(schema),
        sql.Identifier(table),
        col_ids,
        values,
        sql.Identifier(pk_column),
        updates,
    )
    return query, params.values


def build_merge_patch_query(
    *, schema: str, table: str, pk_column: str, pk_value: Value, patch: Mapping[str, Value]
) -> tuple[sql.Composable, Mapping[str, Bound]]:
    """Build a parameterised RFC 7396 merge-patch `UPDATE` by primary key."""
    params = Params()
    assignments = [
        sql.SQL("{} = {}").format(sql.Identifier(key), params.add(adapt(value)))
        for key, value in patch.items()
    ]
    if not assignments:
        return build_get_query(schema=schema, table=table, pk_column=pk_column, pk_value=pk_value)
    query = sql.SQL("UPDATE {}.{} SET {} WHERE {} = {} RETURNING *").format(
        sql.Identifier(schema),
        sql.Identifier(table),
        sql.SQL(", ").join(assignments),
        sql.Identifier(pk_column),
        params.add(pk_value),
    )
    return query, params.values
