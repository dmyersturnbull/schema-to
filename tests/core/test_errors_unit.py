"""How a diagnostic prints its location."""

from tests.support.locations import location, source_ref

from schema_to.core import Position, Range
from schema_to.cst.base import SourceRef
from schema_to.errors import ParseError, SourceLocation, TranspilationWarning


def test_a_location_prints_the_uri_the_pointer_and_where_it_starts() -> None:
    where = SourceLocation("file:///a.yaml", "/paths", Range(Position(3, 7), Position(4, 1)))
    assert str(where) == "file:///a.yaml:/paths:3:7"


def test_a_location_of_a_whole_document_omits_the_pointer() -> None:
    assert str(SourceLocation("file:///a.yaml", "", Range.at(1, 1))) == "file:///a.yaml:1:1"


def test_a_diagnostic_names_where_it_is() -> None:
    where = location("file:///a.yaml", "/x")
    assert str(ParseError("bad", location=where)) == "bad at file:///a.yaml:/x:1:1"
    warning = TranspilationWarning("odd", code="odd-thing", location=where)
    assert str(warning) == "odd [odd-thing] at file:///a.yaml:/x:1:1"


def test_a_source_ref_is_a_location() -> None:
    ref = source_ref("file:///a.yaml", "/x")
    assert ref == SourceRef("file:///a.yaml", "/x", ref.range)
    assert ref.location() == location("file:///a.yaml", "/x")
