"""Core JSON value types, and the narrowing helpers that recover them."""

from collections.abc import Mapping, MutableMapping, MutableSequence, Sequence
from dataclasses import dataclass
from typing import Self, TypeIs, cast

__all__ = [
    "JsonArray",
    "JsonArrayLimb",
    "JsonObject",
    "JsonObjectLimb",
    "JsonPrimitive",
    "JsonValue",
    "Position",
    "Range",
    "as_array",
    "as_object",
    "is_json_array_limb",
    "is_json_compound",
    "is_json_object_limb",
    "is_json_primitive",
    "is_json_primitive_mapping",
    "is_json_primitive_sequence",
    "ptr",
]

type JsonPrimitive = bool | int | float | str | None
type JsonArray = MutableSequence[JsonValue]
type JsonObject = MutableMapping[str, JsonValue]
type JsonValue = JsonPrimitive | JsonArray | JsonObject

type JsonObjectLimb = MutableMapping[str, JsonPrimitive]
type JsonArrayLimb = MutableSequence[JsonPrimitive]


def is_json_primitive_sequence(values: Sequence[JsonValue], /) -> TypeIs[Sequence[JsonPrimitive]]:
    """Returns whether every element of the sequence `values` is a `JsonPrimitive`."""
    return all(isinstance(v, bool | int | float | str | None) for v in values)


def is_json_primitive_mapping(
    values: Mapping[str, JsonValue], /
) -> TypeIs[Mapping[str, JsonPrimitive]]:
    """Returns whether every value of the mapping `values` is a `JsonPrimitive`."""
    return all(isinstance(v, bool | int | float | str | None) for v in values.values())


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


def ptr(parent: str, *segments: str | int) -> str:
    """Append JSON Pointer segments to `parent` ([RFC 6901](https://www.rfc-editor.org/rfc/rfc6901))."""
    parts = [
        s.replace("~", "~0").replace("/", "~1") if isinstance(s, str) else str(s) for s in segments
    ]
    return parent + "".join(f"/{p}" for p in parts)


@dataclass(frozen=True, slots=True)
class Position:
    """A point in a text: a line and a column.

    Attributes:
        line: 1-based line number.
        column: 1-based column number.
    """

    line: int
    column: int

    def __str__(self) -> str:
        return f"{self.line}:{self.column}"


@dataclass(frozen=True, slots=True)
class Range:
    """A span of a text, from one `Position` to another.

    Attributes:
        start: The first position in the span.
        end: The position just after the span.
            Equal to `start` for a span of nothing, such as the point where a parser gave up.
    """

    start: Position
    end: Position

    @classmethod
    def covering(cls, text: str) -> Self:
        """Return the range that spans all of `text`."""
        lines = text.split("\n")
        return cls(Position(1, 1), Position(len(lines), len(lines[-1]) + 1))

    @classmethod
    def at(cls, line: int, column: int) -> Self:
        """Return the empty range at a line and column."""
        position = Position(line, column)
        return cls(position, position)

    def __str__(self) -> str:
        return f"{self.start}-{self.end}"
