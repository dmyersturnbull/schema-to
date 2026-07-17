# Agent instructions

## Linting

Run these often, ignoring their output:

1. `uv run ruff check --fix-only`
2. `uv run format`

Validating Python typing via `uv run ty check`.
Detect other code issues via `uv run ruff check`.

Ty should pass with no violations.
Some Ruff violations may be acceptable; use common sense.
Never suppress Ruff or ty rules, including with comments.

## Testing

Use `uv run pytest`.
Tests should pass.

## Imports

Do not use `from schema_to import bar`;
instead, import from the specific module, as in `from schema_to.foo.bar`.
Do not use `from __future__ import annotations`;
it is not needed in Python 3.14+, which we require.

## Typing

Always use type annotations and do not use `object` or `Any`.
Favor abstract types in `collections.abc` over concrete types.
Use `uv run ty check` to validate typing.

## Conventions

Keep functions and methods small.
Prefer immutable types, using `@dataclass(frozen=True, slots=True)`.
Sometimes defining stateful helper classes can simplify complex methods.

## Docstrings

We use Google docstrings conventions with Markdown syntax.
Omit boilerplate documentation like `Returns: a string`.
Wrap lines between sentences, or between independent clauses for long lines;
do not wrap otherwise.
