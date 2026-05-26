from dataclasses import dataclass
from typing import TYPE_CHECKING

import orjson
from yaml12 import format_yaml, parse_yaml

if TYPE_CHECKING:
    from schema_to.core import JsonValue


@dataclass(frozen=True, slots=True)
class YamlReader:
    def read(self, text: str) -> JsonValue:
        return parse_yaml(text)


@dataclass(frozen=True, slots=True)
class YamlWriter:
    def write(self, data: JsonValue) -> JsonValue:
        return format_yaml(data)


@dataclass(frozen=True, slots=True)
class JsonReader:
    def read(self, text: str) -> JsonValue:
        return orjson.loads(text)


@dataclass(frozen=True, slots=True)
class JsonWriter:
    pretty: bool = False

    def write(self, data: JsonValue) -> JsonValue:
        option = orjson.OPT_APPEND_NEWLINE | orjson.OPT_INDENT_2 if self.pretty else 0
        return orjson.dumps(data, option=option).decode("utf-8")
