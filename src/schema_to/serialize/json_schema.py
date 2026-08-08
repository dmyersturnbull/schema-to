"""Serialize JSON Schema 2020-12 CST nodes back to JSON-compatible values."""

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from schema_to.cst.json_schema import (
    BooleanSchema,
    ConstValue,
    DefaultValue,
    JsonSchema,
    JsonSchemaDocument,
    JsonSchemaType,
    ObjectSchema,
    SchemaKeywordValue,
)

if TYPE_CHECKING:
    from schema_to.core import JsonObject, JsonValue

__all__ = ["JsonSchemaSerializer"]

# Maps each ObjectSchema Python field name to its JSON Schema keyword.
# Built from the field metadata so that the two never drift apart;
# fields with no "key" (extensions, source_ref) are synthetic and handled separately.
_SCHEMA_KEYS: dict[str, str] = {
    f.name: f.metadata["key"] for f in dataclasses.fields(ObjectSchema) if "key" in f.metadata
}


@dataclass(frozen=True, slots=True)
class JsonSchemaSerializer:
    """Convert a `JsonSchema` or `JsonSchemaDocument` CST node to a `JsonValue`.

    The output is a plain Python dict/bool suitable for `orjson.dumps` or `yaml12.format_yaml`.
    Only keywords that differ from absent/default state are emitted,
    so the result is minimal but semantically complete.
    """

    def serialize_document(self, doc: JsonSchemaDocument) -> JsonValue:
        return self.serialize(doc.root)

    def serialize(self, schema: JsonSchema) -> JsonValue:
        if isinstance(schema, BooleanSchema):
            return schema.value
        return self._obj(schema)

    def _obj(self, s: ObjectSchema) -> JsonObject:
        out: JsonObject = {}
        for f in dataclasses.fields(s):
            json_key = _SCHEMA_KEYS.get(f.name)
            if json_key is None:
                continue
            value = getattr(s, f.name)
            if isinstance(value, bool):
                if value:
                    out[json_key] = True
            elif value is not None:
                out[json_key] = self._val(value)
        out.update(s.extensions)
        return out

    # ruff:ignore[too-many-return-statements]  # All returns are in the match.
    def _val(self, value: SchemaKeywordValue) -> JsonValue:
        match value:
            case BooleanSchema() | ObjectSchema():
                return self.serialize(value)
            case DefaultValue(value=v) | ConstValue(value=v):
                return v
            case JsonSchemaType() as t:
                return str(t)
            case frozenset(types_):
                # `sorted` returns list[str]; list[str] ≤ list[JsonValue] ≤ JsonValue,
                # but ty cannot see that subtype relationship, so we assert it with `cast`.
                return cast("JsonValue", sorted(str(t) for t in types_))
            case str():
                return value
            # Every scalar member of `SchemaKeywordValue` is matched above, so what reaches
            # these two arms is a real sequence or mapping.  ty cannot rule out the scalars,
            # and narrows to intersections like `int & Sequence[object]`; `cast` discards those.
            case Sequence() as seq:
                return self._seq(cast("Sequence[SchemaKeywordValue]", seq))
            case Mapping() as mapping:
                return self._map(cast("Mapping[str, SchemaKeywordValue]", mapping))
            case _:
                return value  # int, float, bool, None — all valid JSON scalars

    def _seq(self, seq: Sequence[SchemaKeywordValue]) -> JsonValue:
        """Serialize a keyword whose value is an array of schemas or of plain JSON."""
        items = list(seq)
        if items and isinstance(items[0], (BooleanSchema, ObjectSchema)):
            return [
                self.serialize(v) for v in items if isinstance(v, (BooleanSchema, ObjectSchema))
            ]
        # Narrowing every element would cost a full pass; the first element determines the kind.
        return cast("JsonValue", items)

    def _map(self, mapping: Mapping[str, SchemaKeywordValue]) -> JsonValue:
        """Serialize a keyword whose value maps names to schemas, sets, or plain JSON."""
        if not mapping:
            return {}
        first = next(iter(mapping.values()))
        if isinstance(first, (BooleanSchema, ObjectSchema)):
            return {
                k: self.serialize(v)
                for k, v in mapping.items()
                if isinstance(v, (BooleanSchema, ObjectSchema))
            }
        if isinstance(first, frozenset):
            return {k: sorted(v) for k, v in mapping.items() if isinstance(v, frozenset)}
        return cast("JsonValue", dict(mapping))
