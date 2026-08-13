"""Reifiers that write a parsed document back out, normalised.

These close the pass-through targets: the CST *is* the output, so there is no AST
between parsing and writing.  Everything a filename needs — which file the document
came from, what it was called — the CST already carries, so the reifier does not need
the `RawDoc` it was parsed from.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override

from schema_to.cst.json_schema import JsonSchemaDocument
from schema_to.cst.openapi import OpenApiDocument
from schema_to.io.core import DefaultJsonLikeWriter, JsonLikeWriter
from schema_to.io.sink import JsonSchemaArtifact, OpenApiArtifact
from schema_to.pipeline import Reifier
from schema_to.reify._output import choose_output
from schema_to.result import Ok, Result
from schema_to.serialize.json_schema import JsonSchemaSerializer
from schema_to.serialize.openapi import OpenApiSerializer

if TYPE_CHECKING:
    from schema_to.io.media_type import MediaType

__all__ = ["JsonSchemaReifier", "OpenApiReifier"]


@dataclass(frozen=True, slots=True)
class JsonSchemaReifier(Reifier[JsonSchemaDocument, JsonSchemaArtifact]):
    """Serialises a JSON Schema document to a `.schema.json` or `.schema.yaml` artifact.

    Attributes:
        serializer: Turns the CST back into JSON-like data.
        writer: Encodes that data as bytes.
        output_media_type: Forces JSON or YAML; `None` follows the source document.
    """

    serializer: JsonSchemaSerializer = field(default_factory=JsonSchemaSerializer)
    writer: JsonLikeWriter = field(default_factory=DefaultJsonLikeWriter)
    output_media_type: MediaType | None = None

    @override
    def apply(self, input: JsonSchemaDocument) -> Result[Sequence[JsonSchemaArtifact]]:
        filename, artifact_cls = choose_output(input, self.output_media_type, kind="schema")
        data = self.serializer.serialize_document(input)
        content = self.writer.write_bytes(data, artifact_cls.media_type)
        artifact = artifact_cls(
            artifact_id=filename, content=content, source_ids=(input.source_id,)
        )
        return Ok([artifact])


@dataclass(frozen=True, slots=True)
class OpenApiReifier(Reifier[OpenApiDocument, OpenApiArtifact]):
    """Serialises an OpenAPI 3.1 document to an `.openapi.json` or `.openapi.yaml` artifact.

    Attributes:
        serializer: Turns the CST back into JSON-like data.
        writer: Encodes that data as bytes.
        output_media_type: Forces JSON or YAML; `None` follows the source document.
    """

    serializer: OpenApiSerializer = field(default_factory=OpenApiSerializer)
    writer: JsonLikeWriter = field(default_factory=DefaultJsonLikeWriter)
    output_media_type: MediaType | None = None

    @override
    def apply(self, input: OpenApiDocument) -> Result[Sequence[OpenApiArtifact]]:
        filename, artifact_cls = choose_output(input, self.output_media_type, kind="openapi")
        data = self.serializer.serialize(input)
        content = self.writer.write_bytes(data, artifact_cls.media_type)
        artifact = artifact_cls(
            artifact_id=filename,
            content=content,
            source_ids=(input.source_id,) if input.source_id else (),
        )
        return Ok([artifact])
