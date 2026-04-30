"""Concrete Syntax Tree for [JSON Schema 2020-12](https://json-schema.org/specification).

The tree mirrors the specification's vocabulary structure: each vocabulary's
keywords are grouped into a dedicated frozen dataclass, and an `ObjectSchema`
composes them all.  This design lets consumers pattern-match or pass only the
vocabulary slices they care about.

Vocabulary references:
- [Core](https://json-schema.org/draft/2020-12/json-schema-core)
- [Validation](https://json-schema.org/draft/2020-12/json-schema-validation)
- [Applicator](https://json-schema.org/draft/2020-12/json-schema-core#section-10)
- [Unevaluated](https://json-schema.org/draft/2020-12/json-schema-core#section-11)
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, StrEnum

from schema_to.cst._base import CstNode, JsonValue, SourceRef

__all__ = [
    "ApplicatorKeywords",
    "ArrayKeywords",
    "BooleanSchema",
    "ContentKeywords",
    "CoreKeywords",
    "FormatKeyword",
    "JsonSchema",
    "JsonSchemaDocument",
    "JsonSchemaType",
    "MetadataKeywords",
    "NumericKeywords",
    "ObjectKeywords",
    "ObjectSchema",
    "SchemaType",
    "StringKeywords",
    "UnevaluatedKeywords",
    "ValidationKeywords",
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
# Vocabulary keyword groups
# Each group is an independent frozen dataclass; all fields default to None /
# empty so that a "blank" instance can be constructed with no arguments.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoreKeywords:
    """Keywords from the [Core vocabulary](https://json-schema.org/draft/2020-12/json-schema-core#section-8).

    Attributes:
        id: `$id` — the schema's canonical URI.
        schema: `$schema` — the meta-schema URI declaring which dialect is in use.
        anchor: `$anchor` — a plain-name anchor for `$ref` targeting.
        dynamic_anchor: `$dynamicAnchor` — anchor that participates in dynamic resolution.
        ref: `$ref` — a URI reference to another schema.
        dynamic_ref: `$dynamicRef` — a URI reference resolved via the dynamic scope.
        defs: `$defs` — named schema definitions reusable via `$ref`.
        comment: `$comment` — free-form annotation, never affects validation.
        vocabulary: `$vocabulary` — maps vocabulary URIs to required/optional flags.
    """

    id: str | None = None
    schema: str | None = None
    anchor: str | None = None
    dynamic_anchor: str | None = None
    ref: str | None = None
    dynamic_ref: str | None = None
    defs: Mapping[str, JsonSchema] | None = None
    comment: str | None = None
    vocabulary: Mapping[str, bool] | None = None


@dataclass(frozen=True, slots=True)
class MetadataKeywords:
    """Keywords from the [Meta-Data vocabulary](https://json-schema.org/draft/2020-12/json-schema-validation#section-9).

    These keywords carry human-readable annotations and do not affect validation.

    Attributes:
        title: Short label for the schema.
        description: Longer prose description (CommonMark allowed).
        default: A default JSON value that is valid against this schema.
        deprecated: Signals that the instance's usage is discouraged.
        read_only: The value should only be set by the server.
        write_only: The value should only be set by the client.
        examples: Example values valid against this schema.
    """

    title: str | None = None
    description: str | None = None
    default: JsonValue | None = None
    deprecated: bool = False
    read_only: bool = False
    write_only: bool = False
    examples: Sequence[JsonValue] | None = None


@dataclass(frozen=True, slots=True)
class ValidationKeywords:
    """Type-independent keywords from the [Validation vocabulary](https://json-schema.org/draft/2020-12/json-schema-validation).

    Attributes:
        type: `type` — restricts the instance to one or more primitive types.
        enum: `enum` — the instance must equal one of the listed values.
        const: `const` — the instance must equal this exact value.
    """

    type: SchemaType | None = None
    enum: Sequence[JsonValue] | None = None
    const: ConstValue | None = None


@dataclass(frozen=True, slots=True)
class ConstValue:
    """Wrapper that distinguishes `const: null` from an absent `const` keyword."""

    value: JsonValue


@dataclass(frozen=True, slots=True)
class NumericKeywords:
    """Numeric validation keywords from the [Validation vocabulary](https://json-schema.org/draft/2020-12/json-schema-validation#section-6.2).

    Attributes:
        multiple_of: `multipleOf` — the instance must be a multiple of this value.
        maximum: `maximum` — inclusive upper bound.
        exclusive_maximum: `exclusiveMaximum` — exclusive upper bound.
        minimum: `minimum` — inclusive lower bound.
        exclusive_minimum: `exclusiveMinimum` — exclusive lower bound.
    """

    multiple_of: int | float | None = None
    maximum: int | float | None = None
    exclusive_maximum: int | float | None = None
    minimum: int | float | None = None
    exclusive_minimum: int | float | None = None


@dataclass(frozen=True, slots=True)
class StringKeywords:
    """String validation keywords from the [Validation vocabulary](https://json-schema.org/draft/2020-12/json-schema-validation#section-6.3).

    Attributes:
        max_length: `maxLength` — maximum number of Unicode code points.
        min_length: `minLength` — minimum number of Unicode code points.
        pattern: `pattern` — ECMA-262 regular expression the string must match.
    """

    max_length: int | None = None
    min_length: int | None = None
    pattern: str | None = None


@dataclass(frozen=True, slots=True)
class ArrayKeywords:
    """Array validation and applicator keywords.

    Combines the `items`/`prefixItems` applicators with array-specific validators.

    Attributes:
        prefix_items: `prefixItems` — schemas for positional (tuple) items.
        items: `items` — schema for items beyond those covered by `prefixItems`.
        contains: `contains` — at least one item must match this schema.
        min_contains: `minContains` — minimum number of items matching `contains`.
        max_contains: `maxContains` — maximum number of items matching `contains`.
        min_items: `minItems` — minimum array length.
        max_items: `maxItems` — maximum array length.
        unique_items: `uniqueItems` — all items must be unique when `true`.
    """

    prefix_items: Sequence[JsonSchema] | None = None
    items: JsonSchema | None = None
    contains: JsonSchema | None = None
    min_contains: int | None = None
    max_contains: int | None = None
    min_items: int | None = None
    max_items: int | None = None
    unique_items: bool = False


@dataclass(frozen=True, slots=True)
class ObjectKeywords:
    """Object validation and applicator keywords.

    Attributes:
        properties: `properties` — schemas for named properties.
        pattern_properties: `patternProperties` — schemas keyed by regex patterns.
        additional_properties: `additionalProperties` — schema for unlisted properties.
        property_names: `propertyNames` — every property name must match this schema.
        required: `required` — set of property names that must be present.
        dependent_required: `dependentRequired` — conditional required property sets.
        dependent_schemas: `dependentSchemas` — schemas applied when a key is present.
        min_properties: `minProperties` — minimum number of properties.
        max_properties: `maxProperties` — maximum number of properties.
    """

    properties: Mapping[str, JsonSchema] | None = None
    pattern_properties: Mapping[str, JsonSchema] | None = None
    additional_properties: JsonSchema | None = None
    property_names: JsonSchema | None = None
    required: frozenset[str] | None = None
    dependent_required: Mapping[str, frozenset[str]] | None = None
    dependent_schemas: Mapping[str, JsonSchema] | None = None
    min_properties: int | None = None
    max_properties: int | None = None


@dataclass(frozen=True, slots=True)
class ApplicatorKeywords:
    """Boolean logic applicators from the [Applicator vocabulary](https://json-schema.org/draft/2020-12/json-schema-core#section-10).

    Attributes:
        all_of: `allOf` — instance must be valid against all schemas.
        any_of: `anyOf` — instance must be valid against at least one schema.
        one_of: `oneOf` — instance must be valid against exactly one schema.
        not_: `not` — instance must be invalid against this schema.
        if_: `if` — conditional applicator guard.
        then: `then` — applied when `if_` succeeds.
        else_: `else` — applied when `if_` fails.
    """

    all_of: Sequence[JsonSchema] | None = None
    any_of: Sequence[JsonSchema] | None = None
    one_of: Sequence[JsonSchema] | None = None
    not_: JsonSchema | None = None
    if_: JsonSchema | None = None
    then: JsonSchema | None = None
    else_: JsonSchema | None = None


@dataclass(frozen=True, slots=True)
class UnevaluatedKeywords:
    """Keywords from the [Unevaluated vocabulary](https://json-schema.org/draft/2020-12/json-schema-core#section-11).

    These keywords apply schemas to properties/items not reached by any other
    applicator, making them useful for catch-all validation.

    Attributes:
        unevaluated_items: `unevaluatedItems` — applied to items not matched by
            `prefixItems`, `items`, or `contains` in any subschema.
        unevaluated_properties: `unevaluatedProperties` — applied to properties
            not matched by `properties`, `patternProperties`, or `additionalProperties`.
    """

    unevaluated_items: JsonSchema | None = None
    unevaluated_properties: JsonSchema | None = None


@dataclass(frozen=True, slots=True)
class ContentKeywords:
    """Keywords from the [Content vocabulary](https://json-schema.org/draft/2020-12/json-schema-validation#section-8).

    These annotate strings that carry encoded content (e.g. Base64, JSON-in-string).

    Attributes:
        content_encoding: `contentEncoding` — e.g. `"base64"`.
        content_media_type: `contentMediaType` — media type of the decoded content.
        content_schema: `contentSchema` — schema for the decoded content.
    """

    content_encoding: str | None = None
    content_media_type: str | None = None
    content_schema: JsonSchema | None = None


@dataclass(frozen=True, slots=True)
class FormatKeyword:
    """The `format` keyword from the [Format vocabulary](https://json-schema.org/draft/2020-12/json-schema-validation#section-7).

    Whether `format` triggers assertion or is annotation-only depends on the
    meta-schema dialect in use.

    Attributes:
        format: The format name, e.g. `"date-time"`, `"uri"`, `"uuid"`.
        asserting: `True` when the `format-assertion` vocabulary is declared,
            making `format` a validator rather than a pure annotation.
    """

    format: str | None = None
    asserting: bool = False


# ---------------------------------------------------------------------------
# Schema node types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BooleanSchema(CstNode):
    """A JSON Schema that is either always-valid (`true`) or never-valid (`false`).

    Attributes:
        value: `True` means the schema validates every instance;
            `False` means it rejects every instance.
        source_ref: Origin in the source document.
    """

    value: bool
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class ObjectSchema(CstNode):
    """A JSON Schema expressed as a keyword-bearing object.

    Keywords are grouped by vocabulary into dedicated sub-objects so that
    consumers can selectively access or pattern-match on vocabulary slices.

    Attributes:
        core: Core vocabulary keywords (`$id`, `$ref`, `$defs`, …).
        metadata: Metadata annotations (`title`, `description`, `examples`, …).
        validation: General validation constraints (`type`, `enum`, `const`).
        numeric: Numeric constraints (`minimum`, `maximum`, `multipleOf`, …).
        string: String constraints (`minLength`, `maxLength`, `pattern`).
        array: Array applicators and constraints.
        object: Object applicators and constraints.
        applicator: Boolean logic applicators (`allOf`, `anyOf`, `if`/`then`, …).
        unevaluated: Unevaluated-items/properties keywords.
        content: Content-encoding annotations.
        formatannotation: The `format` keyword.
        extensions: All `x-*` extension keywords, preserving their raw JSON values.
        source_ref: Origin in the source document.
    """

    core: CoreKeywords = field(default_factory=CoreKeywords)
    metadata: MetadataKeywords = field(default_factory=MetadataKeywords)
    validation: ValidationKeywords = field(default_factory=ValidationKeywords)
    numeric: NumericKeywords = field(default_factory=NumericKeywords)
    string: StringKeywords = field(default_factory=StringKeywords)
    array: ArrayKeywords = field(default_factory=ArrayKeywords)
    object: ObjectKeywords = field(default_factory=ObjectKeywords)
    applicator: ApplicatorKeywords = field(default_factory=ApplicatorKeywords)
    unevaluated: UnevaluatedKeywords = field(default_factory=UnevaluatedKeywords)
    content: ContentKeywords = field(default_factory=ContentKeywords)
    formatannotation: FormatKeyword = field(default_factory=FormatKeyword)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


# A schema is either a boolean shorthand or a full keyword object.
type JsonSchema = BooleanSchema | ObjectSchema


@dataclass(frozen=True, slots=True)
class JsonSchemaDocument(CstNode):
    """The root of a parsed JSON Schema 2020-12 document.

    Holds the top-level schema together with the document-level provenance
    required for cross-document `$ref` resolution.

    Attributes:
        root: The top-level schema object (usually an `ObjectSchema`).
        source_id: Matches `RawDocument.source_id` for this document.
        display_name: Short human-readable label (e.g. from the filename stem).
        source_ref: Points to the document root (`""`).
    """

    root: JsonSchema
    source_id: str
    display_name: str | None = None
    source_ref: SourceRef | None = None
