"""Flattening `allOf` branches and `$ref` targets into one schema.

Properties and `required` union; a single-valued keyword takes the first branch that sets one.
A `$ref` is followed when a resolver is present and left in place otherwise.
"""

import orjson
from tests.support.stages import flat_schema
from tests.support.types import JsonLike

from schema_to.cst.json_schema import JsonSchemaMapDocument, JsonSchemaType
from schema_to.io.media_type import MediaTypes
from schema_to.io.source import SchemaMapRawDoc
from schema_to.parse.json_schema import JsonSchemaMapParser
from schema_to.result import Ok


def _parse_map(data: JsonLike, uri: str) -> JsonSchemaMapDocument:
    doc = SchemaMapRawDoc.original(uri, orjson.dumps(data), MediaTypes.json)
    result = JsonSchemaMapParser().apply(doc)
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    return result.value


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------


def test_all_of_merges_properties() -> None:
    flat = flat_schema(
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
    flat = flat_schema(
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
    flat = flat_schema(
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
    flat = flat_schema(
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
    flat = flat_schema({"type": "object", "allOf": [{"type": "object"}]})
    assert flat.get_types() == frozenset({JsonSchemaType.OBJECT})


def test_untyped_branch_does_not_constrain_type() -> None:
    """A branch with no `type` leaves the composed type alone."""
    flat = flat_schema({"allOf": [{"type": "object"}, {"properties": {"a": {"type": "string"}}}]})
    assert flat.get_types() == frozenset({JsonSchemaType.OBJECT})


def test_description_taken_from_first_branch_that_sets_one() -> None:
    flat = flat_schema({"allOf": [{"type": "object"}, {"description": "From the second branch."}]})
    assert flat.description == "From the second branch."


def test_own_description_wins_over_branch() -> None:
    flat = flat_schema({"description": "Mine.", "allOf": [{"description": "Theirs."}]})
    assert flat.description == "Mine."


def test_zero_minimum_is_not_treated_as_unset() -> None:
    """`0` is a real bound, even though `0 == False`."""
    flat = flat_schema({"minimum": 0, "allOf": [{"minimum": 5}]})
    assert flat.minimum == 0


def test_all_of_is_cleared_after_flattening() -> None:
    flat = flat_schema({"allOf": [{"type": "object"}]})
    assert flat.all_of is None


def test_nested_all_of_is_flattened() -> None:
    flat = flat_schema(
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
    flat = flat_schema(
        {"$defs": {"named": {"type": "string", "pattern": "^a+$"}}, "$ref": "#/$defs/named"},
        resolve=True,
    )
    assert flat.get_types() == frozenset({JsonSchemaType.STRING})
    assert flat.pattern == "^a+$"


def test_ref_in_all_of_branch_is_followed() -> None:
    flat = flat_schema(
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
    flat = flat_schema({"$defs": {"named": {"type": "string"}}, "$ref": "#/$defs/named"})
    assert flat.get_types() == frozenset()


def test_sibling_keyword_wins_over_ref_target() -> None:
    """A keyword written next to `$ref` overrides the target's, per 2020-12 semantics."""
    flat = flat_schema(
        {
            "$defs": {"named": {"type": "string", "description": "Target."}},
            "$ref": "#/$defs/named",
            "description": "Sibling.",
        },
        resolve=True,
    )
    assert flat.description == "Sibling."
