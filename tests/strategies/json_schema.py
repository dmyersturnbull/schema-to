"""Strategies for JSON Schema 2020-12 values.

`json_schema_st` generates any value the JSON Schema CST can hold:
a boolean schema, or an object with any mix of the keywords the parser recognizes.
"""

from hypothesis import strategies as st
from tests.strategies._primitives import identifier, json_leaf, safe_text

from schema_to.core import JsonObject, JsonValue

_SCHEMA_TYPES = ["string", "number", "integer", "boolean", "array", "object", "null"]


@st.composite
def _numeric_kw_st(draw: st.DrawFn, d: JsonObject) -> None:
    for kw in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        if draw(st.booleans()):
            d[kw] = draw(
                st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False)
            )
    if draw(st.booleans()):
        d["multipleOf"] = draw(
            st.floats(min_value=0.001, max_value=1000.0, allow_nan=False, allow_infinity=False)
        )


@st.composite
def _string_kw_st(draw: st.DrawFn, d: JsonObject) -> None:
    if draw(st.booleans()):
        d["minLength"] = draw(st.integers(min_value=0, max_value=200))
    if draw(st.booleans()):
        d["maxLength"] = draw(st.integers(min_value=0, max_value=200))
    if draw(st.booleans()):
        d["pattern"] = draw(safe_text)
    if draw(st.booleans()):
        d["format"] = draw(identifier)


@st.composite
def _array_kw_st(draw: st.DrawFn, d: JsonObject, depth: int) -> None:
    if draw(st.booleans()):
        d["minItems"] = draw(st.integers(min_value=0, max_value=100))
    if draw(st.booleans()):
        d["maxItems"] = draw(st.integers(min_value=0, max_value=100))
    if draw(st.booleans()):
        d["uniqueItems"] = draw(st.booleans())
    if depth < 2 and draw(st.booleans()):
        d["items"] = draw(json_schema_st(depth=depth + 1))


@st.composite
def _object_kw_st(draw: st.DrawFn, d: JsonObject, depth: int) -> None:
    if depth < 2 and draw(st.booleans()):
        prop_names = draw(st.lists(identifier, min_size=1, max_size=4, unique=True))
        d["properties"] = {name: draw(json_schema_st(depth=depth + 1)) for name in prop_names}
        if draw(st.booleans()) and prop_names:
            k = draw(st.integers(min_value=1, max_value=len(prop_names)))
            d["required"] = sorted(
                draw(st.lists(st.sampled_from(prop_names), min_size=k, max_size=k, unique=True))
            )
    if depth < 2 and draw(st.booleans()):
        d["additionalProperties"] = draw(st.one_of(st.booleans(), json_schema_st(depth=depth + 1)))


@st.composite
def _applicator_kw_st(draw: st.DrawFn, d: JsonObject, depth: int) -> None:
    if depth < 2:
        for kw in ("allOf", "anyOf", "oneOf"):
            if draw(st.booleans()):
                d[kw] = draw(st.lists(json_schema_st(depth=depth + 1), min_size=1, max_size=3))
        if draw(st.booleans()):
            d["not"] = draw(json_schema_st(depth=depth + 1))
        if draw(st.booleans()):
            d["if"] = draw(json_schema_st(depth=depth + 1))
            if draw(st.booleans()):
                d["then"] = draw(json_schema_st(depth=depth + 1))
            if draw(st.booleans()):
                d["else"] = draw(json_schema_st(depth=depth + 1))


# ---------------------------------------------------------------------------
# JSON Schema strategy
# ---------------------------------------------------------------------------


@st.composite
# ruff:ignore[complex-structure, too-many-branches]  # Shared structure
def json_schema_st(draw: st.DrawFn, depth: int = 0) -> JsonValue:
    """Generate a valid JSON Schema 2020-12 value (bool or object dict)."""
    if depth > 0 and draw(st.booleans()):
        return draw(st.booleans())

    d: JsonObject = {}

    # Core vocabulary
    if draw(st.booleans()):
        d["$id"] = "https://example.com/" + draw(identifier) + ".schema.json"
    if draw(st.booleans()):
        d["$comment"] = draw(safe_text)

    # Metadata vocabulary
    if draw(st.booleans()):
        d["title"] = draw(safe_text)
    if draw(st.booleans()):
        d["description"] = draw(safe_text)
    if draw(st.booleans()):
        d["default"] = draw(json_leaf)
    if draw(st.booleans()):
        d["deprecated"] = draw(st.booleans())
    if draw(st.booleans()):
        d["readOnly"] = draw(st.booleans())
    if draw(st.booleans()):
        d["writeOnly"] = draw(st.booleans())
    if draw(st.booleans()):
        d["examples"] = draw(st.lists(json_leaf, max_size=3))

    # Validation — type
    if draw(st.booleans()):
        n_types = draw(st.integers(min_value=1, max_value=3))
        types = draw(
            st.lists(
                st.sampled_from(_SCHEMA_TYPES), min_size=n_types, max_size=n_types, unique=True
            )
        )
        # ty: ignore[invalid-assignment]  # Hypothesis uses `list`, which is invariant.
        d["type"] = types[0] if len(types) == 1 else types

    # Validation — enum / const (mutually exclusive)
    if draw(st.booleans()):
        d["enum"] = draw(st.lists(json_leaf, min_size=1, max_size=5))
    elif draw(st.booleans()):
        d["const"] = draw(json_leaf)

    draw(_numeric_kw_st(d))
    draw(_string_kw_st(d))
    draw(_array_kw_st(d, depth))
    draw(_object_kw_st(d, depth))
    draw(_applicator_kw_st(d, depth))

    return d
