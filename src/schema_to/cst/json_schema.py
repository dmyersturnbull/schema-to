"""Concrete Syntax Tree for [JSON Schema 2020-12](https://json-schema.org/specification).

Each node type holds the set of keywords defined by the specification, grouped by vocabulary.
The flat `ObjectSchema` avoids indirection through vocabulary sub-objects,
 so that serializers and parsers can iterate `dataclasses.fields()` directly.
"""


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

    Fields are ordered by vocabulary:
    core, metadata, validation, numeric, string, array, object, applicator, unevaluated, content, format.
    Each field maps 1-to-1 to the corresponding JSON Schema keyword.

    Fields `not_`, `if_`, `else_`, and `then_` have `_` suffixes.
    (`not`, `if`, and `else` are Python reserved words; `then` has a suffix for symmetry.)
    """

    # -- Core vocabulary --------------------------------------------------
    id: str | None = field(default=None, metadata={"key": "$id"})
    schema: str | None = field(default=None, metadata={"key": "$schema"})
    anchor: str | None = field(default=None, metadata={"key": "$anchor"})
    dynamic_anchor: str | None = field(default=None, metadata={"key": "$dynamicAnchor"})
    ref: str | None = field(default=None, metadata={"key": "$ref"})
    dynamic_ref: str | None = field(default=None, metadata={"key": "$dynamicRef"})
    defs: Mapping[str, JsonSchema] | None = field(default=None, metadata={"key": "$defs"})
    comment: str | None = field(default=None, metadata={"key": "$comment"})
    vocabulary: Mapping[str, bool] | None = field(default=None, metadata={"key": "$vocabulary"})

    # -- Metadata vocabulary ----------------------------------------------
    title: str | None = field(default=None, metadata={"key": "title"})
    description: str | None = field(default=None, metadata={"key": "description"})
    default: DefaultValue | None = field(default=None, metadata={"key": "default"})
    deprecated: bool = field(default=False, metadata={"key": "deprecated"})
    read_only: bool = field(default=False, metadata={"key": "readOnly"})
    write_only: bool = field(default=False, metadata={"key": "writeOnly"})
    examples: Sequence[JsonValue] | None = field(default=None, metadata={"key": "examples"})

    # -- Validation vocabulary --------------------------------------------
    type: SchemaType | None = field(default=None, metadata={"key": "type"})
    enum: Sequence[JsonValue] | None = field(default=None, metadata={"key": "enum"})
    const: ConstValue | None = field(default=None, metadata={"key": "const"})

    # -- Numeric validation -----------------------------------------------
    multiple_of: float | None = field(default=None, metadata={"key": "multipleOf"})
    maximum: float | None = field(default=None, metadata={"key": "maximum"})
    exclusive_maximum: float | None = field(default=None, metadata={"key": "exclusiveMaximum"})
    minimum: float | None = field(default=None, metadata={"key": "minimum"})
    exclusive_minimum: float | None = field(default=None, metadata={"key": "exclusiveMinimum"})

    # -- String validation ------------------------------------------------
    max_length: int | None = field(default=None, metadata={"key": "maxLength", "kind": "int_nn"})
    min_length: int | None = field(default=None, metadata={"key": "minLength", "kind": "int_nn"})
    pattern: str | None = field(default=None, metadata={"key": "pattern"})

    # -- Array keywords ---------------------------------------------------
    prefix_items: Sequence[JsonSchema] | None = field(default=None, metadata={"key": "prefixItems"})
    items: JsonSchema | None = field(default=None, metadata={"key": "items"})
    contains: JsonSchema | None = field(default=None, metadata={"key": "contains"})
    min_contains: int | None = field(default=None, metadata={"key": "minContains"})
    max_contains: int | None = field(default=None, metadata={"key": "maxContains"})
    min_items: int | None = field(default=None, metadata={"key": "minItems"})
    max_items: int | None = field(default=None, metadata={"key": "maxItems"})
    unique_items: bool = field(default=False, metadata={"key": "uniqueItems"})

    # -- Object keywords --------------------------------------------------
    properties: Mapping[str, JsonSchema] | None = field(
        default=None, metadata={"key": "properties"}
    )
    pattern_properties: Mapping[str, JsonSchema] | None = field(
        default=None, metadata={"key": "patternProperties"}
    )
    additional_properties: JsonSchema | None = field(
        default=None, metadata={"key": "additionalProperties"}
    )
    property_names: JsonSchema | None = field(default=None, metadata={"key": "propertyNames"})
    required: frozenset[str] | None = field(default=None, metadata={"key": "required"})
    dependent_required: Mapping[str, frozenset[str]] | None = field(
        default=None, metadata={"key": "dependentRequired"}
    )
    dependent_schemas: Mapping[str, JsonSchema] | None = field(
        default=None, metadata={"key": "dependentSchemas"}
    )
    min_properties: int | None = field(default=None, metadata={"key": "minProperties"})
    max_properties: int | None = field(default=None, metadata={"key": "maxProperties"})

    # -- Applicator vocabulary --------------------------------------------
    all_of: Sequence[JsonSchema] | None = field(default=None, metadata={"key": "allOf"})
    any_of: Sequence[JsonSchema] | None = field(default=None, metadata={"key": "anyOf"})
    one_of: Sequence[JsonSchema] | None = field(default=None, metadata={"key": "oneOf"})
    not_: JsonSchema | None = field(default=None, metadata={"key": "not"})
    if_: JsonSchema | None = field(default=None, metadata={"key": "if"})
    then_: JsonSchema | None = field(default=None, metadata={"key": "then"})
    else_: JsonSchema | None = field(default=None, metadata={"key": "else"})

    # -- Unevaluated vocabulary -------------------------------------------
    unevaluated_items: JsonSchema | None = field(default=None, metadata={"key": "unevaluatedItems"})
    unevaluated_properties: JsonSchema | None = field(
        default=None, metadata={"key": "unevaluatedProperties"}
    )

    # -- Content vocabulary -----------------------------------------------
    content_encoding: str | None = field(default=None, metadata={"key": "contentEncoding"})
    content_media_type: str | None = field(default=None, metadata={"key": "contentMediaType"})
    content_schema: JsonSchema | None = field(default=None, metadata={"key": "contentSchema"})

    # -- Format vocabulary ------------------------------------------------
    format: str | None = field(default=None, metadata={"key": "format"})

    # -- Extensions and provenance ----------------------------------------
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata={})
    source_ref: SourceRef | None = field(default=None, metadata={})

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
