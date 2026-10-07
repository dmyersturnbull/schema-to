"""Tests for `Uri`: what it accepts, and how it carries a pointer."""

import pytest

from schema_to.io.uri import Uri


@pytest.mark.parametrize(
    "text", ["file:///a.json", "memory:///a.json", "urn:uuid:1234", "https://x.org/a#/b", "t://a"]
)
def test_a_uri_has_a_scheme(text: str) -> None:
    assert Uri.parse(text).scheme == text.partition(":")[0]


@pytest.mark.parametrize("text", ["", "a.json", "./a.json", "/a/b.json", "1x:a", "a b:c"])
def test_a_string_with_no_scheme_is_not_a_uri(text: str) -> None:
    with pytest.raises(ValueError, match="no scheme"):
        Uri.parse(text)


def test_the_parts_are_split_out_and_decoded() -> None:
    uri = Uri.parse("https://example.org/my%20dir/a.json#/two%20words")
    assert (uri.scheme, uri.authority, uri.path, uri.pointer) == (
        "https",
        "example.org",
        "/my dir/a.json",
        "/two words",
    )
    assert uri.document == "https://example.org/my%20dir/a.json"


@pytest.mark.parametrize(
    "text",
    ["file:///a.yaml", "memory:///a.json#/b", "urn:x:y", "test://schema#/b", "https://h/p?q=1"],
)
def test_a_uri_prints_as_it_was_written(text: str) -> None:
    """Including an empty authority, which `urlunsplit` would drop from `memory:///a`."""
    assert str(Uri.parse(text)) == text


def test_a_pointer_replaces_the_fragment() -> None:
    assert str(Uri.parse("file:///c.yaml").with_pointer("/a-data")) == "file:///c.yaml#/a-data"
    assert str(Uri.parse("file:///c.yaml#/a").with_pointer("/b")) == "file:///c.yaml#/b"


def test_an_empty_pointer_addresses_the_whole_document() -> None:
    assert str(Uri.parse("file:///c.yaml#/a").with_pointer("")) == "file:///c.yaml"


def test_characters_a_fragment_cannot_hold_are_encoded() -> None:
    uri = Uri.parse("file:///c.yaml").with_pointer("/two words")
    assert str(uri) == "file:///c.yaml#/two%20words"
    assert Uri.parse(str(uri)).pointer == "/two words"
