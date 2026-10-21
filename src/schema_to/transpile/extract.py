"""Lifting the component schemas out of an OpenAPI document, as standalone schemas.

The output is a JSON Schema document per `components/schemas` entry —
the same thing a JSON Schema file parses to —
so anything that reads JSON Schema reads these.
Composing this in front of the JSON Schema reifier is the `json-schema` target;
composing it in front of a generator would be an OpenAPI-driven Pydantic or SQL target,
which is why it is a stage of its own rather than a step inside one.
"""

from collections.abc import Sequence, Set
from dataclasses import dataclass
from typing import override

from schema_to.cst.json_schema import JsonSchemaDocument
from schema_to.cst.openapi import OpenApiDocument
from schema_to.io.uri import Uri
from schema_to.pipeline import Expander
from schema_to.result import Ok, Result

__all__ = ["OpenApiComponentExtractor"]


@dataclass(frozen=True, slots=True)
class OpenApiComponentExtractor(Expander[OpenApiDocument, JsonSchemaDocument]):
    """Yields one standalone JSON Schema document per `components/schemas` entry.

    Each has its own URI, the OpenAPI document's plus a fragment pointing at the entry,
    so that it is unique and still a real address,
    and carries the entry's name as its display name,
    which is what a reifier downstream names the file after.
    The schema keeps the `SourceRef` it was parsed with,
    so a diagnostic still points into the original document.

    Attributes:
        roots: If given, only components named here are lifted out.
            `None` lifts every one.
    """

    roots: Set[str] | None = None

    @override
    def apply(self, input: OpenApiDocument) -> Result[Sequence[JsonSchemaDocument]]:
        return Ok(self.documents(input))

    def documents(self, input: OpenApiDocument) -> Sequence[JsonSchemaDocument]:
        """Return the standalone document for each component schema that `roots` selects."""
        return [
            JsonSchemaDocument(
                root=schema,
                source_id=str(
                    Uri.parse(input.source_id).with_pointer(schema.source_ref.json_pointer)
                ),
                display_name=name,
            )
            for name, schema in input.components.schemas.items()
            if self.roots is None or name in self.roots
        ]
