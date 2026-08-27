"""Core JSON value types, and the narrowing helpers that recover them."""

from collections.abc import Mapping, MutableMapping, MutableSequence, Sequence
from typing import TypeIs, cast

__all__ = [
    "JsonArray",
    "JsonArrayLimb",
    "JsonObject",
    "JsonObjectLimb",
    "JsonPrimitive",
    "JsonValue",
    "as_array",
    "as_object",
    "is_json_array_limb",
    "is_json_compound",
    "is_json_object_limb",
    "is_json_primitive",
    "is_json_primitive_mapping",
    "is_json_primitive_sequence",
]

type JsonPrimitive = bool | int | float | str | None
type JsonArray = MutableSequence[JsonValue]
type JsonObject = MutableMapping[str, JsonValue]
type JsonValue = JsonPrimitive | JsonArray | JsonObject

type JsonObjectLimb = MutableMapping[str, JsonPrimitive]
type JsonArrayLimb = MutableSequence[JsonPrimitive]


def is_json_primitive_sequence(values: Sequence[JsonValue], /) -> TypeIs[Sequence[JsonPrimitive]]:
    return all(isinstance(v, bool | int | float | str | None) for v in values)


def is_json_primitive_mapping(
    values: Mapping[str, JsonValue], /
) -> TypeIs[Mapping[str, JsonPrimitive]]:
    return all(isinstance(v, bool | int | float | str | None) for v in values)


# ty: ignore[invalid-type-guard-definition]  # ty is wrong
def is_json_array_limb(value: JsonValue, /) -> TypeIs[JsonArrayLimb]:
    """Returns whether the JSON `value` is a JSON array with only primitive elements."""
    return isinstance(value, MutableSequence) and all(
        isinstance(v, bool | int | float | str | None) for v in value
    )


# ty: ignore[invalid-type-guard-definition]  # ty is wrong
def is_json_object_limb(value: JsonValue, /) -> TypeIs[JsonObjectLimb]:
    """Returns whether the JSON `value` a JSON object with only primitive elements."""
    return (
        isinstance(value, MutableMapping)
        and all(isinstance(k, str) for k in value)
        and all(isinstance(v, bool | int | float | str | None) for v in value.values())
    )


def is_json_primitive(value: JsonValue, /) -> TypeIs[JsonPrimitive]:
    """Returns whether the JSON `value` is a `MutableSequence` of `JsonPrimitive`."""
    return isinstance(value, bool | int | float | str | None)


def is_json_compound(value: JsonValue, /) -> TypeIs[JsonPrimitive]:
    """Returns whether the JSON `value` is a compound type (i.e. not a primitive/scalar).

    Note:
        This can't be opened up to `Any` because it's impossible to verify for an arbitrary sequence or mapping,
        without recursing exhausively.
    """
    return isinstance(value, MutableSequence | MutableMapping)


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
