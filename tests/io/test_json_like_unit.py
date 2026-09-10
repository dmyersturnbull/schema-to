"""Reading and writing JSON-like bytes, chosen by media type.

The pipeline never picks a deserializer by file extension:
A document carries a media type, and these decide what that means.
"""

import pytest

from schema_to.core import JsonValue
from schema_to.io.core import (
    DefaultJsonLikeReader,
    DefaultJsonLikeWriter,
    JsonReader,
    JsonWriter,
    ReadError,
    UnsupportedMediaTypeError,
    YamlReader,
    YamlWriter,
)
from schema_to.io.media_type import MediaType, MediaTypeParam, MediaTypes

_JSON_TYPES = [MediaTypes.json, MediaTypes.json_schema, MediaTypes.openapi]
_YAML_TYPES = [MediaTypes.yaml, MediaTypes.json_schema_yaml, MediaTypes.openapi_yaml]


@pytest.mark.parametrize("media_type", _JSON_TYPES)
def test_a_json_media_type_is_read_as_json(media_type: MediaType) -> None:
    """A `+json` suffix means JSON just as much as `application/json` does."""
    assert DefaultJsonLikeReader().read(b'{"a": 1}', media_type) == {"a": 1}


@pytest.mark.parametrize("media_type", _YAML_TYPES)
def test_a_yaml_media_type_is_read_as_yaml(media_type: MediaType) -> None:
    assert DefaultJsonLikeReader().read(b"a: 1\n", media_type) == {"a": 1}


def test_a_media_type_that_is_neither_names_what_is_supported() -> None:
    with pytest.raises(UnsupportedMediaTypeError) as caught:
        DefaultJsonLikeReader().read(b"{}", MediaTypes.sql)
    assert caught.value.media_type == MediaTypes.sql
    assert "application/json" in str(caught.value)


def test_a_non_text_top_level_type_is_not_read() -> None:
    """`image/json` is not a document, whatever its subtype says."""
    with pytest.raises(UnsupportedMediaTypeError):
        DefaultJsonLikeReader().read(b"{}", MediaType("image", "json"))


@pytest.mark.parametrize("media_type", _JSON_TYPES)
def test_a_json_media_type_is_written_as_json(media_type: MediaType) -> None:
    assert DefaultJsonLikeWriter().write_str({"a": 1}, media_type) == '{"a":1}'


@pytest.mark.parametrize("media_type", _YAML_TYPES)
def test_a_yaml_media_type_is_written_as_yaml(media_type: MediaType) -> None:
    assert "a:" in DefaultJsonLikeWriter().write_str({"a": 1}, media_type)


def test_writing_an_unsupported_media_type_is_refused() -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        DefaultJsonLikeWriter().write_str({}, MediaTypes.sql)


def test_pretty_json_is_indented() -> None:
    assert "\n  " in DefaultJsonLikeWriter(pretty=True).write_str({"a": 1}, MediaTypes.json)


def test_bytes_are_encoded_as_the_charset_parameter_asks() -> None:
    """A media type may carry `charset`, and the writer has to honour it."""
    latin = MediaType("application", "json", (MediaTypeParam("charset", "latin-1"),))
    assert DefaultJsonLikeWriter().write_bytes({"a": "é"}, latin) == '{"a":"é"}'.encode("latin-1")


def test_bytes_are_utf_8_when_no_charset_is_given() -> None:
    assert DefaultJsonLikeWriter().write_bytes({"a": "é"}, MediaTypes.json) == b'{"a":"\xc3\xa9"}'


def test_malformed_json_reports_where_it_gave_up() -> None:
    """A parse failure without a position is much harder to act on."""
    with pytest.raises(ReadError) as caught:
        JsonReader().read(b'{"a": }')
    assert caught.value.line is not None
    assert caught.value.column is not None


def test_malformed_yaml_is_a_read_error() -> None:
    with pytest.raises(ReadError):
        YamlReader().read("a: [1, 2\n")


def test_json_reads_text_and_bytes_alike() -> None:
    assert JsonReader().read('{"a": 1}') == JsonReader().read(b'{"a": 1}')


def test_yaml_reads_text_and_bytes_alike() -> None:
    assert YamlReader().read("a: 1\n") == YamlReader().read(b"a: 1\n")


def test_compact_json_has_no_spaces() -> None:
    assert JsonWriter().write({"a": [1, 2]}) == '{"a":[1,2]}'


def test_yaml_round_trips_through_its_own_reader() -> None:
    data: JsonValue = {"a": 1, "b": ["x", "y"], "c": {"d": True}}
    assert YamlReader().read(YamlWriter().write(data)) == data
