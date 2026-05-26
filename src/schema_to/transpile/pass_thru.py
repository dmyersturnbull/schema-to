"""Pass-through transpilers: parse a document and re-emit it normalised.

- `JsonSchemaPassThruTranspiler` — JSON Schema → JSON Schema (identity round-trip).
- `OpenApiPassThruTranspiler` — OpenAPI 3.1 → OpenAPI 3.1 (identity round-trip).

Both accept a `use_yaml` flag (emit YAML instead of JSON, default `False`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from schema_to.transpile.utils import JSON_YAML_ESSENCES, encode, peek_is_openapi

from schema_to.io.sink import OutputArtifact
from schema_to.io.source import JsonSchemaRawDocument, OpenApiRawDocument, RawDocument
from schema_to.parse.json_schema import JsonSchemaParser
from schema_to.parse.openapi import OpenApiParser
from schema_to.pipeline import Transpiler
from schema_to.result import Err, Ok, Result
from schema_to.serialize.json_schema import JsonSchemaSerializer
from schema_to.serialize.openapi import OpenApiSerializer

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["JsonSchemaPassThruTranspiler", "OpenApiPassThruTranspiler"]


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
        return document.media_type.essence in JSON_YAML_ESSENCES and not peek_is_openapi(document)

    def transpile(self, document: RawDocument) -> Result[Sequence[OutputArtifact]]:
        result = self.parser.apply(document)
        if isinstance(result, Err):
            return result
        data = self.serializer.serialize_document(result.value)
        content, media_type = encode(data, use_yaml=self.use_yaml)
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
        return peek_is_openapi(document)

    def transpile(self, document: RawDocument) -> Result[Sequence[OutputArtifact]]:
        result = self.parser.apply(document)
        if isinstance(result, Err):
            return result
        data = self.serializer.serialize(result.value)
        content, media_type = encode(data, use_yaml=self.use_yaml)
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
