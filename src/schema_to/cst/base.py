"""Shared primitives for all CST modules.

Every CST node defines fields for the properties its spec defines:

- A field's name matches its the name of the corresponding property.
  Property names are converted to snake_case,
  and a final `_` is added if the result would otherwise be invalid in Python.
- A field's typing annotation matches the type of the corresponding property.
- A field has a default value iff the corresponding property is optional.

Some fields carry metadata provided via `dataclasses.field`'s `metadata` parameter.
These keys are defined:

- `synthetic`: Marks the field as not defined by the spec or otherwise not part of the wire format.
  These are mostly provenance fields and `extensions` (i.e. `x-*`).
  If present, its value is `True`, and no other metadata keys are present.
- `key`: Overrides the property name.
- `since`: Specifies a minimum OpenAPI version.

Parsers use all these keys, along with field names and typing annotations.
Importantly, typing annotations must resolve at runtime.

Every node carries a `SourceRef` called `source_ref`.
This field links the CST to its origin in a `RawDoc`,
enabling precise error messages and source-map generation.

"""

from abc import ABC
from collections.abc import Mapping
from dataclasses import dataclass

from schema_to.core import Range
from schema_to.errors import SourceLocation

__all__ = ["SYNTHETIC", "CstNode", "SourceRef"]


# Field metadata marking a field that carries no wire data — an extension bag or
# a provenance link.  Every other field is compiled into a plan (`parse._plan`)
# from its type annotation, so a field the wire format does not describe has to
# say so.
SYNTHETIC: Mapping[str, bool] = {"synthetic": True}


@dataclass(frozen=True, slots=True)
class SourceRef:
    """A provenance link from a CST node back to its origin.

    A node parsed from a derived document
    (e.g. one schema lifted out of a schema-map file)
    points at the document it was derived from, not at the derived document,
    so a diagnostic names a place the user can actually open.

    Attributes:
        uri: URI of the original document, matching `RawDoc.origin`'s `uri`.
        json_pointer: An [RFC 6901](https://www.rfc-editor.org/rfc/rfc6901)
          pointer locating this node within that document.
        range: Where the node sits in that document's raw text.
            Until a reader reports the span of each node,
            this is the span of the part of the document that was parsed.
    """

    uri: str
    json_pointer: str
    range: Range

    def location(self) -> SourceLocation:
        """Return this reference as the location of a diagnostic."""
        return SourceLocation(self.uri, self.json_pointer, self.range)


# ruff:ignore[abstract-base-class-without-abstract-method]  # Sealed marker; abstract identity is enforced by the type system.
class CstNode(ABC):
    """Sealed marker base for every CST node.

    Concrete nodes are immutable `@dataclass(frozen=True, slots=True)` subclasses.
    There are two independent subtrees: `JsonSchemaDocument` and `OpenApiDocument`.
    """
