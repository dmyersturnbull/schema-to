"""Shared helpers for the transpile package."""

from __future__ import annotations

from typing import TYPE_CHECKING

from schema_to.io.core import JsonWriter, YamlWriter
from schema_to.io.media_type import MediaType, MediaTypes

if TYPE_CHECKING:
    from schema_to.core import JsonValue


def encode(data: JsonValue, *, use_yaml: bool) -> tuple[bytes, MediaType]:
    if use_yaml:
        return YamlWriter().write(data).encode("utf-8"), MediaTypes.yaml
    return JsonWriter(pretty=True).write(data).encode("utf-8"), MediaTypes.json
