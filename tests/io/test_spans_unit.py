"""Where each value of a JSON or YAML text is, which the readers do not otherwise report."""

import pytest

from schema_to.core import Position
from schema_to.io.core import (
    DefaultJsonLikeReader,
    JsonReader,
    UnsupportedMediaTypeError,
    YamlReader,
)
from schema_to.io.media_type import MediaType, MediaTypes

_JSON = """{
  "a": 1,
  "b": [true, {"c": "x y"}],
  "d/e": null,
  "f": {}
}
"""

_YAML = """a: 1
b:
  - true
  - c: x y
d/e: ~
f: {}
"""


def test_json_values_are_located_by_pointer() -> None:
    spans = JsonReader().spans(_JSON)
    assert spans[""] == (Position(1, 1), Position(6, 2))
    assert spans["/a"] == (Position(2, 8), Position(2, 9))
    assert spans["/b"] == (Position(3, 8), Position(3, 28))
    assert spans["/b/0"] == (Position(3, 9), Position(3, 13))
    assert spans["/b/1/c"] == (Position(3, 21), Position(3, 26))
    assert spans["/d~1e"] == (Position(4, 10), Position(4, 14))
    assert spans["/f"] == (Position(5, 8), Position(5, 10))


def test_json_text_and_bytes_are_located_alike() -> None:
    assert JsonReader().spans(_JSON) == JsonReader().spans(_JSON.encode())


def test_a_json_scalar_document_is_located() -> None:
    assert JsonReader().spans("  true\n") == {"": (Position(1, 3), Position(1, 7))}


def test_deeply_nested_json_is_located() -> None:
    assert len(JsonReader().spans("[" * 300 + "]" * 300)) == 300


def test_yaml_values_are_located_by_pointer() -> None:
    spans = YamlReader().spans(_YAML)
    assert spans[""] == (Position(1, 1), Position(7, 1))
    assert spans["/a"] == (Position(1, 4), Position(1, 5))
    assert spans["/b/0"] == (Position(3, 5), Position(3, 9))
    assert spans["/b/1/c"] == (Position(4, 8), Position(4, 11))
    assert spans["/d~1e"] == (Position(5, 6), Position(5, 7))
    assert spans["/f"] == (Position(6, 4), Position(6, 6))


def test_a_yaml_alias_is_located_where_its_anchor_is() -> None:
    spans = YamlReader().spans("a: &x [1, 2]\nb: *x\n")
    assert spans["/b"] == spans["/a"]
    assert spans["/b/1"] == spans["/a/1"]


def test_a_yaml_document_that_pyyaml_rejects_is_not_located() -> None:
    """`yaml12` follows YAML 1.2, while PyYAML follows 1.1; a document only one accepts has no spans."""
    assert YamlReader().spans("a: [1\n") == {}


def test_an_empty_yaml_document_has_nothing_to_locate() -> None:
    assert YamlReader().spans("") == {}


@pytest.mark.parametrize(
    ("media_type", "text"), [(MediaTypes.json, '{"a": 1}'), (MediaTypes.yaml, "a: 1\n")]
)
def test_the_default_reader_locates_by_media_type(media_type: MediaType, text: str) -> None:
    assert "/a" in DefaultJsonLikeReader().spans(text, media_type)


def test_the_default_reader_rejects_a_media_type_it_cannot_read() -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        DefaultJsonLikeReader().spans("a", MediaType("text", "csv", ()))
