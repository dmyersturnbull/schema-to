"""Abstract data-source types.

A `DataSource` is an abstract, lazily-iterable supplier of `RawDocument`s.
Concrete implementations may represent a single file, a directory tree,
an HTTP endpoint, an in-memory buffer, or any other origin — the pipeline
never assumes a filesystem is present.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator

__all__ = ["DataSource", "MediaType", "RawDocument"]


@dataclass(frozen=True)
class MediaType:
    """An [IANA media type](https://www.iana.org/assignments/media-types/).

    Attributes:
        essence: The type/subtype string without parameters, e.g. `"application/json"`.
        parameters: Optional media-type parameters, e.g. `{"charset": "utf-8"}`.
    """

    essence: str
    parameters: tuple[tuple[str, str], ...] = ()

    @classmethod
    def json(cls) -> MediaType:
        """Return `application/json`."""
        ...

    @classmethod
    def yaml(cls) -> MediaType:
        """Return `application/yaml` ([RFC 9512](https://www.rfc-editor.org/rfc/rfc9512))."""
        ...

    @classmethod
    def from_extension(cls, suffix: str) -> MediaType | None:
        """Infer a media type from a file extension such as `".json"` or `".yaml"`."""
        ...

    def __str__(self) -> str: ...


@dataclass(frozen=True)
class RawDocument:
    """An unparsed document together with its provenance metadata.

    The pipeline never reads files directly; every document arrives through
    a `DataSource` as a `RawDocument`, decoupling I/O from transformation.

    Attributes:
        source_id: Globally unique, opaque identifier (e.g. an absolute URI or
            a content-addressed hash). Used as the key for `$ref` resolution and
            error reporting.
        content: Raw bytes exactly as supplied by the source.
        media_type: Content type, used to select the appropriate `DocumentParser`.
        display_name: Short human-readable name for log messages and generated
            identifiers (e.g. `"users"` from `"users.schema.json"`). Defaults to
            the last path segment of `source_id`.
        base_uri: Base URI for resolving relative `$ref` values.  Defaults to
            `source_id` when not explicitly set.
    """

    source_id: str
    content: bytes
    media_type: MediaType
    display_name: str | None = None
    base_uri: str | None = None


class DataSource(ABC):
    """A lazily-iterable supplier of raw documents.

    A single `DataSource` may yield any number of documents: zero (empty),
    one (a single file or URL), or many (a directory, glob, or API listing).
    Sources are consumed exactly once per `Pipeline.process()` call.
    """

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Stable identifier for this source (e.g. an absolute path or URL)."""
        ...

    @abstractmethod
    def documents(self) -> Iterator[RawDocument]:
        """Yield each document provided by this source in an unspecified order."""
        ...
