"""Abstract data-source types.

A `DataSource` is an abstract, lazily-iterable supplier of `RawDocument`s.
Concrete implementations may represent a single file, a directory tree,
an HTTP endpoint, an in-memory buffer, or any other origin — the pipeline
never assumes a filesystem is present.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from typing import NamedTuple

__all__ = [
    "DataSource",
    "JsonSchemaRawDocument",
    "MediaType",
    "MediaTypeParam",
    "MediaTypes",
    "OpenApiRawDocument",
    "RawDocument",
]


class MediaTypeParam(NamedTuple):
    key: str
    value: str


@dataclass(frozen=True, slots=True)
class MediaType:
    """An [IANA media type](https://www.iana.org/assignments/media-types/)."""

    type: str
    subtype: str
    params: tuple[MediaTypeParam, ...] = ()

    @property
    def essence(self) -> str:
        return f"{self.type}/{self.subtype}"

    @property
    def string(self) -> str:
        return self.essence + "".join(f";{k}={v}" for k, v in self.params)

    @property
    def is_discrete(self) -> bool:
        return self.type not in {"message", "multipart"}

    def __str__(self) -> str:
        return self.string

    @classmethod
    def from_extension(cls, suffix: str) -> MediaType | None:
        """Infer a media type from a file extension such as `".json"` or `".yaml"`."""
        return {".json": MediaTypes.json, ".yaml": MediaTypes.yaml, ".yml": MediaTypes.yaml}.get(
            suffix.lower()
        )


class MediaTypes:
    """Common media type constants."""

    commonmark = MediaType("text", "markdown")
    json = MediaType("application", "json")
    python = MediaType("text", "x-python")
    sql = MediaType("application", "sql")
    typescript = MediaType("application", "typescript")
    yaml = MediaType("application", "yaml")


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class JsonSchemaRawDocument(RawDocument):
    """A `RawDocument` known to contain a JSON Schema 2020-12 document."""


@dataclass(frozen=True, slots=True)
class OpenApiRawDocument(RawDocument):
    """A `RawDocument` known to contain an OpenAPI 3.1 document."""


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
        raise NotImplementedError

    @abstractmethod
    def documents(self) -> Iterator[RawDocument]:
        """Yield each document provided by this source in an unspecified order."""
        raise NotImplementedError
