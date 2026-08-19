"""Utilities for Python generators."""

import keyword
import re
from typing import Literal

from caseutil import to_pascal, to_snake

__all__ = [
    "safe_python_class_name",
    "safe_python_field_name",
    "split_class_name",
    "to_pascal",
    "to_snake",
]

_NON_IDENT = re.compile(r"\W")


def safe_python_class_name(name: str) -> str:
    """Return a valid, non-keyword Python class name derived from *name*.

    Applies PascalCase conversion, strips remaining non-identifier characters,
    prepends `Model` if the result starts with a digit, and appends `_` if
    the result is a Python keyword.  Falls back to `Model` when the input
    yields no identifier characters at all.
    """
    pascal = to_pascal(name) or "Model"
    pascal = _NON_IDENT.sub("", pascal) or "Model"
    if pascal[0].isdigit():
        pascal = "Model" + pascal
    if keyword.iskeyword(pascal) or keyword.issoftkeyword(pascal):
        pascal += "_"
    return pascal


def split_class_name(name: str, variant: Literal["read", "write"]) -> str:
    """Return the class name for the readOnly/writeOnly split *variant* of *name*."""
    suffix = "Read" if variant == "read" else "Write"
    return f"{safe_python_class_name(name)}{suffix}"


def safe_python_field_name(name: str) -> str:
    r"""Return a valid, non-keyword Python field name derived from *name*.

    Applies snake_case conversion,
    strips non-identifier (regex `\W`) characters,
    prepends `field_` if the result starts with a digit,
    and appends `_` if the result is a Python keyword.

    Returns `field_` if the input contains no identifier characters.
    """
    snake = to_snake(name) or "field_"
    snake = _NON_IDENT.sub("_", snake)
    snake = re.sub(r"_+", "_", snake).strip("_") or "field_"
    if snake[0].isdigit():
        snake = "field_" + snake
    if keyword.iskeyword(snake) or keyword.issoftkeyword(snake):
        # Safe because no Python reserved words have `_` suffixes.
        snake += "_"
    return snake
