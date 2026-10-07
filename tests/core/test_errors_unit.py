"""Tests for how a diagnostic prints its location."""

from schema_to.cst.base import SourceRef, location_of
from schema_to.errors import ParseError, SourceLocation, TextRange, TranspilationWarning


def test_a_location_prints_the_uri_the_pointer_and_the_position() -> None:
    location = SourceLocation("file:///a.yaml", "/paths", TextRange(3, 7, 4, 1))
    assert str(location) == "file:///a.yaml:/paths:3:7"
    assert (location.line, location.column) == (3, 7)


def test_a_location_without_a_position_omits_it() -> None:
    location = SourceLocation("file:///a.yaml", "")
    assert str(location) == "file:///a.yaml"
    assert (location.line, location.column) == (None, None)


def test_a_diagnostic_names_where_it_is() -> None:
    location = SourceLocation("file:///a.yaml", "/x")
    assert str(ParseError("bad", location=location)) == "bad at file:///a.yaml:/x"
    warning = TranspilationWarning("odd", code="odd-thing", location=location)
    assert str(warning) == "odd [odd-thing] at file:///a.yaml:/x"


def test_a_source_ref_is_a_location() -> None:
    ref = SourceRef("file:///a.yaml", "/x")
    assert ref.location() == SourceLocation("file:///a.yaml", "/x")
    assert location_of(ref) == ref.location()


def test_a_synthesized_node_has_no_location() -> None:
    assert location_of(None) is None
