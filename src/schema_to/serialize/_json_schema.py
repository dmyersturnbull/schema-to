"""Serialize JSON Schema 2020-12 CST nodes back to JSON-compatible values."""

from __future__ import annotations

from schema_to.cst._base import JsonValue
from schema_to.cst._json_schema import BooleanSchema, JsonSchema, JsonSchemaDocument, ObjectSchema

__all__ = ["JsonSchemaSerializer"]


class JsonSchemaSerializer:
    """Convert a `JsonSchema` or `JsonSchemaDocument` CST node to a `JsonValue`.

    The output is a plain Python dict/bool suitable for passing to `orjson.dumps`
    or `yaml12.format_yaml`.  Only keywords that differ from their absent/default
    state are emitted, so the result is minimal but semantically complete.
    """

    def serialize_document(self, doc: JsonSchemaDocument) -> JsonValue:
        return self.serialize(doc.root)

    def serialize(self, schema: JsonSchema) -> JsonValue:
        if isinstance(schema, BooleanSchema):
            return schema.value
        return self._obj(schema)

    def _obj(self, s: ObjectSchema) -> dict[str, JsonValue]:  # noqa: PLR0912, PLR0915
        out: dict[str, JsonValue] = {}

        # Core vocabulary
        c = s.core
        _set(out, "$id", c.id)
        _set(out, "$schema", c.schema)
        _set(out, "$anchor", c.anchor)
        _set(out, "$dynamicAnchor", c.dynamic_anchor)
        _set(out, "$ref", c.ref)
        _set(out, "$dynamicRef", c.dynamic_ref)
        if c.defs is not None:
            out["$defs"] = {k: self.serialize(v) for k, v in c.defs.items()}
        _set(out, "$comment", c.comment)
        if c.vocabulary is not None:
            out["$vocabulary"] = dict(c.vocabulary)

        # Metadata vocabulary
        m = s.metadata
        _set(out, "title", m.title)
        _set(out, "description", m.description)
        if m.default is not None:
            out["default"] = m.default.value
        if m.deprecated:
            out["deprecated"] = True
        if m.read_only:
            out["readOnly"] = True
        if m.write_only:
            out["writeOnly"] = True
        if m.examples is not None:
            out["examples"] = list(m.examples)

        # Validation vocabulary
        v = s.validation
        if v.type is not None:
            if isinstance(v.type, frozenset):
                out["type"] = sorted(str(t) for t in v.type)
            else:
                out["type"] = str(v.type)
        if v.enum is not None:
            out["enum"] = list(v.enum)
        if v.const is not None:
            out["const"] = v.const.value

        # Numeric validation
        n = s.numeric
        _set(out, "multipleOf", n.multiple_of)
        _set(out, "maximum", n.maximum)
        _set(out, "exclusiveMaximum", n.exclusive_maximum)
        _set(out, "minimum", n.minimum)
        _set(out, "exclusiveMinimum", n.exclusive_minimum)

        # String validation
        sv = s.string
        _set(out, "maxLength", sv.max_length)
        _set(out, "minLength", sv.min_length)
        _set(out, "pattern", sv.pattern)

        # Array applicator / validation
        a = s.array
        if a.prefix_items is not None:
            out["prefixItems"] = [self.serialize(x) for x in a.prefix_items]
        if a.items is not None:
            out["items"] = self.serialize(a.items)
        if a.contains is not None:
            out["contains"] = self.serialize(a.contains)
        _set(out, "minContains", a.min_contains)
        _set(out, "maxContains", a.max_contains)
        _set(out, "minItems", a.min_items)
        _set(out, "maxItems", a.max_items)
        if a.unique_items:
            out["uniqueItems"] = True

        # Object applicator / validation
        o = s.object
        if o.properties is not None:
            out["properties"] = {k: self.serialize(v) for k, v in o.properties.items()}
        if o.pattern_properties is not None:
            out["patternProperties"] = {k: self.serialize(v) for k, v in o.pattern_properties.items()}
        if o.additional_properties is not None:
            out["additionalProperties"] = self.serialize(o.additional_properties)
        if o.property_names is not None:
            out["propertyNames"] = self.serialize(o.property_names)
        if o.required is not None:
            out["required"] = sorted(o.required)
        if o.dependent_required is not None:
            out["dependentRequired"] = {k: sorted(v) for k, v in o.dependent_required.items()}
        if o.dependent_schemas is not None:
            out["dependentSchemas"] = {k: self.serialize(v) for k, v in o.dependent_schemas.items()}
        _set(out, "minProperties", o.min_properties)
        _set(out, "maxProperties", o.max_properties)

        # Applicator vocabulary
        ap = s.applicator
        if ap.all_of is not None:
            out["allOf"] = [self.serialize(x) for x in ap.all_of]
        if ap.any_of is not None:
            out["anyOf"] = [self.serialize(x) for x in ap.any_of]
        if ap.one_of is not None:
            out["oneOf"] = [self.serialize(x) for x in ap.one_of]
        if ap.not_ is not None:
            out["not"] = self.serialize(ap.not_)
        if ap.if_ is not None:
            out["if"] = self.serialize(ap.if_)
        if ap.then is not None:
            out["then"] = self.serialize(ap.then)
        if ap.else_ is not None:
            out["else"] = self.serialize(ap.else_)

        # Unevaluated vocabulary
        u = s.unevaluated
        if u.unevaluated_items is not None:
            out["unevaluatedItems"] = self.serialize(u.unevaluated_items)
        if u.unevaluated_properties is not None:
            out["unevaluatedProperties"] = self.serialize(u.unevaluated_properties)

        # Content vocabulary
        cnt = s.content
        _set(out, "contentEncoding", cnt.content_encoding)
        _set(out, "contentMediaType", cnt.content_media_type)
        if cnt.content_schema is not None:
            out["contentSchema"] = self.serialize(cnt.content_schema)

        # Format annotation
        _set(out, "format", s.format_annotation.format)

        # Extension keywords (x-*)
        out.update(s.extensions)

        return out


def _set(out: dict[str, JsonValue], key: str, value: object) -> None:
    """Write `key: value` only when value is not None."""
    if value is not None:
        out[key] = value  # type: ignore[assignment]
