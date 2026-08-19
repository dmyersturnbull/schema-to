"""Defines abstract and concrete classes for reading and writing JSON-compatible formats."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import orjson
from orjson import JSONDecodeError, JSONEncodeError
from yaml12 import format_yaml, parse_yaml

from schema_to.io.media_type import MediaType, MediaTypes

if TYPE_CHECKING:
    from collections.abc import Set

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
    def __init__(self, msg: str, *, line: int | None = None, column: int | None = None) -> None:
        super().__init__(msg)
        self.line = line
        self.column = column


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


@dataclass(frozen=True, slots=True)
class YamlReader:
    def read(self, text: str | bytes) -> JsonValue:
        if isinstance(text, bytes):
            text = text.decode()
        try:
            return cast("JsonValue", parse_yaml(text))  # yaml12.Yaml is structurally compatible
        except (OSError, TypeError, ValueError) as e:
            raise ReadError(str(e)) from e


@dataclass(frozen=True, slots=True)
class YamlWriter:
    def write(self, data: JsonValue) -> str:
        try:
            return format_yaml(data)  # type: ignore[return-value]  # yaml12 lacks precise stubs
        except (OSError, TypeError, ValueError) as e:
            raise WriteError(str(e)) from e


@dataclass(frozen=True, slots=True)
class JsonReader:
    def read(self, text: str | bytes) -> JsonValue:
        try:
            return orjson.loads(text)
        except JSONDecodeError as e:
            raise ReadError(str(e), line=e.lineno, column=e.colno) from e


@dataclass(frozen=True, slots=True)
class JsonWriter:
    pretty: bool = False

    def write(self, data: JsonValue) -> str:
        option = orjson.OPT_APPEND_NEWLINE | orjson.OPT_INDENT_2 if self.pretty else 0
        try:
            return orjson.dumps(data, option=option).decode()  # type: ignore[return-value]  # orjson lacks precise stubs
        except JSONEncodeError as e:
            raise ReadError(str(e), line=None, column=None) from e
