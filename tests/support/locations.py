"""Provenance for a CST node or a diagnostic that a test builds by hand."""

from schema_to.core import Position, SourceRef

SOMEWHERE = Position(1, 1)


def source_ref(uri: str = "test:///hand-built", json_pointer: str = "") -> SourceRef:
    """Return a place that a test pretends a node or a diagnostic is at."""
    return SourceRef(uri, json_pointer, SOMEWHERE, SOMEWHERE)
