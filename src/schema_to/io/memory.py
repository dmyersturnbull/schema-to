"""In-memory `DataSource` and `DataSink` implementations."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import quote

from schema_to.io.sink import Artifact, DataSink
from schema_to.io.source import DataSource, RawDoc

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["InMemoryDataSink", "InMemoryDataSource", "memory_uri"]


def memory_uri(name: str) -> str:
    """Return the URI for a document called `name` that exists only in memory.

    It is a valid URI but names nothing that can be fetched,
    so a relative `$ref` in such a document cannot reach another document.
    The path is the name, which is what `RawDoc.display_name` is computed from.
    """
    return f"memory:///{quote(name)}"


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
    def artifacts(self) -> Sequence[T]:
        return list(self._artifacts)
