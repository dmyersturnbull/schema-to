"""URI helpers for document identity.

A document's URI is its unique ID and the base its relative `$ref`s resolve against.
A document derived from another gets the original's URI plus a fragment,
`file:///catalog.yaml#/author-data`,
so its ID stays unique while URI math on a reference written in it still lands in the original file.
"""

import re
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urldefrag, urlsplit

__all__ = ["display_name", "is_uri", "pointer_uri"]

# RFC 3986 `scheme ":" rest`, with no whitespace or control characters in the rest.
_URI = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:\S*")

# What a fragment may hold unescaped, beyond unreserved characters (RFC 3986 §3.5).
_FRAGMENT_SAFE = "/~:@!$&'()*+,;="


def is_uri(text: str) -> bool:
    """Report whether `text` is a URI: a scheme, a colon, then no whitespace.

    The scheme need not be one that can be fetched; `memory:` and `urn:` are fine.
    """
    return _URI.fullmatch(text) is not None


def pointer_uri(uri: str, json_pointer: str) -> str:
    """Return `uri` with its fragment replaced by `json_pointer`, percent-encoded.

    An empty pointer addresses the whole document, which needs no fragment.
    """
    base = urldefrag(uri).url
    if not json_pointer:
        return base
    return f"{base}#{quote(json_pointer, safe=_FRAGMENT_SAFE)}"


def display_name(uri: str) -> str:
    """Return a short human-readable name for the document at `uri`.

    This is the last segment of the fragment, if there is one,
    which is how a schema lifted out of a larger file keeps its own name.
    Otherwise, it is the last path segment up to its first dot:
    `file:///dir/users.schema.json` is `users`.
    The result is empty if the URI has neither, as in `test://schema`,
    whose only name-like part is the authority.
    """
    parts = urlsplit(uri)
    if parts.fragment:
        _, _, last = unquote(parts.fragment).rpartition("/")
        return last.replace("~1", "/").replace("~0", "~")
    return PurePosixPath(unquote(parts.path)).name.split(".")[0]
