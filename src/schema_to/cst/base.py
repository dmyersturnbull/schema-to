"""Shared primitives for all CST modules.

Every node in every CST carries a `SourceRef` that links it back to its origin
in a `RawDoc`, enabling precise error messages and source-map generation.
"""

from abc import ABC
from collections.abc import Mapping
from dataclasses import dataclass

__all__ = ["SYNTHETIC", "CstNode", "SourceRef"]


# Field metadata marking a field that carries no wire data — an extension bag or
# a provenance link.  Every other field is compiled into a plan (`parse._plan`)
# from its type annotation, so a field the wire format does not describe has to
# say so.
SYNTHETIC: Mapping[str, bool] = {"synthetic": True}


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
