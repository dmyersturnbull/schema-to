"""Concrete Syntax Tree for [JSON Schema 2020-12](https://json-schema.org/specification).

Each node type holds the set of keywords defined by the specification, grouped by vocabulary.
The flat [ObjectSchema][] avoids indirection through vocabulary sub-objects,
so that serializers and parsers can iterate `dataclasses.fields()` directly.
"""

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Literal, TypeGuard, assert_type

from schema_to.core import JsonValue
from schema_to.cst.base import SYNTHETIC, CstNode, SourceRef
from schema_to.io.uri import pointer_uri

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
type SchemaType = JsonSchemaType | Set[JsonSchemaType]


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

    def get_types(self) -> Set[JsonSchemaType]:
        """Return the schema's types as a frozenset, or empty frozenset if unset."""
        match self:
            case BooleanSchema():
                return frozenset()
            case ObjectSchema(type=None):
                return frozenset()
            case ObjectSchema(type=frozenset(types)):
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
    | Set[JsonSchemaType]
    | Set[str]
    | DefaultValue
    | ConstValue
    | JsonSchema
    | Sequence[JsonValue]
    | Sequence[JsonSchema]
    | Mapping[str, JsonSchema]
    | Mapping[str, bool]
    | Mapping[str, Set[str]]
    | Mapping[str, JsonValue]
    | None
)


# Keywords whose value is one self-contained assertion, so two schemas cannot contribute
# complementary halves of one: either a schema sets it or it does not.
# `properties` and `required` are absent because they accumulate, and `allOf`/`anyOf`/`oneOf`
# because they are the composition being resolved.
SINGULAR_KEYWORDS: Set[str] = frozenset(
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
# Losing one to a merge costs prose; losing any of the others costs validation.
DOC_KEYWORDS: Set[str] = frozenset({"title", "description"})


def is_object_schema(schema: JsonSchema) -> TypeGuard[ObjectSchema]:
    """Return `True` if *schema* describes a JSON object (a table/model).

    True if `schema` is an `ObjectSchema` and **either**:

    - [ObjectSchema.get_types][] contains [JsonSchemaType.OBJECT][]
      Meaning in JSON either `"type": "object"` or `"type": ["object", ...]`)
    - [ObjectSchema.get_types][] is empty but [ObjectSchema.properties][] is not `None`
      Meaning in JSON the key `properties` is present (even if it's empty)

    Note:
        This returns `TypeGuard` rather than `TypeIs` because the condition is more restrictive than just `isinstance(..., ObjectSchema)`.
        `not is_object_schema(x)` does **not** imply `not instance(x, ObjectSchema)`.
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
    title: str | None = None
    description: str | None = None
    default: DefaultValue | None = None
    deprecated: bool = False
    read_only: bool = False
    write_only: bool = False
    examples: Sequence[JsonValue] | None = None

    # -- Validation vocabulary --------------------------------------------
    type: SchemaType | None = None
    enum: Sequence[JsonValue] | None = None
    const: ConstValue | None = None

    # -- Numeric validation -----------------------------------------------
    multiple_of: float | None = None
    maximum: float | None = None
    exclusive_maximum: float | None = None
    minimum: float | None = None
    exclusive_minimum: float | None = None

    # -- String validation ------------------------------------------------
    max_length: int | None = field(default=None, metadata={"min": 0})
    min_length: int | None = field(default=None, metadata={"min": 0})
    pattern: str | None = None

    # -- Array keywords ---------------------------------------------------
    prefix_items: Sequence[JsonSchema] | None = None
    items: JsonSchema | None = None
    contains: JsonSchema | None = None
    min_contains: int | None = None
    max_contains: int | None = None
    min_items: int | None = None
    max_items: int | None = None
    unique_items: bool = False

    # -- Object keywords --------------------------------------------------
    properties: Mapping[str, JsonSchema] | None = None
    pattern_properties: Mapping[str, JsonSchema] | None = None
    additional_properties: JsonSchema | None = None
    property_names: JsonSchema | None = None
    required: Set[str] | None = None
    dependent_required: Mapping[str, Set[str]] | None = None
    dependent_schemas: Mapping[str, JsonSchema] | None = None
    min_properties: int | None = None
    max_properties: int | None = None

    # -- Applicator vocabulary --------------------------------------------
    all_of: Sequence[JsonSchema] | None = None
    any_of: Sequence[JsonSchema] | None = None
    one_of: Sequence[JsonSchema] | None = None
    not_: JsonSchema | None = None
    if_: JsonSchema | None = None
    then_: JsonSchema | None = None
    else_: JsonSchema | None = None

    # -- Unevaluated vocabulary -------------------------------------------
    unevaluated_items: JsonSchema | None = None
    unevaluated_properties: JsonSchema | None = None

    # -- Content vocabulary -----------------------------------------------
    content_encoding: str | None = None
    content_media_type: str | None = None
    content_schema: JsonSchema | None = None

    # -- Format vocabulary ------------------------------------------------
    format: str | None = None

    # -- Extensions and provenance ----------------------------------------
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)

    def get_boolean_applicator(
        self, *, only: Set[BooleanApplicatorKeyword | BooleanApplicatorLiteral] | None = None
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
                if isinstance(values, Sequence):
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

    def get_required(self) -> Set[str]:
        """Return `required`, or empty if unset."""
        return self.required or frozenset()

    def get_dependent_required(self) -> Mapping[str, Set[str]]:
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
        source_id: URI identifying this document,
            which is also what a relative `$ref` inside it resolves against.
            A document carved out of a larger one has the original's URI plus a fragment,
            so that its ID stays unique
            while a reference written in it still resolves as it would in the file it came from.
        display_name: Short name, carried over from `RawDoc.display_name`.
        source_ref: Where in the original document this one's root is.
    """

    root: JsonSchema
    source_id: str
    display_name: str | None = None
    source_ref: SourceRef | None = None

    @classmethod
    def lifted(
        cls, root: JsonSchema, *, from_uri: str, json_pointer: str, name: str
    ) -> JsonSchemaDocument:
        """Return a schema found inside another document, as a document of its own.

        Args:
            root: The schema.
            from_uri: URI of the document it was found in.
            json_pointer: Where in that document it was found.
            name: Its display name.
        """
        return cls(
            root=root,
            source_id=pointer_uri(from_uri, json_pointer),
            display_name=name,
            source_ref=SourceRef(from_uri, json_pointer),
        )


@dataclass(frozen=True, slots=True)
class JsonSchemaMapDocument(CstNode):
    """A document whose root is a map of names to schemas, rather than one schema.

    This is the shape of an OpenAPI `components/schemas` fragment,
    and of any file that collects several related schemas without nesting them under `$defs`.
    Each entry sits directly at the document root,
    so schema `foo` is addressed by the JSON Pointer `/foo` —
    the form a sibling file's `$ref` uses when it writes `./that-file.yaml#/foo`.

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
