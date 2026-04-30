"""Shared utilities for document parsers."""

from __future__ import annotations

from schema_to._errors import SourceLocation, TranspilationError
from schema_to._result import Err, Ok, Result

__all__: list[str] = []


def _ptr(parent: str, *segments: str | int) -> str:
    """Append JSON Pointer segments to `parent` (RFC 6901)."""
    parts = [_escape(str(s)) if isinstance(s, str) else str(s) for s in segments]
    return parent + "".join(f"/{p}" for p in parts)


def _escape(token: str) -> str:
    """Escape a single JSON Pointer token per RFC 6901."""
    return token.replace("~", "~0").replace("/", "~1")


def _loc(source_id: str, pointer: str) -> SourceLocation:
    return SourceLocation(source_id=source_id, json_pointer=pointer)


def _extract[T](
    result: Result[T],
    errors: list[TranspilationError],
) -> T | None:
    """Unwrap `Ok` or accumulate `Err` errors, returning `None` on failure."""
    if isinstance(result, Err):
        errors.extend(result.errors)
        return None
    return result.value
