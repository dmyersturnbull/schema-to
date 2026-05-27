"""Abstract data-source types.

A `DataSource` is an abstract, lazily-iterable supplier of `RawDocument`s.
Concrete implementations may represent a single file, a directory tree,
an HTTP endpoint, an in-memory buffer, or any other origin — the pipeline
never assumes a filesystem is present.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import KW_ONLY, dataclass
from typing import TYPE_CHECKING

from schema_to.io.media_type import MediaType

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["DataSource", "JsonSchemaRawDocument", "OpenApiRawDocument", "RawDocument"]


@dataclass(frozen=True, slots=True)
class RawDocument:
    """An unparsed document together with its provenance metadata.

    The pipeline never reads files directly; every document arrives through
    a `DataSource` as a `RawDocument`, decoupling I/O from transformation.

    Attributes:
        source_id: Globally unique, opaque identifier
            (e.g. an absolute URI or a content-addressed hash).
            Used as the key for `$ref` resolution and error reporting.
        content: Raw bytes exactly as supplied by the source.
        media_type: Content type, used to select the appropriate `DocumentParser`.
        display_name: Short human-readable name for log messages and generated identifiers
            (e.g. `"users"` from `"users.schema.json"`).
            A good default is the last path segment of `source_id`.
        base_uri: Base URI for resolving relative `$ref` values.
            A good default is `source_id`.
    """

    source_id: str
    content: bytes
    media_type: MediaType
    _: KW_ONLY
    display_name: str | None = None
    base_uri: str | None = None


@dataclass(frozen=True, slots=True)
class JsonSchemaRawDocument(RawDocument):
    """A `RawDocument` known to contain a JSON Schema 2020-12 document."""


@dataclass(frozen=True, slots=True)
class OpenApiRawDocument(RawDocument):
    """A `RawDocument` known to contain an OpenAPI 3.1 document."""


class DataSource[T: RawDocument](ABC):
    """A lazily-iterable supplier of raw documents.

    A single `DataSource` may yield any number of documents: zero (empty),
    one (a single file or URL), or many (a directory, glob, or API listing).
    Sources are consumed exactly once per `Pipeline.process()` call.
    """

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Stable identifier for this source (e.g. an absolute path or URL)."""
        raise NotImplementedError

    @abstractmethod
    def documents(self) -> Iterator[T]:
        """Yield each document provided by this source in an unspecified order."""
        raise NotImplementedError
