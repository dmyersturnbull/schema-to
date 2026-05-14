"""Abstract data-source types.

A `DataSource` is an abstract, lazily-iterable supplier of `RawDocument`s.
Concrete implementations may represent a single file, a directory tree,
an HTTP endpoint, an in-memory buffer, or any other origin — the pipeline
never assumes a filesystem is present.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from abc import ABC, abstractmethod
from dataclasses import dataclass, KW_ONLY
from typing import TYPE_CHECKING, NamedTuple, Self

if TYPE_CHECKING:
    from collections.abc import Iterator

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
    _: KW_ONLY
    params: tuple[MediaTypeParam, ...] = ()
    suffixes: tuple[str, ...] = ()
    is_source: bool = False

    def __post_init__(self) -> None:
        if not self.suffixes:
            msg = "Must provide at least 1 suffix."
            raise ValueError(msg)

    @property
    def essence(self) -> str:
        return f"{self.type}/{self.subtype}"

    @property
    def string(self) -> str:
        return self.essence + "".join(f";{k}={v}" for k, v in self.params)

    @property
    def preferred_suffix(self) -> str:
        return self.suffixes[0]

    def __str__(self) -> str:
        return self.string


class MediaTypes:
    """Common media type constants."""

    commonmark = MediaType("text", "markdown", suffixes=(".md",))
    json = MediaType("application", "json", suffixes=(".json",), is_source=True)
    jsonc = MediaType("application", "jsonc", suffixes=(".jsonc",), is_source=True)
    python = MediaType("text", "x-python", suffixes=(".py",))
    sql = MediaType("application", "sql", suffixes=(".sql",))
    typescript = MediaType("application", "typescript", suffixes=(".ts",))
    yaml = MediaType("application", "yaml", suffixes=(".yaml", ".yaml"), is_source=True)

    @classmethod
    def sources(cls) -> tuple[MediaType, ...]:
        return tuple(mt for mt in cls.all() if mt.is_source)

    @classmethod
    def all(cls) -> tuple[MediaType, ...]:
        return tuple(value for value in vars(cls).values() if isinstance(value, MediaType))

    @classmethod
    def source_from_suffix(cls, suffix: str) -> MediaType:
        return cls._suffix_map()[suffix]

    @classmethod
    def from_suffix(cls, suffix: str) -> MediaType | None:
        return cls._suffix_map().get(suffix)

    @classmethod
    @cache
    def _suffix_map(cls) -> dict[str, MediaType]:
        by_suffix: dict[str, set[MediaType]] = {}
        for mt in cls.all():
            for suffix in mt.suffixes:
                by_suffix[suffix].add(mt)
        clashes = {s: mts for s, mts in by_suffix.items() if len(mts) > 1}
        if clashes:
            msg = f"Conflicts in filename suffix / media-type map: {clashes.items()}"
            raise ValueError(msg)
        return {s: next(iter(mts)) for s, mts in by_suffix.items()}


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
    def read(self) -> Iterator[RawDocument]:
        """Yield each document provided by this source in an unspecified order."""
        raise NotImplementedError
