"""In-memory `DataSource` and `DataSink` implementations.

These are primarily useful in tests and for piping one pipeline stage's output
directly into the next without touching the filesystem.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from schema_to.io.sink import DataSink, OutputArtifact
from schema_to.io.source import DataSource, RawDocument

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

__all__ = ["InMemoryDataSink", "InMemoryDataSource"]


class InMemoryDataSource(DataSource):
    """A `DataSource` backed by a pre-supplied list of `RawDocument`s.

    Attributes:
        source_id: Identifier for this source as a whole.
    """

    def __init__(self, documents: Sequence[RawDocument], *, source_id: str = "<memory>") -> None:
        self.documents = list(documents)
        self.source_id = source_id

    @property
    def source_id(self) -> str:
        return self.source_id

    def documents(self) -> Iterator[RawDocument]:
        return iter(self.documents)


class InMemoryDataSink(DataSink):
    """A `DataSink` that accumulates `OutputArtifact`s in memory.

    Retrieve results via the `artifacts` property after `Pipeline.process()`.
    """

    def __init__(self, *, sink_id: str = "<memory>") -> None:
        self.sink_id = sink_id
        self.artifacts: list[OutputArtifact] = []

    @property
    def sink_id(self) -> str:
        return self.sink_id

    @property
    def artifacts(self) -> tuple[OutputArtifact, ...]:
        """All artifacts written so far, in insertion order."""
        return tuple(self.artifacts)

    def write(self, artifact: OutputArtifact) -> None:
        self.artifacts.append(artifact)

    def clear(self) -> None:
        """Discard all accumulated artifacts."""
        self.artifacts.clear()
