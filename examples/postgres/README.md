# PostgreSQL endpoint bodies via the extension mechanism

This example fills generated FastAPI route bodies **without** any PostgreSQL knowledge in schema-to.
The persistence layer lives in Jinja templates,
which generate code that use
[query-dsl](https://github.com/sauron-lab/query-dsl)
at runtime.
The OpenAPI document references the templates
and declares the imports and parameters each operation needs.

## Generating the app

Register each template by name with
`--template <name>=<path>` (repeatable)
and transpile with the plain `fastapi` target:

```bash
schema-to --to fastapi \
  --template list=examples/postgres/templates/list.py.jinja \
  --template get=examples/postgres/templates/get.py.jinja \
  --template put=examples/postgres/templates/put.py.jinja \
  --template patch=examples/postgres/templates/patch.py.jinja \
  --template delete=examples/postgres/templates/delete.py.jinja \
  examples/postgres/things.openapi.yaml -o out/
```

The generated `out/main.py` depends on 
the [`_db.py`](./_db.py) glue module here.
Copy it next to `main.py`, then wire `get_db` to a real connection pool.

## The extension keywords

Each operation (or path item) may carry:

| Keyword               | Value                                                                |
| --------------------- | -------------------------------------------------------------------- |
| `x-fastapi-template`  | The name of a template registered with `--template` (recommended).   |
| `x-fastapi-body`      | An inline Jinja template string (alternative to `x-fastapi-template`).|
| `x-fastapi-imports`   | A list of import statements the body needs.                          |
| `x-fastapi-params`    | Extra signature parameters: `{name, annotation?, default?, kind?}`.  |

Operation-level values override path-item-level values,
so shared parameters (like the injected `conn`) can be declared once per path.
Named templates are preferred over the inline `x-fastapi-body`.

## Template context

Templates render with this context, which is not PostgreSQL-specific:

| Name                | What it is                                                            |
| ------------------- | --------------------------------------------------------------------- |
| `method`, `path`    | The HTTP method and path template.                                    |
| `operation_id`      | The operation's `operationId`, if any.                                |
| `operation`         | The inferred `RestOperation` (`list`, `get`, `put`, `patch`, `delete`).|
| `params`            | The resolved route parameters (`name`, `py_name`, `location`).        |
| `param(name)`       | The Python name of a parameter by its OpenAPI name, or `None`.        |
| `params_by_name`    | Mapping of OpenAPI name → Python name.                                 |
| `ext`               | The merged `x-` extensions (read your own keys here, e.g. `x-pg-table`).|
| `json_properties`   | Resource property names whose JSON Schema type is object or array.    |

Filters and globals:

| Helper                          | Purpose                                              |
| ------------------------------- | ---------------------------------------------------- |
| `\| repr`                       | Render a value as a Python literal (it is `repr`).   |
| `is_item_path(path)`            | True if the path ends in a templated segment.        |
| `resource_name(path)`           | The last non-templated path segment.                 |
| `infer_operation(method, path)` | The `RestOperation` for a path/method pair.          |
| `RestOperation`                 | The operation enum, for comparisons.                 |

Templates own all query-convention knowledge.
The names `where`, `select`, `sort`, etc. are just the parameter names this example uses;
the template reads them with `param("where")` and passes them to query-dsl.
Likewise `json_properties` is derived purely from the JSON Schema types of the resource's properties (object/array ⇒ JSON);
there is no PostgreSQL-specific configuration involved.

## The templates

[`templates/`](./templates) holds one template per REST operation.
They are the recommended starting point for writing your own backend.
Swap the imports and the body and register them with `--template`.
schema-to will render whatever code you provide.
