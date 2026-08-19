"""Hypothesis strategies for generating valid JSON Schema and OpenAPI documents.

All strategies produce values that the corresponding parser can parse without errors,
and that the corresponding serializer can round-trip faithfully.

Strategies only generate fields that the parser and serializer both handle.

Additional strategies:

- `json_schema_with_defs_st` — schemas that include `$defs` and internal
  `$ref` pointers, exercising the resolver.
- `object_schema_st` — schemas typed `object` with named properties,
  exercising the Pydantic generator.
"""

from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Primitive building blocks
# ---------------------------------------------------------------------------

_SCHEMA_TYPES = ["string", "number", "integer", "boolean", "array", "object", "null"]

_safe_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd", "Zs"), whitelist_characters="-_./:()"
    ),
    max_size=40,
)

_nonempty_text = _safe_text.filter(lambda s: s.strip())

_json_leaf = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
    _safe_text,
)

_identifier = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=24,
).filter(lambda s: s[0].isalpha())

# Any syntactically valid media type string.
_media_type_str = st.builds(
    lambda t, s: f"{t}/{s}",
    st.sampled_from(["application", "text", "image", "audio", "video", "model", "font"]),
    _identifier,
)


# ---------------------------------------------------------------------------
# JSON Schema sub-strategies (internal helpers)
# ---------------------------------------------------------------------------


@st.composite
def _numeric_kw_st(draw: st.DrawFn, d: dict) -> None:
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
def _string_kw_st(draw: st.DrawFn, d: dict) -> None:
    if draw(st.booleans()):
        d["minLength"] = draw(st.integers(min_value=0, max_value=200))
    if draw(st.booleans()):
        d["maxLength"] = draw(st.integers(min_value=0, max_value=200))
    if draw(st.booleans()):
        d["pattern"] = draw(_safe_text)
    if draw(st.booleans()):
        d["format"] = draw(_identifier)


@st.composite
def _array_kw_st(draw: st.DrawFn, d: dict, depth: int) -> None:
    if draw(st.booleans()):
        d["minItems"] = draw(st.integers(min_value=0, max_value=100))
    if draw(st.booleans()):
        d["maxItems"] = draw(st.integers(min_value=0, max_value=100))
    if draw(st.booleans()):
        d["uniqueItems"] = draw(st.booleans())
    if depth < 2 and draw(st.booleans()):
        d["items"] = draw(json_schema_st(depth=depth + 1))


@st.composite
def _object_kw_st(draw: st.DrawFn, d: dict, depth: int) -> None:
    if depth < 2 and draw(st.booleans()):
        prop_names = draw(st.lists(_identifier, min_size=1, max_size=4, unique=True))
        d["properties"] = {name: draw(json_schema_st(depth=depth + 1)) for name in prop_names}
        if draw(st.booleans()) and prop_names:
            k = draw(st.integers(min_value=1, max_value=len(prop_names)))
            d["required"] = sorted(
                draw(st.lists(st.sampled_from(prop_names), min_size=k, max_size=k, unique=True))
            )
    if depth < 2 and draw(st.booleans()):
        d["additionalProperties"] = draw(st.one_of(st.booleans(), json_schema_st(depth=depth + 1)))


@st.composite
def _applicator_kw_st(draw: st.DrawFn, d: dict, depth: int) -> None:
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
def json_schema_st(draw: st.DrawFn, depth: int = 0) -> object:
    """Generate a valid JSON Schema 2020-12 value (bool or object dict)."""
    if depth > 0 and draw(st.booleans()):
        return draw(st.booleans())

    d: dict[str, object] = {}

    # Core vocabulary
    if draw(st.booleans()):
        d["$id"] = "https://example.com/" + draw(_identifier) + ".schema.json"
    if draw(st.booleans()):
        d["$comment"] = draw(_safe_text)

    # Metadata vocabulary
    if draw(st.booleans()):
        d["title"] = draw(_safe_text)
    if draw(st.booleans()):
        d["description"] = draw(_safe_text)
    if draw(st.booleans()):
        d["default"] = draw(_json_leaf)
    if draw(st.booleans()):
        d["deprecated"] = draw(st.booleans())
    if draw(st.booleans()):
        d["readOnly"] = draw(st.booleans())
    if draw(st.booleans()):
        d["writeOnly"] = draw(st.booleans())
    if draw(st.booleans()):
        d["examples"] = draw(st.lists(_json_leaf, max_size=3))

    # Validation — type
    if draw(st.booleans()):
        n_types = draw(st.integers(min_value=1, max_value=3))
        types = draw(
            st.lists(
                st.sampled_from(_SCHEMA_TYPES), min_size=n_types, max_size=n_types, unique=True
            )
        )
        d["type"] = types[0] if len(types) == 1 else types

    # Validation — enum / const (mutually exclusive)
    if draw(st.booleans()):
        d["enum"] = draw(st.lists(_json_leaf, min_size=1, max_size=5))
    elif draw(st.booleans()):
        d["const"] = draw(_json_leaf)

    draw(_numeric_kw_st(d))
    draw(_string_kw_st(d))
    draw(_array_kw_st(d, depth))
    draw(_object_kw_st(d, depth))
    draw(_applicator_kw_st(d, depth))

    return d


# ---------------------------------------------------------------------------
# OpenAPI strategies
# ---------------------------------------------------------------------------

_PARAM_LOCATIONS = ["query", "header", "path", "cookie"]

# OpenAPI 3.1 allows exact codes (100-599), wildcard patterns (1xx-5xx),
# and "default".
_STATUS_CODES = (
    [str(c) for c in range(100, 600, 100)]
    + ["200", "201", "400", "404", "500"]
    + [f"{d}xx" for d in range(1, 6)]
    + ["default"]
)


@st.composite
def _response_st(draw: st.DrawFn) -> dict:
    d: dict = {"description": draw(_safe_text)}
    if draw(st.booleans()):
        media_types = draw(st.lists(_media_type_str, min_size=1, max_size=2, unique=True))
        d["content"] = {
            mt: (
                {"schema": draw(json_schema_st())}
                if draw(st.booleans()) and "/" in mt and mt.split("/")[0] in {"application", "text"}
                else {}
            )
            for mt in media_types
        }
    return d


@st.composite
def _parameter_st(draw: st.DrawFn) -> dict:
    return {"name": draw(_identifier), "in": draw(st.sampled_from(_PARAM_LOCATIONS))}


@st.composite
def _operation_st(draw: st.DrawFn) -> dict:
    status = draw(st.sampled_from(_STATUS_CODES))
    d: dict = {"responses": {status: draw(_response_st())}}
    if draw(st.booleans()):
        d["summary"] = draw(_safe_text)
    if draw(st.booleans()):
        d["description"] = draw(_safe_text)
    if draw(st.booleans()):
        d["operationId"] = draw(_identifier)
    if draw(st.booleans()):
        d["deprecated"] = draw(st.booleans())
    if draw(st.booleans()):
        d["tags"] = draw(st.lists(_identifier, min_size=1, max_size=3, unique=True))
    if draw(st.booleans()):
        d["parameters"] = [draw(_parameter_st())]
    return d


@st.composite
def _path_item_st(draw: st.DrawFn) -> dict:
    method = draw(st.sampled_from(["get", "post", "put", "delete", "patch"]))
    d: dict = {method: draw(_operation_st())}
    if draw(st.booleans()):
        d["summary"] = draw(_safe_text)
    if draw(st.booleans()):
        d["description"] = draw(_safe_text)
    if draw(st.booleans()):
        d["parameters"] = [draw(_parameter_st())]
    return d


@st.composite
def openapi_doc_st(draw: st.DrawFn) -> dict:
    """Generate a minimal but valid OpenAPI 3.1 document dict."""
    d: dict = {
        "openapi": "3.1.0",
        "info": {"title": draw(_nonempty_text), "version": draw(_nonempty_text)},
    }

    # Optional paths (empty paths: {} is valid)
    if draw(st.booleans()):
        path_names = draw(
            st.lists(st.builds(lambda s: f"/{s}", _identifier), min_size=0, max_size=3, unique=True)
        )
        d["paths"] = {path: draw(_path_item_st()) for path in path_names}

    # Optional components/schemas
    if draw(st.booleans()):
        schema_names = draw(st.lists(_identifier, min_size=1, max_size=4, unique=True))
        d["components"] = {"schemas": {name: draw(json_schema_st()) for name in schema_names}}

    # Optional servers
    if draw(st.booleans()):
        d["servers"] = [{"url": "https://api.example.com"}]

    return d


# ---------------------------------------------------------------------------
# Schema-with-$defs strategy (for resolver tests)
# ---------------------------------------------------------------------------

# Primitive leaf types suitable for $defs entries.
_PRIMITIVE_TYPES = ["string", "integer", "number", "boolean"]


@st.composite
def json_schema_with_defs_st(draw: st.DrawFn) -> dict:
    """Generate a JSON Schema 2020-12 object dict that includes `$defs` and internal `$ref` pointers.

    Guarantees that every `$ref` is resolvable.
    The generated schema always has `type: object` at the root and at least one `$defs` entry.
    Some properties may use `$ref` to those defs.
    """
    def_names = draw(st.lists(_identifier, min_size=1, max_size=4, unique=True))

    defs: dict[str, object] = {}
    for name in def_names:
        defs[name] = {"type": draw(st.sampled_from(_PRIMITIVE_TYPES))}

    d: dict[str, object] = {"type": "object", "$defs": defs}

    if draw(st.booleans()):
        d["title"] = draw(_nonempty_text)
    if draw(st.booleans()):
        d["description"] = draw(_safe_text)

    # Properties: mix of direct types and $ref to defined defs.
    prop_names = draw(st.lists(_identifier, min_size=0, max_size=5, unique=True))
    if prop_names:
        props: dict[str, object] = {}
        for prop in prop_names:
            if draw(st.booleans()) and def_names:
                ref_target = draw(st.sampled_from(def_names))
                props[prop] = {"$ref": f"#/$defs/{ref_target}"}
            else:
                props[prop] = {"type": draw(st.sampled_from(_PRIMITIVE_TYPES))}
        d["properties"] = props
        if draw(st.booleans()) and prop_names:
            k = draw(st.integers(min_value=1, max_value=len(prop_names)))
            d["required"] = sorted(
                draw(st.lists(st.sampled_from(prop_names), min_size=k, max_size=k, unique=True))
            )

    return d


# ---------------------------------------------------------------------------
# Object schema strategy (for Pydantic generator tests)
# ---------------------------------------------------------------------------

# Leaf schema types that map cleanly to Python annotations.
_LEAF_TYPES = ["string", "integer", "number", "boolean"]


@st.composite
def _leaf_schema_st(draw: st.DrawFn) -> dict:
    t = draw(st.sampled_from(_LEAF_TYPES))
    d: dict[str, object] = {"type": t}
    if draw(st.booleans()):
        d["description"] = draw(_safe_text)
    return d


@st.composite
def object_schema_st(draw: st.DrawFn) -> dict:
    """Generate an `object`-typed JSON Schema suitable for Pydantic generation.

    Properties use only leaf primitive types (no recursive nesting), making the
    generated classes simple and the test assertions tractable.  The schema
    always has `type: object` so the generator always produces a `ClassDef`.
    """
    d: dict[str, object] = {"type": "object"}

    if draw(st.booleans()):
        d["title"] = draw(_nonempty_text)
    if draw(st.booleans()):
        d["description"] = draw(_safe_text)

    prop_names = draw(st.lists(_identifier, min_size=0, max_size=6, unique=True))
    if prop_names:
        d["properties"] = {name: draw(_leaf_schema_st()) for name in prop_names}
        if draw(st.booleans()) and prop_names:
            k = draw(st.integers(min_value=1, max_value=len(prop_names)))
            d["required"] = sorted(
                draw(st.lists(st.sampled_from(prop_names), min_size=k, max_size=k, unique=True))
            )

    return d


# ---------------------------------------------------------------------------
# SQL object schema strategy (for PostgreSQL generator tests)
# ---------------------------------------------------------------------------


@st.composite
def sql_object_schema_st(draw: st.DrawFn) -> dict:
    """Generate a JSON Schema 2020-12 object dict suitable for SQL generation tests.

    The root is always `type: object`.  `$defs` entries (if present) are also
    `type: object` schemas so they each become a separate `CREATE TABLE`.
    Properties use only leaf primitive types so column type assertions are
    straightforward.
    """
    def_names = draw(st.lists(_identifier, min_size=0, max_size=3, unique=True))

    defs: dict[str, object] = {}
    for name in def_names:
        prop_names = draw(st.lists(_identifier, min_size=0, max_size=4, unique=True))
        def_schema: dict[str, object] = {"type": "object"}
        if prop_names:
            def_schema["properties"] = {
                p: {"type": draw(st.sampled_from(_LEAF_TYPES))} for p in prop_names
            }
        defs[name] = def_schema

    d: dict[str, object] = {"type": "object"}
    if defs:
        d["$defs"] = defs

    if draw(st.booleans()):
        d["title"] = draw(_nonempty_text)
    if draw(st.booleans()):
        d["description"] = draw(_safe_text)

    prop_names = draw(st.lists(_identifier, min_size=0, max_size=6, unique=True))
    if prop_names:
        d["properties"] = {name: draw(_leaf_schema_st()) for name in prop_names}
        if draw(st.booleans()) and prop_names:
            k = draw(st.integers(min_value=1, max_value=len(prop_names)))
            d["required"] = sorted(
                draw(st.lists(st.sampled_from(prop_names), min_size=k, max_size=k, unique=True))
            )

    return d
