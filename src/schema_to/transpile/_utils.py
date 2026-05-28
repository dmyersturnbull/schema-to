"""Shared helpers for the transpile package."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from schema_to import MediaType, MediaTypes
from schema_to.io.core import JsonReader, JsonWriter, YamlReader, YamlWriter

if TYPE_CHECKING:
    from schema_to.core import JsonValue
    from schema_to.io.source import RawDoc

JSON_YAML_ESSENCES: frozenset[str] = frozenset(
    {"application/json", "application/yaml", "text/yaml"}
)


def encode(data: JsonValue, *, use_yaml: bool) -> tuple[bytes, MediaType]:
    if use_yaml:
        return YamlWriter().write(data).encode("utf-8"), MediaTypes.yaml
    return JsonWriter(pretty=True).write(data).encode("utf-8"), MediaTypes.json


def peek_is_openapi(document: RawDoc) -> bool:
    """Return `True` if the document root object has an `openapi` version string."""
    if document.media_type.essence not in JSON_YAML_ESSENCES:
        return False
    try:
        if document.media_type.essence == "application/json":
            data = JsonReader().read(document.content.decode("utf-8"))
        else:
            data = YamlReader().read(document.content.decode("utf-8"))
        return isinstance(data, dict) and isinstance(
            cast("dict[str, object]", data).get("openapi"), str
        )
    except json.JSONDecodeError, ValueError, UnicodeDecodeError:
        return False
