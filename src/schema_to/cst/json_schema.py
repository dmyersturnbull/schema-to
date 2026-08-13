"""Concrete Syntax Tree for [JSON Schema 2020-12](https://json-schema.org/specification).

Each node type holds the set of keywords defined by the specification, grouped by vocabulary.
The flat `ObjectSchema` avoids indirection through vocabulary sub-objects,
so that serializers and parsers can iterate `dataclasses.fields()` directly.
"""

from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Literal, TypeIs, assert_type

from schema_to.cst.base import CstNode, SourceRef

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from collections.abc import Set as AbstractSet

    from schema_to.core import JsonValue

__all__ = [
    "DOC_KEYWORDS",
    "SINGULAR_KEYWORDS",
    "BooleanApplicatorKeyword",
    "BooleanSchema",
    "ConstValue",
    "DefaultValue",
    "JsonSchema",
    "JsonSchemaDocument",
    "JsonSchemaMapDocument",
    "JsonSchemaType",
    "ObjectSchema",
    "SchemaKeywordValue",
    "SchemaType",
    "is_object_schema",
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

# Union of every type that can appear as an `ObjectSchema` field value.
# Parsers, serializers, and mergers all move keyword values generically —
# by iterating `dataclasses.fields(ObjectSchema)` — so they need one type
# covering all of them, rather than `Any`.
type SchemaKeywordValue = (
    str
    | bool
    | int
    | float
    | JsonSchemaType
    | frozenset[JsonSchemaType]
    | frozenset[str]
    | DefaultValue
    | ConstValue
    | JsonSchema
    | Sequence[JsonValue]
    | Sequence[JsonSchema]
    | Mapping[str, JsonSchema]
    | Mapping[str, bool]
    | Mapping[str, frozenset[str]]
    | Mapping[str, JsonValue]
    | None
)


# Keywords whose value is one self-contained assertion,
# so two schemas cannot contribute complementary halves of one.
# `properties` and `required` are absent because they accumulate,
# and `allOf`/`anyOf`/`oneOf` because they are the composition being resolved.
SINGULAR_KEYWORDS: frozenset[str] = frozenset(
    {
        "title",
        "description",
        "format",
        "pattern",
        "enum",
        "const",
        "minimum",
        "maximum",
        "exclusive_minimum",
        "exclusive_maximum",
        "min_length",
        "max_length",
        "items",
        "property_names",
        "additional_properties",
        "unevaluated_properties",
        "pattern_properties",
        "read_only",
        "write_only",
    }
)


# The subset of `SINGULAR_KEYWORDS` that documents a schema rather than constraining it.
# Losing one to a merge only costs prose.
DOC_KEYWORDS: frozenset[str] = frozenset({"title", "description"})


def is_object_schema(schema: JsonSchema) -> TypeIs[ObjectSchema]:
    """Return `True` if *schema* describes a JSON object (a table/model).

    True when `object` is among the declared types,
    or when no type is declared but `properties` are present
    (a common shorthand for an object schema).
    """
    if not isinstance(schema, ObjectSchema):
        return False
    types = schema.get_types()
    return JsonSchemaType.OBJECT in types or (not types and schema.properties is not None)


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
    id: str | None = field(default=None, metadata={"key": "$id", "kind": "str"})
    schema: str | None = field(default=None, metadata={"key": "$schema", "kind": "str"})
    anchor: str | None = field(default=None, metadata={"key": "$anchor", "kind": "str"})
    dynamic_anchor: str | None = field(
        default=None, metadata={"key": "$dynamicAnchor", "kind": "str"}
    )
    ref: str | None = field(default=None, metadata={"key": "$ref", "kind": "str"})
    dynamic_ref: str | None = field(default=None, metadata={"key": "$dynamicRef", "kind": "str"})
    defs: Mapping[str, JsonSchema] | None = field(
        default=None, metadata={"key": "$defs", "kind": "schema_map"}
    )
    comment: str | None = field(default=None, metadata={"key": "$comment", "kind": "str"})
    vocabulary: Mapping[str, bool] | None = field(
        default=None, metadata={"key": "$vocabulary", "kind": "bool_map"}
    )

    # -- Metadata vocabulary ----------------------------------------------
    title: str | None = field(default=None, metadata={"key": "title", "kind": "str"})
    description: str | None = field(default=None, metadata={"key": "description", "kind": "str"})
    default: DefaultValue | None = field(
        default=None, metadata={"key": "default", "kind": "default_value"}
    )
    deprecated: bool = field(default=False, metadata={"key": "deprecated", "kind": "bool"})
    read_only: bool = field(default=False, metadata={"key": "readOnly", "kind": "bool"})
    write_only: bool = field(default=False, metadata={"key": "writeOnly", "kind": "bool"})
    examples: Sequence[JsonValue] | None = field(
        default=None, metadata={"key": "examples", "kind": "json_array"}
    )

    # -- Validation vocabulary --------------------------------------------
    type: SchemaType | None = field(default=None, metadata={"key": "type", "kind": "schema_type"})
    enum: Sequence[JsonValue] | None = field(
        default=None, metadata={"key": "enum", "kind": "json_array"}
    )
    const: ConstValue | None = field(default=None, metadata={"key": "const", "kind": "const_value"})

    # -- Numeric validation -----------------------------------------------
    multiple_of: float | None = field(default=None, metadata={"key": "multipleOf", "kind": "num"})
    maximum: float | None = field(default=None, metadata={"key": "maximum", "kind": "num"})
    exclusive_maximum: float | None = field(
        default=None, metadata={"key": "exclusiveMaximum", "kind": "num"}
    )
    minimum: float | None = field(default=None, metadata={"key": "minimum", "kind": "num"})
    exclusive_minimum: float | None = field(
        default=None, metadata={"key": "exclusiveMinimum", "kind": "num"}
    )

    # -- String validation ------------------------------------------------
    max_length: int | None = field(default=None, metadata={"key": "maxLength", "kind": "int_nn"})
    min_length: int | None = field(default=None, metadata={"key": "minLength", "kind": "int_nn"})
    pattern: str | None = field(default=None, metadata={"key": "pattern", "kind": "str"})

    # -- Array keywords ---------------------------------------------------
    prefix_items: Sequence[JsonSchema] | None = field(
        default=None, metadata={"key": "prefixItems", "kind": "schema_list"}
    )
    items: JsonSchema | None = field(
        default=None, metadata={"key": "items", "kind": "optional_schema"}
    )
    contains: JsonSchema | None = field(
        default=None, metadata={"key": "contains", "kind": "optional_schema"}
    )
    min_contains: int | None = field(default=None, metadata={"key": "minContains", "kind": "int"})
    max_contains: int | None = field(default=None, metadata={"key": "maxContains", "kind": "int"})
    min_items: int | None = field(default=None, metadata={"key": "minItems", "kind": "int"})
    max_items: int | None = field(default=None, metadata={"key": "maxItems", "kind": "int"})
    unique_items: bool = field(default=False, metadata={"key": "uniqueItems", "kind": "bool"})

    # -- Object keywords --------------------------------------------------
    properties: Mapping[str, JsonSchema] | None = field(
        default=None, metadata={"key": "properties", "kind": "schema_map"}
    )
    pattern_properties: Mapping[str, JsonSchema] | None = field(
        default=None, metadata={"key": "patternProperties", "kind": "schema_map"}
    )
    additional_properties: JsonSchema | None = field(
        default=None, metadata={"key": "additionalProperties", "kind": "optional_schema"}
    )
    property_names: JsonSchema | None = field(
        default=None, metadata={"key": "propertyNames", "kind": "optional_schema"}
    )
    required: frozenset[str] | None = field(
        default=None, metadata={"key": "required", "kind": "str_frozenset"}
    )
    dependent_required: Mapping[str, frozenset[str]] | None = field(
        default=None, metadata={"key": "dependentRequired", "kind": "dep_required_map"}
    )
    dependent_schemas: Mapping[str, JsonSchema] | None = field(
        default=None, metadata={"key": "dependentSchemas", "kind": "schema_map"}
    )
    min_properties: int | None = field(
        default=None, metadata={"key": "minProperties", "kind": "int"}
    )
    max_properties: int | None = field(
        default=None, metadata={"key": "maxProperties", "kind": "int"}
    )

    # -- Applicator vocabulary --------------------------------------------
    all_of: Sequence[JsonSchema] | None = field(
        default=None, metadata={"key": "allOf", "kind": "schema_list"}
    )
    any_of: Sequence[JsonSchema] | None = field(
        default=None, metadata={"key": "anyOf", "kind": "schema_list"}
    )
    one_of: Sequence[JsonSchema] | None = field(
        default=None, metadata={"key": "oneOf", "kind": "schema_list"}
    )
    not_: JsonSchema | None = field(
        default=None, metadata={"key": "not", "kind": "optional_schema"}
    )
    if_: JsonSchema | None = field(default=None, metadata={"key": "if", "kind": "optional_schema"})
    then_: JsonSchema | None = field(
        default=None, metadata={"key": "then", "kind": "optional_schema"}
    )
    else_: JsonSchema | None = field(
        default=None, metadata={"key": "else", "kind": "optional_schema"}
    )

    # -- Unevaluated vocabulary -------------------------------------------
    unevaluated_items: JsonSchema | None = field(
        default=None, metadata={"key": "unevaluatedItems", "kind": "optional_schema"}
    )
    unevaluated_properties: JsonSchema | None = field(
        default=None, metadata={"key": "unevaluatedProperties", "kind": "optional_schema"}
    )

    # -- Content vocabulary -----------------------------------------------
    content_encoding: str | None = field(
        default=None, metadata={"key": "contentEncoding", "kind": "str"}
    )
    content_media_type: str | None = field(
        default=None, metadata={"key": "contentMediaType", "kind": "str"}
    )
    content_schema: JsonSchema | None = field(
        default=None, metadata={"key": "contentSchema", "kind": "optional_schema"}
    )

    # -- Format vocabulary ------------------------------------------------
    format: str | None = field(default=None, metadata={"key": "format", "kind": "str"})

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
    """The root of a parsed JSON Schema 2020-12 document.

    Attributes:
        source_id: Identifies this document.
        base_uri: What a relative `$ref` inside it resolves against.  Usually the same
            as `source_id`; they differ for a document carved out of a larger one,
            whose ID must stay unique while its references still mean what they did
            in the file they were written in.
    """

    root: JsonSchema
    source_id: str
    display_name: str | None = None
    source_ref: SourceRef | None = None
    base_uri: str | None = None

    def get_base_uri(self) -> str:
        """Return what a relative `$ref` in this document resolves against."""
        return self.base_uri or self.source_id


@dataclass(frozen=True, slots=True)
class JsonSchemaMapDocument(CstNode):
    """A document whose root is a map of names to schemas, rather than one schema.

    This is the shape of an OpenAPI `components/schemas` fragment, and of any file
    that collects several related schemas without nesting them under `$defs`.
    Each entry sits directly at the document root, so schema `foo` is addressed by
    the JSON Pointer `/foo` — the form a sibling file's `$ref` uses when it writes
    `./that-file.yaml#/foo`.

    Attributes:
        schemas: The named schemas, in document order.
    """

    schemas: Mapping[str, JsonSchema]
    source_id: str
    display_name: str | None = None
    source_ref: SourceRef | None = None

    def get_schema(self, name: str) -> JsonSchema | None:
        """Return the schema named `name`, or `None`."""
        return self.schemas.get(name)
