"""Tests for `RawDoc`: its identity, the name computed from it, and where it really lives."""

import pytest
from tests.support.docs import json_schema_doc

from schema_to.errors import SourceLocation, TextRange
from schema_to.io.media_type import MediaTypes
from schema_to.io.memory import memory_uri
from schema_to.io.source import JsonSchemaRawDoc, Origin, RawDoc


@pytest.mark.parametrize("uri", ["", "main.yaml", "./main.yaml", "/abs/main.yaml", "a b:c"])
def test_an_identifier_that_is_not_a_uri_is_rejected(uri: str) -> None:
    with pytest.raises(ValueError, match="must be a URI"):
        RawDoc(uri=uri, content=b"{}", media_type=MediaTypes.json)


def test_a_subclass_is_validated_too() -> None:
    with pytest.raises(ValueError, match="must be a URI"):
        JsonSchemaRawDoc(uri="main.yaml", content=b"{}", media_type=MediaTypes.json)


def test_a_custom_scheme_is_a_uri() -> None:
    doc = RawDoc(uri=memory_uri("users.schema.json"), content=b"{}", media_type=MediaTypes.json)
    assert doc.uri == "memory:///users.schema.json"
    assert doc.display_name == "users"


def test_the_display_name_is_computed_from_the_uri() -> None:
    assert json_schema_doc({}, "file:///dir/users.schema.json").display_name == "users"


def test_a_document_is_its_own_provenance() -> None:
    doc = json_schema_doc({}, "file:///a.json")
    assert doc.origin is None
    assert doc.provenance == Origin("file:///a.json")
    assert doc.location() == SourceLocation("file:///a.json", "")
    assert doc.location("/x", at=TextRange(2, 5)) == SourceLocation(
        "file:///a.json", "/x", TextRange(2, 5)
    )


def test_a_derived_document_locates_things_in_the_original() -> None:
    origin = Origin("file:///c.yaml", "/thing", TextRange(10, 1, 14, 1))
    doc = JsonSchemaRawDoc(
        uri="file:///c.yaml#/thing", content=b"{}", media_type=MediaTypes.json, origin=origin
    )
    assert doc.provenance == origin
    # A position in re-encoded content means nothing in the original, so the original's range wins.
    assert doc.location("/properties/a", at=TextRange(1, 40)) == SourceLocation(
        "file:///c.yaml", "/thing/properties/a", TextRange(10, 1, 14, 1)
    )


def test_a_memory_uri_encodes_what_a_path_cannot_hold() -> None:
    assert memory_uri("two words") == "memory:///two%20words"
