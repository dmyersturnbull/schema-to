"""Expanding a schema-map document into one virtual document per named schema.

Each expanded document keeps a `$ref` to its siblings resolvable,
and carries a `doc_id` that names both the file it came from and the schema inside it.
"""

from dataclasses import replace

from tests.support.docs import json_schema_doc, schema_map_doc
from tests.support.drive import PYDANTIC, Route

from schema_to.io.source import SchemaMapRawDoc
from schema_to.result import Ok
from schema_to.transpile.schema_map import SchemaMapExpander

_PYDANTIC_MAP = Route("pydantic", SchemaMapRawDoc, schema_map=True)


def test_expanded_document_ids_name_the_file_and_the_schema() -> None:
    """A diagnostic should be able to say which file *and* which schema."""
    doc = schema_map_doc({"a-data": {"type": "object"}}, "catalog")
    expanded = SchemaMapExpander().apply(doc)
    assert isinstance(expanded, Ok)
    [virtual] = expanded.value
    assert virtual.doc_id == "file:///catalog.yaml#/a-data"
    assert virtual.base_uri == "file:///catalog.yaml"
    assert virtual.display_name == "a-data"


def test_sibling_refs_resolve_after_expansion() -> None:
    """`#/other` means the sibling in the *file*, which splitting would otherwise break."""
    doc = schema_map_doc(
        {
            "stamp": {"type": "string", "pattern": "^2"},
            "thing": {"type": "object", "properties": {"at": {"$ref": "#/stamp"}}},
        },
        "catalog",
    )
    result = _PYDANTIC_MAP.run(doc)
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    assert {a.artifact_id for a in result.value} == {"stamp.py", "thing.py"}


def test_roots_expands_only_named_schemas_but_siblings_still_resolve() -> None:
    """`roots` narrows which named schemas become artifacts, not which ones can be $ref'd."""
    doc = schema_map_doc(
        {
            "stamp": {"type": "string", "pattern": "^2"},
            "thing": {"type": "object", "properties": {"at": {"$ref": "#/stamp"}}},
        },
        "catalog",
    )
    result = replace(_PYDANTIC_MAP, roots=frozenset({"thing"})).run(doc)
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    # `stamp` was filtered out, so only `thing` becomes a virtual document — and so
    # only its module is written, even though `stamp` still resolved.
    assert {a.artifact_id for a in result.value} == {"thing.py"}


def test_expansion_without_a_resolver_seeds_nothing() -> None:
    """A target that never follows a `$ref` is given no resolver, and needs none."""
    doc = schema_map_doc({"a": {"type": "object"}}, "catalog")
    assert isinstance(SchemaMapExpander().apply(doc), Ok)


def test_a_module_is_named_after_its_document() -> None:
    doc = json_schema_doc({"type": "object"}, "test://a", display_name="thing")
    result = PYDANTIC.run(doc)
    assert isinstance(result, Ok)
    assert [a.artifact_id for a in result.value] == ["thing.py"]


def test_several_documents_are_named_apart() -> None:
    """They would otherwise overwrite one another in the sink."""
    docs = [
        json_schema_doc({"type": "object"}, f"test://{n}", display_name=n)
        for n in ("thing-one", "thing-two")
    ]
    result = PYDANTIC.run(*docs)
    assert isinstance(result, Ok)
    assert [a.artifact_id for a in result.value] == ["thing_one.py", "thing_two.py"]
