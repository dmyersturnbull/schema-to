"""Transpile-time helpers for the PostgreSQL endpoint-body backend.

The list-operation query parameters (`select`, `where`, `sort`) are *runtime*
strings, so the SQL that interprets them is built at request time by the shipped
`pg_runtime` module — not here.  This module supplies the small amount of
*static* information the backend needs while generating code: which of a
resource's columns hold JSON (so dotted paths can address into them) and the
resource's column names.

A column is treated as JSON when its property schema is `object`- or
`array`-typed, or when it carries an `x-pg-type` extension of `json`/`jsonb`
(matching the convention used by the SQL DDL generator).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from schema_to.cst.json_schema import BooleanSchema, JsonSchemaType, ObjectSchema
from schema_to.generate._names import safe_sql_identifier

if TYPE_CHECKING:
    from collections.abc import Mapping

    from schema_to.cst.json_schema import JsonSchema

__all__ = ["column_names", "json_columns"]

_JSON_TYPES = frozenset({JsonSchemaType.OBJECT, JsonSchemaType.ARRAY})
_JSON_PG_TYPES = frozenset({"json", "jsonb"})


def _properties(schema: ObjectSchema | None) -> Mapping[str, JsonSchema]:
    if schema is None:
        return {}
    return schema.properties or {}


def column_names(schema: ObjectSchema | None) -> tuple[str, ...]:
    """Return the resource's column names as safe SQL identifiers."""
    return tuple(safe_sql_identifier(name) for name in _properties(schema))


def _is_json_property(prop: JsonSchema) -> bool:
    if isinstance(prop, BooleanSchema):
        return False
    pg_type = prop.extensions.get("x-pg-type")
    if isinstance(pg_type, str) and pg_type.lower() in _JSON_PG_TYPES:
        return True
    return bool(_property_types(prop) & _JSON_TYPES)


def _property_types(prop: ObjectSchema) -> frozenset[JsonSchemaType]:
    t = prop.type
    if t is None:
        return frozenset()
    return t if isinstance(t, frozenset) else frozenset({t})


def json_columns(schema: ObjectSchema | None) -> frozenset[str]:
    """Return the names of columns that hold JSON, as safe SQL identifiers."""
    return frozenset(
        safe_sql_identifier(name)
        for name, prop in _properties(schema).items()
        if _is_json_property(prop)
    )
