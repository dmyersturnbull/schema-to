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

raw → ⟨read⟩ → `Input` → ⟨resolve refs⟩ → ⟨verify⟩ → `InputCst` → **⟨generate⟩** → `OutputAst` → ⟨reify⟩ → raw
