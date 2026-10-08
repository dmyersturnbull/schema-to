"""Tests for `RawDoc`: its identity, the name computed from it, and where it really lives."""

import pytest
from tests.support.docs import json_schema_doc

from schema_to.core import Position, SourceRef
from schema_to.io.media_type import MediaTypes
from schema_to.io.memory import memory_uri
from schema_to.io.source import JsonSchemaRawDoc, RawDoc


@pytest.mark.parametrize("uri", ["", "main.yaml", "./main.yaml", "/abs/main.yaml", "a b:c"])
def test_an_identifier_that_is_not_a_uri_is_rejected(uri: str) -> None:
    with pytest.raises(ValueError, match="no scheme"):
        RawDoc.original(uri, b"{}", MediaTypes.json)


def test_a_subclass_is_validated_too() -> None:
    with pytest.raises(ValueError, match="no scheme"):
        JsonSchemaRawDoc.original("main.yaml", b"{}", MediaTypes.json)


def test_a_custom_scheme_is_a_uri() -> None:
    doc = RawDoc.original(memory_uri("users.schema.json"), b"{}", MediaTypes.json)
    assert doc.uri == "memory:///users.schema.json"
    assert doc.display_name == "users"


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("file:///dir/users.schema.json", "users"),
        ("file:///dir/catalog.yaml", "catalog"),
        ("memory:///thing", "thing"),
        ("https://example.com/a/b/product.json", "product"),
        ("file:///my%20schema.json", "my schema"),
        ("test://schema", ""),
    ],
)
def test_the_display_name_is_the_last_path_segment_before_its_first_dot(
    uri: str, expected: str
) -> None:
    assert json_schema_doc({}, uri).display_name == expected


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
    assert json_schema_doc({}, uri).display_name == expected


def test_a_whole_file_is_its_own_origin() -> None:
    doc = JsonSchemaRawDoc.original(
        "file:///a.json", b'{\n  "type": "object"\n}\n', MediaTypes.json
    )
    assert doc.origin == SourceRef("file:///a.json", "", Position(1, 1), Position(4, 1))
    assert doc.ref("") == doc.origin


def test_a_derived_document_locates_things_in_the_original() -> None:
    origin = SourceRef("file:///c.yaml", "/thing", Position(2, 1), Position(5, 1))
    doc = JsonSchemaRawDoc(
        uri="file:///c.yaml#/thing", content=b"{}", media_type=MediaTypes.json, origin=origin
    )
    assert doc.ref("/properties/a") == SourceRef(
        "file:///c.yaml", "/thing/properties/a", origin.start, origin.end
    )


def test_a_memory_uri_encodes_what_a_path_cannot_hold() -> None:
    assert memory_uri("two words") == "memory:///two%20words"
