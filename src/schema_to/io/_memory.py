"""In-memory `DataSource` and `DataSink` implementations.

These are primarily useful in tests and for piping one pipeline stage's output
directly into the next without touching the filesystem.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from schema_to.io._sink import DataSink, OutputArtifact
from schema_to.io._source import DataSource, RawDocument

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

__all__ = ["InMemoryDataSink", "InMemoryDataSource"]


class InMemoryDataSource(DataSource):
    """A `DataSource` backed by a pre-supplied list of `RawDocument`s.

    Attributes:
        source_id: Identifier for this source as a whole.
    """

    def __init__(self, documents: Sequence[RawDocument], *, source_id: str = "<memory>") -> None:
        self._documents = list(documents)
        self._source_id = source_id

    @property
    def source_id(self) -> str:
        return self._source_id

    def read(self) -> Iterator[RawDocument]:
        return iter(self._documents)


class InMemoryDataSink(DataSink):
    """A `DataSink` that accumulates `OutputArtifact`s in memory.

    Retrieve results via the `artifacts` property after `Pipeline.process()`.
    """

    def __init__(self, *, sink_id: str = "<memory>") -> None:
        self._sink_id = sink_id
        self._artifacts: list[OutputArtifact] = []

    @property
    def sink_id(self) -> str:
        return self._sink_id

    @property
    def artifacts(self) -> tuple[OutputArtifact, ...]:
        """All artifacts written so far, in insertion order."""
        return tuple(self._artifacts)

    def write(self, artifact: OutputArtifact) -> None:
        self._artifacts.append(artifact)

    def clear(self) -> None:
        """Discard all accumulated artifacts."""
        self._artifacts.clear()
