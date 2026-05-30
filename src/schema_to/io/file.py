"""Filesystem-backed `DataSource` and `DataSink` implementations."""

from __future__ import annotations

import glob
from dataclasses import KW_ONLY, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from schema_to.io.media_type import MediaTypes
from schema_to.io.os_errors import PathMissingError, TypedNotADirectoryError
from schema_to.io.routing import peek_is_openapi
from schema_to.io.sink import Artifact, DataSink
from schema_to.io.source import DataSource, JsonSchemaRawDoc, OpenApiRawDoc, RawDoc

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from schema_to.io.media_type import MediaType

__all__ = ["DirectoryDataSource", "FileDataSink", "FileDataSource", "FileDataSourceFactory"]


@dataclass(frozen=True, slots=True)
class FileDataSource(DataSource):
    """A `DataSource` backed by a single file on the local filesystem.

    Attributes:
        path: Absolute or relative path to the file.
    """

    path: Path
    media_type: MediaType = field(init=False, hash=False, repr=False)

    def __post_init__(self) -> None:
        if not self.path.is_file():
            raise PathMissingError(filename=self.path)
        object.__setattr__(self, "media_type", MediaTypes.from_input_suffix(self.path.suffix))

    @property
    def source_id(self) -> str:
        return self.path.as_uri()

    def documents(self) -> Iterator[RawDoc]:
        content = self.path.read_bytes()
        doc_cls: type[RawDoc] = (
            OpenApiRawDoc if peek_is_openapi(content, self.media_type) else JsonSchemaRawDoc
        )
        yield doc_cls(
            source_id=self.path.as_uri(),
            content=content,
            media_type=self.media_type,
            display_name=self.path.stem,
            base_uri=self.path.as_uri(),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class FileDataSourceFactory[I: RawDoc]:
    recursive: bool

    def get(self, paths: Sequence[Path]) -> Sequence[DataSource[I]]:
        return list(self._get(paths))

    def _get(self, paths: Sequence[Path]) -> Iterator[DataSource[I]]:
        for p in paths:
            if p.is_dir():
                yield DirectoryDataSource(p, recursive=self.recursive)
            elif p.is_file():
                yield FileDataSource(p)


@dataclass(frozen=True, slots=True)
class DirectoryDataSource(DataSource):
    """A `DataSource` that yields all files matching globs patterns under a directory.

    Files whose extension maps to no known media type are silently skipped,
    so a directory can contain a mix of schema files and unrelated assets.

    Attributes:
        root: Path to the directory.
        recursive: Whether to look in subdirectories.
        include_hidden: Whether to look in dotted directories.
    """

    root: Path
    _: KW_ONLY
    recursive: bool
    include_hidden: bool = False
    paths: frozenset[Path] = field(init=False, hash=False, repr=False)

    def __post_init__(self) -> None:
        if not self.root.is_dir():
            raise TypedNotADirectoryError(filename=self.root)
        setattr(self, "paths", frozenset(sorted(self.__expand_sources())))  # noqa: B010 # workaround to allow `slos=True`

    def __expand_sources(self) -> Iterator[Path]:
        # ruff: noqa: PTH207 # `glob.glob` skips hidden dirs (including `.git/`).
        for suffix in MediaTypes.input_suffixes:
            for path in glob.glob(
                f"**/*{suffix}" if self.recursive else f"*{suffix}",
                root_dir=str(self.root),
                recursive=True,  # True just means that `**` works.
                include_hidden=self.include_hidden,
            ):
                if (p := Path(path)).is_file():
                    yield p

    @property
    def source_id(self) -> str:
        return self.root.as_uri()

    def documents(self) -> Iterator[RawDoc]:
        for path in self.paths:
            media_type = MediaTypes.from_input_suffix(path.suffix)
            content = path.read_bytes()
            doc_cls: type[RawDoc] = (
                OpenApiRawDoc if peek_is_openapi(content, media_type) else JsonSchemaRawDoc
            )
            yield doc_cls(
                source_id=path.as_uri(),
                content=content,
                media_type=media_type,
                display_name=path.stem,
                base_uri=path.as_uri(),
            )


@dataclass(frozen=True, slots=True)
class FileDataSink[O: Artifact](DataSink[O]):
    """A `DataSink` that writes each `Artifact` as a file under a root directory.

    `artifact.artifact_id` is treated as a relative path from `root`.  Parent
    directories are created automatically when `create_dirs` is `True`.

    Attributes:
        root: Base directory for all written files.
    """

    root: Path

    @property
    def sink_id(self) -> str:
        return self.root.as_uri()

    def write(self, artifact: O) -> None:
        dest = self.root / artifact.artifact_id
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(artifact.content)
