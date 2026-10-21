"""Pointers and positions."""

import pytest

from schema_to.core import Position, ptr


@pytest.mark.parametrize(
    ("segment", "expected"), [("a/b", "#/a~1b"), ("a~b", "#/a~0b"), ("a~/b", "#/a~0~1b")]
)
def test_a_segment_escapes_the_characters_a_pointer_reserves(segment: str, expected: str) -> None:
    """`~` and `/` both mean something in a pointer, so a name holding one has to escape it."""
    assert ptr("#", segment) == expected


def test_a_pointer_with_no_segments_is_the_parent() -> None:
    assert ptr("#") == "#"


def test_segments_are_joined_onto_the_parent() -> None:
    assert ptr("#", "paths", "get") == "#/paths/get"


def test_an_integer_segment_becomes_an_index() -> None:
    assert ptr("#/items", 0) == "#/items/0"


def test_a_position_prints_as_line_and_column() -> None:
    assert str(Position(3, 7)) == "3:7"


def test_a_position_may_have_only_a_line() -> None:
    assert str(Position(3, None)) == "3"
