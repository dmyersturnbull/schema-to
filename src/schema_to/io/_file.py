"""Filesystem-backed `DataSource` and `DataSink` implementations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from schema_to import ParseError
from schema_to._core import JsonValue
from schema_to.io._core import YamlReader, JsonReader
from schema_to.io._sink import DataSink, OutputArtifact
from schema_to.io._source import DataSource, MediaType, RawDocument

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["FileDataSink", "FileDataSource", "JsonLikeReader"]


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

    def read(self) -> Iterator[RawDocument]:
        if self.media_type.is_source:
            yield RawDocument(
                source_id=self.path.as_uri(),
                content=self.path.read_bytes(),
                media_type=self.media_type,
                display_name=self.path.stem,
                base_uri=self.path.as_uri(),
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


@dataclass(frozen=True, slots=True)
class JsonLikeReader:
    def read(self, data: bytes | str, media_type: MediaType) -> JsonValue:
        match media_type.essence:
            case "application/yaml" | "text/yaml":
                return YamlReader().read(data)
            case "application/json":
                return JsonReader().read(data)
            case _:
                msg = f"Cannot read from {media_type}"
                raise ParseError(msg)
