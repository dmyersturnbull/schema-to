"""Abstract data-sink types.

A `DataSink` is the write-side dual of `DataSource`: it accepts `OutputArtifact`s
produced by the pipeline without exposing how or where they are stored.  Concrete
implementations may write to a directory, accumulate in memory, upload to an
object store, etc.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass

from schema_to.io._source import MediaType

__all__ = ["DataSink", "OutputArtifact"]


@dataclass(frozen=True)
class OutputArtifact:
    """A single output document ready to be written to a sink.

    Attributes:
        artifact_id: Suggested name for the artifact within the sink, typically
            a relative path such as `"migrations/001_users.sql"`.
        content: Serialised output bytes.
        media_type: Content type of the output.
        source_ids: `source_id`s of the `RawDocument`s that contributed to this
            artifact, for traceability.
    """

    artifact_id: str
    content: bytes
    media_type: MediaType
    source_ids: tuple[str, ...] = ()


class DataSink(ABC):
    """An abstract destination for output artifacts produced by the pipeline."""

    @property
    @abstractmethod
    def sink_id(self) -> str:
        """Stable identifier for this sink (e.g. an output directory path or URL)."""
        ...

    @abstractmethod
    def write(self, artifact: OutputArtifact) -> None:
        """Persist or collect a single output artifact."""
        ...

    def write_all(self, artifacts: Iterable[OutputArtifact]) -> None:
        """Write every artifact from an iterable by delegating to `write`."""
        ...
