"""Pointers, positions, and ranges."""

import pytest

from schema_to.core import Position, Range, ptr


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


def test_a_range_covers_all_of_a_text() -> None:
    assert Range.covering("ab\ncde\n") == Range(Position(1, 1), Position(3, 1))
    assert Range.covering("ab\ncde") == Range(Position(1, 1), Position(2, 4))
    assert Range.covering("") == Range(Position(1, 1), Position(1, 1))


def test_an_empty_range_is_one_position() -> None:
    assert Range.at(2, 5) == Range(Position(2, 5), Position(2, 5))


def test_a_range_prints_its_ends() -> None:
    assert str(Range(Position(1, 1), Position(3, 4))) == "1:1-3:4"
