"""Concrete Syntax Tree for [JSON Schema 2020-12](https://json-schema.org/specification).

Each node type holds exactly the set of keywords defined by the specification,
grouped by vocabulary.  The flat `ObjectSchema` avoids indirection through
vocabulary sub-objects so that serializers and parsers can iterate
`dataclasses.fields()` directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Literal, assert_type

from schema_to.cst.base import CstNode, SourceRef

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from collections.abc import Set as AbstractSet

    from schema_to.core import JsonValue

__all__ = [
    "BooleanApplicatorKeyword",
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

    STRING = auto()
    NUMBER = auto()
    INTEGER = auto()
    BOOLEAN = auto()
    ARRAY = auto()
    OBJECT = auto()
    NULL = auto()


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


class _JsonSchema(CstNode):
    """Either a boolean or a full keyword object.

    This is an internal, sealed abstract class.
    Use `JsonSchema` instead.
    """

    def get_types(self) -> frozenset[JsonSchemaType]:
        """Return the schema's types as a frozenset, or empty frozenset if unset."""
        match self:
            case BooleanSchema():
                return frozenset()
            case ObjectSchema(type=None):
                return frozenset()
            case ObjectSchema(type=frozenset() as types):
                return types
            case ObjectSchema(type=JsonSchemaType() as t):
                return frozenset({t})
        msg = f"Unsupported JSON Schema node: {type(self).__name__}"
        raise AssertionError(msg)


type JsonSchema = BooleanSchema | ObjectSchema
type BooleanApplicatorLiteral = Literal["not", "anyOf", "oneOf", "allOf"]


class BooleanApplicatorKeyword(StrEnum):
    NOT = "not"
    ANY_OF = "anyOf"
    ONE_OF = "oneOf"
    ALL_OF = "allOf"


@dataclass(frozen=True, slots=True)
class BooleanSchema(_JsonSchema):
    """A JSON Schema that is always-valid (`true`) or never-valid (`false`)."""

    value: bool
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class ObjectSchema(_JsonSchema):
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

    def get_boolean_applicator(
        self,
        *,
        only: AbstractSet[BooleanApplicatorKeyword | BooleanApplicatorLiteral] | None = None,
    ) -> tuple[BooleanApplicatorKeyword | None, Sequence[JsonSchema]]:
        """Return the type and value of `not`/`anyOf`/`oneOf`/`allOf` defined on this schema.

        Arguments:
            only: If not `None`, only consider these keywords.

        Returns:
            The (mutually exclusive) keyword and its value, or `(None, [])` if none exists.
        """
        rev_map = {member.value: member for member in BooleanApplicatorKeyword.__members__.values()}
        if only is None:
            only = set(BooleanApplicatorKeyword.__members__.values())
        only = {rev_map[v] if isinstance(v, str) else v for v in only}
        assert_type(only, set[BooleanApplicatorKeyword])
        for app, values in {
            BooleanApplicatorKeyword.NOT: self.not_,
            BooleanApplicatorKeyword.ANY_OF: self.any_of,
            BooleanApplicatorKeyword.ONE_OF: self.one_of,
            BooleanApplicatorKeyword.ALL_OF: self.all_of,
        }.items():
            if app in only:
                if isinstance(values, list):
                    return app, values
                if isinstance(values, (BooleanSchema, ObjectSchema)):
                    return app, [values]
        return None, []

    def get_defs(self) -> Mapping[str, JsonSchema]:
        """Return `defs`, or empty if unset."""
        return self.defs or {}

    def get_vocabulary(self) -> Mapping[str, bool]:
        """Return `vocabulary`, or empty if unset."""
        return self.vocabulary or {}

    def get_examples(self) -> Sequence[JsonValue]:
        """Return `examples`, or empty if unset."""
        return self.examples or []

    def get_prefix_items(self) -> Sequence[JsonSchema]:
        """Return `prefix_items`, or empty if unset."""
        return self.prefix_items or []

    def get_pattern_properties(self) -> Mapping[str, JsonSchema]:
        """Return `pattern_properties`, or empty if unset."""
        return self.pattern_properties or {}

    def get_required(self) -> frozenset[str]:
        """Return `required`, or empty if unset."""
        return self.required or frozenset()

    def get_dependent_required(self) -> Mapping[str, frozenset[str]]:
        """Return `dependent_required`, or empty if unset."""
        return self.dependent_required or {}

    def get_dependent_schemas(self) -> Mapping[str, JsonSchema]:
        """Return `dependent_schemas`, or empty if unset."""
        return self.dependent_schemas or {}

    def get_extensions(self) -> Mapping[str, JsonValue]:
        """Return `extensions`, or empty if unset."""
        return self.extensions or {}


@dataclass(frozen=True, slots=True)
class JsonSchemaDocument(CstNode):
    """The root of a parsed JSON Schema 2020-12 document."""

    root: JsonSchema
    source_id: str
    display_name: str | None = None
    source_ref: SourceRef | None = None
