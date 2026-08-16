"""Serialize OpenAPI 3.1 CST nodes back to JSON-compatible values."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from schema_to.serialize._emit import emit_node

if TYPE_CHECKING:
    from schema_to.core import JsonObject
    from schema_to.cst.openapi import OpenApiDocument

__all__ = ["OpenApiSerializer"]


@dataclass(frozen=True, slots=True)
class OpenApiSerializer:
    """Convert an `OpenApiDocument` CST node to a JSON-serializable `JsonObject`.

    Every object is emitted from the plan compiled off its CST class, so the
    output covers exactly the keys the parser reads.
    """

    def serialize(self, doc: OpenApiDocument) -> JsonObject:
        """Emit `doc` as a plain dict suitable for `orjson.dumps` or `format_yaml`."""
        return emit_node(doc)
