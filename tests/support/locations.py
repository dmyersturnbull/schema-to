"""Provenance for a CST node or a diagnostic that a test builds by hand."""

from schema_to.core import Range
from schema_to.cst.base import SourceRef
from schema_to.errors import SourceLocation

SOMEWHERE = Range.at(1, 1)


def source_ref(uri: str = "test:///hand-built", json_pointer: str = "") -> SourceRef:
    """Return where a node that a test built by hand pretends to come from."""
    return SourceRef(uri, json_pointer, SOMEWHERE)


def location(uri: str = "test:///hand-built", json_pointer: str = "") -> SourceLocation:
    """Return a place that a test pretends a diagnostic is about."""
    return SourceLocation(uri, json_pointer, SOMEWHERE)
