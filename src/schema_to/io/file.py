"""Filesystem-backed `DataSource` and `DataSink` implementations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from schema_to.io.sink import DataSink, OutputArtifact
from schema_to.io.source import DataSource, MediaType, RawDocument

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["DirectoryDataSource", "FileDataSink", "FileDataSource"]


class FileDataSource(DataSource):
    """A `DataSource` backed by a single file on the local filesystem.

    The media type is inferred from the file extension; pass `media_type`
    explicitly to override.

    Attributes:
        path: Absolute or relative path to the file.
        media_type: Content type override.  Inferred from suffix if `None`.
    """

    def __init__(self, path: Path | str, *, media_type: MediaType | None = None) -> None:
        self.path = Path(path).resolve()
        self.media_type = media_type

    @property
    def source_id(self) -> str:
        return self.path.as_uri()

    def documents(self) -> Iterator[RawDocument]:
        mt = self.media_type or MediaType.from_extension(self.path.suffix)
        if mt is None:
            return
        yield RawDocument(
            source_id=self.path.as_uri(),
            content=self.path.read_bytes(),
            media_type=mt,
            display_name=self.path.stem,
            base_uri=self.path.as_uri(),
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
        self, root: Path | str, pattern: str = "**/*", *, media_type: MediaType | None = None
    ) -> None:
        self.root = Path(root).resolve()
        self.pattern = pattern
        self.media_type = media_type

    @property
    def source_id(self) -> str:
        return self.root.as_uri()

    def documents(self) -> Iterator[RawDocument]:
        for path in sorted(self.root.glob(self.pattern)):
            if not path.is_file():
                continue
            mt = self.media_type or MediaType.from_extension(path.suffix)
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
        self.root = Path(root).resolve()
        self.create_dirs = create_dirs

    @property
    def sink_id(self) -> str:
        return self.root.as_uri()

    def write(self, artifact: OutputArtifact) -> None:
        dest = self.root / artifact.artifact_id
        if self.create_dirs:
            dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(artifact.content)
