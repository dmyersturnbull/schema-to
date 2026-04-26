# schema-to

A modern transpiler for [JSON Schema 2020-12](https://json-schema.org/) and [OpenAPI 3.1+](https://www.openapis.org/), converting schema definitions into production-ready code and database migrations.

**Status:** Early development (v0.0.1). Core transpilation pipeline under active development.

Transpile JSON Schema 2020-12 into PostgreSQL DDLs, TypeScript types, and Python dataclasses/Pydantic models. Transpile OpenAPI 3.1+ into FastAPI endpoints with proper type hints.

## Table of Contents

- [Rationale](#rationale)
- [Goals](#goals)
- [Planned Targets](#planned-targets)
- [Non-Goals](#non-goals)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
- [Architecture](#architecture)
- [Contributing](#contributing)
- [License](#license)

## Rationale

[OpenAPI 3.1](https://www.openapis.org/blog/2021/02/16/migrating-from-openapi-3-0-to-3-1-0)
introduced a critical feature: full compatibility with [JSON Schema 2020-12](https://json-schema.org/specification), the current standard.
Unfortunately, four years later, most tooling is still stuck on OpenAPI 3.0 and JSON Schema 2019-09, which lack essential modern features.

**The problem:** Schema-first development requires tooling that understands current specifications. Most generators either:
- Ignore recent schema features
- Use ad-hoc workarounds instead of standard keywords
- Split effort between incompatible schema and API specs
- Miss opportunities for composition and validation

**The solution:** `schema-to` provides a unified transpilation pipeline that:
- Leverages the full JSON Schema 2020-12 specification
- Composes transpilation stages cleanly (input → CST → AST → output)
- Supports nested transpilation (e.g., Markdown in descriptions, JSON Schema in OpenAPI)
- Generates code in multiple languages from a single source of truth

## Goals

- **Formal abstractions:** Define transformation stages explicitly and decouple them.
  Use a concrete syntax tree (CST) for input with comprehensive support for all standard keywords.
- **Nested pipelines:** Support OpenAPI containing JSON Schema (as `schema`) and Markdown (as `description`), plus outputs that compose other formats (e.g., pg_jsonschema for JSON validation).
- **Multi-source:** Read from multiple files, e.g., auto-generating a table per `table-name.schema.json`.
- **Performance:** Fast transpilation for large schemas.
- **Simplicity:** No magic, minimal behavior-changing flags. Consistent, predictable behavior across targets.

## Planned Targets

### Input Formats
- JSON Schema 2020-12 (primary)
- OpenAPI 3.1, 3.2

### Output Formats
- **SQL:**
  - PostgreSQL DDL with JSON Schema validation via [pg_jsonschema](https://github.com/supabase/pg_jsonschema)
  - Custom extensions: `x-is-table`, `x-is-fk`, `x-is-index`, etc.
- **Backend:**
  - TypeScript types
  - Python dataclasses or Pydantic 2 models
  - FastAPI endpoints from OpenAPI
- **Documentation:**
  - SQL comments (from `title`, `description`, `examples`, etc.)
  - TypeScript/JSDoc comments
  - Python docstrings (Google-style)
  - CommonMark

## Non-Goals

- **Exhaustive feature coverage:** Keywords like `if`/`else`/`then`/`not` don't apply to all targets; we emit warnings when unsupported keywords are encountered.
- **Every language:** PRs for additional languages are welcome, but we maintain a curated focus.
- **Variants:** We avoid extensive target-specific variants of otherwise-supported languages.
- **Other input formats:** Only JSON Schema and OpenAPI 3.1+; no XML, Protocol Buffers, GraphQL schemas, etc.
- **Legacy support:** No pre-3.1 OpenAPI or pre-2020-12 JSON Schema.

## Quick Start

### Minimal example

Create a schema file `user.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "User",
  "type": "object",
  "properties": {
    "id": { "type": "integer" },
    "email": { "type": "string", "format": "email" },
    "name": { "type": "string" }
  },
  "required": ["id", "email"]
}
```

Transpile to TypeScript:

```bash
schema-to --input user.schema.json --output user.ts --target typescript
```

Generate PostgreSQL DDL:

```bash
schema-to --input user.schema.json --output user.sql --target postgres
```

## Installation

### From PyPI

```bash
pip install schema-to
```

### From source (development)

```bash
git clone https://github.com/dmyersturnbull/schema-to.git
cd schema-to
pip install -e ".[dev]"
```

Requires Python 3.14+.

## Usage

### Command-line interface

```bash
schema-to --help
```

### As a library

```python
from schema_to import transpile

result = transpile(
    source="path/to/schema.json",
    target="typescript",
    output="generated/types.ts"
)
```

### Examples

- Converting a full OpenAPI spec to FastAPI application
- Generating TypeScript types from JSON Schema with full `$ref` resolution
- Creating PostgreSQL migrations from nested schemas
- Composing multiple schema files into a single output

See `examples/` for complete samples (coming soon).

## Architecture

```
raw
 ├─ ⟨read⟩ → Input
 │   └─ ⟨resolve $refs, verify⟩ → InputCst
 │       └─ ⟨generate⟩ → OutputAst
 │           └─ ⟨reify⟩ → raw
```

**Stages:**
1. **Read:** Parse JSON/YAML into typed input representation
2. **Resolve & Verify:** Dereference `$ref` links, validate against spec
3. **CST:** Concrete syntax tree with full keyword information
4. **Generate:** Transform CST to language-specific AST
5. **Reify:** Emit code or SQL from AST

Each stage exposes a stable API for extensibility.

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Add tests for your changes
4. Ensure linting passes: `ruff check .` and `ruff format .`
5. Run tests: `pytest`
6. Commit with clear messages
7. Push and open a pull request

### Development setup

```bash
pip install -e ".[dev]"
ruff check . --fix
pytest
```

## License

MIT. See [LICENSE](LICENSE) for details.
