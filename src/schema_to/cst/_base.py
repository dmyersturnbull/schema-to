"""Shared primitives for all CST modules.

Every node in every CST carries a `SourceRef` that links it back to its origin
in a `RawDocument`, enabling precise error messages and source-map generation.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

__all__ = ["CstNode", "JsonValue", "SourceRef"]

# JSON value type as defined in RFC 8259.
# Self-referential via PEP 695 lazy type alias.
type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True)
class SourceRef:
    """A provenance link from a CST node back to its origin.

    Attributes:
        source_id: Identifier matching `RawDocument.source_id`.
        json_pointer: [RFC 6901](https://www.rfc-editor.org/rfc/rfc6901) pointer
            locating this node within the parsed document tree.
    """

    source_id: str
    json_pointer: str


class CstNode(ABC):
    """Sealed marker base for every CST node.

    Concrete nodes are immutable `@dataclass(frozen=True)` subclasses.  The
    hierarchy has two independent subtrees — one rooted at `JsonSchemaDocument`
    and one at `OpenApiDocument` — reflecting the two supported input formats.
    """
