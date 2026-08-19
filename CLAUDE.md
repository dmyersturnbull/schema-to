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

## Line breaks in documentation

We use a simple form of semantic line breaks in docstrings and other documentation.
This means only breaking lines at semantically important places.

Always use a `\n` before and after every:

- sentence (except if enclosed in quotes, parentheses, brackets, or markup)
- long (> about 40 characters) independent clause
- long Markdown link or code snippet
- long text enclosed in `_`/`_`, `**`/`**`, or a pair of quotes, parentheses, or brackets

You **may** use additional line breaks to clarify or highlight;
for example, by putting each item in an inline list on its own line.
Break at lower-precedence places first, and preserve grouping and parity.

Do **not** break in arbitrary places.
Do **not** enforce a strict line-length requirement.
