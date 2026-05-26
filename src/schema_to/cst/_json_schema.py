"""Concrete Syntax Tree for [JSON Schema 2020-12](https://json-schema.org/specification).

Each node type holds exactly the set of keywords defined by the specification,
grouped by vocabulary.  The flat `ObjectSchema` avoids indirection through
vocabulary sub-objects so that serializers and parsers can iterate
`dataclasses.fields()` directly.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from schema_to.cst._base import CstNode, JsonValue, SourceRef

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "BooleanSchema",
    "ConstValue",
    "DefaultValue",
    "JsonSchema",
    "JsonSchemaDocument",
    "JsonSchemaType",
    "ObjectSchema",
    "SchemaType",
]


# ---------------------------------------------------------------------------
# Primitive enumerations
# ---------------------------------------------------------------------------


class JsonSchemaType(StrEnum):
    """The seven primitive types recognised by JSON Schema.

    Corresponds to the allowed string values of the `type` keyword.
    """

    STRING = enum.auto()
    NUMBER = enum.auto()
    INTEGER = enum.auto()
    BOOLEAN = enum.auto()
    ARRAY = enum.auto()
    OBJECT = enum.auto()
    NULL = enum.auto()


# A schema's `type` keyword is either a single type or a non-empty set of types.
type SchemaType = JsonSchemaType | frozenset[JsonSchemaType]


# ---------------------------------------------------------------------------
# Wrapper types for distinguishing absent keywords from null values
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DefaultValue:
    """Distinguishes `default: null` from an absent `default` keyword."""

    value: JsonValue


@dataclass(frozen=True, slots=True)
class ConstValue:
    """Distinguishes `const: null` from an absent `const` keyword."""

    value: JsonValue


# ---------------------------------------------------------------------------
# Schema node types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BooleanSchema(CstNode):
    """A JSON Schema that is always-valid (`true`) or never-valid (`false`)."""

    value: bool
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class ObjectSchema(CstNode):
    """A JSON Schema expressed as a keyword-bearing object.

    Fields are ordered by vocabulary: core, metadata, validation, numeric,
    string, array, object, applicator, unevaluated, content, format.
    Each field maps 1-to-1 to the corresponding JSON Schema keyword.

    Fields named with a trailing underscore (`not_`, `if_`, `else_`) avoid
    collisions with Python reserved words.
    """

    # -- Core vocabulary --------------------------------------------------
    id: str | None = None  # $id
    schema: str | None = None  # $schema
    anchor: str | None = None  # $anchor
    dynamic_anchor: str | None = None  # $dynamicAnchor
    ref: str | None = None  # $ref
    dynamic_ref: str | None = None  # $dynamicRef
    defs: Mapping[str, JsonSchema] | None = None  # $defs
    comment: str | None = None  # $comment
    vocabulary: Mapping[str, bool] | None = None  # $vocabulary

    # -- Metadata vocabulary ----------------------------------------------
    title: str | None = None
    description: str | None = None
    default: DefaultValue | None = None  # null-safe wrapper
    deprecated: bool = False
    read_only: bool = False  # readOnly
    write_only: bool = False  # writeOnly
    examples: Sequence[JsonValue] | None = None

    # -- Validation vocabulary --------------------------------------------
    type: SchemaType | None = None
    enum: Sequence[JsonValue] | None = None
    const: ConstValue | None = None  # null-safe wrapper

    # -- Numeric validation -----------------------------------------------
    multiple_of: float | None = None  # multipleOf
    maximum: float | None = None
    exclusive_maximum: float | None = None  # exclusiveMaximum
    minimum: float | None = None
    exclusive_minimum: float | None = None  # exclusiveMinimum

    # -- String validation ------------------------------------------------
    max_length: int | None = None  # maxLength
    min_length: int | None = None  # minLength
    pattern: str | None = None

    # -- Array keywords ---------------------------------------------------
    prefix_items: Sequence[JsonSchema] | None = None  # prefixItems
    items: JsonSchema | None = None
    contains: JsonSchema | None = None
    min_contains: int | None = None  # minContains
    max_contains: int | None = None  # maxContains
    min_items: int | None = None  # minItems
    max_items: int | None = None  # maxItems
    unique_items: bool = False  # uniqueItems

    # -- Object keywords --------------------------------------------------
    properties: Mapping[str, JsonSchema] | None = None
    pattern_properties: Mapping[str, JsonSchema] | None = None  # patternProperties
    additional_properties: JsonSchema | None = None  # additionalProperties
    property_names: JsonSchema | None = None  # propertyNames
    required: frozenset[str] | None = None
    dependent_required: Mapping[str, frozenset[str]] | None = None  # dependentRequired
    dependent_schemas: Mapping[str, JsonSchema] | None = None  # dependentSchemas
    min_properties: int | None = None  # minProperties
    max_properties: int | None = None  # maxProperties

    # -- Applicator vocabulary --------------------------------------------
    all_of: Sequence[JsonSchema] | None = None  # allOf
    any_of: Sequence[JsonSchema] | None = None  # anyOf
    one_of: Sequence[JsonSchema] | None = None  # oneOf
    not_: JsonSchema | None = None  # not
    if_: JsonSchema | None = None  # if
    then: JsonSchema | None = None
    else_: JsonSchema | None = None  # else

    # -- Unevaluated vocabulary -------------------------------------------
    unevaluated_items: JsonSchema | None = None  # unevaluatedItems
    unevaluated_properties: JsonSchema | None = None  # unevaluatedProperties

    # -- Content vocabulary -----------------------------------------------
    content_encoding: str | None = None  # contentEncoding
    content_media_type: str | None = None  # contentMediaType
    content_schema: JsonSchema | None = None  # contentSchema

    # -- Format vocabulary ------------------------------------------------
    format: str | None = None

    # -- Extensions and provenance ----------------------------------------
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None

    def get_types(self) -> frozenset[JsonSchemaType]:
        """Return the schema's types as a frozenset, or empty frozenset if unset."""
        if self.type is None:
            return frozenset()
        if isinstance(self.type, frozenset):
            return self.type
        return frozenset({self.type})

    def get_required(self) -> frozenset[str]:
        """Return required property names, or empty frozenset if unset."""
        return self.required or frozenset()


# A schema is either a boolean shorthand or a full keyword object.
type JsonSchema = BooleanSchema | ObjectSchema


@dataclass(frozen=True, slots=True)
class JsonSchemaDocument(CstNode):
    """The root of a parsed JSON Schema 2020-12 document."""

    root: JsonSchema
    source_id: str
    display_name: str | None = None
    source_ref: SourceRef | None = None
