"""Filesystem-backed `DataSource` and `DataSink` implementations."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from schema_to.io._sink import DataSink, OutputArtifact
from schema_to.io._source import DataSource, MediaType, RawDocument

__all__ = ["DirectoryDataSource", "FileDataSink", "FileDataSource"]


class FileDataSource(DataSource):
    """A `DataSource` backed by a single file on the local filesystem.

    The media type is inferred from the file extension; pass `media_type`
    explicitly to override.

    Attributes:
        path: Absolute or relative path to the file.
        media_type: Content type override.  Inferred from suffix if `None`.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        media_type: MediaType | None = None,
    ) -> None:
        self._path = Path(path).resolve()
        self._media_type = media_type

    @property
    def source_id(self) -> str:
        return self._path.as_uri()

    def documents(self) -> Iterator[RawDocument]:
        mt = self._media_type or MediaType.from_extension(self._path.suffix)
        if mt is None:
            return
        yield RawDocument(
            source_id=self._path.as_uri(),
            content=self._path.read_bytes(),
            media_type=mt,
            display_name=self._path.stem,
            base_uri=self._path.as_uri(),
        )


class DirectoryDataSource(DataSource):
    """A `DataSource` that yields all files matching a glob pattern under a directory.

    Files whose extension maps to no known media type are silently skipped, so
    a directory can contain a mix of schema files and unrelated assets.

    Attributes:
        root: Path to the directory.
        pattern: `pathlib`-style glob pattern relative to `root`.
        media_type: Override media type applied to every matched file.
            When `None`, the type is inferred per-file from the extension.
    """

    def __init__(
        self,
        root: Path | str,
        pattern: str = "**/*",
        *,
        media_type: MediaType | None = None,
    ) -> None:
        self._root = Path(root).resolve()
        self._pattern = pattern
        self._media_type = media_type

    @property
    def source_id(self) -> str:
        return self._root.as_uri()

    def documents(self) -> Iterator[RawDocument]:
        for path in sorted(self._root.glob(self._pattern)):
            if not path.is_file():
                continue
            mt = self._media_type or MediaType.from_extension(path.suffix)
            if mt is None:
                continue
            yield RawDocument(
                source_id=path.as_uri(),
                content=path.read_bytes(),
                media_type=mt,
                display_name=path.stem,
                base_uri=path.as_uri(),
            )


class FileDataSink(DataSink):
    """A `DataSink` that writes each `OutputArtifact` as a file under a root directory.

    `artifact.artifact_id` is treated as a relative path from `root`.  Parent
    directories are created automatically when `create_dirs` is `True`.

    Attributes:
        root: Base directory for all written files.
        create_dirs: Create missing parent directories when `True` (default).
    """

    def __init__(self, root: Path | str, *, create_dirs: bool = True) -> None:
        self._root = Path(root).resolve()
        self._create_dirs = create_dirs

    @property
    def sink_id(self) -> str:
        return self._root.as_uri()

    def write(self, artifact: OutputArtifact) -> None:
        dest = self._root / artifact.artifact_id
        if self._create_dirs:
            dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(artifact.content)
