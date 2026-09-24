"""Parsing and resolving a document whose root maps names to schemas.

Each entry is parsed at its own pointer (i.e. `/thing`, not `/$defs/thing`)
because that is where a sibling file's `$ref` points.
"""

from tests.support.docs import schema_map_doc
from tests.support.types import JsonLike

from schema_to.cst.json_schema import JsonSchemaMapDocument, JsonSchemaType, ObjectSchema
from schema_to.parse.json_schema import JsonSchemaMapParser
from schema_to.resolve.json_schema import JsonSchemaRefResolver
from schema_to.result import Err, Ok

_PARSER = JsonSchemaMapParser()


def _parse(data: JsonLike, name: str = "catalog") -> JsonSchemaMapDocument:
    result = _PARSER.apply(schema_map_doc(data, name))
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    return result.value


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_each_entry_becomes_a_named_schema() -> None:
    doc = _parse({"thing": {"type": "object"}, "other": {"type": "string"}})
    assert set(doc.schemas) == {"thing", "other"}


def test_entries_keep_document_order() -> None:
    doc = _parse({"c": {"type": "string"}, "a": {"type": "string"}, "b": {"type": "string"}})
    assert list(doc.schemas) == ["c", "a", "b"]


def test_entry_is_parsed_at_its_own_pointer() -> None:
    """`/thing`, not `/$defs/thing` — that is where a sibling file's `$ref` points."""
    doc = _parse({"thing": {"type": "object"}})
    schema = doc.schemas["thing"]
    assert schema.source_ref is not None
    assert schema.source_ref.json_pointer == "/thing"


def test_get_schema_returns_none_for_unknown_name() -> None:
    assert _parse({"thing": {"type": "object"}}).get_schema("nope") is None


def test_non_object_root_is_an_error() -> None:
    result = _PARSER.apply(schema_map_doc([{"type": "object"}]))
    assert isinstance(result, Err)
    assert "object mapping names to schemas" in result.errors[0].message


def test_malformed_entry_is_an_error() -> None:
    result = _PARSER.apply(schema_map_doc({"thing": "not a schema"}))
    assert isinstance(result, Err)


def test_errors_accumulate_across_entries() -> None:
    result = _PARSER.apply(schema_map_doc({"a": "bad", "b": "also bad"}))
    assert isinstance(result, Err)
    assert len(result.errors) == 2


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_resolver_indexes_entries_by_pointer() -> None:
    doc = _parse({"thing": {"type": "object"}})
    resolver = JsonSchemaRefResolver()
    resolver.register_map(doc)
    found = resolver.lookup("#/thing", base_uri="file:///catalog.yaml")
    assert isinstance(found, ObjectSchema)
    assert found.get_types() == frozenset({JsonSchemaType.OBJECT})


def test_registered_source_ids_includes_map_documents() -> None:
    resolver = JsonSchemaRefResolver()
    resolver.register_map(_parse({"thing": {"type": "object"}}))
    assert resolver.registered_source_ids() == frozenset({"file:///catalog.yaml"})


def test_apply_map_accepts_resolvable_refs() -> None:
    doc = _parse({"named": {"type": "string"}, "user": {"$ref": "#/named"}})
    resolver = JsonSchemaRefResolver()
    assert isinstance(resolver.apply_map(doc), Ok)


def test_apply_map_reports_unresolvable_refs() -> None:
    doc = _parse({"user": {"$ref": "#/missing"}})
    resolver = JsonSchemaRefResolver()
    result = resolver.apply_map(doc)
    assert isinstance(result, Err)
    assert "missing" in result.errors[0].message


def test_ref_resolves_across_two_map_documents() -> None:
    base = _parse({"timestamp": {"type": "string", "pattern": "^2"}}, "base")
    main = _parse({"thing": {"$ref": "./base.yaml#/timestamp"}}, "main")
    resolver = JsonSchemaRefResolver()
    resolver.register_map(base)
    resolver.register_map(main)
    assert isinstance(resolver.apply_map(main), Ok)
    found = resolver.lookup("./base.yaml#/timestamp", base_uri="file:///main.yaml")
    assert isinstance(found, ObjectSchema)
    assert found.pattern == "^2"
