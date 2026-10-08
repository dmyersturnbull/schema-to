"""Expanding a schema-map document into one virtual document per named schema.

Each expanded document keeps a `$ref` to its siblings resolvable,
and has a `uri` that names both the file it came from and the schema inside it.
"""

from dataclasses import replace

from tests.support.asserts import ok
from tests.support.docs import json_schema_doc, schema_map_doc
from tests.support.drive import PYDANTIC, Route

from schema_to.core import Range, SourceRef
from schema_to.io.media_type import MediaTypes
from schema_to.io.source import JsonSchemaRawDoc, SchemaMapRawDoc
from schema_to.parse.json_schema import JsonSchemaParser
from schema_to.result import Err, Ok
from schema_to.transpile.schema_map import SchemaMapExpander

RANGE = Range.covering('{"bad": 1}')
_PYDANTIC_MAP = Route("pydantic", SchemaMapRawDoc, schema_map=True)


def test_expanded_document_uris_name_the_file_and_the_schema() -> None:
    """The URI is unique, and the display name is the schema's, not the file's."""
    doc = schema_map_doc({"a-data": {"type": "object"}}, "catalog")
    expanded = SchemaMapExpander().apply(doc)
    assert isinstance(expanded, Ok)
    [virtual] = expanded.value
    assert virtual.uri == "file:///catalog.yaml#/a-data"
    assert virtual.display_name == "a-data"


def test_an_expanded_document_remembers_where_it_came_from() -> None:
    """A diagnostic names the file the user wrote, not the virtual URI that exists nowhere."""
    doc = schema_map_doc({"a/b": {"type": "object"}}, "catalog")
    expanded = SchemaMapExpander().apply(doc)
    assert isinstance(expanded, Ok)
    [virtual] = expanded.value
    assert virtual.origin == SourceRef("file:///catalog.yaml", "/a~1b", virtual.origin.range)
    where = virtual.ref("/properties/x")
    assert (where.uri, where.json_pointer) == ("file:///catalog.yaml", "/a~1b/properties/x")
    assert virtual.display_name == "a/b"


def test_parsing_a_derived_document_points_the_cst_into_the_original() -> None:
    """A node in a derived document has the original's URI and pointer in its `source_ref`."""
    derived = JsonSchemaRawDoc(
        uri="file:///catalog.yaml#/bad",
        content=b'{"type": "nonsense"}',
        media_type=MediaTypes.json,
        origin=SourceRef("file:///catalog.yaml", "/bad", RANGE),
    )
    failed = JsonSchemaParser().apply(derived)
    assert isinstance(failed, Err)
    assert failed.errors[0].location == SourceRef("file:///catalog.yaml", "/bad/type", RANGE)

    parsed = ok(JsonSchemaParser().apply(replace(derived, content=b'{"type": "object"}')))
    assert parsed.source_id == "file:///catalog.yaml#/bad"
    assert parsed.root.source_ref == SourceRef("file:///catalog.yaml", "/bad", RANGE)


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
    doc = json_schema_doc({"type": "object"}, "test:///thing")
    result = PYDANTIC.run(doc)
    assert isinstance(result, Ok)
    assert [a.artifact_id for a in result.value] == ["thing.py"]


def test_several_documents_are_named_apart() -> None:
    """They would otherwise overwrite one another in the sink."""
    docs = [json_schema_doc({"type": "object"}, f"test:///{n}") for n in ("thing-one", "thing-two")]
    result = PYDANTIC.run(*docs)
    assert isinstance(result, Ok)
    assert [a.artifact_id for a in result.value] == ["thing_one.py", "thing_two.py"]
