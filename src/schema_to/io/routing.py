"""Routing utility: peek at document bytes to determine the schema format.

Called by `PeekingDirectorySource` as a secondary content guard so that files
matched by compound extensions can be further validated before being promoted
to typed `RawDoc` subclasses.
"""


from enum import Enum, auto
from typing import cast

from schema_to.io.core import JsonReader, ReadError, YamlReader

__all__ = ["DocType", "peek_doc_type"]

_JSON_SCHEMA_KEYWORDS: frozenset[str] = frozenset(
    {"$schema", "$defs", "definitions", "type", "properties", "allOf", "anyOf", "oneOf", "items"}
)


class DocType(Enum):
    JSON_SCHEMA = auto()
    OPENAPI = auto()


def peek_doc_type(content: bytes) -> DocType | None:
    """Peek at raw bytes to determine schema format without a media-type hint.

    Tries JSON first, then YAML.  Returns:
    - `DocType.OPENAPI`      if the dict contains `"openapi"` with a string value
    - `DocType.JSON_SCHEMA`  if the dict contains recognised JSON Schema keywords
                             (any of: `$schema`, `$defs`, `definitions`, `type`,
                             `properties`, `allOf`, `anyOf`, `oneOf`, `items`)
    - `None`                 if the bytes are unparseable or look like neither
    """
    data = _try_parse(content)
    if not isinstance(data, dict):
        return None
    d = cast("dict[str, object]", data)
    if isinstance(d.get("openapi"), str):
        return DocType.OPENAPI
    if _JSON_SCHEMA_KEYWORDS & d.keys():
        return DocType.JSON_SCHEMA
    return None


def _try_parse(content: bytes) -> object:
    try:
        return JsonReader().read(content)
    except ReadError:  # ruff:ignore[try-except-pass]  # Just using the exception to check.
        pass
    try:
        return YamlReader().read(content)
    except ReadError:  # ruff:ignore[try-except-pass]  # Just using the exception to check.
        pass
    return None
