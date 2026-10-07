"""Filesystem-backed `DataSource` and `DataSink` implementations."""

import glob
import os
from collections.abc import Callable, Mapping, Set
from dataclasses import KW_ONLY, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from schema_to.io.media_type import MediaType, MediaTypes
from schema_to.io.os_errors import PathMissingError, TypedNotADirectoryError
from schema_to.io.routing import is_schema_map, peek_doc_type
from schema_to.io.sink import Artifact, DataSink
from schema_to.io.source import DataSource, JsonSchemaRawDoc, OpenApiRawDoc, RawDoc, SchemaMapRawDoc

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

__all__ = [
    "DirectoryDataSource",
    "DocFormat",
    "FileDataSink",
    "FileDataSource",
    "FileDataSourceFactory",
    "PeekingDirectorySource",
    "SchemaMapDirectorySource",
    "SuffixMap",
]

DocFormat = tuple[type[RawDoc], MediaType]
SuffixMap = Mapping[str, DocFormat]
PeekFn = Callable[[bytes | str], type[RawDoc] | None]

_DEFAULT_SUFFIX_MAP: SuffixMap = {
    ".schema.json": (JsonSchemaRawDoc, MediaTypes.json_schema),
    ".schema.yaml": (JsonSchemaRawDoc, MediaTypes.json_schema_yaml),
    ".schema.yml": (JsonSchemaRawDoc, MediaTypes.json_schema_yaml),
    ".openapi.json": (OpenApiRawDoc, MediaTypes.openapi),
    ".openapi.yaml": (OpenApiRawDoc, MediaTypes.openapi_yaml),
    ".openapi.yml": (OpenApiRawDoc, MediaTypes.openapi_yaml),
}


def _to_source_id(path: Path) -> str:
    """Return the `file://` URI of *path*, made absolute against the working directory.

    `..` and `.` segments are collapsed lexically.
    Symlinks are deliberately not followed (unlike `Path.resolve`),
    but an unnormalised `..` would make `urljoin` of a relative `$ref` land on the wrong URI.
    """
    return Path(os.path.normpath(path.absolute())).as_uri()


def _infer_from_path(path: Path) -> tuple[type[RawDoc], MediaType]:
    """Return `(doc_cls, media_type)` for *path* by matching its name against [DirectoryDataSource.suffix_map][].

    Checks longest suffixes first.

    Raises:
        ValueError: If the extension is not recognized.
    """
    name = path.name.lower()
    for suffix in sorted(DirectoryDataSource.suffix_map, key=len, reverse=True):
        if name.endswith(suffix):
            return DirectoryDataSource.suffix_map[suffix]
    recognised = ", ".join(sorted(DirectoryDataSource.suffix_map))
    msg = f"Cannot infer document type from {path.name!r}. Use a recognised compound extension: {recognised}."
    raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class FileDataSource(DataSource):
    """A `DataSource` backed by a single file on the local filesystem.

    Attributes:
        path: Absolute or relative path to the file.
        doc_cls: The `RawDoc` subclass to wrap the file content in.
        media_type: Content type, used by parsers to select a deserialiser.
    """

    path: Path
    doc_cls: type[RawDoc]
    media_type: MediaType

    @property
    def source_id(self) -> str:
        return _to_source_id(self.path)

    def documents(self) -> Iterator[RawDoc]:
        if not self.path.is_file():
            raise PathMissingError(filename=self.path)
        yield self.doc_cls.original(
            _to_source_id(self.path), self.path.read_bytes(), self.media_type
        )


@dataclass(frozen=True, slots=True)
class DirectoryDataSource(DataSource):
    """A `DataSource` that yields all schema files matching known compound extensions under a directory.

    Files whose name does not end with a recognised compound extension are skipped.

    Subclass and override [suffix_map][] or [peek_fn][] to customise discovery.

    Attributes:
        root: Path to the directory.
        recursive: Whether to look in subdirectories.
        include_hidden: Whether to look in dotted directories.
    """

    suffix_map: ClassVar[SuffixMap] = _DEFAULT_SUFFIX_MAP
    peek_fn: ClassVar[PeekFn | None] = None

    root: Path
    _: KW_ONLY
    recursive: bool
    include_hidden: bool = False
    paths: Set[Path] = field(init=False, hash=False, repr=False)

    def __post_init__(self) -> None:
        if not self.root.is_dir():
            raise TypedNotADirectoryError(filename=self.root)
        # `object.__setattr__` is how a frozen dataclass fills a derived field;
        # plain `setattr` raises `FrozenInstanceError`.
        object.__setattr__(self, "paths", frozenset(sorted(self.__expand_sources())))

    def __expand_sources(self) -> Iterator[Path]:
        cls = type(self)
        # `glob.glob` skips hidden dirs (including `.git/`).
        for suffix in cls.suffix_map:
            # ruff:ignore[glob]  # `glob.glob` can ignore hidden directories.
            for path_str in glob.glob(
                f"**/*{suffix}" if self.recursive else f"*{suffix}",
                root_dir=str(self.root),
                recursive=True,  # True just means that `**` works.
                include_hidden=self.include_hidden,
            ):
                p = self.root / path_str
                if p.is_file():
                    yield p

    @property
    def source_id(self) -> str:
        return _to_source_id(self.root)

    def documents(self) -> Iterator[RawDoc]:
        cls = type(self)
        for path in self.paths:
            doc_cls, media_type = _infer_from_path(path)
            content = path.read_bytes()
            if cls.peek_fn is not None and cls.peek_fn(content) is None:
                continue
            yield doc_cls.original(_to_source_id(path), content, media_type)


@dataclass(frozen=True, slots=True)
class SchemaMapDirectorySource(DataSource):
    """A `DataSource` yielding every file under a directory as a `SchemaMapRawDoc`.

    Use this for a tree of files that each hold several named schemas at the top level.
    An OpenAPI `components/schemas` fragment split across files,
    where one file `$ref`s another by relative path (`../base/time.yaml#/timestamp`).

    Unlike `DirectoryDataSource`, this matches on plain `.yaml` / `.yml` / `.json` rather than compound extensions,
    since these files carry no compound suffix.
    The caller selects this source explicitly rather than the pipeline sniffing for it because the distinguishing evidence is weak:
    A schema map looks like a single schema whose keywords are all unrecognised, and both are valid documents.
    `peek_doc_type` does rule out the confusable cases (see [is_schema_map][schema_to.io.routing.is_schema_map))
    so files that are definitely something else are skipped rather than mis-parsed.

    `uri` is each file's URI, so a relative `$ref` resolves by URI math against the referring file, exactly as it does on disk.

    Attributes:
        root: Path to the directory.
        recursive: Whether to look in subdirectories.
        include_hidden: Whether to look in dotted directories.
        exclude: Filenames, relative to `root`, to skip.
    """

    suffixes: ClassVar[Mapping[str, MediaType]] = {
        ".yaml": MediaTypes.yaml,
        ".yml": MediaTypes.yaml,
        ".json": MediaTypes.json,
    }

    root: Path
    _: KW_ONLY
    recursive: bool = True
    include_hidden: bool = False
    exclude: Set[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.root.is_dir():
            raise TypedNotADirectoryError(filename=self.root)

    @property
    def source_id(self) -> str:
        return _to_source_id(self.root)

    def documents(self) -> Iterator[SchemaMapRawDoc]:
        for path in sorted(self._paths()):
            content = path.read_bytes()
            if not is_schema_map(content):
                continue
            yield SchemaMapRawDoc.original(
                _to_source_id(path), content, type(self).suffixes[path.suffix.lower()]
            )

    def _paths(self) -> Iterator[Path]:
        for suffix in type(self).suffixes:
            # ruff:ignore[glob]  # `glob.glob` can ignore hidden directories.
            for path_str in glob.glob(
                f"**/*{suffix}" if self.recursive else f"*{suffix}",
                root_dir=str(self.root),
                recursive=True,  # True just means that `**` works.
                include_hidden=self.include_hidden,
            ):
                if path_str not in self.exclude and (self.root / path_str).is_file():
                    yield self.root / path_str


@dataclass(frozen=True, slots=True)
class PeekingDirectorySource(DirectoryDataSource):
    """DirectoryDataSource that uses [peek_doc_type][schema_to.io.routing.peek_doc_type] as a secondary filter.

    Files whose compound extension matches but whose content cannot be identified as a JSON Schema or OpenAPI document are skipped.
    """

    peek_fn: ClassVar[Callable[[bytes], object] | None] = peek_doc_type


@dataclass(frozen=True, slots=True, kw_only=True)
class FileDataSourceFactory[I: RawDoc]:
    """Factory for [FileDataSource][]."""

    recursive: bool
    include_hidden: bool = False

    def get(self, paths: Sequence[Path]) -> Sequence[DataSource[I]]:
        return list(self._get(paths))

    def _get(self, paths: Sequence[Path]) -> Iterator[DataSource[I]]:
        for p in paths:
            if p.is_dir():
                yield PeekingDirectorySource(
                    p, recursive=self.recursive, include_hidden=self.include_hidden
                )
            elif p.is_file():
                doc_cls, media_type = _infer_from_path(p)
                yield FileDataSource(p, doc_cls, media_type)


@dataclass(frozen=True, slots=True)
class FileDataSink[O: Artifact](DataSink[O]):
    """A `DataSink` that writes each `Artifact` as a file under a root directory.

    `artifact.artifact_id` is treated as a relative path from `root`.
    Parent directories are created automatically when `create_dirs` is `True`.

    Attributes:
        root: Base directory for all written files.
    """

    root: Path

    @property
    def sink_id(self) -> str:
        return _to_source_id(self.root)

    def write(self, artifact: O) -> None:
        dest = self.root / artifact.artifact_id
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(artifact.content)
