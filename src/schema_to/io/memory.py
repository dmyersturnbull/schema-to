"""In-memory `DataSource` and `DataSink` implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from schema_to.io.sink import DataSink, Artifact
from schema_to.io.source import DataSource, RawDoc

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["InMemoryDataSink", "InMemoryDataSource"]


@dataclass
class InMemoryDataSource[T: RawDoc](DataSource[T]):
    """A `DataSource` backed by an in-memory list of `RawDoc`s."""

    _documents: list[T] = field(default_factory=list)

    @property
    def source_id(self) -> str:
        return "memory"

    def documents(self) -> Iterator[T]:
        yield from self._documents

    def add(self, document: T) -> None:
        self._documents.append(document)


@dataclass
class InMemoryDataSink[T: Artifact](DataSink[T]):
    """A `DataSink` that accumulates `Artifact`s in memory."""

    _artifacts: list[T] = field(default_factory=list)

    @property
    def sink_id(self) -> str:
        return "memory"

    def write(self, artifact: T) -> None:
        self._artifacts.append(artifact)

    @property
    def artifacts(self) -> list[T]:
        return list(self._artifacts)
