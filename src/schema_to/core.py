"""Core JSON value types, and the narrowing helpers that recover them."""

from collections.abc import Mapping, MutableMapping, MutableSequence, Sequence
from dataclasses import dataclass
from typing import NamedTuple, Self, TypeIs, cast

__all__ = [
    "JsonArray",
    "JsonArrayLimb",
    "JsonObject",
    "JsonObjectLimb",
    "JsonPrimitive",
    "JsonValue",
    "Position",
    "SourceRef",
    "Span",
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
    """A point in a text: a line, and usually a column.

    Attributes:
        line: 1-based line number.
        column: 1-based column number, or `None` if only the line is known.
    """

    line: int
    column: int | None

    def __str__(self) -> str:
        return str(self.line) if self.column is None else f"{self.line}:{self.column}"


class Span(NamedTuple):
    """Where something starts, and the position just after where it ends."""

    start: Position
    end: Position

    @classmethod
    def of(cls, start: tuple[int, int | None], end: tuple[int, int | None]) -> Self:
        return cls(Position(*start), Position(*end))


@dataclass(frozen=True, slots=True)
class SourceRef:
    """A place in a file that the user wrote.

    It records where a CST node came from, where a `RawDoc`'s content came from,
    and where a diagnostic is about.
    A node or document derived from part of a file points into that file,
    not at the derived thing's own URI, which exists nowhere,
    so a diagnostic names a place the user can actually open.

    Attributes:
        uri: URI of the file, matching `RawDoc.origin`'s `uri`, without a fragment.
        json_pointer: An [RFC 6901](https://www.rfc-editor.org/rfc/rfc6901)
            pointer to the place within that file.
            Empty for the file as a whole.
        start: Where the place begins in the file's raw text, or `None` if that is not known.
            If a reader cannot locate the place itself,
            this is where the smallest enclosing piece of text that it can locate begins.
        end: The position just after where the place ends, with the same caveat as `start`.
    """

    uri: str
    json_pointer: str
    start: Position | None
    end: Position | None

    def __str__(self) -> str:
        pointer = f":{self.json_pointer}" if self.json_pointer else ""
        start = f":{self.start}" if self.start is not None else ""
        return f"{self.uri}{pointer}{start}"
