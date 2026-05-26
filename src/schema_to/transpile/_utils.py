"""Shared helpers for the transpile package."""

from __future__ import annotations

from typing import TYPE_CHECKING

import orjson

from schema_to.io.source import MediaType, MediaTypes

if TYPE_CHECKING:
    from schema_to.io.source import RawDocument

JSON_YAML_ESSENCES: frozenset[str] = frozenset(
    {"application/json", "application/yaml", "text/yaml"}
)


def encode(data: object, *, use_yaml: bool) -> tuple[bytes, MediaType]:
    if use_yaml:
        from yaml12 import format_yaml  # noqa: PLC0415

        return format_yaml(data).encode("utf-8"), MediaTypes.yaml
    return orjson.dumps(
        data, option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE
    ), MediaTypes.json


def peek_is_openapi(document: RawDocument) -> bool:
    """Return `True` if the document root object has an `openapi` version string."""
    if document.media_type.essence not in JSON_YAML_ESSENCES:
        return False
    try:
        if document.media_type.essence == "application/json":
            data = orjson.loads(document.content)
        else:
            from yaml12 import parse_yaml  # noqa: PLC0415

            data = parse_yaml(document.content.decode("utf-8"))
        return isinstance(data, dict) and isinstance(data.get("openapi"), str)
    except Exception:  # noqa: BLE001
        return False
