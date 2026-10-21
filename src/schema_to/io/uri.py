"""A parsed document URI.

A document's URI is its unique ID and the base its relative `$ref`s resolve against.
A document derived from part of another gets the original's URI plus a fragment,
`file:///catalog.yaml#/author-data`,
so its ID stays unique while URI math on a reference written in it still lands in the original file.
"""

from dataclasses import dataclass, replace
from urllib.parse import quote, unquote, urldefrag, urlsplit

__all__ = ["Uri"]

# What a fragment may hold unescaped, beyond unreserved characters (RFC 3986 §3.5).
_FRAGMENT_SAFE = "/~:@!$&'()*+,;="


@dataclass(frozen=True, slots=True)
class Uri:
    """A URI split into the parts that this library cares about.

    Attributes:
        document: The URI without its fragment, exactly as written.
        scheme: The scheme, such as `file`.
        authority: The part after `//`, such as a host. Empty if there is none.
        path: The percent-decoded path.
        pointer: The percent-decoded fragment.
            This is a JSON Pointer when the URI addresses a node of a document.
            Empty if there is no fragment.
    """

    document: str
    scheme: str
    authority: str
    path: str
    pointer: str

    @classmethod
    def parse(cls, text: str) -> Uri:
        """Split `text` into a `Uri`.

        The scheme need not be one that can be fetched; `memory:` and `urn:` are fine.

        Raises:
            ValueError: If `text` has no scheme.
        """
        parts = urlsplit(text)
        if not parts.scheme:
            msg = f"Not a URI, because it has no scheme: {text!r}."
            raise ValueError(msg)
        return cls(
            document=urldefrag(text).url,
            scheme=parts.scheme,
            authority=parts.netloc,
            path=unquote(parts.path),
            pointer=unquote(parts.fragment),
        )

    def with_pointer(self, pointer: str) -> Uri:
        """Return this URI with its fragment replaced by `pointer`."""
        return replace(self, pointer=pointer)

    def __str__(self) -> str:
        if not self.pointer:
            return self.document
        return f"{self.document}#{quote(self.pointer, safe=_FRAGMENT_SAFE)}"
