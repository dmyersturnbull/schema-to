"""Shared primitives for all CST modules.

Every node in every CST carries a `SourceRef` that links it back to its origin
in a `RawDoc`, enabling precise error messages and source-map generation.
"""

from abc import ABC
from dataclasses import dataclass

__all__ = ["CstNode", "SourceRef"]


@dataclass(frozen=True, slots=True)
class SourceRef:
    """A provenance link from a CST node back to its origin.

    Attributes:
        source_id: Identifier matching `RawDoc.source_id`.
        json_pointer: An [RFC 6901](https://www.rfc-editor.org/rfc/rfc6901)
          pointer locating this node within the parsed document tree.
    """

    source_id: str
    json_pointer: str


# ruff:ignore[abstract-base-class-without-abstract-method]  # Sealed marker; abstract identity is enforced by the type system.
class CstNode(ABC):
    """Sealed marker base for every CST node.

    Concrete nodes are immutable `@dataclass(frozen=True, slots=True)` subclasses.
    The hierarchy has two independent subtrees: `JsonSchemaDocument` and `OpenApiDocument`.
    """
