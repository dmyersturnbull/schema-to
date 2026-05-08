"""Serialize JSON Schema 2020-12 CST nodes back to JSON-compatible values."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from schema_to._core import JsonObject, JsonValue
from schema_to.cst._json_schema import (
    BooleanSchema,
    ConstValue,
    DefaultValue,
    JsonSchema,
    JsonSchemaDocument,
    JsonSchemaType,
    ObjectSchema,
)

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

    def _val(self, value: object) -> JsonValue:
        if isinstance(value, (BooleanSchema, ObjectSchema)):
            return self.serialize(value)
        if isinstance(value, (DefaultValue, ConstValue)):
            return value.value
        if isinstance(value, JsonSchemaType):
            return str(value)
        if isinstance(value, frozenset):
            return sorted(str(t) for t in value)
        if isinstance(value, Sequence) and not isinstance(value, str):
            items = list(value)
            if items and isinstance(items[0], (BooleanSchema, ObjectSchema)):
                return [self.serialize(v) for v in items]  # type: ignore[arg-type]
            return items  # type: ignore[return-value]
        if isinstance(value, Mapping):
            if not value:
                return {}
            first_v = next(iter(value.values()))
            if isinstance(first_v, (BooleanSchema, ObjectSchema)):
                return {k: self.serialize(v) for k, v in value.items()}  # type: ignore[arg-type]
            if isinstance(first_v, frozenset):
                return {k: sorted(v) for k, v in value.items()}  # type: ignore[return-value]
            return dict(value)  # type: ignore[return-value]
        return value  # type: ignore[return-value]
