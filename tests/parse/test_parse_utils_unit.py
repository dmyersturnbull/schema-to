"""The typed accessors and pointer helpers the parsers share.

A document's shape is unknown until the parser looks, so every read of a field
goes through one of these rather than an unchecked subscript.
"""

import pytest
from tests.support.docs import json_schema_doc

from schema_to.core import JsonObject
from schema_to.cst.openapi import HttpMethod, ParameterLocation
from schema_to.errors import ParseError, TranspilationError
from schema_to.io.core import DefaultJsonLikeReader
from schema_to.io.media_type import MediaTypes
from schema_to.io.source import JsonSchemaRawDoc
from schema_to.parse._utils import (
    bool_field,
    decode_raw_doc,
    enum_member,
    extract,
    int_field,
    loc,
    num_field,
    ptr,
    str_field,
    str_or,
)
from schema_to.result import Err, Ok

_DATA: JsonObject = {
    "text": "x",
    "number": 1.5,
    "whole": 3,
    "flag": True,
    "nothing": None,
    "list": [1],
}


# ---------------------------------------------------------------------------
# Enum lookup
# ---------------------------------------------------------------------------


def test_a_known_enum_value_is_found() -> None:
    assert enum_member(HttpMethod, "get") is HttpMethod.GET


def test_an_unknown_enum_value_is_none_rather_than_an_error() -> None:
    """Constructing the enum in a `try` would swallow unrelated `ValueError`s."""
    assert enum_member(HttpMethod, "teleport") is None


def test_a_value_of_the_wrong_type_is_none() -> None:
    assert enum_member(ParameterLocation, 3) is None


# ---------------------------------------------------------------------------
# JSON Pointers
# ---------------------------------------------------------------------------


def test_segments_are_joined_onto_the_parent() -> None:
    assert ptr("#", "paths", "get") == "#/paths/get"


def test_an_integer_segment_becomes_an_index() -> None:
    assert ptr("#/items", 0) == "#/items/0"


@pytest.mark.parametrize(
    ("segment", "expected"), [("a/b", "#/a~1b"), ("a~b", "#/a~0b"), ("a~/b", "#/a~0~1b")]
)
def test_a_segment_escapes_the_characters_a_pointer_reserves(segment: str, expected: str) -> None:
    """`~` and `/` both mean something in a pointer, so a name holding one has to escape it."""
    assert ptr("#", segment) == expected


def test_a_pointer_with_no_segments_is_the_parent() -> None:
    assert ptr("#") == "#"


def test_a_location_names_the_document_and_the_pointer() -> None:
    location = loc("file:///a.yaml", "#/paths")
    assert (location.doc_id, location.json_pointer) == ("file:///a.yaml", "#/paths")


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def test_a_document_is_decoded_by_its_media_type() -> None:
    doc = json_schema_doc({"type": "object"})
    assert decode_raw_doc(doc, DefaultJsonLikeReader()) == {"type": "object"}


def test_malformed_bytes_become_a_parse_error_that_says_where() -> None:
    doc = JsonSchemaRawDoc(doc_id="d", content=b'{"a": }', media_type=MediaTypes.json)
    with pytest.raises(ParseError) as caught:
        decode_raw_doc(doc, DefaultJsonLikeReader())
    assert caught.value.location is not None
    assert caught.value.location.doc_id == "d"
    assert caught.value.location.line is not None


# ---------------------------------------------------------------------------
# Unwrapping
# ---------------------------------------------------------------------------


def test_extract_returns_the_value_of_an_ok() -> None:
    errors: list[TranspilationError] = []
    assert extract(Ok(7), errors) == 7
    assert errors == []


def test_extract_accumulates_the_errors_of_an_err() -> None:
    """A parser keeps going after a bad node, so the errors pile up rather than raising."""
    errors: list[TranspilationError] = []
    first, second = ParseError("one"), ParseError("two")
    assert extract(Err.of(first, second), errors) is None
    assert errors == [first, second]


# ---------------------------------------------------------------------------
# Typed field accessors
# ---------------------------------------------------------------------------


def test_a_string_field_is_returned() -> None:
    assert str_field(_DATA, "text") == "x"


@pytest.mark.parametrize("key", ["number", "flag", "nothing", "list", "absent"])
def test_a_field_that_is_not_a_string_reads_as_none(key: str) -> None:
    assert str_field(_DATA, key) is None


def test_a_string_field_with_a_default_falls_back() -> None:
    assert str_or(_DATA, "absent", "fallback") == "fallback"


def test_a_string_field_with_a_default_prefers_the_value() -> None:
    assert str_or(_DATA, "text", "fallback") == "x"


def test_the_default_default_is_empty() -> None:
    assert not str_or(_DATA, "absent")


@pytest.mark.parametrize(("key", "expected"), [("number", 1.5), ("whole", 3)])
def test_a_numeric_field_reads_as_a_number(key: str, expected: float) -> None:
    assert num_field(_DATA, key) == expected


def test_a_boolean_is_not_a_number() -> None:
    """`True` is an `int` in Python, but `true` is not a number in JSON."""
    assert num_field(_DATA, "flag") is None


@pytest.mark.parametrize("key", ["text", "nothing", "absent"])
def test_a_field_that_is_not_numeric_reads_as_none(key: str) -> None:
    assert num_field(_DATA, key) is None


def test_an_integer_field_is_returned() -> None:
    assert int_field(_DATA, "whole") == 3


def test_a_float_is_not_an_integer() -> None:
    assert int_field(_DATA, "number") is None


def test_a_boolean_is_not_an_integer() -> None:
    assert int_field(_DATA, "flag") is None


def test_a_boolean_field_is_returned() -> None:
    assert bool_field(_DATA, "flag") is True


@pytest.mark.parametrize("key", ["whole", "text", "nothing", "absent"])
def test_a_field_that_is_not_a_boolean_reads_as_none(key: str) -> None:
    """A `1` is not a `true`; coercing one would hide a malformed document."""
    assert bool_field(_DATA, key) is None
