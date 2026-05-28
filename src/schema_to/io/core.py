from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import orjson
from orjson import JSONDecodeError, JSONEncodeError
from yaml12 import format_yaml, parse_yaml

from schema_to import MediaType, MediaTypes

if TYPE_CHECKING:
    from schema_to.core import JsonValue


class ReadError(Exception):
    def __init__(self, msg: str, *, line: int | None = None, column: int | None = None) -> None:
        super().__init__(msg)
        self.line = line
        self.column = column


class WriteError(Exception):
    def __init__(self, msg: str) -> None:
        super().__init__(msg)


@dataclass(frozen=True, slots=True)
class JsonLikeReader:
    def read(self, text: str | bytes, media_type: MediaType) -> JsonValue:
        if media_type == MediaTypes.yaml:
            return YamlReader().read(text)
        if media_type == MediaTypes.json:
            return JsonReader().read(text)
        msg = f"Unsupported media type for JSON Schema: {media_type}"
        raise ReadError(msg)


@dataclass(frozen=True, slots=True)
class YamlReader:
    def read(self, text: str | bytes) -> JsonValue:
        if isinstance(text, bytes):
            text = text.decode("utf-8")
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
            return orjson.dumps(data, option=option).decode("utf-8")  # type: ignore[return-value]  # orjson lacks precise stubs
        except JSONEncodeError as e:
            raise ReadError(str(e), line=None, column=None) from e
