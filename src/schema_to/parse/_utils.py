"""Shared utilities for document parsers."""

from collections.abc import MutableSequence
from typing import TYPE_CHECKING, cast

from schema_to.errors import ParseError, SourceLocation, TranspilationError
from schema_to.io.core import JsonLikeReader, ReadError
from schema_to.result import Err, Result

if TYPE_CHECKING:
    from enum import Enum

    from schema_to.core import JsonArray, JsonObject, JsonValue
    from schema_to.io.source import RawDoc

__all__ = [
    "as_json_dict",
    "as_json_list",
    "bool_field",
    "decode_raw_doc",
    "enum_member",
    "extract",
    "int_field",
    "loc",
    "num_field",
    "ptr",
    "str_field",
    "str_or",
]


def enum_member[E: Enum](enum_cls: type[E], value: object) -> E | None:
    """Return the `enum_cls` member whose value equals `value`, or `None`.

    Avoids constructing the enum in a `try`/`except ValueError`, which would
    also swallow unrelated `ValueError`s.
    """
    return next((member for member in enum_cls if member.value == value), None)


def ptr(parent: str, *segments: str | int) -> str:
    """Append JSON Pointer segments to `parent` (RFC 6901)."""
    parts = [
        s.replace("~", "~0").replace("/", "~1") if isinstance(s, str) else str(s) for s in segments
    ]
    return parent + "".join(f"/{p}" for p in parts)


def loc(source_id: str, pointer: str) -> SourceLocation:
    return SourceLocation(doc_id=source_id, json_pointer=pointer)


def decode_raw_doc(doc: RawDoc, reader: JsonLikeReader) -> JsonValue:
    """Decode a raw document's bytes to a JSON-compatible value.

    Raises:
        ParseError: If `doc` is malformed.
    """
    try:
        return reader.read(doc.content, doc.media_type)
    except ReadError as e:
        raise ParseError(
            str(e), location=SourceLocation(doc.doc_id, line=e.line, column=e.column)
        ) from e


def extract[T](result: Result[T], errors: MutableSequence[TranspilationError]) -> T | None:
    """Unwrap `Ok` or accumulate `Err` errors, returning `None` on failure.

    Modifies the argument `errors`.
    """
    if isinstance(result, Err):
        errors.extend(result.errors)
        return None
    return result.value


# Typed field accessors for `JsonObject`:
# After `isinstance(x, dict)`, ty narrows to `dict[object, object]`
# rather than `JsonObject`.
# This is a current limitation in ty.
# These helpers centralise the pattern of:
#   v = data.get(key); return v if isinstance(v, <T>) else <default>
# so callers get a properly typed result without repeating the idiom.


def as_json_dict(v: object) -> JsonObject:
    """Reinterpret an already-checked dict as `JsonObject`.

    Caller must have verified `isinstance(v, dict)` before calling.
    """
    return cast("JsonObject", v)


# TODO: Why does this exist?
def as_json_list(v: object) -> JsonArray:
    """Reinterpret an already-checked list as `JsonArray`.

    Caller must have verified `isinstance(v, MutableSequence)` before calling.
    """
    return cast("JsonArray", v)


def str_field(data: JsonObject, key: str) -> str | None:
    """Return `data[key]` as `str`, or `None` if absent or not a string."""
    v = data.get(key)
    return v if isinstance(v, str) else None


def str_or(data: JsonObject, key: str, default: str = "") -> str:
    """Return `data[key]` as `str`, or `default` if absent or not a string."""
    v = data.get(key)
    return v if isinstance(v, str) else default


def num_field(data: JsonObject, key: str) -> int | float | None:
    """Return `data[key]` as `int | float`, or `None` if absent, not numeric, or boolean."""
    v = data.get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def int_field(data: JsonObject, key: str) -> int | None:
    """Return `data[key]` as `int`, or `None` if absent, not an int, or boolean."""
    v = data.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def bool_field(data: JsonObject, key: str) -> bool | None:
    """Return `data[key]` as `bool`, or `None` if absent or not a boolean."""
    v = data.get(key)
    return v if isinstance(v, bool) else None
