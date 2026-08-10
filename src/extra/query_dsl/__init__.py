"""query-dsl: parameterised PostgreSQL queries from REST query strings.

A small, dependency-light runtime for FastAPI (or any) services that expose REST
collections.  It compiles the ``select``/``where``/``sort``/``limit``/``offset``
query parameters into injection-safe ``psycopg.sql`` queries and provides
primary-key builders for the single-item operations.

The ``where`` grammar (compiled to a SQL predicate)::

    expr       := or_expr
    or_expr    := and_expr ( "or" and_expr )*
    and_expr   := not_expr ( "and" not_expr )*
    not_expr   := "not" not_expr | atom
    atom       := "(" expr ")" | comparison
    comparison := path OP value
    OP         := "eq" | "ne" | "lt" | "le" | "gt" | "ge" | "in" | "like"
    path       := IDENT ( "." IDENT )*      # dotted: nested keys address JSON
    value      := number | string | "true" | "false" | "null"
                  | "[" value ( "," value )* "]"

A dotted ``path`` whose head names a JSON column addresses into the JSON value:
``meta.theme`` becomes ``"meta" #>> '{theme}'``.

This package is generated for, and vendored by, schema-to as the runtime the
generated FastAPI endpoint bodies depend on; it is intended to be published
separately on PyPI.
"""

from query_dsl._builders import (
    build_delete_query,
    build_get_query,
    build_list_query,
    build_merge_patch_query,
    build_replace_query,
)
from query_dsl._compose import QueryError

__all__ = [
    "QueryError",
    "build_delete_query",
    "build_get_query",
    "build_list_query",
    "build_merge_patch_query",
    "build_replace_query",
]
