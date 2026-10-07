"""Turning documents that hold a set of schemas into the unit a target reads.

A schema-map file is a *set* of schemas, so every target needs an answer to
"what does one produce from N schemas?"
There are two, and both are a stage here:

- A target whose unit is one schema —
  Pydantic models, a pass-thru re-emit —
  takes the schemas one at a time.
  `SchemaMapExpander` splits a document into one virtual document per named schema,
  so the target reads what it already knows how to read.
- A target whose unit is the whole set —
  a PostgreSQL migration, whose foreign keys cannot be ordered until every table is known —
  needs the set as one document.
  `SchemaMapMerger` folds it into one.

Both are ordinary cardinality kinds —
an `Expander` and a `Reducer` —
so they compose in front of a target rather than wrapping it:

```python
Each(SchemaMapExpander(resolver=r)).then(Flatten()).then(per_schema_target)
Each(JsonSchemaMapParser()).then(SchemaMapMerger()).then(whole_set_target)
```

A virtual document keeps the file it came from in its URI
(`…/catalog.yaml#/author-data`),
so its ID is unique and still a real address:
that fragment is also the pointer a sibling file's `$ref` would use.
It also records the file and pointer as its `Origin`,
so a diagnostic names the real file *and* the schema in it,
rather than the virtual URI, which exists nowhere.

Splitting a file would ordinarily break the references written **within&* it:
`#/other` means "the `other` member of this document",
and once the file is split, each schema **is** the document.
So the unsplit document is registered with the resolver the following stages use;
it is never handed the file, but its inputs point into it.
The URI math then works out on its own,
because a virtual document's URI is the file's URI plus a fragment:
Resolving `#/other` against
`…/catalog.yaml#/author-data`
replaces the fragment and yields
`…/catalog.yaml#/other`,
which is exactly where the sibling was registered.
Expanding under `Each` registers every file before any target stage runs,
so a reference into a file read later still resolves.

Seeding rather than inlining keeps references shared.
Inlining each schema until it stands alone would also work,
but it erases every reference to fix the few that broke —
and a definition used in fourteen places would become fourteen copies,
which for a target whose purpose is named types is the whole game.
"""

from collections.abc import Sequence, Set
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override

from schema_to.cst.json_schema import JsonSchemaMapDocument
from schema_to.errors import ResolutionError, SourceLocation
from schema_to.io.core import DefaultJsonLikeWriter, JsonLikeWriter
from schema_to.io.source import JsonSchemaRawDoc, Origin, SchemaMapRawDoc
from schema_to.io.uri import pointer_uri
from schema_to.parse._utils import ptr
from schema_to.parse.json_schema import JsonSchemaMapParser
from schema_to.pipeline import Expander, Reducer
from schema_to.resolve.json_schema import JsonSchemaRefResolver
from schema_to.result import Err, Ok, Result
from schema_to.serialize.json_schema import JsonSchemaSerializer

if TYPE_CHECKING:
    from collections.abc import Iterator

    from schema_to.cst.json_schema import JsonSchema

__all__ = ["SchemaMapExpander", "SchemaMapMerger"]

_SERIALIZER = JsonSchemaSerializer()


@dataclass(frozen=True, slots=True)
class SchemaMapExpander(Expander[SchemaMapRawDoc, JsonSchemaRawDoc]):
    """Splits a schema-map document into one virtual document per named schema.

    Attributes:
        resolver: Registered with the unsplit document,
            so references written within the file still resolve once it's split.
            `None` when the stages that follow don't resolve references and there's nothing to seed.
        parser: Parses the schema map.
            Injected for testability.
        writer: Re-encodes each named schema as bytes for the next stage to parse back.
        roots: If given, only schemas named here are expanded;
            the rest are still registered, so a `$ref` into one of them still resolves.
            `None` expands every schema.
    """

    resolver: JsonSchemaRefResolver | None = None
    parser: JsonSchemaMapParser = field(default_factory=JsonSchemaMapParser)
    writer: JsonLikeWriter = field(default_factory=DefaultJsonLikeWriter)
    roots: Set[str] | None = None

    @override
    def apply(self, input: SchemaMapRawDoc) -> Result[Sequence[JsonSchemaRawDoc]]:
        parsed = self.parser.apply(input)
        if isinstance(parsed, Err):
            return parsed
        if self.resolver is not None:
            self.resolver.register_map(parsed.value)
        return Ok(list(self._virtual_docs(parsed.value, input)))

    def _virtual_docs(
        self, parsed: JsonSchemaMapDocument, doc: SchemaMapRawDoc
    ) -> Iterator[JsonSchemaRawDoc]:
        home = doc.provenance
        for name, schema in parsed.schemas.items():
            if self.roots is not None and name not in self.roots:
                continue
            pointer = ptr(home.json_pointer, name)
            yield JsonSchemaRawDoc(
                uri=pointer_uri(home.uri, pointer),
                content=self.writer.write_bytes(_SERIALIZER.serialize(schema), doc.media_type),
                media_type=doc.media_type,
                origin=Origin(home.uri, pointer),
            )


@dataclass(frozen=True, slots=True)
class SchemaMapMerger(Reducer[JsonSchemaMapDocument, JsonSchemaMapDocument]):
    """Folds a set of schema-map documents into the single map they describe together.

    A directory of schema files is one namespace:
    `./other.yaml#/thing` and `#/thing` name the same schema from different files,
    and a target whose unit is the set —
    a migration, say —
    has no use for the file boundaries.
    Merging them here means such a target is an ordinary `Transformer` over one document
    rather than a stage that folds and generates at once.

    Each schema keeps its own `source_ref`,
    so which file it came from survives the merge and a diagnostic can still name it.
    Two files may not use one schema name:
    within a single namespace that is a genuine ambiguity, not a merge artefact.

    Attributes:
        source_id: Identifier for the merged document.
            It names the set, not a file, since no one file is where these schemas live.
    """

    source_id: str = "urn:schema-to:schema-map-set"

    @override
    def apply(self, input: Sequence[JsonSchemaMapDocument]) -> Result[JsonSchemaMapDocument]:
        merged: dict[str, JsonSchema] = {}
        origins: dict[str, str] = {}
        errors: list[ResolutionError] = []
        for document in input:
            for name, schema in document.schemas.items():
                clash = origins.get(name)
                if clash is not None:
                    errors.append(_duplicate(name, clash, document.source_id))
                    continue
                merged[name] = schema
                origins[name] = document.source_id
        if errors:
            return Err(tuple(errors))
        return Ok(JsonSchemaMapDocument(schemas=merged, source_id=self.source_id))


def _duplicate(name: str, first: str, second: str) -> ResolutionError:
    msg = (
        f"Schema {name!r} is declared in both {first!r} and {second!r}; "
        f"a set of schema-map files is one namespace, so a name may be used once."
    )
    return ResolutionError(msg, location=SourceLocation(second, f"/{name}"))
