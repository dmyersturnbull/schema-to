from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import final

import orjson
from yaml12 import format_yaml, parse_yaml

from schema_to._core import JsonValue


class Reader[T](ABC):
    @abstractmethod
    def read(self, data: str | bytes) -> T:
        raise NotImplementedError

    @final
    @classmethod
    def _decode(cls, data: str | bytes) -> str:
        if isinstance(data, bytes):
            return data.decode("utf-8")
        return data


class Writer[T](ABC):
    @abstractmethod
    def write_str(self, data: T) -> str:
        raise NotImplementedError
        # Default: `return self.write_bytes(data).decode("utf-8")`

    @abstractmethod
    def write_bytes(self, data: T) -> bytes:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class YamlReader(Reader[JsonValue]):
    def read(self, data: str | bytes) -> JsonValue:
        data = self._decode(data)
        return parse_yaml(data)  # ty:ignore[invalid-return-type]


@dataclass(frozen=True, slots=True)
class YamlWriter(Writer[JsonValue]):
    def write_str(self, data: JsonValue) -> str:
        return format_yaml(data)

    def write_bytes(self, data: JsonValue) -> bytes:
        return format_yaml(data).encode("utf-8")


@dataclass(frozen=True, slots=True)
class JsonReader(Reader[JsonValue]):
    def read(self, data: str | bytes) -> JsonValue:
        data = self._decode(data)
        return orjson.loads(data)


@dataclass(frozen=True, slots=True)
class JsonWriter(Writer[JsonValue]):
    pretty: bool = False

    def write_str(self, data: JsonValue) -> str:
        return self.write_bytes(data).decode("utf-8")

    def write_bytes(self, data: JsonValue) -> bytes:
        option = orjson.OPT_APPEND_NEWLINE | orjson.OPT_INDENT_2 if self.pretty else 0
        return orjson.dumps(data, option=option)
