"""Defines abstract and concrete classes for reading and writing JSON-compatible formats."""

import re
from abc import ABC, abstractmethod
from bisect import bisect_right
from dataclasses import dataclass
from itertools import count
from json import JSONDecoder
from typing import TYPE_CHECKING, cast

import orjson
import yaml
from orjson import JSONDecodeError, JSONEncodeError
from yaml12 import format_yaml, parse_yaml

from schema_to.core import Position, Span, ptr
from schema_to.io.media_type import MediaType, MediaTypes

if TYPE_CHECKING:
    from collections.abc import Mapping, Set

    from schema_to.core import JsonValue

__all__ = [
    "DefaultJsonLikeReader",
    "DefaultJsonLikeWriter",
    "JsonLikeReader",
    "JsonLikeWriter",
    "JsonReader",
    "JsonWriter",
    "ReadError",
    "UnsupportedMediaTypeError",
    "WriteError",
    "YamlReader",
    "YamlWriter",
]


class ReadError(Exception):
    """Content could not be read.

    Attributes:
        position: Where the reader gave up, or `None` if it did not say.
    """

    def __init__(self, msg: str, *, position: Position | None) -> None:
        super().__init__(msg)
        self.position = position


class WriteError(Exception):
    def __init__(self, msg: str) -> None:
        super().__init__(msg)


class UnsupportedMediaTypeError(Exception):
    def __init__(self, *, media_type: MediaType, supported: Set[MediaType]) -> None:
        super().__init__(
            f"Unsupported media type: {media_type}."
            f" Supported: {', '.join(mt.essence for mt in supported)}."
        )
        self.media_type = media_type
        self.supported = supported


class JsonLikeReader(ABC):
    """Abstract reader that decodes JSON-compatible bytes given a media type.

    It is crucial that `read` raises `ReadError`.
    """

    @abstractmethod
    def read(self, content: str | bytes, media_type: MediaType) -> JsonValue:
        """Parses JSON-compatible content, using a known media-type.

        Args:
            content: Text or bytes.
            media_type: IANA media-type of the content.
              Implementations MAY infer the text encoding of bytes from a `charset` param.

        Raises:
            ReadError: If the content is invalid.
                Implementations MUST raise an instance of this class (or a subtype).
            UnsupportedMediaTypeError: If the media-type `media_type` is not supported.
        """
        raise NotImplementedError

    @abstractmethod
    def spans(self, content: str | bytes, media_type: MediaType) -> Mapping[str, Span]:
        """Locates every value of JSON-compatible content that `read` has accepted.

        Args:
            content: Text or bytes that `read` returned a value for.
            media_type: IANA media-type of the content.

        Returns:
            Where each value starts and ends in the text, keyed by its
            [RFC 6901](https://www.rfc-editor.org/rfc/rfc6901) JSON Pointer.
            A value that the reader cannot locate is left out.

        Raises:
            UnsupportedMediaTypeError: If the media-type `media_type` is not supported.
        """
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class DefaultJsonLikeReader(JsonLikeReader):
    """Concrete reader supporting `application/json`, `application/yaml`, and `+json`/`+yaml`."""

    def read(self, content: str | bytes, media_type: MediaType) -> JsonValue:
        if media_type.type in {"text", "application"}:
            if media_type.subtype.endswith(("+json", "json")):
                return JsonReader().read(content)
            if media_type.subtype.endswith(("+yaml", "yaml")):
                return YamlReader().read(content)
        raise UnsupportedMediaTypeError(
            media_type=media_type, supported={MediaTypes.json, MediaTypes.yaml}
        )

    def spans(self, content: str | bytes, media_type: MediaType) -> Mapping[str, Span]:
        if media_type.type in {"text", "application"}:
            if media_type.subtype.endswith(("+json", "json")):
                return JsonReader().spans(content)
            if media_type.subtype.endswith(("+yaml", "yaml")):
                return YamlReader().spans(content)
        raise UnsupportedMediaTypeError(
            media_type=media_type, supported={MediaTypes.json, MediaTypes.yaml}
        )


class JsonLikeWriter(ABC):
    """Abstract writer that encodes objects into JSON, YAML, etc., bytes of a given media type."""

    @abstractmethod
    def write_str(self, data: JsonValue, media_type: MediaType) -> str:
        """Writes values to a JSON-compatible format of a specified media-type.

        Args:
            data: Value to serialize.
            media_type: IANA media-type of the content.

        Raises:
            WriteError: If serialization failed.
            UnsupportedMediaTypeError: If the media-type `media_type` is not supported.
        """
        raise NotImplementedError

    @abstractmethod
    def write_bytes(self, data: JsonValue, media_type: MediaType) -> bytes:
        """Writes values to a JSON-compatible format of a specified media-type.

        Args:
            data: Value to serialize.
            media_type: IANA media-type of the content.
                Implementations MAY vary the encoding using a `charset` param.

        Raises:
            WriteError: If serialization failed.
            UnsupportedMediaTypeError: If the media-type `media_type` is not supported.
        """
        raise NotImplementedError


@dataclass(frozen=True, slots=True, kw_only=True)
class DefaultJsonLikeWriter(JsonLikeWriter):
    """Concrete writer supporting JSON and YAML."""

    pretty: bool = False

    def write_str(self, data: JsonValue, media_type: MediaType) -> str:
        subtype = media_type.subtype
        if subtype.endswith(("+json", "json")):
            return JsonWriter(pretty=self.pretty).write(data)
        if subtype.endswith(("+yaml", "yaml")):
            return YamlWriter().write(data)
        raise UnsupportedMediaTypeError(
            media_type=media_type, supported={MediaTypes.json, MediaTypes.yaml}
        )

    def write_bytes(self, data: JsonValue, media_type: MediaType) -> bytes:
        encoding = media_type.get_param_value("charset", "utf-8")
        return self.write_str(data, media_type).encode(encoding=encoding)


# How `yaml12` ends the message of a syntax error, as in "... at byte 7 line 2 column 2".
_YAML12_POSITION = re.compile(r" line (\d+) column (\d+)$")


@dataclass(frozen=True, slots=True)
class YamlReader:
    """A concrete YAML parser."""

    def read(self, text: str | bytes) -> JsonValue:
        if isinstance(text, bytes):
            text = text.decode()
        try:
            return cast("JsonValue", parse_yaml(text))  # yaml12.Yaml is structurally compatible
        except (OSError, TypeError, ValueError) as e:
            raise ReadError(str(e), position=self._position_in(str(e))) from e

    def spans(self, text: str | bytes) -> Mapping[str, Span]:
        """Locate every value of YAML that `read` accepted.

        `yaml12` does not report where values are, so this composes the text again with PyYAML,
        which does, and reads only the structure.
        PyYAML implements YAML 1.1, so it can reject text that `yaml12` accepts,
        in which case nothing is located.
        """
        if isinstance(text, bytes):
            text = text.decode()
        try:
            root = yaml.compose(text, Loader=yaml.SafeLoader)
        except yaml.YAMLError:
            return {}
        found: dict[str, Span] = {}
        if root is not None:
            self._locate(root, "", found, ancestors=set())
        return found

    def _locate(
        self, node: yaml.Node, pointer: str, found: dict[str, Span], *, ancestors: set[int]
    ) -> None:
        start, end = node.start_mark, node.end_mark
        found[pointer] = Span.of(
            (start.line + 1, start.column + 1),
            (end.line + 1, end.column + 1),
        )
        if id(node) in ancestors:  # An alias that refers to a node it is inside of.
            return
        ancestors.add(id(node))
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                if isinstance(key, yaml.ScalarNode):
                    self._locate(value, ptr(pointer, key.value), found, ancestors=ancestors)
        elif isinstance(node, yaml.SequenceNode):
            for index, value in enumerate(node.value):
                self._locate(value, ptr(pointer, index), found, ancestors=ancestors)
        ancestors.remove(id(node))

    def _position_in(self, message: str) -> Position | None:
        found = _YAML12_POSITION.search(message)
        return Position(int(found[1]), int(found[2])) if found else None


@dataclass(frozen=True, slots=True)
class YamlWriter:
    """A concrete YAML serializer."""

    def write(self, data: JsonValue) -> str:
        try:
            return format_yaml(data)  # type: ignore[return-value]  # yaml12 lacks precise stubs
        except (OSError, TypeError, ValueError) as e:
            raise WriteError(str(e)) from e


@dataclass(frozen=True, slots=True)
class JsonReader:
    """A concrete JSON parser."""

    def read(self, text: str | bytes) -> JsonValue:
        try:
            return orjson.loads(text)
        except JSONDecodeError as e:
            raise ReadError(str(e), position=Position(e.lineno, e.colno)) from e

    def spans(self, text: str | bytes) -> Mapping[str, Span]:
        """Locate every value of JSON that `read` accepted.

        `orjson` does not report where values are, so this scans the text again.
        The text is known to be valid, so the scan only has to find where each value ends.
        """
        if isinstance(text, bytes):
            text = text.decode()
        line_starts = [0, *(i + 1 for i, char in enumerate(text) if char == "\n")]
        scanner = _JsonScanner(text, line_starts, {})
        scanner.value(0, "")
        return scanner.found


@dataclass(frozen=True, slots=True)
class JsonWriter:
    """A concrete JSON serializer."""

    pretty: bool = False

    def write(self, data: JsonValue) -> str:
        option = orjson.OPT_APPEND_NEWLINE | orjson.OPT_INDENT_2 if self.pretty else 0
        try:
            return orjson.dumps(data, option=option).decode()  # type: ignore[return-value]  # orjson lacks precise stubs
        except JSONEncodeError as e:
            raise ReadError(str(e), position=None) from e


_JSON_WHITESPACE = re.compile(r"[ \t\n\r]*")
_JSON = JSONDecoder()


@dataclass(slots=True)
class _JsonScanner:
    """Finds where every value in valid JSON text starts and ends.

    Attributes:
        text: The JSON.
        line_starts: The offset in `text` at which each line starts.
        found: Where each value is, keyed by pointer. Filled as the scan goes.
    """

    text: str
    line_starts: list[int]
    found: dict[str, Span]

    def value(self, offset: int, pointer: str) -> int:
        """Scan the value at or after `offset`, and return the offset just after it."""
        start = self._skip_whitespace(offset)
        match self.text[start]:
            case "{":
                end = self._object(start + 1, pointer)
            case "[":
                end = self._array(start + 1, pointer)
            case _:  # A string, number, `true`, `false`, or `null`.
                end = _JSON.raw_decode(self.text, start)[1]
        self.found[pointer] = Span(self._position(start), self._position(end))
        return end

    def _object(self, offset: int, pointer: str) -> int:
        at = self._skip_whitespace(offset)
        if self.text[at] == "}":
            return at + 1
        while True:
            key, at = _JSON.raw_decode(self.text, self._skip_whitespace(at))
            at = self._skip_whitespace(at) + 1  # The colon.
            at = self._skip_whitespace(self.value(at, ptr(pointer, key)))
            if self.text[at] == "}":
                return at + 1
            at += 1  # The comma.

    def _array(self, offset: int, pointer: str) -> int:
        at = self._skip_whitespace(offset)
        if self.text[at] == "]":
            return at + 1
        for index in count():
            at = self._skip_whitespace(self.value(at, ptr(pointer, index)))
            if self.text[at] == "]":
                return at + 1
            at += 1  # The comma.
        raise AssertionError  # pragma: no cover — `count` does not end.

    def _skip_whitespace(self, offset: int) -> int:
        return cast("re.Match[str]", _JSON_WHITESPACE.match(self.text, offset)).end()

    def _position(self, offset: int) -> Position:
        line = bisect_right(self.line_starts, offset)
        return Position(line, offset - self.line_starts[line - 1] + 1)
