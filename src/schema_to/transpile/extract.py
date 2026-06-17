"""Transpilers that extract sub-documents from a larger document."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override

from schema_to import JsonSchemaParser
from schema_to.cst.base import SourceRef
from schema_to.cst.json_schema import BooleanSchema, JsonSchemaDocument, ObjectSchema
from schema_to.io.core import DefaultJsonLikeReader, DefaultJsonLikeWriter, JsonLikeWriter
from schema_to.io.sink import JsonSchemaArtifact
from schema_to.io.source import OpenApiRawDoc
from schema_to.parse.openapi import OpenApiParser
from schema_to.pipeline import Transpiler
from schema_to.result import Err, Ok, Result
from schema_to.serialize.json_schema import JsonSchemaSerializer
from schema_to.transpile._utils import choose_output

if TYPE_CHECKING:
    from collections.abc import Sequence

    from schema_to.io.media_type import MediaType

__all__ = ["OpenApiExtractTranspiler"]


@dataclass(frozen=True, slots=True)
class OpenApiExtractTranspiler(Transpiler[OpenApiRawDoc, JsonSchemaArtifact]):
    """Extract `components/schemas` from an OpenAPI document as standalone JSON Schema files.

    Each named schema in `components/schemas` becomes a separate `Artifact`
    with `artifact_id` equal to `<schema-name>.schema.json` (or `.yaml`).

    Attributes:
        parser: OpenAPI parser (injected for testability).
        js_serializer: JSON Schema serializer (injected for testability).
    """

    parser: OpenApiParser = field(
        default_factory=lambda: OpenApiParser(
            reader=DefaultJsonLikeReader(), js=JsonSchemaParser(reader=DefaultJsonLikeReader())
        )
    )
    js_serializer: JsonSchemaSerializer = field(default_factory=JsonSchemaSerializer)
    writer: JsonLikeWriter = field(default_factory=DefaultJsonLikeWriter)
    output_media_type: MediaType | None = None

    @override
    def accepts(self, doc: OpenApiRawDoc) -> bool:
        return isinstance(doc, OpenApiRawDoc)

    @override
    def transpile(self, doc: OpenApiRawDoc) -> Result[Sequence[JsonSchemaArtifact]]:
        result = self.parser.apply(doc)
        if isinstance(result, Err):
            return result
        cst = result.value
        artifacts = []
        for name, schema in cst.components.schemas.items():
            artifacts.append(self._extract_doc(doc, name, schema))
        return Ok(artifacts)

    def _extract_doc(
        self, doc: OpenApiRawDoc, name: str, schema: BooleanSchema | ObjectSchema
    ) -> JsonSchemaArtifact:
        doc_cst = JsonSchemaDocument(
            root=schema,
            source_id=doc.doc_id,
            display_name=name,
            source_ref=SourceRef(doc.doc_id, f"/components/schemas/{name}"),
        )
        data = self.js_serializer.serialize_document(doc_cst)
        filename, artifact_cls = choose_output(doc, self.output_media_type, kind="schema")
        content = self.writer.write_bytes(data, artifact_cls.media_type)
        return artifact_cls(artifact_id=filename, content=content, source_ids=(doc.doc_id,))
