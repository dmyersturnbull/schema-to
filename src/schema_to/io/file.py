"""Filesystem-backed `DataSource` and `DataSink` implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from schema_to import MediaType
from schema_to.io.sink import DataSink, OutputArtifact
from schema_to.io.source import DataSource, RawDocument

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = ["FileDataSink", "FileDataSource"]


@dataclass(frozen=True, slots=True)
class FileDataSource(DataSource):
    """A `DataSource` backed by a single file on the local filesystem.

    The media type is inferred from the file extension; pass `media_type`
    explicitly to override.

    Attributes:
        path: Absolute or relative path to the file.
        media_type: Content type override.  Inferred from suffix if `None`.
    """

    path: Path
    media_type: MediaType

    @property
    def source_id(self) -> str:
        return self.path.as_uri()

    def documents(self) -> Iterator[RawDocument]:
        yield RawDocument(
            source_id=self.path.as_uri(),
            content=self.path.read_bytes(),
            media_type=self.media_type,
            display_name=self.path.stem,
            base_uri=self.path.as_uri(),
        )


@dataclass(frozen=True, slots=True)
class FileDataSink(DataSink):
    """A `DataSink` that writes each `OutputArtifact` as a file under a root directory.

    `artifact.artifact_id` is treated as a relative path from `root`.  Parent
    directories are created automatically when `create_dirs` is `True`.

    Attributes:
        root: Base directory for all written files.
    """

    root: Path

    @property
    def sink_id(self) -> str:
        return self.root.as_uri()

    def write(self, artifact: OutputArtifact) -> None:
        dest = self.root / artifact.artifact_id
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(artifact.content)
