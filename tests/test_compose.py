"""Tests for `allOf` / `$ref` flattening.

Covers:
- Targeted: `allOf` merges properties, required, and type.
- Targeted: single-valued keywords take the first branch that sets one.
- Targeted: `$ref` targets are followed when a resolver is present, and left alone otherwise.
- Targeted: conflicting, recursive, and unsatisfiable compositions warn rather than fail.
- Integration: an `allOf`-composed schema becomes a table with every branch's columns.
"""

import orjson

from schema_to.cst.json_schema import JsonSchemaType, ObjectSchema, is_object_schema
from schema_to.generate._compose import SchemaFlattener
from schema_to.io.media_type import MediaTypes
from schema_to.io.source import JsonSchemaRawDoc
from schema_to.parse.json_schema import JsonSchemaParser
from schema_to.resolve.json_schema import JsonSchemaRefResolver
from schema_to.result import Ok

_PARSER = JsonSchemaParser()
_SOURCE_ID = "test://schema"


def _parse(data: object, source_id: str = _SOURCE_ID) -> ObjectSchema:
    doc = JsonSchemaRawDoc(doc_id=source_id, content=orjson.dumps(data), media_type=MediaTypes.json)
    result = _PARSER.apply(doc)
    assert isinstance(result, Ok)
    root = result.value.root
    assert isinstance(root, ObjectSchema)
    return root


def _flatten(data: object, *, resolve: bool = False) -> ObjectSchema:
    schema = _parse(data)
    resolver = None
    if resolve:
        resolver = JsonSchemaRefResolver()
        doc = JsonSchemaRawDoc(
            doc_id=_SOURCE_ID, content=orjson.dumps(data), media_type=MediaTypes.json
        )
        parsed = _PARSER.apply(doc)
        assert isinstance(parsed, Ok)
        resolver.register(parsed.value)
    flat = SchemaFlattener(resolver=resolver).flatten(schema, base_uri=_SOURCE_ID).schema
    assert isinstance(flat, ObjectSchema)
    return flat


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------


def test_all_of_merges_properties() -> None:
    flat = _flatten(
        {
            "allOf": [
                {"type": "object", "properties": {"a": {"type": "string"}}},
                {"type": "object", "properties": {"b": {"type": "integer"}}},
            ]
        }
    )
    assert set(flat.properties or {}) == {"a", "b"}


def test_merged_properties_keep_declaration_order() -> None:
    """Columns should come out in the order the branches declare them."""
    flat = _flatten(
        {
            "type": "object",
            "properties": {"own": {"type": "string"}},
            "allOf": [
                {"type": "object", "properties": {"first": {"type": "string"}}},
                {"type": "object", "properties": {"second": {"type": "string"}}},
            ],
        }
    )
    assert list(flat.properties or {}) == ["own", "first", "second"]


def test_all_of_unions_required() -> None:
    flat = _flatten(
        {
            "allOf": [
                {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}},
                {"type": "object", "required": ["b"], "properties": {"b": {"type": "string"}}},
            ]
        }
    )
    assert flat.get_required() == frozenset({"a", "b"})


def test_all_of_merges_with_own_properties() -> None:
    """Keywords on the composing schema merge with those from its branches."""
    flat = _flatten(
        {
            "type": "object",
            "required": ["own"],
            "properties": {"own": {"type": "string"}},
            "allOf": [{"type": "object", "properties": {"branch": {"type": "integer"}}}],
        }
    )
    assert set(flat.properties or {}) == {"own", "branch"}
    assert flat.get_required() == frozenset({"own"})


def test_all_of_intersects_type() -> None:
    flat = _flatten({"type": "object", "allOf": [{"type": "object"}]})
    assert flat.get_types() == frozenset({JsonSchemaType.OBJECT})


def test_untyped_branch_does_not_constrain_type() -> None:
    """A branch with no `type` leaves the composed type alone."""
    flat = _flatten({"allOf": [{"type": "object"}, {"properties": {"a": {"type": "string"}}}]})
    assert flat.get_types() == frozenset({JsonSchemaType.OBJECT})


def test_description_taken_from_first_branch_that_sets_one() -> None:
    flat = _flatten({"allOf": [{"type": "object"}, {"description": "From the second branch."}]})
    assert flat.description == "From the second branch."


def test_own_description_wins_over_branch() -> None:
    flat = _flatten({"description": "Mine.", "allOf": [{"description": "Theirs."}]})
    assert flat.description == "Mine."


def test_zero_minimum_is_not_treated_as_unset() -> None:
    """`0` is a real bound, even though `0 == False`."""
    flat = _flatten({"minimum": 0, "allOf": [{"minimum": 5}]})
    assert flat.minimum == 0


def test_all_of_is_cleared_after_flattening() -> None:
    flat = _flatten({"allOf": [{"type": "object"}]})
    assert flat.all_of is None


def test_nested_all_of_is_flattened() -> None:
    flat = _flatten(
        {
            "allOf": [
                {
                    "type": "object",
                    "allOf": [{"type": "object", "properties": {"deep": {"type": "string"}}}],
                }
            ]
        }
    )
    assert set(flat.properties or {}) == {"deep"}


# ---------------------------------------------------------------------------
# $ref
# ---------------------------------------------------------------------------


def test_ref_is_followed_with_a_resolver() -> None:
    flat = _flatten(
        {"$defs": {"named": {"type": "string", "pattern": "^a+$"}}, "$ref": "#/$defs/named"},
        resolve=True,
    )
    assert flat.get_types() == frozenset({JsonSchemaType.STRING})
    assert flat.pattern == "^a+$"


def test_ref_in_all_of_branch_is_followed() -> None:
    flat = _flatten(
        {
            "$defs": {"content": {"type": "object", "properties": {"c": {"type": "integer"}}}},
            "type": "object",
            "properties": {"own": {"type": "string"}},
            "allOf": [{"$ref": "#/$defs/content"}],
        },
        resolve=True,
    )
    assert set(flat.properties or {}) == {"own", "c"}


def test_ref_is_left_alone_without_a_resolver() -> None:
    flat = _flatten({"$defs": {"named": {"type": "string"}}, "$ref": "#/$defs/named"})
    assert flat.get_types() == frozenset()


def test_sibling_keyword_wins_over_ref_target() -> None:
    """A keyword written next to `$ref` overrides the target's, per 2020-12 semantics."""
    flat = _flatten(
        {
            "$defs": {"named": {"type": "string", "description": "Target."}},
            "$ref": "#/$defs/named",
            "description": "Sibling.",
        },
        resolve=True,
    )
    assert flat.description == "Sibling."


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------


def _warnings(data: object, *, resolve: bool = False) -> list[str]:
    schema = _parse(data)
    resolver = None
    if resolve:
        doc = JsonSchemaRawDoc(
            doc_id=_SOURCE_ID, content=orjson.dumps(data), media_type=MediaTypes.json
        )
        parsed = _PARSER.apply(doc)
        assert isinstance(parsed, Ok)
        resolver = JsonSchemaRefResolver()
        resolver.register(parsed.value)
    result = SchemaFlattener(resolver=resolver).flatten(schema, base_uri=_SOURCE_ID)
    return [w.code for w in result.warnings if w.code]


def test_conflicting_property_warns_and_keeps_first() -> None:
    data = {
        "allOf": [
            {"type": "object", "properties": {"a": {"type": "string"}}},
            {"type": "object", "properties": {"a": {"type": "integer"}}},
        ]
    }
    assert "conflicting-property" in _warnings(data)
    props = _flatten(data).properties or {}
    a = props["a"]
    assert isinstance(a, ObjectSchema)
    assert a.get_types() == frozenset({JsonSchemaType.STRING})


def test_identical_property_in_two_branches_does_not_warn() -> None:
    data = {
        "allOf": [
            {"type": "object", "properties": {"a": {"type": "string"}}},
            {"type": "object", "properties": {"a": {"type": "string"}}},
        ]
    }
    assert "conflicting-property" not in _warnings(data)


def test_false_branch_warns() -> None:
    assert "unsatisfiable-branch" in _warnings({"type": "object", "allOf": [False]})


def test_unresolvable_ref_warns() -> None:
    assert "unresolved-ref" in _warnings({"$ref": "#/$defs/missing"}, resolve=True)


def test_recursive_ref_terminates() -> None:
    """A self-referential schema stops instead of recursing forever."""
    data = {"$defs": {"node": {"type": "object", "allOf": [{"$ref": "#/$defs/node"}]}}}
    schema = _parse(data)
    doc = JsonSchemaRawDoc(
        doc_id=_SOURCE_ID, content=orjson.dumps(data), media_type=MediaTypes.json
    )
    parsed = _PARSER.apply(doc)
    assert isinstance(parsed, Ok)
    resolver = JsonSchemaRefResolver()
    resolver.register(parsed.value)
    defs = schema.get_defs()
    result = SchemaFlattener(resolver=resolver).flatten(defs["node"], base_uri=_SOURCE_ID)
    assert "recursive-ref" in [w.code for w in result.warnings]


def test_all_of_root_is_an_object_schema_once_flattened() -> None:
    """`is_object_schema` is a syntactic check, so flattening has to come first."""
    flat = _flatten({"allOf": [{"type": "object", "properties": {"a": {"type": "string"}}}]})
    assert is_object_schema(flat)
