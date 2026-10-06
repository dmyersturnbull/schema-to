"""Reading documents off disk: one file, a directory tree, and the factory that picks between them.

A file's compound extension (e.g. `.schema.json`, `.openapi.yaml`)
says which `RawDoc` subclass it becomes and which media type it carries.
"""

from pathlib import Path

import pytest
from tests.support.trees import write

from schema_to.io.file import (
    DirectoryDataSource,
    FileDataSource,
    FileDataSourceFactory,
    PeekingDirectorySource,
)
from schema_to.io.media_type import MediaTypes
from schema_to.io.os_errors import PathMissingError, TypedNotADirectoryError
from schema_to.io.source import JsonSchemaRawDoc, OpenApiRawDoc

_SCHEMA = '{"type": "object"}'
_OPENAPI = '{"openapi": "3.1.0", "info": {"title": "T", "version": "1"}}'


def test_a_single_file_becomes_one_document(tmp_path: Path) -> None:
    path = write(tmp_path, "thing.schema.json", _SCHEMA)
    source = FileDataSource(path, JsonSchemaRawDoc, MediaTypes.json_schema)
    [doc] = source.documents()
    assert doc.doc_id == path.as_uri()
    assert doc.base_uri == path.as_uri()
    assert doc.content == _SCHEMA.encode()


def test_the_display_name_drops_the_whole_compound_extension(tmp_path: Path) -> None:
    """`thing.schema.json` is the `thing` schema, not the `thing.schema` one."""
    path = write(tmp_path, "thing.schema.json", _SCHEMA)
    [doc] = FileDataSource(path, JsonSchemaRawDoc, MediaTypes.json_schema).documents()
    assert doc.display_name == "thing"


def test_a_single_extension_keeps_its_stem(tmp_path: Path) -> None:
    path = write(tmp_path, "thing.json", _SCHEMA)
    [doc] = FileDataSource(path, JsonSchemaRawDoc, MediaTypes.json).documents()
    assert doc.display_name == "thing"


def test_the_source_id_is_the_file_uri(tmp_path: Path) -> None:
    path = write(tmp_path, "thing.schema.json", _SCHEMA)
    source = FileDataSource(path, JsonSchemaRawDoc, MediaTypes.json_schema)
    assert source.source_id == path.as_uri()


def test_a_missing_file_says_so_when_read(tmp_path: Path) -> None:
    """The error waits for `documents()`, since constructing a source touches no disk."""
    source = FileDataSource(tmp_path / "nope.schema.json", JsonSchemaRawDoc, MediaTypes.json_schema)
    with pytest.raises(PathMissingError):
        list(source.documents())


def test_a_directory_yields_a_document_per_recognised_file(tmp_path: Path) -> None:
    write(tmp_path, "a.schema.json", _SCHEMA)
    write(tmp_path, "b.openapi.json", _OPENAPI)
    docs = list(DirectoryDataSource(tmp_path, recursive=False).documents())
    assert {d.display_name for d in docs} == {"a", "b"}


def test_the_extension_decides_the_document_class(tmp_path: Path) -> None:
    write(tmp_path, "a.schema.json", _SCHEMA)
    write(tmp_path, "b.openapi.yaml", "openapi: 3.1.0\ninfo: {}\n")
    by_name = {
        d.display_name: d for d in DirectoryDataSource(tmp_path, recursive=False).documents()
    }
    assert isinstance(by_name["a"], JsonSchemaRawDoc)
    assert isinstance(by_name["b"], OpenApiRawDoc)
    assert by_name["b"].media_type == MediaTypes.openapi_yaml


def test_an_unrecognised_extension_is_skipped(tmp_path: Path) -> None:
    """A schema directory may hold unrelated files, so an unknown name is not an error."""
    write(tmp_path, "a.schema.json", _SCHEMA)
    write(tmp_path, "notes.md", "# notes")
    write(tmp_path, "data.json", "{}")
    assert len(list(DirectoryDataSource(tmp_path, recursive=False).documents())) == 1


def test_a_shallow_source_ignores_subdirectories(tmp_path: Path) -> None:
    write(tmp_path, "a.schema.json", _SCHEMA)
    write(tmp_path, "nested/b.schema.json", _SCHEMA)
    docs = DirectoryDataSource(tmp_path, recursive=False).documents()
    assert [d.display_name for d in docs] == ["a"]


def test_a_recursive_source_walks_down(tmp_path: Path) -> None:
    write(tmp_path, "a.schema.json", _SCHEMA)
    write(tmp_path, "nested/deeper/b.schema.json", _SCHEMA)
    docs = DirectoryDataSource(tmp_path, recursive=True).documents()
    assert {d.display_name for d in docs} == {"a", "b"}


def test_hidden_directories_are_skipped_by_default(tmp_path: Path) -> None:
    """A `.git/` full of JSON is not a schema directory."""
    write(tmp_path, "a.schema.json", _SCHEMA)
    write(tmp_path, ".hidden/b.schema.json", _SCHEMA)
    docs = DirectoryDataSource(tmp_path, recursive=True).documents()
    assert [d.display_name for d in docs] == ["a"]


def test_hidden_directories_can_be_asked_for(tmp_path: Path) -> None:
    write(tmp_path, ".hidden/b.schema.json", _SCHEMA)
    source = DirectoryDataSource(tmp_path, recursive=True, include_hidden=True)
    assert [d.display_name for d in source.documents()] == ["b"]


def test_a_directory_source_over_a_file_is_an_error(tmp_path: Path) -> None:
    path = write(tmp_path, "a.schema.json", _SCHEMA)
    with pytest.raises(TypedNotADirectoryError):
        DirectoryDataSource(path, recursive=False)


def test_a_peeking_source_skips_a_file_whose_content_says_nothing(tmp_path: Path) -> None:
    """The extension is a hint; the content is the guard behind it."""
    write(tmp_path, "real.schema.json", _SCHEMA)
    write(tmp_path, "fake.schema.json", '{"host": "localhost"}')
    docs = PeekingDirectorySource(tmp_path, recursive=False).documents()
    assert [d.display_name for d in docs] == ["real"]


def test_the_factory_reads_a_file_as_a_file(tmp_path: Path) -> None:
    path = write(tmp_path, "a.schema.json", _SCHEMA)
    [source] = FileDataSourceFactory(recursive=False).get([path])
    assert isinstance(source, FileDataSource)


def test_the_factory_reads_a_directory_as_a_tree(tmp_path: Path) -> None:
    write(tmp_path, "a.schema.json", _SCHEMA)
    [source] = FileDataSourceFactory(recursive=True).get([tmp_path])
    assert isinstance(source, PeekingDirectorySource)


def test_the_factory_names_the_extensions_it_knows(tmp_path: Path) -> None:
    """An unusable path should say what would have worked."""
    path = write(tmp_path, "thing.txt", "x")
    with pytest.raises(ValueError, match=r"\.schema\.json") as caught:
        FileDataSourceFactory(recursive=False).get([path])
    assert "thing.txt" in str(caught.value)


def test_the_factory_skips_a_path_that_is_neither(tmp_path: Path) -> None:
    assert FileDataSourceFactory(recursive=False).get([tmp_path / "nope.schema.json"]) == []


def test_a_relative_file_path_gets_an_absolute_uri(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path, "thing.schema.json", _SCHEMA)
    monkeypatch.chdir(tmp_path)
    source = FileDataSource(Path("thing.schema.json"), JsonSchemaRawDoc, MediaTypes.json_schema)
    [doc] = source.documents()
    assert doc.doc_id == path.as_uri()
    assert doc.base_uri == path.as_uri()
    assert source.source_id == path.as_uri()


def test_dot_dot_segments_are_collapsed_in_the_uri(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise a relative `$ref` joined onto the URI would not match the referenced file's URI."""
    path = write(tmp_path, "a/thing.schema.json", _SCHEMA)
    write(tmp_path, "b/keep", "")
    monkeypatch.chdir(tmp_path / "b")
    source = FileDataSource(
        Path("../a/thing.schema.json"), JsonSchemaRawDoc, MediaTypes.json_schema
    )
    assert source.source_id == path.as_uri()


def test_symlinks_are_not_followed_in_the_uri(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path, "real/thing.schema.json", _SCHEMA)
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    monkeypatch.chdir(tmp_path)
    source = FileDataSource(
        Path("link/thing.schema.json"), JsonSchemaRawDoc, MediaTypes.json_schema
    )
    assert source.source_id == (tmp_path / "link" / "thing.schema.json").as_uri()


@pytest.mark.parametrize("relative", [".", "sub/..", "../{name}"])
def test_a_relative_directory_yields_absolute_document_uris(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    root = tmp_path / "in"
    path = write(root, "sub/a.schema.json", _SCHEMA)
    monkeypatch.chdir(root)
    rel = Path(relative.format(name=root.name))
    source = DirectoryDataSource(rel, recursive=True)
    [doc] = source.documents()
    assert doc.doc_id == path.as_uri()
    assert source.source_id == root.as_uri()


def test_the_factory_accepts_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path, "d/a.schema.json", _SCHEMA)
    monkeypatch.chdir(tmp_path)
    [source] = FileDataSourceFactory(recursive=True).get([Path("d")])
    [doc] = source.documents()
    assert doc.doc_id.startswith("file:///")
