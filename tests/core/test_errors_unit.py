"""How a diagnostic prints its location."""

from tests.support.locations import source_ref

from schema_to.core import Position, Range, SourceRef
from schema_to.errors import ParseError, TranspilationWarning


def test_a_place_prints_the_uri_the_pointer_and_where_it_starts() -> None:
    where = SourceRef("file:///a.yaml", "/paths", Range(Position(3, 7), Position(4, 1)))
    assert str(where) == "file:///a.yaml:/paths:3:7"


def test_a_place_in_a_whole_file_omits_the_pointer() -> None:
    assert str(SourceRef("file:///a.yaml", "", Range.at(1, 1))) == "file:///a.yaml:1:1"


def test_a_diagnostic_names_where_it_is() -> None:
    where = source_ref("file:///a.yaml", "/x")
    assert str(ParseError("bad", location=where)) == "bad at file:///a.yaml:/x:1:1"
    warning = TranspilationWarning("odd", code="odd-thing", location=where)
    assert str(warning) == "odd [odd-thing] at file:///a.yaml:/x:1:1"
