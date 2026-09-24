"""Narrowing an arbitrary JSON value to the shape a caller needs.

The parser reads documents whose shape is not known until it looks,
so every step down into one goes through a check here.
"""

import pytest

from schema_to.core import (
    JsonValue,
    as_array,
    as_object,
    is_json_array_limb,
    is_json_compound,
    is_json_object_limb,
    is_json_primitive,
    is_json_primitive_mapping,
    is_json_primitive_sequence,
)

_PRIMITIVES: list[JsonValue] = [None, True, 1, 1.5, "text"]


@pytest.mark.parametrize("value", _PRIMITIVES)
def test_a_scalar_is_a_primitive(value: JsonValue) -> None:
    assert is_json_primitive(value)


@pytest.mark.parametrize("value", [[], {}, [1], {"a": 1}])
def test_a_container_is_not_a_primitive(value: JsonValue) -> None:
    assert not is_json_primitive(value)


@pytest.mark.parametrize("value", [[], {}, [1], {"a": 1}])
def test_a_container_is_compound(value: JsonValue) -> None:
    assert is_json_compound(value)


@pytest.mark.parametrize("value", _PRIMITIVES)
def test_a_scalar_is_not_compound(value: JsonValue) -> None:
    assert not is_json_compound(value)


def test_an_object_is_recovered_as_a_mapping() -> None:
    assert as_object({"a": 1}) == {"a": 1}


@pytest.mark.parametrize("value", [[1], "text", 1, None])
def test_anything_but_an_object_recovers_as_none(value: JsonValue) -> None:
    assert as_object(value) is None


def test_an_array_is_recovered_as_a_sequence() -> None:
    assert as_array([1, 2]) == [1, 2]


def test_a_string_is_never_an_array() -> None:
    """A `str` is a `Sequence`, but a JSON array it is not."""
    assert as_array("text") is None


@pytest.mark.parametrize("value", [{"a": 1}, 1, None])
def test_anything_but_an_array_recovers_as_none(value: JsonValue) -> None:
    assert as_array(value) is None


def test_an_array_of_scalars_is_a_limb() -> None:
    """A limb is a container the parser can read without recursing into it."""
    assert is_json_array_limb([1, "a", None, True])


def test_an_array_holding_a_container_is_not_a_limb() -> None:
    assert not is_json_array_limb([1, {"a": 1}])


def test_an_object_is_not_an_array_limb() -> None:
    assert not is_json_array_limb({"a": 1})


def test_an_object_of_scalars_is_a_limb() -> None:
    assert is_json_object_limb({"a": 1, "b": None})


def test_an_object_holding_a_container_is_not_a_limb() -> None:
    assert not is_json_object_limb({"a": [1]})


def test_an_array_is_not_an_object_limb() -> None:
    assert not is_json_object_limb([1, 2])


def test_a_sequence_of_scalars_is_recognised() -> None:
    assert is_json_primitive_sequence([1, "a", None])


def test_a_sequence_holding_a_container_is_not() -> None:
    assert not is_json_primitive_sequence([1, [2]])


def test_a_mapping_of_scalars_is_recognised() -> None:
    assert is_json_primitive_mapping({"a": 1, "b": "x"})


def test_a_mapping_holding_a_container_is_not() -> None:
    assert not is_json_primitive_mapping({"a": {"b": 1}})


def test_an_empty_container_is_vacuously_primitive() -> None:
    assert is_json_primitive_sequence([])
    assert is_json_primitive_mapping({})
