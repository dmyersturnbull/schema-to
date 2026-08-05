"""Low-level SQL composition shared by the query builders.

Holds
the bound-parameter accumulator;
the JSON value adapter;
and helpers that turn dotted paths, `select` lists, and `sort` lists into `psycopg.sql` fragments.
Everything here is injection-safe:
Identifiers are quoted and every literal value is bound as a parameter.
"""


from collections.abc import Iterable, Mapping, Sequence

from psycopg import sql
from psycopg.types.json import Jsonb

__all__ = [
    "Bound",
    "Params",
    "QueryError",
    "Value",
    "adapt",
    "column_ref",
    "order_by",
    "select_list",
]

# A JSON-shaped value accepted from a request and bound into a query.
type Value = str | int | float | bool | Sequence[Value] | Mapping[str, Value] | None
# A value after JSON adaptation, as stored for `cursor.execute`.
type Bound = Value | Jsonb


class QueryError(ValueError):
    """Raised when a `where`/`select`/`sort` expression is malformed.

    Subclasses `ValueError` so callers may catch either.
    """


# Comparison operators accepted in a `where` expression, each mapped to its
# SQL spelling as a composable (built from a literal, so it is injection-safe).
OPERATORS: dict[str, sql.SQL] = {
    "eq": sql.SQL("="),
    "ne": sql.SQL("<>"),
    "lt": sql.SQL("<"),
    "le": sql.SQL("<="),
    "gt": sql.SQL(">"),
    "ge": sql.SQL(">="),
    "like": sql.SQL("LIKE"),
}


def adapt(value: Value) -> Bound:
    """Wrap JSON-shaped values so psycopg adapts them to `jsonb`."""
    if isinstance(value, (dict, list)):
        return Jsonb(value)
    return value


class Params:
    """Accumulates bound parameters and hands out named placeholders."""

    def __init__(self) -> None:
        self.values: dict[str, Bound] = {}

    def add(self, value: Bound) -> sql.Placeholder:
        name = f"p{len(self.values)}"
        self.values[name] = value
        return sql.Placeholder(name)


def _split_path(path: str) -> list[str]:
    return [p for p in path.split(".") if p]


def column_ref(path: str, json_columns: frozenset[str], params: Params) -> sql.Composable:
    """Build a column or JSON-extraction reference from a dotted path.

    A dotted path whose head names a JSON column addresses into the JSON value:
    `meta.theme` becomes `"meta" #>> '{theme}'`.
    """
    parts = _split_path(path)
    head = parts[0]
    if len(parts) == 1:
        return sql.Identifier(head)
    if head not in json_columns:
        msg = f"Cannot address into non-JSON column {head!r}."
        raise QueryError(msg)
    return sql.SQL("{} #>> {}").format(sql.Identifier(head), params.add(parts[1:]))


def select_list(select: str | None, json_columns: frozenset[str], params: Params) -> sql.Composable:
    """Compile a comma-separated `select` list, defaulting to `*`."""
    if not select:
        return sql.SQL("*")
    items: list[sql.Composable] = list(_select_items(select, json_columns, params))
    return sql.SQL(", ").join(items) if items else sql.SQL("*")


def _select_items(
    select: str, json_columns: frozenset[str], params: Params
) -> Iterable[sql.Composable]:
    for raw in select.split(","):
        path = raw.strip()
        if not path:
            continue
        col = column_ref(path, json_columns, params)
        if "." in path:
            col = sql.SQL("{} AS {}").format(col, sql.Identifier(path))
        yield col


def order_by(sort: str, json_columns: frozenset[str], params: Params) -> sql.Composable:
    """Compile a comma-separated `sort` list (`-` prefix means descending)."""
    return sql.SQL(", ").join(_order_items(sort, json_columns, params))


def _order_items(
    sort: str, json_columns: frozenset[str], params: Params
) -> Iterable[sql.Composable]:
    for raw in sort.split(","):
        token = raw.strip()
        if not token:
            continue
        descending = token.startswith("-")
        path = token[1:] if descending else token
        col = column_ref(path, json_columns, params)
        yield col + (sql.SQL(" DESC") if descending else sql.SQL(" ASC"))
