"""JSON Schema 2020-12 document parser.

Converts a `RawDoc` (JSON or YAML bytes) into a `JsonSchemaDocument` CST.
The parser is **non-resolving**:
`$ref` and `$dynamicRef` values are stored as raw URI strings.
Pass the result to a `RefResolver` stage to inline them.

Every keyword is read by the shared plan interpreter in `parse._build`,
driven by the field annotations on `ObjectSchema`.
What remains here is the document envelope:
decoding the bytes, and attaching the identity and base URI that the `RawDoc` carries rather than the schema.

Errors are accumulated, so a single parse call returns the complete diagnostics.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from schema_to import DefaultJsonLikeReader
from schema_to.core import as_object
from schema_to.cst.json_schema import JsonSchema, JsonSchemaDocument, JsonSchemaMapDocument
from schema_to.errors import ParseError, TranspilationError
from schema_to.io.source import JsonSchemaRawDoc, SchemaMapRawDoc
from schema_to.parse._build import Cursor, Failed, build_schema
from schema_to.parse._utils import decode_raw_doc, locate_raw_doc
from schema_to.pipeline import DocParser
from schema_to.result import Err, Ok, Result

if TYPE_CHECKING:
    from schema_to.io.core import JsonLikeReader

__all__ = ["JsonSchemaMapParser", "JsonSchemaParser"]


@dataclass(frozen=True, slots=True, kw_only=True)
class JsonSchemaParser(DocParser[JsonSchemaRawDoc, JsonSchemaDocument]):
    """Parses JSON or YAML bytes into a `JsonSchemaDocument` CST.

    The parser is stateless: a single instance may be reused across documents.
    """

    reader: JsonLikeReader = field(default_factory=DefaultJsonLikeReader)

    def apply(self, input: JsonSchemaRawDoc) -> Result[JsonSchemaDocument]:
        try:
            raw = decode_raw_doc(input, self.reader)
        except TranspilationError as exc:
            return Err((exc,))
        at = Cursor.of(input, locate_raw_doc(input, self.reader), None)
        root = build_schema(raw, at)
        if isinstance(root, Failed) or at.errors:
            return Err(tuple(at.errors), warnings=tuple(at.warnings))
        return Ok(
            JsonSchemaDocument(root=root, source_id=input.uri, display_name=input.display_name),
            warnings=tuple(at.warnings),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class JsonSchemaMapParser(DocParser[SchemaMapRawDoc, JsonSchemaMapDocument]):
    """Parses a map of names to schemas into a `JsonSchemaMapDocument` CST.

    Each entry is parsed at the pointer it occupies in the document —
    schema `foo` at `/foo` —
    so that a `$ref` written by a sibling file (`./this.yaml#/foo`)
    resolves against the same address.
    """

    schema_parser: JsonSchemaParser = field(default_factory=JsonSchemaParser)

    def apply(self, input: SchemaMapRawDoc) -> Result[JsonSchemaMapDocument]:
        try:
            raw = decode_raw_doc(input, self.schema_parser.reader)
        except TranspilationError as exc:
            return Err((exc,))
        entries = as_object(raw)
        if entries is None:
            return Err.of(
                ParseError(
                    f"A schema-map document must be an object mapping names to schemas; "
                    f"got {type(raw).__name__!r}.",
                    location=input.ref(""),
                )
            )
        at = Cursor.of(input, locate_raw_doc(input, self.schema_parser.reader), None)
        schemas: dict[str, JsonSchema] = {}
        for name, value in entries.items():
            schema = build_schema(value, at.at(name))
            if not isinstance(schema, Failed):
                schemas[name] = schema
        if at.errors:
            return Err(tuple(at.errors), warnings=tuple(at.warnings))
        return Ok(
            JsonSchemaMapDocument(schemas=schemas, source_id=input.uri), warnings=tuple(at.warnings)
        )
