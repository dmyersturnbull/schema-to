"""Shared utilities for document parsers."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from schema_to.errors import ParseError, SourceLocation, TranspilationError
from schema_to.io.core import DefaultJsonLikeReader, ReadError
from schema_to.result import Err, Result

if TYPE_CHECKING:
    from schema_to.core import JsonValue
    from schema_to.io.source import RawDoc

__all__ = [
    "as_json_dict",
    "as_json_list",
    "bool_field",
    "decode_raw_doc",
    "extract",
    "int_field",
    "loc",
    "num_field",
    "ptr",
    "str_field",
    "str_or",
]


def ptr(parent: str, *segments: str | int) -> str:
    """Append JSON Pointer segments to `parent` (RFC 6901)."""
    parts = [
        s.replace("~", "~0").replace("/", "~1") if isinstance(s, str) else str(s) for s in segments
    ]
    return parent + "".join(f"/{p}" for p in parts)


def loc(source_id: str, pointer: str) -> SourceLocation:
    return SourceLocation(source_id=source_id, json_pointer=pointer)


def decode_raw_doc(document: RawDoc) -> JsonValue:
    """Decode a raw document's bytes to a JSON-compatible value.

    Raises `ParseError` (a `TranspilationError`) on malformed input so callers
    can treat it uniformly alongside other parse errors.
    """
    try:
        return DefaultJsonLikeReader().read(document.content, document.media_type)
    except ReadError as e:
        raise ParseError(
            str(e), location=SourceLocation(document.source_id, line=e.line, column=e.column)
        ) from e


def extract[T](result: Result[T], errors: list[TranspilationError]) -> T | None:
    """Unwrap `Ok` or accumulate `Err` errors, returning `None` on failure."""
    if isinstance(result, Err):
        errors.extend(result.errors)
        return None
    return result.value


# ---------------------------------------------------------------------------
# Typed field accessors for dict[str, JsonValue]
#
# After `isinstance(x, dict)`, ty narrows to `dict[object, object]` rather
# than `dict[str, JsonValue]`.  These helpers centralise the pattern of:
#   v = data.get(key); return v if isinstance(v, <T>) else <default>
# so callers get a properly typed result without repeating the idiom.
# ---------------------------------------------------------------------------


# TODO: Why does this exist?
def as_json_dict(v: object) -> dict[str, JsonValue]:
    """Reinterpret an already-checked dict as `dict[str, JsonValue]`.

    Caller must have verified `isinstance(v, dict)` before calling.
    """
    return cast("dict[str, JsonValue]", v)


# TODO: Why does this exist?
def as_json_list(v: object) -> list[JsonValue]:
    """Reinterpret an already-checked list as `list[JsonValue]`.

    Caller must have verified `isinstance(v, list)` before calling.
    """
    return cast("list[JsonValue]", v)


def str_field(data: dict[str, JsonValue], key: str) -> str | None:
    """Return `data[key]` as `str`, or `None` if absent or not a string."""
    v = data.get(key)
    return v if isinstance(v, str) else None


def str_or(data: dict[str, JsonValue], key: str, default: str = "") -> str:
    """Return `data[key]` as `str`, or `default` if absent or not a string."""
    v = data.get(key)
    return v if isinstance(v, str) else default


def num_field(data: dict[str, JsonValue], key: str) -> int | float | None:
    """Return `data[key]` as `int | float`, or `None` if absent, not numeric, or boolean."""
    v = data.get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def int_field(data: dict[str, JsonValue], key: str) -> int | None:
    """Return `data[key]` as `int`, or `None` if absent, not an int, or boolean."""
    v = data.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def bool_field(data: dict[str, JsonValue], key: str) -> bool | None:
    """Return `data[key]` as `bool`, or `None` if absent or not a boolean."""
    v = data.get(key)
    return v if isinstance(v, bool) else None
