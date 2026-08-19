"""Tests for schema-map documents: files holding several named schemas at the top level.

Covers:

- Targeted: each named schema is parsed at its own pointer.
- Targeted: a non-object root, and a malformed entry, are reported as errors.
- Targeted: the resolver indexes entries at `/name` and resolves refs across files.
- Targeted: the directory source yields one `SchemaMapRawDoc` per file.
- Integration: a two-file tree resolves a relative cross-file `$ref` and flattens.
"""

from pathlib import Path

import orjson
import pytest

from schema_to.cst.json_schema import JsonSchemaMapDocument, JsonSchemaType, ObjectSchema
from schema_to.io.file import SchemaMapDirectorySource
from schema_to.io.media_type import MediaTypes
from schema_to.io.os_errors import TypedNotADirectoryError
from schema_to.io.source import SchemaMapRawDoc
from schema_to.parse.json_schema import JsonSchemaMapParser
from schema_to.resolve.json_schema import JsonSchemaRefResolver
from schema_to.result import Err, Ok

_PARSER = JsonSchemaMapParser()


def _doc(data: object, doc_id: str = "test://catalog") -> SchemaMapRawDoc:
    return SchemaMapRawDoc(
        doc_id=doc_id,
        content=orjson.dumps(data),
        media_type=MediaTypes.json,
        display_name="catalog",
    )


def _parse(data: object, doc_id: str = "test://catalog") -> JsonSchemaMapDocument:
    result = _PARSER.apply(_doc(data, doc_id))
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
    result = _PARSER.apply(_doc([{"type": "object"}]))
    assert isinstance(result, Err)
    assert "object mapping names to schemas" in result.errors[0].message


def test_malformed_entry_is_an_error() -> None:
    result = _PARSER.apply(_doc({"thing": "not a schema"}))
    assert isinstance(result, Err)


def test_errors_accumulate_across_entries() -> None:
    result = _PARSER.apply(_doc({"a": "bad", "b": "also bad"}))
    assert isinstance(result, Err)
    assert len(result.errors) == 2


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_resolver_indexes_entries_by_pointer() -> None:
    doc = _parse({"thing": {"type": "object"}})
    resolver = JsonSchemaRefResolver()
    resolver.register_map(doc)
    found = resolver.lookup("#/thing", base_uri="test://catalog")
    assert isinstance(found, ObjectSchema)
    assert found.get_types() == frozenset({JsonSchemaType.OBJECT})


def test_registered_source_ids_includes_map_documents() -> None:
    resolver = JsonSchemaRefResolver()
    resolver.register_map(_parse({"thing": {"type": "object"}}))
    assert resolver.registered_source_ids() == frozenset({"test://catalog"})


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
    base = _parse({"timestamp": {"type": "string", "pattern": "^2"}}, "file:///base.yaml")
    main = _parse({"thing": {"$ref": "./base.yaml#/timestamp"}}, "file:///main.yaml")
    resolver = JsonSchemaRefResolver()
    resolver.register_map(base)
    resolver.register_map(main)
    assert isinstance(resolver.apply_map(main), Ok)
    found = resolver.lookup("./base.yaml#/timestamp", base_uri="file:///main.yaml")
    assert isinstance(found, ObjectSchema)
    assert found.pattern == "^2"


# ---------------------------------------------------------------------------
# Directory source
# ---------------------------------------------------------------------------


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_directory_source_yields_one_doc_per_file(tmp_path: Path) -> None:
    _write(tmp_path, "a.yaml", "thing:\n  type: object\n")
    _write(tmp_path, "nested/b.yaml", "other:\n  type: string\n")
    docs = list(SchemaMapDirectorySource(tmp_path).documents())
    assert [d.display_name for d in docs] == ["a", "b"]
    assert all(isinstance(d, SchemaMapRawDoc) for d in docs)


def test_directory_source_skips_unrecognised_suffixes(tmp_path: Path) -> None:
    _write(tmp_path, "a.yaml", "thing:\n  type: object\n")
    _write(tmp_path, "README.md", "not a schema")
    assert len(list(SchemaMapDirectorySource(tmp_path).documents())) == 1


def test_directory_source_honours_exclude(tmp_path: Path) -> None:
    _write(tmp_path, "a.yaml", "thing:\n  type: object\n")
    _write(tmp_path, "skip.yaml", "other:\n  type: string\n")
    source = SchemaMapDirectorySource(tmp_path, exclude=frozenset({"skip.yaml"}))
    assert [d.display_name for d in source.documents()] == ["a"]


def test_directory_source_can_stay_shallow(tmp_path: Path) -> None:
    _write(tmp_path, "a.yaml", "thing:\n  type: object\n")
    _write(tmp_path, "nested/b.yaml", "other:\n  type: string\n")
    source = SchemaMapDirectorySource(tmp_path, recursive=False)
    assert [d.display_name for d in source.documents()] == ["a"]


def test_directory_source_rejects_a_non_directory(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.yaml", "thing:\n  type: object\n")
    with pytest.raises(TypedNotADirectoryError):
        SchemaMapDirectorySource(path)
