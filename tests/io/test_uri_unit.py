"""Tests for document URIs: validity, fragments, and the name computed from them."""

import pytest

from schema_to.io.uri import display_name, is_uri, pointer_uri


@pytest.mark.parametrize(
    "text", ["file:///a.json", "memory:///a.json", "urn:uuid:1234", "https://x.org/a#/b", "t://a"]
)
def test_a_scheme_and_no_whitespace_make_a_uri(text: str) -> None:
    assert is_uri(text)


@pytest.mark.parametrize("text", ["", "a.json", "./a.json", "/a/b.json", "1x:a", "file:///a b"])
def test_anything_else_is_not(text: str) -> None:
    assert not is_uri(text)


def test_a_pointer_becomes_the_fragment() -> None:
    assert pointer_uri("file:///c.yaml", "/a-data") == "file:///c.yaml#/a-data"


def test_an_existing_fragment_is_replaced_not_nested() -> None:
    assert pointer_uri("file:///c.yaml#/a", "/b") == "file:///c.yaml#/b"


def test_an_empty_pointer_is_the_whole_document() -> None:
    assert pointer_uri("file:///c.yaml#/a", "") == "file:///c.yaml"


def test_characters_a_uri_cannot_hold_are_encoded() -> None:
    uri = pointer_uri("file:///c.yaml", "/two words")
    assert uri == "file:///c.yaml#/two%20words"
    assert is_uri(uri)


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("file:///dir/users.schema.json", "users"),
        ("file:///dir/catalog.yaml", "catalog"),
        ("memory:///thing", "thing"),
        ("https://example.com/a/b/product.json", "product"),
        ("file:///my%20schema.json", "my schema"),
    ],
)
def test_the_name_is_the_last_path_segment_before_its_first_dot(uri: str, expected: str) -> None:
    assert display_name(uri) == expected


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("file:///catalog.yaml#/author-data", "author-data"),
        ("file:///catalog.yaml#/v1.0", "v1.0"),
        ("file:///catalog.yaml#/a~1b", "a/b"),
        ("file:///catalog.yaml#/a~0b", "a~b"),
        ("file:///catalog.yaml#/two%20words", "two words"),
        ("file:///api.yaml#/components/schemas/Pet", "Pet"),
    ],
)
def test_a_fragment_names_a_document_carved_out_of_a_file(uri: str, expected: str) -> None:
    """The file is shared by every document carved out of it, so its name cannot tell them apart."""
    assert display_name(uri) == expected


@pytest.mark.parametrize("uri", ["test://schema", "memory:", "file:///"])
def test_a_uri_with_no_path_has_no_name(uri: str) -> None:
    assert not display_name(uri)
