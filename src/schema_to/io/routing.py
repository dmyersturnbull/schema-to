"""Routing utility: peek at document bytes to determine the schema format.

Called by `PeekingDirectorySource` as a content-aware secondary guard after filtering by filename extension.
Think: magic bytes.
Files with compound extensions like `.openapi.json` can be checked for specific content,
before being narrowed to their `RawDoc` subclasses.

The
"""

from collections.abc import Callable
from enum import Enum, auto
from typing import cast

from schema_to.io.core import JsonReader, ReadError, YamlReader

__all__ = ["DocType", "DocTypeGuesser", "is_schema_map", "peek_doc_type"]

_JSON_SCHEMA_KEYWORDS: frozenset[str] = frozenset(
    {
        "$schema",
        "$ref",
        "$dynamicRef",
        "$defs",
        "definitions",
        "type",
        "properties",
        "allOf",
        "anyOf",
        "oneOf",
        "items",
    }
)


class DocType(Enum):
    JSON_SCHEMA = auto()
    OPENAPI = auto()


DocTypeGuesser = Callable[[bytes], DocType | None]


def peek_doc_type(content: bytes) -> DocType | None:
    """Peek at raw bytes to determine schema format without a media-type hint.

    Tries JSON first, then YAML.  Returns:
    - `DocType.OPENAPI` if the dict contains `"openapi"` with a string value
    - `DocType.JSON_SCHEMA` if the dict contains any recognised JSON Schema keyword
       (see `_JSON_SCHEMA_KEYWORDS`; a bare `$ref` counts, since that alone is a schema)
    - `None`  if the bytes are unparseable or look like neither
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


def is_schema_map(content: bytes) -> bool:
    """Peek at raw bytes to decide whether they could be a map of named schemas.

    The evidence is negative rather than positive, because a map of named schemas has
    no marker of its own — it is an object whose keys are arbitrary names. What it is
    *not* is decidable, though:

    - an OpenAPI document, which declares `openapi: <version>` at the top level;
    - a single JSON Schema, which puts its keywords at the top level, whereas a
      schema map puts names there and keywords one level down;
    - anything that is not a JSON or YAML object at all.

    So a top-level JSON Schema keyword rules the file out, and a *second*-level one
    is what a schema map looks like. A file with neither — an empty object, or a
    config file of plain strings — is not claimed either.
    """
    data = _try_parse(content)
    if not isinstance(data, dict):
        return False
    top = cast("dict[str, object]", data)
    if isinstance(top.get("openapi"), str) or _JSON_SCHEMA_KEYWORDS & top.keys():
        return False
    return any(
        isinstance(entry, dict) and _JSON_SCHEMA_KEYWORDS & cast("dict[str, object]", entry).keys()
        for entry in top.values()
    )


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
