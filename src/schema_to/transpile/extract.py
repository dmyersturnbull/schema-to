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
from schema_to.parse._utils import ptr
from schema_to.pipeline import Expander
from schema_to.result import Ok, Result

__all__ = ["OpenApiComponentExtractor"]


@dataclass(frozen=True, slots=True)
class OpenApiComponentExtractor(Expander[OpenApiDocument, JsonSchemaDocument]):
    """Yields one standalone JSON Schema document per `components/schemas` entry.

    Each has its own URI, the OpenAPI document's plus a fragment pointing at the entry,
    carries the entry's name as its display name,
    which is what a reifier downstream names the file after,
    and has a `SourceRef` back to the position it was lifted from,
    so a diagnostic can still point into the original document.

    Attributes:
        roots: If given, only components named here are lifted out.
            `None` lifts every one.
    """

    roots: Set[str] | None = None

    @override
    def apply(self, input: OpenApiDocument) -> Result[Sequence[JsonSchemaDocument]]:
        source_id = input.source_id or ""
        return Ok(
            [
                JsonSchemaDocument.lifted(
                    schema,
                    from_uri=source_id,
                    json_pointer=ptr("", "components", "schemas", name),
                    name=name,
                )
                for name, schema in input.components.schemas.items()
                if self.roots is None or name in self.roots
            ]
        )
