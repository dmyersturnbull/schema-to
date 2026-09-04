"""Guessing a document's kind from its bytes, when the filename does not settle it."""

import orjson
import pytest

from schema_to.io.routing import DocType, is_schema_map, peek_doc_type


def _json(data: object) -> bytes:
    return orjson.dumps(data)


def test_an_openapi_version_string_names_an_openapi_document() -> None:
    assert peek_doc_type(_json({"openapi": "3.1.0", "info": {}})) is DocType.OPENAPI


def test_a_non_string_openapi_key_is_not_taken_as_a_version() -> None:
    """`openapi: 3` is not a version string, so the document is not claimed on that alone."""
    assert peek_doc_type(_json({"openapi": 3})) is None


@pytest.mark.parametrize(
    "keyword", ["$schema", "$ref", "$dynamicRef", "$defs", "definitions", "type", "properties"]
)
def test_a_top_level_json_schema_keyword_names_a_schema(keyword: str) -> None:
    assert peek_doc_type(_json({keyword: "x"})) is DocType.JSON_SCHEMA


def test_yaml_is_read_when_the_bytes_are_not_json() -> None:
    assert peek_doc_type(b"openapi: 3.1.0\ninfo: {}\n") is DocType.OPENAPI


@pytest.mark.parametrize("content", [b"", b"not: [valid", b"[1, 2, 3]", b'"a string"'])
def test_bytes_that_are_not_an_object_are_claimed_by_nothing(content: bytes) -> None:
    assert peek_doc_type(content) is None
    assert not is_schema_map(content)


def test_an_object_of_nothing_recognisable_is_claimed_by_nothing() -> None:
    assert peek_doc_type(_json({"name": "thing", "port": 8080})) is None


def test_keywords_one_level_down_look_like_a_schema_map() -> None:
    assert is_schema_map(_json({"thing": {"type": "object"}, "stamp": {"type": "string"}}))


def test_one_named_schema_is_enough() -> None:
    assert is_schema_map(_json({"a": {"port": 1}, "b": {"type": "string"}}))


def test_a_top_level_keyword_rules_out_a_schema_map() -> None:
    """Keywords at the top mean the file is one schema, not a map of them."""
    assert not is_schema_map(_json({"type": "object", "properties": {"a": {"type": "string"}}}))


def test_an_openapi_document_is_not_a_schema_map() -> None:
    assert not is_schema_map(_json({"openapi": "3.1.0", "components": {"schemas": {}}}))


def test_an_object_of_plain_values_is_not_claimed() -> None:
    """A config file of strings has no schema keywords anywhere, so nothing claims it."""
    assert not is_schema_map(_json({"host": "localhost", "port": 8080}))


def test_an_empty_object_is_not_claimed() -> None:
    assert not is_schema_map(_json({}))
