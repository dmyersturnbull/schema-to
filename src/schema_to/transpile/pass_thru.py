"""Pass-through transpilers: parse a document and re-emit it normalised.

- `JsonSchemaPassThruTranspiler` — JSON Schema → JSON Schema (identity round-trip).
- `OpenApiPassThruTranspiler` — OpenAPI 3.1 → OpenAPI 3.1 (identity round-trip).

Both accept a `use_yaml` flag (emit YAML instead of JSON, default `False`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from schema_to.io.sink import Artifact, JsonArtifact, YamlArtifact
from schema_to.io.source import JsonSchemaRawDoc, OpenApiRawDoc, RawDoc
from schema_to.parse.json_schema import JsonSchemaParser
from schema_to.parse.openapi import OpenApiParser
from schema_to.pipeline import Transpiler
from schema_to.result import Err, Ok, Result
from schema_to.serialize.json_schema import JsonSchemaSerializer
from schema_to.serialize.openapi import OpenApiSerializer
from schema_to.transpile._utils import encode, peek_is_openapi

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["JsonSchemaPassThruTranspiler", "OpenApiPassThruTranspiler"]


@dataclass(frozen=True)
class JsonSchemaPassThruTranspiler(Transpiler[RawDoc, Artifact]):
    """Parse a JSON Schema document and emit it back as normalised JSON or YAML.

    Attributes:
        parser: JSON Schema parser (injected for testability).
        serializer: JSON Schema serializer (injected for testability).
        use_yaml: Emit YAML instead of JSON (default `False`).
    """

    parser: JsonSchemaParser = field(default_factory=JsonSchemaParser)
    serializer: JsonSchemaSerializer = field(default_factory=JsonSchemaSerializer)
    use_yaml: bool = False

    def accepts(self, doc: RawDoc) -> bool:
        if isinstance(doc, OpenApiRawDoc):
            return False
        if isinstance(doc, JsonSchemaRawDoc):
            return True
        return not peek_is_openapi(doc)

    def transpile(self, doc: RawDoc) -> Result[Sequence[Artifact]]:
        result = self.parser.apply(cast("JsonSchemaRawDoc", doc))  # accepts() guarantees the type
        if isinstance(result, Err):
            return result
        data = self.serializer.serialize_document(result.value)
        content, _ = encode(data, use_yaml=self.use_yaml)
        ext = ".yaml" if self.use_yaml else ".json"
        stem = doc.display_name or "schema"
        artifact_cls = YamlArtifact if self.use_yaml else JsonArtifact
        return Ok(
            [
                artifact_cls(
                    artifact_id=f"{stem}.schema{ext}", content=content, source_ids=(doc.source_id,)
                )
            ]
        )


@dataclass(frozen=True)
class OpenApiPassThruTranspiler(Transpiler[RawDoc, Artifact]):
    """Parse an OpenAPI 3.1 document and emit it back as normalised JSON or YAML.

    Attributes:
        parser: OpenAPI parser (injected for testability).
        serializer: OpenAPI serializer (injected for testability).
        use_yaml: Emit YAML instead of JSON (default `False`).
    """

    parser: OpenApiParser = field(default_factory=OpenApiParser)
    serializer: OpenApiSerializer = field(default_factory=OpenApiSerializer)
    use_yaml: bool = False

    def accepts(self, doc: RawDoc) -> bool:
        return isinstance(doc, OpenApiRawDoc) or peek_is_openapi(doc)

    def transpile(self, doc: RawDoc) -> Result[Sequence[Artifact]]:
        result = self.parser.apply(cast("OpenApiRawDoc", doc))  # accepts() guarantees the type
        if isinstance(result, Err):
            return result
        data = self.serializer.serialize(result.value)
        content, _ = encode(data, use_yaml=self.use_yaml)
        ext = ".yaml" if self.use_yaml else ".json"
        stem = doc.display_name or "openapi"
        artifact_cls = YamlArtifact if self.use_yaml else JsonArtifact
        return Ok(
            [artifact_cls(artifact_id=f"{stem}{ext}", content=content, source_ids=(doc.source_id,))]
        )
