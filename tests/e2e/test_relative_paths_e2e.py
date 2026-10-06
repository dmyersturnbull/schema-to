"""Whole runs over input paths given relative to the working directory, as a person types them.

A relative `$ref` is resolved against the file that contains it, never against the working directory,
so every run here must give the same answer from wherever it starts.
"""

from collections.abc import Sequence
from pathlib import Path

import pytest
from tests.support.trees import write, write_all

from schema_to.io.file import FileDataSourceFactory, SchemaMapDirectorySource
from schema_to.io.media_type import MediaTypes
from schema_to.io.memory import InMemoryDataSink
from schema_to.io.sink import Artifact
from schema_to.pipeline import Pipeline, ProcessSummary
from schema_to.result import Err, Ok, Result
from schema_to.transpile.std_router import SupportedTarget, TranspilerRouter

# `a` sorts before the file it refers to, so a run that resolved each file as it read it would fail.
_SCHEMAS = {
    "in/a.schema.json": (
        '{"title": "A", "type": "object", "properties": {'
        '"b": {"$ref": "sub/b.schema.json"}, '
        '"c": {"$ref": "./sub/b.schema.json#/$defs/C"}}}'
    ),
    "in/sub/b.schema.json": (
        '{"title": "B", "type": "object", "properties": {"x": {"type": "string"}}, '
        '"$defs": {"C": {"type": "integer"}}}'
    ),
}

_MAPS = {
    "in/base/time.yaml": "timestamp:\n  type: string\n",
    "in/main/catalog.yaml": (
        "thing:\n"
        "  type: object\n"
        "  properties:\n"
        "    t:\n"
        "      $ref: '../base/time.yaml#/timestamp'\n"
        "    o:\n"
        "      $ref: '#/other'\n"
        "other:\n"
        "  type: string\n"
    ),
}

# Where to run from, and how the input directory is named from there.
_PLACES = [(".", "in"), ("in", "."), ("in/sub", ".."), ("elsewhere", "../in")]


def _run(
    paths: Sequence[Path], target: SupportedTarget, *, schema_map: bool
) -> Result[ProcessSummary]:
    transpilers = TranspilerRouter().route(target, MediaTypes.json, schema_map=schema_map)
    if schema_map:
        sources = [SchemaMapDirectorySource(p, recursive=True) for p in paths]
    else:
        sources = FileDataSourceFactory(recursive=True).get(paths)
    sink: InMemoryDataSink[Artifact] = InMemoryDataSink()
    return Pipeline(sources=sources, transpilers=transpilers, sink=sink).process()


@pytest.mark.parametrize(("cwd", "input_dir"), _PLACES)
@pytest.mark.parametrize("target", [SupportedTarget.PYDANTIC, SupportedTarget.POSTGRES])
def test_refs_across_files_resolve_from_any_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cwd: str,
    input_dir: str,
    target: SupportedTarget,
) -> None:
    write_all(tmp_path, _SCHEMAS)
    (tmp_path / cwd).mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path / cwd)
    result = _run([Path(input_dir)], target, schema_map=False)
    assert isinstance(result, Ok), [str(e) for e in result.errors]
    assert len(result.value.docs_used) == 2


@pytest.mark.parametrize(("cwd", "input_dir"), _PLACES)
@pytest.mark.parametrize(
    "target", [SupportedTarget.PYDANTIC, SupportedTarget.POSTGRES, SupportedTarget.PASS_THRU]
)
def test_schema_map_refs_resolve_from_any_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cwd: str,
    input_dir: str,
    target: SupportedTarget,
) -> None:
    write_all(tmp_path, _MAPS)
    (tmp_path / cwd).mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path / cwd)
    result = _run([Path(input_dir)], target, schema_map=True)
    assert isinstance(result, Ok), [str(e) for e in result.errors]


def test_relative_files_named_one_by_one_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_all(tmp_path, _SCHEMAS)
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")
    paths = [Path("../in/a.schema.json"), Path("../in/sub/b.schema.json")]
    assert isinstance(_run(paths, SupportedTarget.PYDANTIC, schema_map=False), Ok)


def test_an_unresolvable_ref_is_reported_at_its_line_and_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(
        tmp_path,
        "in/main/catalog.yaml",
        "thing:\n  type: object\n  properties:\n    t:\n      $ref: '../base/nope.yaml#/x'\n",
    )
    monkeypatch.chdir(tmp_path)
    result = _run([Path("in")], SupportedTarget.PYDANTIC, schema_map=True)
    assert isinstance(result, Err)
    [error] = result.errors
    assert error.location is not None
    assert (error.location.line, error.location.column) == (4, 5)
    assert "not among the inputs" in error.message
