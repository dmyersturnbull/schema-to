"""Static resource information drawn from a resolved object schema.

Endpoint-body templates sometimes need to know a resource's property names,
or which properties hold structured JSON so dotted query paths can address into them.
This is plain JSON Schema introspection:
No persistence layer is assumed,
and property names are returned verbatim, not sanitised for any target.
"""

from typing import TYPE_CHECKING

from schema_to.cst.json_schema import JsonSchemaType

if TYPE_CHECKING:
    from collections.abc import Mapping

    from schema_to.cst.json_schema import JsonSchema, ObjectSchema

__all__ = ["json_properties", "property_names"]

# Property types holding structured JSON addressable by a dotted query path.
_COMPOSITE_JSON_TYPES = frozenset({JsonSchemaType.OBJECT, JsonSchemaType.ARRAY})


def property_names(schema: ObjectSchema | None) -> tuple[str, ...]:
    """Return the resource's property names in declaration order."""
    return tuple(_properties(schema))


def json_properties(schema: ObjectSchema | None) -> tuple[str, ...]:
    """Return the names of properties whose schema is `object`- or `array`-typed."""
    return tuple(
        name
        for name, prop in _properties(schema).items()
        if prop.get_types() & _COMPOSITE_JSON_TYPES
    )


def _properties(schema: ObjectSchema | None) -> Mapping[str, JsonSchema]:
    if schema is None:
        return {}
    return schema.properties or {}
