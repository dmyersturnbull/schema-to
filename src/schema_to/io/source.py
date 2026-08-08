"""Abstract data-source types.

A `DataSource` is an abstract, lazily-iterable supplier of `RawDoc`s.
Concrete implementations may represent a single file, a directory tree,
an HTTP endpoint, an in-memory buffer, or any other origin — the pipeline
never assumes a filesystem is present.
"""


from abc import ABC, abstractmethod
from dataclasses import KW_ONLY, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from schema_to.io.media_type import MediaType

__all__ = ["DataSource", "JsonSchemaRawDoc", "OpenApiRawDoc", "RawDoc", "SchemaMapRawDoc"]


@dataclass(frozen=True, slots=True)
class RawDoc:
    """An unparsed document together with its provenance metadata.

    The pipeline never reads files directly:
    Every document arrives through a `DataSource` as a `RawDoc`.
    This decouples I/O from transformation.

    Attributes:
        doc_id: Globally unique, opaque identifier
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

    doc_id: str
    content: bytes
    media_type: MediaType
    _: KW_ONLY
    display_name: str | None = None
    base_uri: str | None = None


@dataclass(frozen=True, slots=True)
class JsonSchemaRawDoc(RawDoc):
    """A `RawDoc` known to contain a JSON Schema 2020-12 document."""


@dataclass(frozen=True, slots=True)
class SchemaMapRawDoc(RawDoc):
    """A `RawDoc` whose root is a map of names to JSON Schema 2020-12 schemas.

    Distinct from `JsonSchemaRawDoc`, whose root is itself a schema:
    the two cannot be told apart by content, since a map of named schemas is
    indistinguishable from a schema whose keywords are all unrecognised.
    """


@dataclass(frozen=True, slots=True)
class OpenApiRawDoc(RawDoc):
    """A `RawDoc` known to contain an OpenAPI 3.1 document."""


class DataSource[I: RawDoc](ABC):
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
    def documents(self) -> Iterator[I]:
        """Yield each document provided by this source in an unspecified order."""
        raise NotImplementedError
