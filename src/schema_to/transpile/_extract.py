"""Transpilers that extract sub-documents from a larger document."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from schema_to._pipeline import Transpiler
from schema_to._result import Err, Ok, Result
from schema_to.cst._base import SourceRef
from schema_to.cst._json_schema import JsonSchemaDocument
from schema_to.io._sink import OutputArtifact
from schema_to.io._source import (
    JsonSchemaRawDocument,
    OpenApiRawDocument,
    RawDocument,
)
from schema_to.parse._openapi import OpenApiParser
from schema_to.serialize._json_schema import JsonSchemaSerializer
from schema_to.transpile._utils import encode, peek_is_openapi

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["OpenApiExtractTranspiler"]


@dataclass(frozen=True)
class OpenApiExtractTranspiler(Transpiler):
    """Extract `components/schemas` from an OpenAPI document as standalone JSON Schema files.

    Each named schema in `components/schemas` becomes a separate `OutputArtifact`
    with `artifact_id` equal to `<schema-name>.schema.json` (or `.yaml`).

    Attributes:
        parser: OpenAPI parser (injected for testability).
        js_serializer: JSON Schema serializer (injected for testability).
        use_yaml: Emit YAML instead of JSON (default `False`).
    """

    parser: OpenApiParser = field(default_factory=OpenApiParser)
    js_serializer: JsonSchemaSerializer = field(default_factory=JsonSchemaSerializer)
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
        cst = result.value
        artifacts: list[OutputArtifact] = []
        ext = ".yaml" if self.use_yaml else ".json"

        for name, schema in cst.components.schemas.items():
            doc_cst = JsonSchemaDocument(
                root=schema,
                source_id=document.source_id,
                display_name=name,
                source_ref=SourceRef(document.source_id, f"/components/schemas/{name}"),
            )
            data = self.js_serializer.serialize_document(doc_cst)
            content, media_type = encode(data, use_yaml=self.use_yaml)
            artifacts.append(
                OutputArtifact(
                    artifact_id=f"{name}.schema{ext}",
                    content=content,
                    media_type=media_type,
                    source_ids=(document.source_id,),
                )
            )

        return Ok(artifacts)
