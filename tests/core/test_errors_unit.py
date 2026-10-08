"""How a diagnostic prints its location."""

from tests.support.locations import source_ref

from schema_to.core import Position, SourceRef
from schema_to.errors import ParseError, TranspilationWarning


def test_a_place_prints_the_uri_the_pointer_and_where_it_starts() -> None:
    where = SourceRef("file:///a.yaml", "/paths", Position(3, 7), Position(4, 1))
    assert str(where) == "file:///a.yaml:/paths:3:7"


def test_a_place_with_only_a_line_prints_just_the_line() -> None:
    assert str(SourceRef("file:///a.yaml", "", Position(3, None), None)) == "file:///a.yaml:3"


def test_a_place_with_no_position_prints_just_the_file() -> None:
    assert str(SourceRef("file:///a.yaml", "/x", None, None)) == "file:///a.yaml:/x"


def test_a_diagnostic_names_where_it_is() -> None:
    where = source_ref("file:///a.yaml", "/x")
    assert str(ParseError("bad", location=where)) == "bad at file:///a.yaml:/x:1:1"
    warning = TranspilationWarning("odd", code="odd-thing", location=where)
    assert str(warning) == "odd [odd-thing] at file:///a.yaml:/x:1:1"
