"""Serialize JSON Schema 2020-12 CST nodes back to JSON-compatible values."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from schema_to.serialize._emit import emit_schema

if TYPE_CHECKING:
    from schema_to.core import JsonValue
    from schema_to.cst.json_schema import JsonSchema, JsonSchemaDocument

__all__ = ["JsonSchemaSerializer"]


@dataclass(frozen=True, slots=True)
class JsonSchemaSerializer:
    """Convert a `JsonSchema` or `JsonSchemaDocument` CST node to a `JsonValue`.

    The output is a plain Python dict/bool suitable for `orjson.dumps` or `yaml12.format_yaml`.
    Only keywords that differ from absent/default state are emitted,
    so the result is minimal but semantically complete.
    """

    def serialize_document(self, doc: JsonSchemaDocument) -> JsonValue:
        """Emit the document's root schema."""
        return self.serialize(doc.root)

    def serialize(self, schema: JsonSchema) -> JsonValue:
        """Emit one schema as `true`, `false`, or a keyword object."""
        return emit_schema(schema)
