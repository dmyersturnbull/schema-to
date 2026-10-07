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
from typing import TYPE_CHECKING

from schema_to.errors import SourceLocation, TextRange
from schema_to.io.uri import display_name as uri_display_name
from schema_to.io.uri import is_uri

if TYPE_CHECKING:
    from collections.abc import Iterator

    from schema_to.io.media_type import MediaType

__all__ = ["DataSource", "JsonSchemaRawDoc", "OpenApiRawDoc", "Origin", "RawDoc", "SchemaMapRawDoc"]


@dataclass(frozen=True, slots=True)
class Origin:
    """Where the content of a derived `RawDoc` actually lives.

    Stages that split or rewrite a document yield documents of their own,
    each with a new URI so that it stays unique.
    That URI names something that exists nowhere,
    so the derived document records the real place here,
    and a diagnostic can point at somewhere the user can open.

    Attributes:
        uri: URI of the original document, without a fragment.
        json_pointer: [RFC 6901](https://www.rfc-editor.org/rfc/rfc6901)
            pointer to the content within the original.
            Empty means all of it.
        range: Where the content sits in the original's raw text.
            `None` if unknown,
            which it is for anything but a reader that reports spans.
            The built-in readers do not.
    """

    uri: str
    json_pointer: str = ""
    range: TextRange | None = None


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
            A document derived from another has a fragment,
            as in `file:///catalog.yaml#/author-data`.
        content: Raw bytes exactly as supplied by the source.
        media_type: Content type, used to select the appropriate `DocumentParser`.
        origin: Where the content actually lives, if not at `uri`.
            `None` for a document that is its own original.

    Raises:
        ValueError: If `uri` is not a URI.
    """

    uri: str
    content: bytes
    media_type: MediaType
    _: KW_ONLY
    origin: Origin | None = None

    def __post_init__(self) -> None:
        if not is_uri(self.uri):
            msg = (
                f"A document's identifier must be a URI, with a scheme, "
                f"such as 'file:///a.json' or 'memory:///a.json'; got {self.uri!r}."
            )
            raise ValueError(msg)

    @property
    def display_name(self) -> str:
        """Short human-readable name for log messages and generated identifiers.

        For example, `"users"` for `file:///dir/users.schema.json`.
        See [schema_to.io.uri.display_name][].
        """
        return uri_display_name(self.uri)

    @property
    def provenance(self) -> Origin:
        """Where the content actually lives: its `origin`, or else itself."""
        return self.origin or Origin(self.uri)

    def location(self, json_pointer: str = "", *, at: TextRange | None = None) -> SourceLocation:
        """Return the location of a node within this document, for a diagnostic.

        For a derived document, this is in the original.
        Its content has been re-encoded, so `at`, a position in that content,
        means nothing there and the original's own range, if any, is used instead.

        Args:
            json_pointer: Pointer to the node, relative to this document.
            at: Where the node sits in `content`, if known.
        """
        home = self.provenance
        span = home.range if self.origin is not None else at
        return SourceLocation(home.uri, home.json_pointer + json_pointer, span)


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
