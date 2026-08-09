"""Adapter that lets any per-schema target consume documents holding several schemas.

A schema-map file is a *set* of schemas, so every target needs an answer to
"what does one produce from N schemas?"  There are two, and both exist:

- A target whose unit is one schema — Pydantic models, a pass-thru re-emit — takes
  the schemas one at a time.  That is this module: each document is split into one
  virtual document per named schema, and the inner transpiler sees only those.
- A target whose unit is the whole set — a PostgreSQL migration, whose foreign keys
  cannot be ordered until every table is known — consumes the batch directly.
  See `transpile.sql_tables`.

A virtual document keeps the file it came from in its ID
(`…/catalog.yaml#/author-data`), so a diagnostic names the real file *and* the schema
within it, rather than one at the cost of the other.  That fragment is also the
pointer a sibling file's `$ref` would use, so the ID stays a real address.

Known limitation: a schema referring to a *sibling in the same file* (`$ref: "#/other"`)
does not resolve after expansion.  `#/other` means "the `other` member of this
document", and once the file has been split, each schema *is* the document — the
sibling is no longer inside it.  Targets whose unit is the whole set are unaffected,
since nothing is split.  Fixing it for per-schema targets means either giving the
inner transpiler a resolver seeded with the unsplit documents, or inlining each
schema so it stands alone; the second duplicates shared definitions rather than
sharing them, which is a real cost for a target that generates named types.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override

from schema_to.io.core import DefaultJsonLikeWriter, JsonLikeWriter
from schema_to.io.source import JsonSchemaRawDoc, SchemaMapRawDoc
from schema_to.parse.json_schema import JsonSchemaMapParser
from schema_to.pipeline import Transpiler
from schema_to.result import Err, Ok, Result
from schema_to.serialize.json_schema import JsonSchemaSerializer

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from schema_to.cst.json_schema import JsonSchemaMapDocument
    from schema_to.errors import TranspilationError, TranspilationWarning
    from schema_to.io.sink import Artifact

__all__ = ["SchemaMapExpandingTranspiler"]

_SERIALIZER = JsonSchemaSerializer()


@dataclass(frozen=True, slots=True)
class SchemaMapExpandingTranspiler[O: Artifact](Transpiler[SchemaMapRawDoc, O]):
    """Presents each named schema of a schema-map document to a per-schema transpiler.

    Attributes:
        inner: The transpiler that handles one schema at a time.
        parser: Parses the schema map.  Injected for testability.
        writer: Re-encodes each named schema as bytes for `inner` to parse back.
    """

    inner: Transpiler[JsonSchemaRawDoc, O]
    parser: JsonSchemaMapParser = field(default_factory=JsonSchemaMapParser)
    writer: JsonLikeWriter = field(default_factory=DefaultJsonLikeWriter)

    @override
    def accepts(self, doc: SchemaMapRawDoc) -> bool:
        return isinstance(doc, SchemaMapRawDoc)

    @override
    def transpile(self, doc: SchemaMapRawDoc) -> Result[Sequence[O]]:
        return self.transpile_all([doc])

    @override
    def transpile_all(self, docs: Sequence[SchemaMapRawDoc]) -> Result[Sequence[O]]:
        """Expand every document, then hand the whole batch to `inner` at once.

        Expanding all of them first matters even for a per-schema target: `inner` may
        need to resolve a `$ref` from one file into another, which it cannot do
        before that other file has been read.
        """
        expanded: list[JsonSchemaRawDoc] = []
        errors: list[TranspilationError] = []
        for doc in docs:
            result = self.expand(doc)
            if isinstance(result, Err):
                errors.extend(result.errors)
            else:
                expanded.extend(result.value)
        if errors:
            return Err(tuple(errors))
        return self.inner.transpile_all(expanded)

    @property
    @override
    def warnings(self) -> Sequence[TranspilationWarning]:
        return list(self.inner.warnings)

    def expand(self, doc: SchemaMapRawDoc) -> Result[Sequence[JsonSchemaRawDoc]]:
        """Split one document into a virtual `JsonSchemaRawDoc` per named schema."""
        parsed = self.parser.apply(doc)
        if isinstance(parsed, Err):
            return parsed
        return Ok(list(self._virtual_docs(parsed.value, doc)))

    def _virtual_docs(
        self, parsed: JsonSchemaMapDocument, doc: SchemaMapRawDoc
    ) -> Iterator[JsonSchemaRawDoc]:
        for name, schema in parsed.schemas.items():
            yield JsonSchemaRawDoc(
                doc_id=f"{doc.doc_id}#/{name}",
                content=self.writer.write_bytes(_SERIALIZER.serialize(schema), doc.media_type),
                media_type=doc.media_type,
                display_name=name,
                base_uri=doc.doc_id,
            )
