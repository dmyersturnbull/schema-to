"""Transpilers that extract sub-documents from a larger document."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from schema_to.cst.base import SourceRef
from schema_to.cst.json_schema import JsonSchemaDocument
from schema_to.io.sink import Artifact, JsonSchemaJsonArtifact, JsonSchemaYamlArtifact
from schema_to.io.source import OpenApiRawDoc, RawDoc
from schema_to.parse.openapi import OpenApiParser
from schema_to.pipeline import Transpiler
from schema_to.result import Err, Ok, Result
from schema_to.serialize.json_schema import JsonSchemaSerializer
from schema_to.transpile._utils import encode

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["OpenApiExtractTranspiler"]


@dataclass(frozen=True, slots=True)
class OpenApiExtractTranspiler(Transpiler[RawDoc, Artifact]):
    """Extract `components/schemas` from an OpenAPI document as standalone JSON Schema files.

    Each named schema in `components/schemas` becomes a separate `Artifact`
    with `artifact_id` equal to `<schema-name>.schema.json` (or `.yaml`).

    Attributes:
        parser: OpenAPI parser (injected for testability).
        js_serializer: JSON Schema serializer (injected for testability).
        use_yaml: Emit YAML instead of JSON (default `False`).
    """

    parser: OpenApiParser = field(default_factory=OpenApiParser)
    js_serializer: JsonSchemaSerializer = field(default_factory=JsonSchemaSerializer)
    use_yaml: bool = False

    def accepts(self, doc: RawDoc) -> bool:
        return isinstance(doc, OpenApiRawDoc)

    def transpile(self, doc: RawDoc) -> Result[Sequence[Artifact]]:
        assert isinstance(doc, OpenApiRawDoc)  # noqa: S101  # guaranteed by accepts()
        result = self.parser.apply(doc)
        if isinstance(result, Err):
            return result
        cst = result.value
        artifacts: list[Artifact] = []
        ext = ".yaml" if self.use_yaml else ".json"

        artifact_cls = JsonSchemaYamlArtifact if self.use_yaml else JsonSchemaJsonArtifact
        for name, schema in cst.components.schemas.items():
            doc_cst = JsonSchemaDocument(
                root=schema,
                source_id=doc.source_id,
                display_name=name,
                source_ref=SourceRef(doc.source_id, f"/components/schemas/{name}"),
            )
            data = self.js_serializer.serialize_document(doc_cst)
            content = encode(data, use_yaml=self.use_yaml)
            artifacts.append(
                artifact_cls(
                    artifact_id=f"{name}.schema{ext}", content=content, source_ids=(doc.source_id,)
                )
            )

        return Ok(artifacts)
