"""Core JSON value types, and the narrowing helpers that recover them.

`isinstance(v, Mapping)` narrows only to `Mapping[Unknown, object]`: the checker
cannot know the keys are strings.  But a value decoded from JSON or YAML always
has string keys and JSON values, so the check and the cast belong together.
`as_object` and `as_array` pair them, so callers get a typed result from one call
instead of repeating an unchecked `cast` at every use.
"""

from collections.abc import Mapping, MutableMapping, MutableSequence, Sequence
from typing import cast

__all__ = ["JsonArray", "JsonObject", "JsonPrimitive", "JsonValue", "as_array", "as_object"]

type JsonPrimitive = bool | int | float | str | None
type JsonArray = MutableSequence[JsonValue]
type JsonObject = MutableMapping[str, JsonValue]
type JsonValue = JsonPrimitive | JsonArray | JsonObject


def as_object(value: JsonValue) -> Mapping[str, JsonValue] | None:
    """Return `value` as a JSON object, or `None` if it is not one."""
    if not isinstance(value, Mapping):
        return None
    return cast("Mapping[str, JsonValue]", value)


def as_array(value: JsonValue) -> Sequence[JsonValue] | None:
    """Return `value` as a JSON array, or `None` if it is not one.

    A `str` is a `Sequence` but never a JSON array, so it is rejected here.
    """
    if not isinstance(value, Sequence) or isinstance(value, str):
        return None
    return cast("Sequence[JsonValue]", value)
