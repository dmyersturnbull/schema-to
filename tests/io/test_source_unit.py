"""Walking a directory of schema-map files into `SchemaMapRawDoc`s."""

from pathlib import Path

import pytest
from tests.support.trees import write

from schema_to.io.file import SchemaMapDirectorySource
from schema_to.io.os_errors import TypedNotADirectoryError
from schema_to.io.source import SchemaMapRawDoc


def test_directory_source_yields_one_doc_per_file(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", "thing:\n  type: object\n")
    write(tmp_path, "nested/b.yaml", "other:\n  type: string\n")
    docs = list(SchemaMapDirectorySource(tmp_path).documents())
    assert [d.display_name for d in docs] == ["a", "b"]
    assert all(isinstance(d, SchemaMapRawDoc) for d in docs)


def test_directory_source_skips_unrecognised_suffixes(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", "thing:\n  type: object\n")
    write(tmp_path, "README.md", "not a schema")
    assert len(list(SchemaMapDirectorySource(tmp_path).documents())) == 1


def test_directory_source_honours_exclude(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", "thing:\n  type: object\n")
    write(tmp_path, "skip.yaml", "other:\n  type: string\n")
    source = SchemaMapDirectorySource(tmp_path, exclude=frozenset({"skip.yaml"}))
    assert [d.display_name for d in source.documents()] == ["a"]


def test_directory_source_can_stay_shallow(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", "thing:\n  type: object\n")
    write(tmp_path, "nested/b.yaml", "other:\n  type: string\n")
    source = SchemaMapDirectorySource(tmp_path, recursive=False)
    assert [d.display_name for d in source.documents()] == ["a"]


def test_directory_source_rejects_a_non_directory(tmp_path: Path) -> None:
    path = write(tmp_path, "a.yaml", "thing:\n  type: object\n")
    with pytest.raises(TypedNotADirectoryError):
        SchemaMapDirectorySource(path)
