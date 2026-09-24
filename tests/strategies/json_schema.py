"""Strategies for JSON Schema 2020-12 values.

`json_schema_st` generates any value the JSON Schema CST can hold:
a boolean schema, or an object carrying any mix of the keywords [schema_to.cst.json_schema.ObjectSchema][] declares,
including `x-*` extension keys.

The image is the whole supported keyword set.
[tests/parse/test_plan_compiler_unit.py][] pins the CST's fields against a golden snapshot,
so a keyword added to the CST and not to this module shows up there as a diff.

A schema carries a bounded subset of the keywords rather than an independent coin flip per keyword:
The keyword set is large enough that flipping each one generates documents too big for Hypothesis to explore,
and every keyword is still reachable.

Two things are deliberately narrowed because widening them would generate documents that are no longer about the parser:

- A `$ref` is a well-formed pointer, but not necessarily one that resolves.
  Parsing and serializing carry a `$ref` verbatim, so an unresolvable one is still a faithful document;
  [tests.strategies.restricted][] generates the resolvable kind for the tests that resolve.
- `pattern` and `patternProperties` keys are arbitrary text rather than valid regular  expressions.
  The parser stores the string without compiling it;
  a generator that compiles one is covered by targeted tests instead.
"""

from collections.abc import Mapping

from hypothesis import strategies as st
from tests.strategies._primitives import identifier, json_leaf, media_type_str, safe_text

from schema_to.core import JsonObject, JsonValue

_SCHEMA_TYPES = ["string", "number", "integer", "boolean", "array", "object", "null"]
_CONTENT_ENCODINGS = ["7bit", "8bit", "base64", "binary", "quoted-printable"]

_MAX_DEPTH = 2
"""How deep a subschema may nest before only scalar keywords are drawn."""

_MAX_SCALAR_KEYWORDS = 6
_MAX_SUBSCHEMA_KEYWORDS = 2

_bounded_float = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False)
_count = st.integers(min_value=0, max_value=100)
_pointer = st.builds(lambda name: f"#/$defs/{name}", identifier)
_schema_id = st.builds(lambda name: f"https://example.com/{name}.schema.json", identifier)
_vocabulary = st.builds(
    lambda name, required: {f"https://json-schema.org/draft/2020-12/vocab/{name}": required},
    identifier,
    st.booleans(),
)


def _type_st() -> st.SearchStrategy[JsonValue]:
    """One type name, or a list of distinct ones — the CST accepts either form."""
    single: st.SearchStrategy[JsonValue] = st.sampled_from(_SCHEMA_TYPES)
    several: st.SearchStrategy[JsonValue] = st.lists(
        st.sampled_from(_SCHEMA_TYPES), min_size=2, max_size=3, unique=True
    )
    return st.one_of(single, several)


_SCALAR_KEYWORDS: Mapping[str, st.SearchStrategy[JsonValue]] = {
    # Core
    "$id": _schema_id,
    "$schema": st.just("https://json-schema.org/draft/2020-12/schema"),
    "$comment": safe_text,
    "$anchor": identifier,
    "$dynamicAnchor": identifier,
    "$ref": _pointer,
    "$dynamicRef": _pointer,
    "$vocabulary": _vocabulary,
    # Metadata
    "title": safe_text,
    "description": safe_text,
    "default": json_leaf,
    "deprecated": st.booleans(),
    "readOnly": st.booleans(),
    "writeOnly": st.booleans(),
    "examples": st.lists(json_leaf, max_size=3),
    # Validation
    "type": _type_st(),
    "multipleOf": st.floats(min_value=0.001, max_value=1000.0, allow_nan=False),
    "minimum": _bounded_float,
    "maximum": _bounded_float,
    "exclusiveMinimum": _bounded_float,
    "exclusiveMaximum": _bounded_float,
    "minLength": st.integers(min_value=0, max_value=200),
    "maxLength": st.integers(min_value=0, max_value=200),
    "pattern": safe_text,
    "format": identifier,
    "contentEncoding": st.sampled_from(_CONTENT_ENCODINGS),
    "contentMediaType": media_type_str,
    "minItems": _count,
    "maxItems": _count,
    "uniqueItems": st.booleans(),
    "minContains": _count,
    "maxContains": _count,
    "minProperties": _count,
    "maxProperties": _count,
}
"""Keywords whose values hold no subschema, so nesting depth does not reach them."""

_SUBSCHEMA_KEYWORDS = (
    "items",
    "contains",
    "unevaluatedItems",
    "propertyNames",
    "unevaluatedProperties",
    "contentSchema",
    "not",
)
"""Keywords whose value is one schema."""

_SCHEMA_LIST_KEYWORDS = ("prefixItems", "allOf", "anyOf", "oneOf")
"""Keywords whose value is a non-empty array of schemas."""


@st.composite
def _scalar_kw_st(draw: st.DrawFn, d: JsonObject) -> None:
    names = draw(
        st.lists(
            st.sampled_from(sorted(_SCALAR_KEYWORDS)), max_size=_MAX_SCALAR_KEYWORDS, unique=True
        )
    )
    for name in names:
        d[name] = draw(_SCALAR_KEYWORDS[name])
    # `enum` and `const` say the same thing two ways, so a schema carries at most one.
    if draw(st.booleans()):
        d["enum"] = draw(st.lists(json_leaf, min_size=1, max_size=4))
    elif draw(st.booleans()):
        d["const"] = draw(json_leaf)
    if draw(st.booleans()):
        d[f"x-{draw(identifier)}"] = draw(json_leaf)


@st.composite
def _subschema_kw_st(draw: st.DrawFn, d: JsonObject, depth: int) -> None:
    """Keywords whose values are themselves schemas, drawn only while depth allows."""
    nested = json_schema_st(depth=depth + 1)
    names = draw(
        st.lists(
            st.sampled_from([*_SUBSCHEMA_KEYWORDS, *_SCHEMA_LIST_KEYWORDS]),
            max_size=_MAX_SUBSCHEMA_KEYWORDS,
            unique=True,
        )
    )
    for name in names:
        if name in _SCHEMA_LIST_KEYWORDS:
            d[name] = draw(st.lists(nested, min_size=1, max_size=2))
        else:
            d[name] = draw(nested)
    if "not" not in names and draw(st.booleans()):
        # `if` only means anything with a branch beside it.
        d["if"] = draw(nested)
        d["then"] = draw(nested)
        if draw(st.booleans()):
            d["else"] = draw(nested)
    if draw(st.booleans()):
        d["additionalProperties"] = draw(st.one_of(st.booleans(), nested))
    if draw(st.booleans()):
        d["patternProperties"] = {draw(safe_text): draw(nested)}
    if draw(st.booleans()):
        names_ = draw(st.lists(identifier, min_size=1, max_size=2, unique=True))
        d["$defs"] = {name: draw(nested) for name in names_}


@st.composite
def _properties_kw_st(draw: st.DrawFn, d: JsonObject, depth: int) -> None:
    """`properties` and the keywords that only mean something beside it."""
    if not draw(st.booleans()):
        return
    nested = json_schema_st(depth=depth + 1)
    names = draw(st.lists(identifier, min_size=1, max_size=3, unique=True))
    d["properties"] = {name: draw(nested) for name in names}
    if draw(st.booleans()):
        k = draw(st.integers(min_value=1, max_value=len(names)))
        d["required"] = sorted(
            draw(st.lists(st.sampled_from(names), min_size=k, max_size=k, unique=True))
        )
    if draw(st.booleans()):
        d["dependentRequired"] = {
            draw(st.sampled_from(names)): sorted(
                draw(st.lists(st.sampled_from(names), min_size=1, max_size=2, unique=True))
            )
        }
    if draw(st.booleans()):
        d["dependentSchemas"] = {draw(st.sampled_from(names)): draw(nested)}


@st.composite
def json_schema_st(draw: st.DrawFn, depth: int = 0) -> JsonValue:
    """Generate a valid JSON Schema 2020-12 value: a boolean schema, or an object of keywords."""
    if depth > 0 and draw(st.booleans()):
        return draw(st.booleans())

    d: JsonObject = {}
    draw(_scalar_kw_st(d))
    if depth < _MAX_DEPTH:
        draw(_subschema_kw_st(d, depth))
        draw(_properties_kw_st(d, depth))
    return d
