import re
from collections.abc import Set

from caseutil import to_snake

_NON_IDENT = re.compile(r"\W")


def safe_sql_identifier(name: str) -> str:
    """Return a valid lowercase PostgreSQL identifier derived from *name*.

    Applies snake_case conversion,
    strips non-identifier characters,
    and prepends `col_` if the result starts with a digit.

    Returns `col_` for empty input.
    Does not quote reserved words; pass the result through `quote_sql_identifier` to emit it.
    """
    snake = to_snake(name) or "col_"
    snake = _NON_IDENT.sub("_", snake)
    snake = re.sub(r"_+", "_", snake).strip("_") or "col_"
    if snake[0].isdigit():
        snake = "col_" + snake
    return snake.lower()


# Words PostgreSQL will not accept as a bare column or table name.
# Drawn from the `reserved` and `type_func_name` categories of the keyword table in
# https://www.postgresql.org/docs/current/sql-keywords-appendix.html — the two that a
# name must be quoted to escape.  The `non_reserved` and `col_name` categories are
# usable bare and are deliberately absent.
_SQL_RESERVED: Set[str] = frozenset(
    [
        "all",
        "analyse",
        "analyze",
        "and",
        "any",
        "array",
        "as",
        "asc",
        "asymmetric",
        "authorization",
        "binary",
        "both",
        "case",
        "cast",
        "check",
        "collate",
        "collation",
        "column",
        "concurrently",
        "constraint",
        "create",
        "cross",
        "current_catalog",
        "current_date",
        "current_role",
        "current_schema",
        "current_time",
        "current_timestamp",
        "current_user",
        "default",
        "deferrable",
        "desc",
        "distinct",
        "do",
        "else",
        "end",
        "except",
        "false",
        "fetch",
        "for",
        "foreign",
        "freeze",
        "from",
        "full",
        "grant",
        "group",
        "having",
        "ilike",
        "in",
        "initially",
        "inner",
        "intersect",
        "into",
        "is",
        "isnull",
        "join",
        "lateral",
        "leading",
        "left",
        "like",
        "limit",
        "localtime",
        "localtimestamp",
        "natural",
        "not",
        "notnull",
        "null",
        "offset",
        "on",
        "only",
        "or",
        "order",
        "outer",
        "overlaps",
        "placing",
        "primary",
        "references",
        "returning",
        "right",
        "select",
        "session_user",
        "similar",
        "some",
        "symmetric",
        "system_user",
        "table",
        "tablesample",
        "then",
        "to",
        "trailing",
        "true",
        "union",
        "unique",
        "user",
        "using",
        "variadic",
        "verbose",
        "when",
        "where",
        "window",
        "with",
    ]
)
_BARE_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def quote_sql_identifier(name: str) -> str:
    """Return *name* ready to appear in SQL, double-quoted only when it has to be.

    Quoting is not free: a quoted identifier is case-sensitive and must then be quoted
    everywhere it appears.  So quote only what PostgreSQL would otherwise reject — a
    reserved word such as `end` or `group`, or a name with characters outside
    `[a-z0-9_]` — and leave ordinary names bare, which keeps generated DDL readable
    and hand-editable.

    A name already containing a double quote is assumed to be a qualified or
    pre-quoted expression (`myschema.things`) and is passed through untouched.
    """
    if "." in name or '"' in name:
        return name
    if _BARE_IDENTIFIER.match(name) and name not in _SQL_RESERVED:
        return name
    return '"' + name.replace('"', '""') + '"'
