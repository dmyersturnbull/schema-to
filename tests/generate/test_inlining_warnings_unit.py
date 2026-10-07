"""What flattening warns about rather than failing on.

Two branches that set the same keyword to different values lose one of them, so the flattener says so.
Branches that agree, and siblings that deliberately override a `$ref` target, do not warn.
"""

import orjson
from tests.support.docs import DEFAULT_SCHEMA_URI
from tests.support.stages import flat_schema, flatten_warnings, json_schema_cst, object_schema
from tests.support.types import JsonLike

from schema_to.cst.json_schema import (
    JsonSchemaMapDocument,
    JsonSchemaType,
    ObjectSchema,
    is_object_schema,
)
from schema_to.generate.inlining import SchemaFlattener
from schema_to.io.media_type import MediaTypes
from schema_to.io.source import SchemaMapRawDoc
from schema_to.parse.json_schema import JsonSchemaMapParser
from schema_to.resolve.json_schema import JsonSchemaRefResolver
from schema_to.result import Ok


def _parse_map(data: JsonLike, uri: str) -> JsonSchemaMapDocument:
    doc = SchemaMapRawDoc(uri=uri, content=orjson.dumps(data), media_type=MediaTypes.json)
    result = JsonSchemaMapParser().apply(doc)
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    return result.value


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------


def test_conflicting_property_warns_and_keeps_first() -> None:
    data = {
        "allOf": [
            {"type": "object", "properties": {"a": {"type": "string"}}},
            {"type": "object", "properties": {"a": {"type": "integer"}}},
        ]
    }
    assert "conflicting-property" in flatten_warnings(data)
    props = flat_schema(data).properties or {}
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
    assert "conflicting-property" not in flatten_warnings(data)


def test_false_branch_warns() -> None:
    assert "unsatisfiable-branch" in flatten_warnings({"type": "object", "allOf": [False]})


def test_unresolvable_ref_warns() -> None:
    assert "unresolved-ref" in flatten_warnings({"$ref": "#/$defs/missing"}, resolve=True)


def test_recursive_ref_terminates() -> None:
    """A self-referential schema stops instead of recursing forever."""
    data = {"$defs": {"node": {"type": "object", "allOf": [{"$ref": "#/$defs/node"}]}}}
    resolver = JsonSchemaRefResolver()
    resolver.register(json_schema_cst(data, DEFAULT_SCHEMA_URI))
    node = object_schema(data).get_defs()["node"]
    result = SchemaFlattener(resolver=resolver).flatten(node, base_uri=DEFAULT_SCHEMA_URI)
    assert "recursive-ref" in [w.code for w in result.warnings]


def test_all_of_root_is_an_object_schema_once_flattened() -> None:
    """`is_object_schema` is a syntactic check, so flattening has to come first."""
    flat = flat_schema({"allOf": [{"type": "object", "properties": {"a": {"type": "string"}}}]})
    assert is_object_schema(flat)


def test_ref_target_resolves_its_own_refs_against_its_own_document() -> None:
    """A chained ref: `main` -> `base#/outer` -> `base#/inner`, all from `main`'s view.

    `#/inner` is written in `base`, so it means `base`'s `inner` — not `main`'s.
    Getting this wrong silently degraded the column to jsonb rather than failing.
    """
    base = _parse_map(
        {"inner": {"type": "string", "pattern": "^x"}, "outer": {"$ref": "#/inner"}},
        "file:///base.yaml",
    )
    main = _parse_map({"thing": {"$ref": "./base.yaml#/outer"}}, "file:///main.yaml")
    resolver = JsonSchemaRefResolver()
    resolver.register_map(base)
    resolver.register_map(main)
    result = SchemaFlattener(resolver=resolver).flatten(
        main.schemas["thing"], base_uri="file:///main.yaml"
    )
    assert [w.code for w in result.warnings] == []
    assert isinstance(result.schema, ObjectSchema)
    assert result.schema.get_types() == frozenset({JsonSchemaType.STRING})
    assert result.schema.pattern == "^x"


def test_sibling_overriding_a_ref_target_does_not_warn() -> None:
    """2020-12 makes siblings override the target; narrowing in place is the idiom."""
    data = {
        "$defs": {"stamp": {"type": "string", "description": "A timestamp."}},
        "$ref": "#/$defs/stamp",
        "description": "When the resource was last modified.",
    }
    assert "conflicting-keyword" not in flatten_warnings(data, resolve=True)


def test_conflicting_constraints_across_all_of_branches_warn() -> None:
    """Only one `pattern` survives the merge, so the other is silently unenforced."""
    data = {"allOf": [{"type": "string", "pattern": "^a"}, {"type": "string", "pattern": "^b"}]}
    assert "conflicting-keyword" in flatten_warnings(data)


def test_conflicting_descriptions_do_not_warn() -> None:
    """A wrapper describing itself and `allOf`-ing a described definition is the norm."""
    data = {
        "description": "The resource.",
        "allOf": [{"type": "object", "description": "The hashable content."}],
    }
    assert "conflicting-keyword" not in flatten_warnings(data)


def test_identical_schema_valued_keyword_across_branches_does_not_warn() -> None:
    """`items`/`propertyNames`/etc. carry a `source_ref`.

    So two branches spelling out the same constraint must compare by content,
    not by where each was written.
    """
    pattern = {"type": "string", "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$"}
    data = {"propertyNames": pattern, "allOf": [{"type": "object", "propertyNames": dict(pattern)}]}
    assert "conflicting-keyword" not in flatten_warnings(data)


def test_differing_schema_valued_keyword_across_branches_warns() -> None:
    """A real difference in a schema-valued keyword still has to warn."""
    data = {
        "propertyNames": {"type": "string", "pattern": "^a"},
        "allOf": [{"type": "object", "propertyNames": {"type": "string", "pattern": "^b"}}],
    }
    assert "conflicting-keyword" in flatten_warnings(data)
