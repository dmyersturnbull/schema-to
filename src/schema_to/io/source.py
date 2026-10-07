"""Abstract data-source types.

A `DataSource` is an abstract, lazily-iterable supplier of `RawDoc`s.
Concrete implementations may represent
a single file,
a directory tree,
an HTTP endpoint,
an in-memory buffer,
or another origin.
"""

from abc import ABC, abstractmethod
from dataclasses import KW_ONLY, dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Self

from schema_to.core import Range
from schema_to.errors import SourceLocation
from schema_to.io.uri import Uri

if TYPE_CHECKING:
    from collections.abc import Iterator

    from schema_to.io.media_type import MediaType

__all__ = ["DataSource", "JsonSchemaRawDoc", "OpenApiRawDoc", "Origin", "RawDoc", "SchemaMapRawDoc"]


@dataclass(frozen=True, slots=True)
class Origin:
    """The part of the file the user wrote that a `RawDoc`'s content came from.

    A stage that splits a document yields documents of its own,
    each with a new URI of its own so that it stays unique.
    That URI names something that exists nowhere.
    The origin is the real place instead,
    so that a diagnostic about the document can point somewhere the user can open.
    A document that is a whole file has the file as its origin.

    Attributes:
        uri: URI of the file the user wrote, without a fragment.
        json_pointer: [RFC 6901](https://www.rfc-editor.org/rfc/rfc6901)
            pointer to the content within that file.
            Empty if the content is all of it.
        range: Where the content sits in that file's raw text.
            Until a reader reports the span of each node,
            this is the span of the whole file.
    """

    uri: str
    json_pointer: str
    range: Range

    @classmethod
    def whole(cls, uri: str, content: bytes) -> Self:
        """Return the origin of a document that is all of the file at `uri`, which holds `content`."""
        return cls(uri, "", Range.covering(content.decode(errors="replace")))


@dataclass(frozen=True, slots=True)
class RawDoc:
    """An unparsed document together with its provenance metadata.

    The pipeline never reads files directly:
    Every document arrives through a `DataSource` as a `RawDoc`.
    This decouples I/O from transformation.

    Attributes:
        uri: Globally unique identifier, which is also the base for resolving relative `$ref`s.
            Must be a URI, though not necessarily one that can be fetched:
            a document from an `InMemoryDataSource` has a custom-scheme URI
            (e.g. `memory:///users.schema.json`) that resolves nowhere,
            and so only a `$ref` within it can be followed.
            The path should be meaningful, since `display_name` is computed from it.
            A document derived from part of another has a fragment,
            as in `file:///catalog.yaml#/author-data`.
        content: Raw bytes exactly as supplied by the source.
        media_type: Content type, used to select the appropriate `DocumentParser`.
        origin: Where in the file the user wrote this document's content came from.

    Raises:
        ValueError: If `uri` is not a URI.
    """

    uri: str
    content: bytes
    media_type: MediaType
    _: KW_ONLY
    origin: Origin

    def __post_init__(self) -> None:
        Uri.parse(self.uri)

    @classmethod
    def original(cls, uri: str, content: bytes, media_type: MediaType) -> Self:
        """Return a document that is all of the file at `uri`, which holds `content`."""
        return cls(uri, content, media_type, origin=Origin.whole(uri, content))

    @property
    def display_name(self) -> str:
        """Short human-readable name for log messages and generated identifiers.

        This is the last segment of the URI's fragment, if there is one,
        which is how a document carved out of a larger file keeps its own name.
        Otherwise, it is the last segment of the path, up to its first dot:
        `file:///dir/users.schema.json` is `users`.
        It is empty if the URI has neither, as in `test://schema`,
        whose only name-like part is the authority.
        """
        uri = Uri.parse(self.uri)
        if uri.pointer:
            name = uri.pointer.rpartition("/")[2]
            return name.replace("~1", "/").replace("~0", "~")
        return PurePosixPath(uri.path).name.split(".")[0]

    def location(self, json_pointer: str) -> SourceLocation:
        """Return the location of a node within this document, as the user would find it.

        Args:
            json_pointer: Pointer to the node, relative to this document.
                Empty for the document as a whole.
        """
        return SourceLocation(
            self.origin.uri, self.origin.json_pointer + json_pointer, self.origin.range
        )


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
