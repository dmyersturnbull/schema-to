"""Shared utilities for document parsers."""

from __future__ import annotations

from schema_to._errors import SourceLocation, TranspilationError
from schema_to._result import Err, Result

__all__ = ["extract", "loc", "ptr"]


def ptr(parent: str, *segments: str | int) -> str:
    """Append JSON Pointer segments to `parent` (RFC 6901)."""
    parts = [
        s.replace("~", "~0").replace("/", "~1") if isinstance(s, str) else str(s) for s in segments
    ]
    return parent + "".join(f"/{p}" for p in parts)


def loc(source_id: str, pointer: str) -> SourceLocation:
    return SourceLocation(source_id=source_id, json_pointer=pointer)


def extract[T](result: Result[T], errors: list[TranspilationError]) -> T | None:
    """Unwrap `Ok` or accumulate `Err` errors, returning `None` on failure."""
    if isinstance(result, Err):
        errors.extend(result.errors)
        return None
    return result.value
