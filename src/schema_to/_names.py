"""Identifier name utilities shared across generators and reifiers.

Provides case-conversion functions (PascalCase, snake_case) and Python-specific
sanitisers that produce valid identifiers, avoiding reserved keywords.
"""

from __future__ import annotations

import keyword
import re

__all__ = [
    "WORD_SPLIT_RE",
    "safe_python_class_name",
    "safe_python_field_name",
    "safe_sql_identifier",
    "to_pascal",
    "to_snake",
]

# Splits on camelCase boundaries and on separator characters.
WORD_SPLIT_RE: re.Pattern[str] = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|[-_\s]+")

# Matches at least one word character (used to filter empty parts).
_HAS_WORD = re.compile(r"\w")

# Matches any character that is not a Unicode word character.
_NON_WORD = re.compile(r"[^\w]")


def to_pascal(name: str) -> str:
    """Return *name* converted to PascalCase.

    Non-alphanumeric, non-separator characters are treated as word boundaries
    and discarded.  Empty string input returns ``""``.
    """
    safe = re.sub(r"[^\w\s\-]", " ", name)
    parts = WORD_SPLIT_RE.split(safe)
    return "".join(p.capitalize() for p in parts if _HAS_WORD.search(p))


def to_snake(name: str) -> str:
    """Return *name* converted to snake_case.

    Non-alphanumeric characters become underscores; consecutive underscores
    are collapsed; leading/trailing underscores are stripped.
    """
    safe = re.sub(r"[^\w\s\-]", "_", name)
    s = re.sub(r"[-\s]+", "_", safe)
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s.lower()


def safe_python_class_name(name: str) -> str:
    """Return a valid, non-keyword Python class name derived from *name*.

    Applies PascalCase conversion, strips remaining non-identifier characters,
    prepends ``"Model"`` if the result starts with a digit, and appends
    ``"_"`` if the result is a Python keyword.  Falls back to ``"Model"``
    when the input yields no identifier characters at all.
    """
    pascal = to_pascal(name) or "Model"
    pascal = _NON_WORD.sub("", pascal) or "Model"
    if pascal[0].isdigit():
        pascal = "Model" + pascal
    if keyword.iskeyword(pascal) or keyword.issoftkeyword(pascal):
        pascal += "_"
    return pascal


def safe_sql_identifier(name: str) -> str:
    """Return a valid lowercase PostgreSQL identifier derived from *name*.

    Applies snake_case conversion, strips non-identifier characters, prepends
    ``"col_"`` if the result starts with a digit, and falls back to ``"col_"``
    for empty input.  Does not quote reserved words — callers may wrap the
    result in double quotes if needed.
    """
    snake = to_snake(name) or "col_"
    snake = _NON_WORD.sub("_", snake)
    snake = re.sub(r"_+", "_", snake).strip("_") or "col_"
    if snake[0].isdigit():
        snake = "col_" + snake
    return snake.lower()


def safe_python_field_name(name: str) -> str:
    """Return a valid, non-keyword Python field name derived from *name*.

    Applies snake_case conversion, strips remaining non-identifier characters,
    prepends ``"field_"`` if the result starts with a digit, and appends
    ``"_"`` if the result is a Python keyword.  Falls back to ``"field_"``
    when the input yields no identifier characters at all.
    """
    snake = to_snake(name) or "field_"
    snake = _NON_WORD.sub("_", snake)
    snake = re.sub(r"_+", "_", snake).strip("_") or "field_"
    if snake[0].isdigit():
        snake = "field_" + snake
    if keyword.iskeyword(snake) or keyword.issoftkeyword(snake):
        snake += "_"
    return snake
