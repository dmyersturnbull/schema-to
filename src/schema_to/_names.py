"""Identifier name utilities shared across generators and reifiers.

Provides case-conversion functions (PascalCase, snake_case) backed by the
``caseutil`` package, and language-specific sanitisers that produce valid
identifiers while avoiding reserved keywords.
"""

from __future__ import annotations

import keyword
import re

from caseutil import to_pascal, to_snake

__all__ = [
    "safe_python_class_name",
    "safe_python_field_name",
    "safe_sql_identifier",
    "to_pascal",
    "to_snake",
]

_NON_IDENT = re.compile(r"[^\w]")


def safe_python_class_name(name: str) -> str:
    """Return a valid, non-keyword Python class name derived from *name*.

    Applies PascalCase conversion, strips remaining non-identifier characters,
    prepends ``Model`` if the result starts with a digit, and appends ``_`` if
    the result is a Python keyword.  Falls back to ``Model`` when the input
    yields no identifier characters at all.
    """
    pascal = to_pascal(name) or "Model"
    pascal = _NON_IDENT.sub("", pascal) or "Model"
    if pascal[0].isdigit():
        pascal = "Model" + pascal
    if keyword.iskeyword(pascal) or keyword.issoftkeyword(pascal):
        pascal += "_"
    return pascal


def safe_python_field_name(name: str) -> str:
    """Return a valid, non-keyword Python field name derived from *name*.

    Applies snake_case conversion, strips remaining non-identifier characters,
    prepends ``field_`` if the result starts with a digit, and appends ``_``
    if the result is a Python keyword.  Falls back to ``field_`` when the
    input yields no identifier characters at all.
    """
    snake = to_snake(name) or "field_"
    snake = _NON_IDENT.sub("_", snake)
    snake = re.sub(r"_+", "_", snake).strip("_") or "field_"
    if snake[0].isdigit():
        snake = "field_" + snake
    if keyword.iskeyword(snake) or keyword.issoftkeyword(snake):
        snake += "_"
    return snake


def safe_sql_identifier(name: str) -> str:
    """Return a valid lowercase PostgreSQL identifier derived from *name*.

    Applies snake_case conversion, strips non-identifier characters, prepends
    ``col_`` if the result starts with a digit, and falls back to ``col_`` for
    empty input.  Does not quote reserved words — callers may wrap the result
    in double quotes if needed.
    """
    snake = to_snake(name) or "col_"
    snake = _NON_IDENT.sub("_", snake)
    snake = re.sub(r"_+", "_", snake).strip("_") or "col_"
    if snake[0].isdigit():
        snake = "col_" + snake
    return snake.lower()
