# PostgreSQL endpoint bodies via the extension mechanism

This example shows how to fill generated FastAPI route bodies **without** any
PostgreSQL knowledge in schema-to. The persistence layer lives entirely in the
OpenAPI document, expressed through three extension keywords, plus the
standalone [`query-dsl`](../../src/extra/) runtime library.

Generate the app with the plain `fastapi` target:

```bash
schema-to --to fastapi examples/postgres/openapi.yaml -o out/
```

The generated `out/main.py` depends on `query-dsl` (install it) and on the
[`_db.py`](./_db.py) glue module in this directory (copy it next to `main.py`,
then wire `get_db` to a real connection pool).

## The extension keywords

Each operation (or path item) may carry:

| Keyword             | Value                                                              |
| ------------------- | ----------------------------------------------------------------- |
| `x-fastapi-body`    | A Jinja template rendered into the route body.                    |
| `x-fastapi-imports` | A list of import statements the body needs.                       |
| `x-fastapi-params`  | Extra signature parameters: `{name, annotation?, default?, kind?}`. |

Operation-level values override path-item-level values, so shared parameters
(like the injected `conn`) can be declared once per path.

## Template context

`x-fastapi-body` is rendered with:

- `ext` — the merged `x-` extensions (read your own keys here, e.g.
  `x-pg-table`, `x-pg-schema`, `x-pg-id`).
- `arg(role)` — the Python name of a parameter by role (`id`, `body`, `select`,
  `where`, `sort`, `limit`, `offset`), or the literal `None` when absent.
- `json_columns` — resource properties holding JSON (object-/array-typed),
  passed to `build_list_query` so dotted `where` paths can address into them.
- `method`, `path`, `operation`, `params`, `params_by_name`, `params_by_role`.
- The `| py` filter renders a value as a Python literal (it is `repr`).
- The REST helpers `is_item_path`, `resource_name`, `infer_operation`,
  `role_for_param`, and the `RestOperation` / `ParamRole` enums.

## The templates

The `x-fastapi-body` blocks in [`openapi.yaml`](./openapi.yaml) are the
reference templates — one per REST operation (list, get, replace, merge-patch,
delete). They double as documentation for writing your own backend (SQLite, an
HTTP upstream, an in-memory store, …): swap the imports and the body, and
schema-to renders whatever code you provide.
