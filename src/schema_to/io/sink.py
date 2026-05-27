"""Abstract data-sink types.

A `DataSink` is the write-side dual of `DataSource`: it accepts `OutputArtifact`s
produced by the pipeline without exposing how or where they are stored.  Concrete
implementations may write to a directory, accumulate in memory, upload to an
object store, etc.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from collections.abc import Iterable

    from schema_to import MediaType, MediaTypes

__all__ = ["DataSink", "OutputArtifact"]


@dataclass(frozen=True, slots=True)
class OutputArtifact(ABC):
    """A single output document ready to be written to a sink.

    Attributes:
        artifact_id: Suggested name for the artifact within the sink,
            typically a relative path such as `"migrations/001_users.sql"`.
        content: Serialised output bytes.
        media_type: Content type of the output.
        source_ids: `source_id`s of the `RawDocument`s that contributed to this artifact, for traceability.
    """

    artifact_id: str
    content: bytes
    source_ids: tuple[str, ...] = ()
    media_type: ClassVar[MediaType]


# TODO: Where should we put these concrete types?


# TODO: What about YAML?
@dataclass(frozen=True, slots=True)
class JsonOutputArtifact(OutputArtifact):
    """A `.json` file."""

    media_type: ClassVar[MediaType] = MediaTypes.json


@dataclass(frozen=True, slots=True)
class PythonOutputArtifact(OutputArtifact):
    """A `.py` file."""

    media_type: ClassVar[MediaType] = MediaTypes.python


@dataclass(frozen=True, slots=True)
class SqlOutputArtifact(OutputArtifact):
    """A `.sql` file."""

    media_type: ClassVar[MediaType] = MediaTypes.sql


class DataSink[T: OutputArtifact](ABC):
    """An abstract destination for output artifacts produced by the pipeline."""

    @property
    @abstractmethod
    def sink_id(self) -> str:
        """Stable identifier for this sink (e.g. an output directory path or URL)."""
        raise NotImplementedError

    @abstractmethod
    def write(self, artifact: T) -> None:
        """Persist or collect a single output artifact."""
        raise NotImplementedError

    def write_all(self, artifacts: Iterable[T]) -> None:
        """Write every artifact from an iterable by delegating to `write`."""
        for artifact in artifacts:
            self.write(artifact)
