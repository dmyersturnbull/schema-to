"""Serialize JSON Schema 2020-12 CST nodes back to JSON-compatible values."""

from __future__ import annotations

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
)

if TYPE_CHECKING:
    from schema_to.core import JsonObject, JsonValue

__all__ = ["JsonSchemaSerializer"]

# Maps each ObjectSchema Python field name to its JSON Schema keyword.
# Fields absent from this map (extensions, source_ref) are handled separately.
_SCHEMA_KEYS: dict[str, str] = {
    "id": "$id",
    "schema": "$schema",
    "anchor": "$anchor",
    "dynamic_anchor": "$dynamicAnchor",
    "ref": "$ref",
    "dynamic_ref": "$dynamicRef",
    "defs": "$defs",
    "comment": "$comment",
    "vocabulary": "$vocabulary",
    "title": "title",
    "description": "description",
    "default": "default",
    "deprecated": "deprecated",
    "read_only": "readOnly",
    "write_only": "writeOnly",
    "examples": "examples",
    "type": "type",
    "enum": "enum",
    "const": "const",
    "multiple_of": "multipleOf",
    "maximum": "maximum",
    "exclusive_maximum": "exclusiveMaximum",
    "minimum": "minimum",
    "exclusive_minimum": "exclusiveMinimum",
    "max_length": "maxLength",
    "min_length": "minLength",
    "pattern": "pattern",
    "prefix_items": "prefixItems",
    "items": "items",
    "contains": "contains",
    "min_contains": "minContains",
    "max_contains": "maxContains",
    "min_items": "minItems",
    "max_items": "maxItems",
    "unique_items": "uniqueItems",
    "properties": "properties",
    "pattern_properties": "patternProperties",
    "additional_properties": "additionalProperties",
    "property_names": "propertyNames",
    "required": "required",
    "dependent_required": "dependentRequired",
    "dependent_schemas": "dependentSchemas",
    "min_properties": "minProperties",
    "max_properties": "maxProperties",
    "all_of": "allOf",
    "any_of": "anyOf",
    "one_of": "oneOf",
    "not_": "not",
    "if_": "if",
    "then": "then",
    "else_": "else",
    "unevaluated_items": "unevaluatedItems",
    "unevaluated_properties": "unevaluatedProperties",
    "content_encoding": "contentEncoding",
    "content_media_type": "contentMediaType",
    "content_schema": "contentSchema",
    "format": "format",
}


@dataclass(frozen=True)
class JsonSchemaSerializer:
    """Convert a `JsonSchema` or `JsonSchemaDocument` CST node to a `JsonValue`.

    The output is a plain Python dict/bool suitable for `orjson.dumps` or
    `yaml12.format_yaml`.  Only keywords that differ from absent/default state
    are emitted, so the result is minimal but semantically complete.
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

    def _val(self, value: JsonValue) -> JsonValue:  # noqa: PLR0911 # all returns are in the match
        match value:
            case BooleanSchema() | ObjectSchema():
                return self.serialize(value)
            case DefaultValue(value=v) | ConstValue(value=v):
                return v
            case JsonSchemaType() as t:
                return str(t)
            case frozenset(types_):
                # sorted() returns list[str]; list[str] ≤ list[JsonValue] ≤ JsonValue,
                # but ty can't see that subtype relationship, so we assert it with cast.
                return cast("JsonValue", sorted(str(t) for t in types_))
            case str():
                return value
            case Sequence() as seq:
                items = list(seq)
                if items and isinstance(items[0], (BooleanSchema, ObjectSchema)):
                    return [self.serialize(v) for v in items]
                return items
            case Mapping() as mapping:
                if not mapping:
                    return {}
                first_v = next(iter(mapping.values()))
                if isinstance(first_v, (BooleanSchema, ObjectSchema)):
                    return {k: self.serialize(v) for k, v in mapping.items()}
                if isinstance(first_v, frozenset):
                    return {k: sorted(v) for k, v in mapping.items()}
                return dict(mapping)
            case _:
                return value  # int, float, bool, None — all valid JSON scalars
