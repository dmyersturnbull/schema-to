"""Adapter that lets any per-schema target consume documents holding several schemas.

A schema-map file is a *set* of schemas, so every target needs an answer to
"what does one produce from N schemas?"  There are two, and both exist:

- A target whose unit is one schema — Pydantic models, a pass-thru re-emit — takes
  the schemas one at a time.  That is this module: each document is split into one
  virtual document per named schema, and the stage that follows sees only those.
- A target whose unit is the whole set — a PostgreSQL migration, whose foreign keys
  cannot be ordered until every table is known — consumes the batch directly, with
  no expansion at all.  See `generate.sql_tables`.

Because expansion is a stage from documents to documents, it composes in front of a
per-schema target rather than wrapping it:

```python
SchemaMapExpander(resolver=resolver).then(per_schema_stage)
```

A virtual document keeps the file it came from in its ID
(`…/catalog.yaml#/author-data`), so a diagnostic names the real file *and* the schema
within it, rather than one at the cost of the other.  That fragment is also the
pointer a sibling file's `$ref` would use, so the ID stays a real address.

Splitting a file would ordinarily break the references written *within* it: `#/other`
means "the `other` member of this document", and once the file is split, each schema
*is* the document.  So the unsplit documents are registered with the resolver the
following stages use — it is never handed them, but its inputs point into them.  The
URI math then works out on its own, because a virtual document's ID is the file's URI
plus a fragment: resolving `#/other` against `…/catalog.yaml#/author-data` replaces
the fragment and yields `…/catalog.yaml#/other`, which is exactly where the sibling
was registered.

Seeding rather than inlining keeps references shared.  Inlining each schema until it
stands alone would also work, but it erases every reference to fix the few that broke
— and a definition used in fourteen places would become fourteen copies, which for a
target whose purpose is named types is the whole game.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override

from schema_to.io.core import DefaultJsonLikeWriter, JsonLikeWriter
from schema_to.io.source import JsonSchemaRawDoc, SchemaMapRawDoc
from schema_to.parse.json_schema import JsonSchemaMapParser
from schema_to.pipeline import Stage
from schema_to.resolve.json_schema import JsonSchemaRefResolver
from schema_to.result import Err, Ok, Result
from schema_to.serialize.json_schema import JsonSchemaSerializer

if TYPE_CHECKING:
    from collections.abc import Iterator

    from schema_to.cst.json_schema import JsonSchemaMapDocument
    from schema_to.errors import TranspilationError

__all__ = ["SchemaMapExpander"]

_SERIALIZER = JsonSchemaSerializer()


@dataclass(frozen=True, slots=True)
class SchemaMapExpander(Stage[Sequence[SchemaMapRawDoc], Sequence[JsonSchemaRawDoc]]):
    """Splits each schema-map document into one virtual document per named schema.

    Every document is parsed before any is expanded: a reference may point from any
    one file into any other, so all of them have to be registered before the first
    schema is handed on.

    Attributes:
        resolver: Registered with the unsplit documents, so references written within
            a file still resolve once it is split.  `None` when the stages that follow
            do not resolve references and there is nothing to seed.
        parser: Parses the schema map.  Injected for testability.
        writer: Re-encodes each named schema as bytes for the next stage to parse back.
        roots: If given, only schemas named here are expanded; the rest are still
            registered, so a `$ref` into one of them still resolves. `None` expands
            every schema.
    """

    resolver: JsonSchemaRefResolver | None = None
    parser: JsonSchemaMapParser = field(default_factory=JsonSchemaMapParser)
    writer: JsonLikeWriter = field(default_factory=DefaultJsonLikeWriter)
    roots: frozenset[str] | None = None

    @override
    def apply(self, input: Sequence[SchemaMapRawDoc]) -> Result[Sequence[JsonSchemaRawDoc]]:
        parsed: list[tuple[SchemaMapRawDoc, JsonSchemaMapDocument]] = []
        errors: list[TranspilationError] = []
        for doc in input:
            result = self.parser.apply(doc)
            if isinstance(result, Err):
                errors.extend(result.errors)
            else:
                parsed.append((doc, result.value))
        if errors:
            return Err(tuple(errors))
        self._seed(cst for _, cst in parsed)
        return Ok([v for doc, cst in parsed for v in self._virtual_docs(cst, doc)])

    def _seed(self, documents: Iterator[JsonSchemaMapDocument]) -> None:
        """Register the unsplit documents so references written within them still resolve."""
        if self.resolver is None:
            return
        for document in documents:
            self.resolver.register_map(document)

    def _virtual_docs(
        self, parsed: JsonSchemaMapDocument, doc: SchemaMapRawDoc
    ) -> Iterator[JsonSchemaRawDoc]:
        for name, schema in parsed.schemas.items():
            if self.roots is not None and name not in self.roots:
                continue
            yield JsonSchemaRawDoc(
                doc_id=f"{doc.doc_id}#/{name}",
                content=self.writer.write_bytes(_SERIALIZER.serialize(schema), doc.media_type),
                media_type=doc.media_type,
                display_name=name,
                base_uri=doc.doc_id,
            )
