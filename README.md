# schema-to

Transpile JSON Schema 2020-12 into PostgreSQL DDLs, TypeScript defs, and Python types,
and transpile OpenAPI 3.1 and 3.2 docs into FastAPI endpoints.

### Rationale

[OpenAPI 3.1](https://www.openapis.org/blog/2021/02/16/migrating-from-openapi-3-0-to-3-1-0)
introduced very important features, including full compatibility with JSON Schema, specifically the still-current version 2020-12.
Unfortunately, 4 years later, most OpenAPI tools are still limited to 3.0.
Similarly, most JSON Schema tools are stuck on 2019-09.

We need better tools for schema-first projects.
`schema-to` transpiles modern OpenAPI and JSON Schema docs into SQL, TypeScript, Python, and CommonMark.
It should be easy to add new languages to that list.

### Goals

- Define abstractions formally and expose them in an API.
  Keep transpilation stages decoupled.
  Use a concrete syntax tree (CST) for the input (OpenAPI / JSON Schema),
  with dedicated support for all standard keywords.
- Support composing or "nesting" transpilation pipelines.
  This means for nested input, such as OpenAPI containing JSON Schema (as `schema`) and CommonMark (as `description`).
  It also means for nested output, such as
  [pg_jsonschema](https://github.com/supabase/pg_jsonschema) validation of `jsonb` types.
- Allow reading multiple sources, exposing their filenames.
  E.g. to generate a table per `table-name.schema.json`.
- High performance.
- No non-obvious/magic special cases, and minimal behavior-changing switches (e.g. no `--text-as-github-flavored-markdown`).

### Planned targets

- JSON Schema → PostgreSQL.
  Define JSON Schema extensions if/as needed (e.g. `x-is-table` and `x-is-fk`).
- JSON Schema → [pg_jsonschema](https://github.com/supabase/pg_jsonschema).
- JSON Schema → TypeScript types.
- JSON Schema → Python (dataclass OR Pydantic 2).
- OpenAPI → FastAPI endpoints (with dataclasses or Pydantic types)
- JSON Schema → (SQL comment OR TSDoc OR Google-style docstring OR simple CommonMark) of
  `title`, `description`, `examples`, `deprecated`, `readOnly`, `writeOnly`, `contentEncoding`, and `contentMediaType`.

### Non-goals

- Support for all OpenAPI and JSON Schema features with all (or even any) targets.
  Keywords like `if`, `else`, `then`, and `not` don't even make sense for some targets.
  Keywords can be ignored as long as warnings are emitted when seen.
- Tons of target languages.
  PRs for more languages are welcome, however.
- Extensive variants on otherwise-implemented target languages.
- Support for source languages other than OpenAPI and JSON Schema.
- Support for pre-3.1 OpenAPI or pre-2020-12 JSON Schema.

### Architecture

The pipeline has distinct, decoupled stages:

```
raw files
  → [read]          → Input
  → [resolve $refs] → Input (resolved)
  → [verify]        → InputCst
  → [generate]      → OutputAst
  → [reify]         → raw output
```

**Stages**

| Stage | Module | Description |
|-------|--------|-------------|
| **Read** | `schema_to.read` | Parses raw JSON or YAML into `Input`, a loosely-typed document tree. Accepts multiple source files and tracks their filenames for use downstream (e.g. `users.schema.json` → table name `users`). |
| **Resolve** | `schema_to.resolve` | Resolves `$ref` pointers—within and across files—into a fully-resolved document. Handles both JSON Schema `$ref` and OpenAPI component references. |
| **Verify** | `schema_to.verify` | Validates the resolved document against its meta-schema (JSON Schema 2020-12 or OpenAPI 3.1/3.2). Emits structured diagnostics. Fails fast by default. |
| **InputCst** | `schema_to.cst` | A typed Concrete Syntax Tree produced after verification. Preserves the full source structure 1:1—all standard keywords are represented as typed fields, not stringly-typed dicts. No normalization or lossy transformations. |
| **Generate** | `schema_to.generate` | Walks the `InputCst` and produces an `OutputAst`—a typed tree of target-language constructs (e.g. `CreateTable`, `TsInterface`, `PyDataclass`). Each target registers its own generator. |
| **OutputAst** | `schema_to.ast` | A target-specific abstract syntax tree. Unlike the CST it has no source positions. It can be inspected or transformed before rendering. |
| **Reify** | `schema_to.reify` | Renders the `OutputAst` to a string or file. Handles formatting, indentation, and target-specific conventions. |

**Composable pipelines**

Some inputs are nested: OpenAPI embeds JSON Schema in `schema` fields and CommonMark in `description` fields.
Pipelines compose by running a sub-pipeline on embedded nodes:

- OpenAPI → FastAPI delegates `schema` nodes to a JSON Schema → Pydantic sub-pipeline.
- JSON Schema → PostgreSQL delegates `description` fields to a CommonMark → SQL-comment sub-pipeline.
- JSON Schema → PostgreSQL with `jsonb` columns delegates those columns to a JSON Schema → pg_jsonschema sub-pipeline.

Nesting is explicit and traceable—there are no implicit format-detection heuristics.

**Adding a target**

Each target lives under `schema_to/targets/<name>/` and registers:

1. A **generator**: `InputCst → OutputAst`
2. A **reifier**: `OutputAst → str`
3. Optionally: its own `OutputAst` node library if the target's constructs are novel

Targets may consume only the CST nodes they understand and emit warnings for anything they skip (e.g. `if`/`then`/`else` for SQL targets).

**Planned module layout**

```
schema_to/
  __main__.py          # CLI entry point
  read.py              # JSON/YAML → Input
  resolve.py           # $ref resolution
  verify.py            # meta-schema validation → InputCst
  cst/
    json_schema.py     # JSON Schema 2020-12 CST nodes
    openapi.py         # OpenAPI 3.1/3.2 CST nodes
  generate.py          # generator dispatcher
  ast/
    sql.py             # SQL construct nodes
    typescript.py      # TypeScript construct nodes
    python.py          # Python construct nodes
  reify.py             # reifier dispatcher
  targets/
    postgres/          # JSON Schema → PostgreSQL DDL
    pg_jsonschema/     # JSON Schema → pg_jsonschema CHECK constraints
    typescript/        # JSON Schema → TypeScript type definitions
    python/            # JSON Schema → dataclasses or Pydantic v2 models
    fastapi/           # OpenAPI → FastAPI endpoints
```
