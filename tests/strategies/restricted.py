"""Deliberately narrowed schema strategies, for generators with shape-dependent assertions.

Each strategy here generates a proper subset of what `json_schema_st` does.
The docstring on each says what it leaves out,
so that a gap is visible where it matters rather than hidden in the strategy body.
"""

from hypothesis import strategies as st
from tests.strategies._primitives import identifier, nonempty_text, safe_text

from schema_to.core import JsonObject

# Primitive leaf types suitable for $defs entries.
_PRIMITIVE_TYPES = ["string", "integer", "number", "boolean"]


@st.composite
def json_schema_with_defs_st(draw: st.DrawFn) -> JsonObject:
    """Generate a JSON Schema 2020-12 object dict that includes `$defs` and internal `$ref` pointers.

    Guarantees that every `$ref` is resolvable.
    The generated schema always has `type: object` at the root and at least one `$defs` entry.
    Some properties may use `$ref` to those defs.
    """
    def_names = draw(st.lists(identifier, min_size=1, max_size=4, unique=True))

    defs: JsonObject = {}
    for name in def_names:
        defs[name] = {"type": draw(st.sampled_from(_PRIMITIVE_TYPES))}

    d: JsonObject = {"type": "object", "$defs": defs}

    if draw(st.booleans()):
        d["title"] = draw(nonempty_text)
    if draw(st.booleans()):
        d["description"] = draw(safe_text)

    # Properties: mix of direct types and $ref to defined defs.
    prop_names = draw(st.lists(identifier, min_size=0, max_size=5, unique=True))
    if prop_names:
        props: JsonObject = {}
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


# Leaf schema types that map cleanly to Python annotations.
_LEAF_TYPES = ["string", "integer", "number", "boolean"]


@st.composite
def _leaf_schema_st(draw: st.DrawFn) -> JsonObject:
    t = draw(st.sampled_from(_LEAF_TYPES))
    d: JsonObject = {"type": t}
    if draw(st.booleans()):
        d["description"] = draw(safe_text)
    return d


@st.composite
def object_schema_st(draw: st.DrawFn) -> JsonObject:
    """Generate an `object`-typed JSON Schema suitable for Pydantic generation.

    Properties use only leaf primitive types (no recursive nesting), making the
    generated classes simple and the test assertions tractable.  The schema
    always has `type: object` so the generator always produces a `ClassDef`.
    """
    d: JsonObject = {"type": "object"}

    if draw(st.booleans()):
        d["title"] = draw(nonempty_text)
    if draw(st.booleans()):
        d["description"] = draw(safe_text)

    prop_names = draw(st.lists(identifier, min_size=0, max_size=6, unique=True))
    if prop_names:
        d["properties"] = {name: draw(_leaf_schema_st()) for name in prop_names}
        if draw(st.booleans()) and prop_names:
            k = draw(st.integers(min_value=1, max_value=len(prop_names)))
            d["required"] = sorted(
                draw(st.lists(st.sampled_from(prop_names), min_size=k, max_size=k, unique=True))
            )

    return d


@st.composite
def sql_object_schema_st(draw: st.DrawFn) -> JsonObject:
    """Generate a JSON Schema 2020-12 object dict suitable for SQL generation tests.

    The root is always `type: object`.
    `$defs` entries (if present) are also `type: object` schemas so they each become a separate `CREATE TABLE`.
    Properties use only leaf primitive types so column type assertions are straightforward.
    """
    def_names = draw(st.lists(identifier, min_size=0, max_size=3, unique=True))

    defs: JsonObject = {}
    for name in def_names:
        prop_names = draw(st.lists(identifier, min_size=0, max_size=4, unique=True))
        def_schema: JsonObject = {"type": "object"}
        if prop_names:
            def_schema["properties"] = {
                p: {"type": draw(st.sampled_from(_LEAF_TYPES))} for p in prop_names
            }
        defs[name] = def_schema

    d: JsonObject = {"type": "object"}
    if defs:
        d["$defs"] = defs

    if draw(st.booleans()):
        d["title"] = draw(nonempty_text)
    if draw(st.booleans()):
        d["description"] = draw(safe_text)

    prop_names = draw(st.lists(identifier, min_size=0, max_size=6, unique=True))
    if prop_names:
        d["properties"] = {name: draw(_leaf_schema_st()) for name in prop_names}
        if draw(st.booleans()) and prop_names:
            k = draw(st.integers(min_value=1, max_value=len(prop_names)))
            d["required"] = sorted(
                draw(st.lists(st.sampled_from(prop_names), min_size=k, max_size=k, unique=True))
            )

    return d
