"""Pass-through transpilers: parse a document and re-emit it normalised.

- `JsonSchemaPassThruTranspiler` — JSON Schema → JSON Schema (identity round-trip).
- `OpenApiPassThruTranspiler` — OpenAPI 3.1 → OpenAPI 3.1 (identity round-trip).

Both accept a `use_yaml` flag (emit YAML instead of JSON, default `False`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import orjson

from schema_to._pipeline import Transpiler
from schema_to._result import Err, Ok, Result
from schema_to.io._sink import OutputArtifact
from schema_to.io._source import (
    JsonSchemaRawDocument,
    MediaType,
    MediaTypes,
    OpenApiRawDocument,
    RawDocument,
)
from schema_to.parse._json_schema import JsonSchemaParser
from schema_to.parse._openapi import OpenApiParser
from schema_to.serialize._json_schema import JsonSchemaSerializer
from schema_to.serialize._openapi import OpenApiSerializer

__all__ = ["JsonSchemaPassThruTranspiler", "OpenApiPassThruTranspiler"]

_JSON_YAML_ESSENCES = frozenset({"application/json", "application/yaml", "text/yaml"})


def _encode(data: object, *, use_yaml: bool) -> tuple[bytes, MediaType]:
    """Serialize `data` to bytes, returning content and the appropriate media type."""
    if use_yaml:
        from yaml12 import format_yaml  # noqa: PLC0415

        return format_yaml(data).encode("utf-8"), MediaTypes.yaml
    return orjson.dumps(
        data, option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE
    ), MediaTypes.json


def _peek_is_openapi(document: RawDocument) -> bool:
    """Return `True` if the document root object has an `openapi` version string.

    Used only when the document type is not already known (plain `RawDocument`).
    """
    if document.media_type.essence not in _JSON_YAML_ESSENCES:
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


@dataclass(frozen=True)
class JsonSchemaPassThruTranspiler(Transpiler):
    """Parse a JSON Schema document and emit it back as normalised JSON or YAML.

    Attributes:
        parser: JSON Schema parser (injected for testability).
        serializer: JSON Schema serializer (injected for testability).
        use_yaml: Emit YAML instead of JSON (default `False`).
    """

    parser: JsonSchemaParser = field(default_factory=JsonSchemaParser)
    serializer: JsonSchemaSerializer = field(default_factory=JsonSchemaSerializer)
    use_yaml: bool = False

    def accepts(self, document: RawDocument) -> bool:
        if isinstance(document, JsonSchemaRawDocument):
            return True
        if isinstance(document, OpenApiRawDocument):
            return False
        return document.media_type.essence in _JSON_YAML_ESSENCES and not _peek_is_openapi(document)

    def transpile(self, document: RawDocument) -> Result[Sequence[OutputArtifact]]:
        result = self.parser.apply(document)
        if isinstance(result, Err):
            return result
        data = self.serializer.serialize_document(result.value)
        content, media_type = _encode(data, use_yaml=self.use_yaml)
        ext = ".yaml" if self.use_yaml else ".json"
        stem = document.display_name or "schema"
        return Ok(
            [
                OutputArtifact(
                    artifact_id=f"{stem}.schema{ext}",
                    content=content,
                    media_type=media_type,
                    source_ids=(document.source_id,),
                )
            ]
        )


@dataclass(frozen=True)
class OpenApiPassThruTranspiler(Transpiler):
    """Parse an OpenAPI 3.1 document and emit it back as normalised JSON or YAML.

    Attributes:
        parser: OpenAPI parser (injected for testability).
        serializer: OpenAPI serializer (injected for testability).
        use_yaml: Emit YAML instead of JSON (default `False`).
    """

    parser: OpenApiParser = field(default_factory=OpenApiParser)
    serializer: OpenApiSerializer = field(default_factory=OpenApiSerializer)
    use_yaml: bool = False

    def accepts(self, document: RawDocument) -> bool:
        if isinstance(document, OpenApiRawDocument):
            return True
        if isinstance(document, JsonSchemaRawDocument):
            return False
        return _peek_is_openapi(document)

    def transpile(self, document: RawDocument) -> Result[Sequence[OutputArtifact]]:
        result = self.parser.apply(document)
        if isinstance(result, Err):
            return result
        data = self.serializer.serialize(result.value)
        content, media_type = _encode(data, use_yaml=self.use_yaml)
        ext = ".yaml" if self.use_yaml else ".json"
        stem = document.display_name or "openapi"
        return Ok(
            [
                OutputArtifact(
                    artifact_id=f"{stem}{ext}",
                    content=content,
                    media_type=media_type,
                    source_ids=(document.source_id,),
                )
            ]
        )
