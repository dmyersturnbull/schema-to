# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`schema-to` is a transpiler for JSON Schema 2020-12 and OpenAPI 3.1+ that converts schema definitions into production-ready code and database migrations. Current targets: Pydantic v2 models, PostgreSQL DDL (via `pg_jsonschema`), and pass-through normalization. TypeScript and FastAPI targets are planned.

## Commands

```bash
# Install dev dependencies
uv sync --dev

# Run all tests
uv run pytest

# Run a single test file or test by name
uv run pytest tests/test_pydantic_transpiler.py
uv run pytest -k "test_nested_object"

# Run slow/e2e tests (excluded by default)
uv run pytest -m slow
uv run pytest -m e2e

# Lint and format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Type check
uv run ty check

# Run the CLI
uv run schema-to --help
```

## Architecture

The pipeline has exactly four sequential stages:

```
RawDoc (bytes)
  →[parse]→   CstNode  (Concrete Syntax Tree — all keywords preserved)
  →[resolve]→ CstNode  ($ref / $dynamicRef inlined from registry)
  →[generate]→ AstNode (target-language Abstract Syntax Tree)
  →[reify]→   Artifact (output bytes)
```

### Stage algebra (`pipeline.py`)

`Stage[X, Y]` is a Kleisli arrow `X → Result[Y]`. Stages compose left-to-right via `.then()`, short-circuiting on `Err`:

```python
full_stage: Stage[RawDoc, JsonSchemaDocument] = JsonSchemaParser().then(JsonSchemaRefResolver())
```

Specialised subtypes: `DocParser`, `RefResolver`, `Transformer`, `Reifier`.

To add a new transpiler, subclass `TypedTranspiler[I, O, C, A]` and implement the four abstract methods (`parse`, `resolve`, `generate`, `reify`). Register it in `transpile/factory.py` (`TranspilerRouter`).

### Result monad (`result.py`)

All pipeline operations return `Result[T] = Ok[T] | Err`. `Err` accumulates multiple `TranspilationError`s rather than stopping at the first.

```python
match pipeline.process():
    case Ok(summary): ...
    case Err(errors): ...
```

### Module layout

| Path | Role |
|------|------|
| `cst/` | Input CST nodes for JSON Schema 2020-12 (`cst/json_schema.py`) and OpenAPI 3.1 (`cst/openapi.py`) |
| `ast/` | Output AST nodes for Python (`ast/python.py`), SQL (`ast/sql.py`), TypeScript (`ast/typescript.py`) |
| `parse/` | Stage 1 — bytes → CST |
| `resolve/` | Stage 2 — `$ref` resolution using the `referencing` library |
| `generate/` | Stage 3 — CST → AST (Pydantic: `generate/pydantic.py`, SQL: `generate/sql.py`) |
| `reify/` | Stage 4 — AST → output bytes |
| `serialize/` | Pass-through serialization (CST → bytes, for format normalization) |
| `transpile/` | End-to-end transpiler compositions; `factory.py` maps CLI target names |
| `io/` | Data sources (`FileDataSource`, `InMemoryDataSource`), sinks, `MediaType`, content-based routing |
| `pipeline.py` | `Stage` algebra, `Transpiler` contract, `Pipeline` orchestrator |
| `result.py` | `Ok[T]` / `Err` sum type |
| `errors.py` | `TranspilationError` hierarchy by stage |

### Error types (`errors.py`)

Stage-specific errors: `ParseError`, `ResolutionError`, `SchemaValidationError`, `GenerationError`, `ReificationError`. All subclass `TranspilationError` and carry an optional `SourceLocation` (RFC 6901 JSON pointer + line/column).

`TranspilationWarning` (non-fatal) is used when a JSON Schema keyword is unsupported by a target — emit a warning rather than an error.

## Conventions

- **Dataclasses:** All data containers use `@dataclass(frozen=True, slots=True)`. Mutability is the exception, not the rule.
- **Imports:** Absolute imports only — relative imports are banned (`ban-relative-imports = "all"`).
- **Docstrings:** Google-style. The `D1` family (missing docstrings) is ignored, so docstrings are optional but must be Google-style when present.
- **Linting:** `ruff` with `select = ["ALL"]` and `preview = true`. Run `ruff check --fix` before committing. Tests relax docstring and `S10x` (assert/hardcoded credential) rules.
- **Type checking:** `ty` (not mypy). Python 3.14 is required; use modern syntax (`type X = …`, `[T]` generic syntax on classes and functions).
- **Test infra:** `InMemoryDataSource` / `InMemoryDataSink` (in `io/memory.py`) are the primary testing seams — pass schema bytes in, assert artifact bytes out. `tests/strategies.py` provides Hypothesis strategies.
- **Safe identifier generation:** `generate/_names.py` handles turning JSON Schema property names into valid Python/SQL identifiers. Use it rather than ad-hoc string manipulation.
