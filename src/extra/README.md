# query-dsl

Parameterised PostgreSQL queries built from REST query strings.

`query-dsl` compiles the `select` / `where` / `sort` / `limit` / `offset` query
parameters of a REST collection endpoint into injection-safe
[`psycopg.sql`](https://www.psycopg.org/psycopg3/docs/api/sql.html) queries, and
provides primary-key builders for the single-item operations. It is the runtime
that [schema-to](../../README.md)'s generated FastAPI endpoint bodies depend on.

> This package is staged inside the schema-to repository under `src/extra/`. It
> is meant to be extracted into its own repository and published to PyPI; until
> then it lives here and is exercised by schema-to's test suite.

## Usage

```python
from psycopg.rows import dict_row
from query_dsl import build_list_query

query, params = build_list_query(
    schema="public",
    table="things",
    where="name eq 'bob' and age ge 18",
    sort="-created_at",
    limit=20,
    json_columns=("meta",),
)
async with conn.cursor(row_factory=dict_row) as cur:
    await cur.execute(query, params)
    rows = await cur.fetchall()
```

### The `where` grammar

```
expr       := or_expr
or_expr    := and_expr ( "or" and_expr )*
and_expr   := not_expr ( "and" not_expr )*
not_expr   := "not" not_expr | atom
atom       := "(" expr ")" | comparison
comparison := path OP value
OP         := "eq" | "ne" | "lt" | "le" | "gt" | "ge" | "in" | "like"
path       := IDENT ( "." IDENT )*
value      := number | string | "true" | "false" | "null" | "[" value ( "," value )* "]"
```

A dotted `path` whose head names a JSON column addresses into the JSON value:
`meta.theme` becomes `"meta" #>> '{theme}'`. Malformed expressions raise
`query_dsl.QueryError` (a `ValueError`).
