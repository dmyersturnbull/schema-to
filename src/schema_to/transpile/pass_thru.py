"""Pass-through transpilers: parse a document and re-emit it normalised.

- `JsonSchemaPassThruTranspiler` — JSON Schema → JSON Schema (identity round-trip).
- `OpenApiPassThruTranspiler` — OpenAPI 3.1 → OpenAPI 3.1 (identity round-trip).

Both accept a `use_yaml` flag (emit YAML instead of JSON, default `False`).

Documents arrive as `JsonSchemaRawDoc` or `OpenApiRawDoc` because
`FileDataSource` uses compound filename extensions to select the correct subclass
at source-collection time.  Transpiler `accepts()` methods are therefore a simple
`isinstance` check with no additional I/O.
"""


from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override

from schema_to.io.core import DefaultJsonLikeReader, DefaultJsonLikeWriter
from schema_to.io.sink import Artifact
from schema_to.io.source import JsonSchemaRawDoc, OpenApiRawDoc
from schema_to.parse.json_schema import JsonSchemaParser
from schema_to.parse.openapi import OpenApiParser
from schema_to.pipeline import Transpiler
from schema_to.result import Err, Ok, Result
from schema_to.serialize.json_schema import JsonSchemaSerializer
from schema_to.serialize.openapi import OpenApiSerializer
from schema_to.transpile._utils import choose_output

if TYPE_CHECKING:
    from collections.abc import Sequence

    from schema_to.io.core import JsonLikeWriter
    from schema_to.io.media_type import MediaType

__all__ = ["JsonSchemaPassThruTranspiler", "OpenApiPassThruTranspiler"]


@dataclass(frozen=True, slots=True)
class JsonSchemaPassThruTranspiler(Transpiler[JsonSchemaRawDoc, Artifact]):
    """Parse a JSON Schema document and emit it back as normalised JSON or YAML."""

    parser: JsonSchemaParser = field(
        default_factory=lambda: JsonSchemaParser(reader=DefaultJsonLikeReader())
    )
    serializer: JsonSchemaSerializer = field(default_factory=JsonSchemaSerializer)
    writer: JsonLikeWriter = field(default_factory=DefaultJsonLikeWriter)
    output_media_type: MediaType | None = None

    @override
    def accepts(self, doc: JsonSchemaRawDoc) -> bool:
        return isinstance(doc, JsonSchemaRawDoc)

    @override
    def transpile(self, doc: JsonSchemaRawDoc) -> Result[Sequence[Artifact]]:
        result = self.parser.apply(doc)
        if isinstance(result, Err):
            return result
        data = self.serializer.serialize_document(result.value)
        filename, artifact_cls = choose_output(doc, self.output_media_type, kind="schema")
        content = self.writer.write_bytes(data, artifact_cls.media_type)
        artifact = artifact_cls(artifact_id=filename, content=content, source_ids=(doc.doc_id,))
        return Ok([artifact])


@dataclass(frozen=True, slots=True)
class OpenApiPassThruTranspiler(Transpiler[OpenApiRawDoc, Artifact]):
    """Parse an OpenAPI 3.1 document and emit it back as normalised JSON or YAML."""

    parser: OpenApiParser = field(
        default_factory=lambda: OpenApiParser(
            reader=DefaultJsonLikeReader(), js=JsonSchemaParser(reader=DefaultJsonLikeReader())
        )
    )
    serializer: OpenApiSerializer = field(default_factory=OpenApiSerializer)
    writer: JsonLikeWriter = field(default_factory=DefaultJsonLikeWriter)
    output_media_type: MediaType | None = None

    @override
    def accepts(self, doc: OpenApiRawDoc) -> bool:
        return isinstance(doc, OpenApiRawDoc)

    @override
    def transpile(self, doc: OpenApiRawDoc) -> Result[Sequence[Artifact]]:
        result = self.parser.apply(doc)
        if isinstance(result, Err):
            return result
        data = self.serializer.serialize(result.value)
        filename, artifact_cls = choose_output(doc, self.output_media_type, kind="openapi")
        content = self.writer.write_bytes(data, artifact_cls.media_type)
        artifact = artifact_cls(artifact_id=filename, content=content, source_ids=(doc.doc_id,))
        return Ok([artifact])
