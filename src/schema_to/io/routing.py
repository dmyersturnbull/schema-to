"""Routing utility: peek at document bytes to determine the schema format.

Called by `FileDataSource` at document-creation time so that plain file bytes
can be promoted to the correct typed `RawDoc` subclass
(`OpenApiRawDoc` vs `JsonSchemaRawDoc`) before transpiler dispatch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from schema_to.io.core import JsonLikeReader, ReadError

if TYPE_CHECKING:
    from schema_to.core import JsonValue
    from schema_to.io.media_type import MediaType

__all__ = ["peek_is_openapi"]

_JSON_YAML_ESSENCES: frozenset[str] = frozenset(
    {"application/json", "application/yaml", "text/yaml"}
)


def peek_is_openapi(content: bytes, media_type: MediaType) -> bool:
    """Return `True` if the raw bytes represent an OpenAPI 3.x document.

    Both JSON Schema and OpenAPI share the same `.json` / `.yaml` file
    extensions, so the only way to distinguish them is to parse the content
    and check for the `"openapi"` version field.  This peek is performed
    once at source-creation time so that transpiler `accepts()` methods can
    use simple `isinstance` checks rather than re-parsing on every dispatch.
    """
    if media_type.essence not in _JSON_YAML_ESSENCES:
        return False
    try:
        data = JsonLikeReader().read(content, media_type)
    except ReadError:
        return False
    if not isinstance(data, dict):
        return False
    # After isinstance(data, dict), ty narrows to dict[object, object]; cast to get str keys.
    d = cast("dict[str, JsonValue]", data)
    return isinstance(d.get("openapi"), str)
