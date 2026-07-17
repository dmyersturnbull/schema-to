"""Static resource information drawn from a resolved object schema.

Endpoint-body templates sometimes need to know a resource's property names, or
which properties hold structured JSON (so dotted query paths can address into
them).  This is plain JSON Schema introspection — no persistence layer is
assumed; property names are returned verbatim, not sanitised for any target.
"""


from typing import TYPE_CHECKING

from schema_to.cst.json_schema import BooleanSchema, JsonSchemaType

if TYPE_CHECKING:
    from collections.abc import Mapping

    from schema_to.cst.json_schema import JsonSchema, ObjectSchema

__all__ = ["json_properties", "property_names"]

_JSON_TYPES = frozenset({JsonSchemaType.OBJECT, JsonSchemaType.ARRAY})


def _properties(schema: ObjectSchema | None) -> Mapping[str, JsonSchema]:
    if schema is None:
        return {}
    return schema.properties or {}


def property_names(schema: ObjectSchema | None) -> tuple[str, ...]:
    """Return the resource's property names in declaration order."""
    return tuple(_properties(schema))


def _is_json_property(prop: JsonSchema) -> bool:
    if isinstance(prop, BooleanSchema):
        return False
    return bool(_property_types(prop) & _JSON_TYPES)


def _property_types(prop: ObjectSchema) -> frozenset[JsonSchemaType]:
    t = prop.type
    if t is None:
        return frozenset()
    return t if isinstance(t, frozenset) else frozenset({t})


def json_properties(schema: ObjectSchema | None) -> tuple[str, ...]:
    """Return the names of properties whose schema is `object`- or `array`-typed."""
    return tuple(name for name, prop in _properties(schema).items() if _is_json_property(prop))
