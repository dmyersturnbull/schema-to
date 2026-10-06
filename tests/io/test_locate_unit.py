"""Finding the line and column a JSON Pointer names in raw JSON or YAML text."""

import pytest

from schema_to.errors import SourceLocation
from schema_to.io.locate import DocumentLocator, TextPosition, locate, split_doc_id
from schema_to.io.media_type import MediaType, MediaTypes
from schema_to.io.source import JsonSchemaRawDoc, SchemaMapRawDoc

_JSON = """{
  "title": "A",
  "properties": {
    "a/b": {"type": "string"},
    "list": {
      "allOf": [
        {"type": "object"},
        {"$ref": "#/$defs/x"}
      ]
    }
  }
}
"""

_YAML = """# leading comment
title: A
properties:
  name:
    type: string
  'quoted key':
    type: integer
  list:
    allOf:
      - type: object
      -
        $ref: '#/$defs/x'
  compact:
  - type: string
  inline: {type: string}
"""


@pytest.mark.parametrize(
    ("pointer", "expected"),
    [
        ("", TextPosition(1, 1)),
        ("/title", TextPosition(2, 3)),
        ("/properties/a~1b", TextPosition(4, 5)),
        ("/properties/list/allOf/0", TextPosition(7, 9)),
        ("/properties/list/allOf/1/$ref", TextPosition(8, 10)),
    ],
)
def test_json_pointers_are_found_exactly(pointer: str, expected: TextPosition) -> None:
    assert locate(_JSON, MediaTypes.json_schema, pointer) == expected


@pytest.mark.parametrize(
    ("pointer", "expected"),
    [
        ("", TextPosition(2, 1)),
        ("/properties/name", TextPosition(4, 3)),
        ("/properties/name/type", TextPosition(5, 5)),
        ("/properties/quoted key/type", TextPosition(7, 5)),
        ("/properties/list/allOf/0", TextPosition(10, 9)),
        ("/properties/list/allOf/1/$ref", TextPosition(12, 9)),
        ("/properties/compact/0/type", TextPosition(14, 5)),
    ],
)
def test_yaml_block_pointers_are_found(pointer: str, expected: TextPosition) -> None:
    assert locate(_YAML, MediaTypes.yaml, pointer) == expected


@pytest.mark.parametrize(
    ("text", "media_type", "pointer", "expected"),
    [
        (_JSON, MediaTypes.json, "/properties/missing", TextPosition(3, 3)),
        (_JSON, MediaTypes.json, "/properties/list/allOf/9", TextPosition(6, 7)),
        (_YAML, MediaTypes.yaml, "/properties/missing", TextPosition(3, 1)),
        (_YAML, MediaTypes.yaml, "/properties/inline/type", TextPosition(15, 3)),
    ],
    ids=["json-member", "json-element", "yaml-member", "yaml-flow"],
)
def test_an_unfollowable_pointer_gives_its_deepest_ancestor(
    text: str, media_type: MediaType, pointer: str, expected: TextPosition
) -> None:
    """A YAML flow collection, or a missing member, still points into the right neighbourhood."""
    assert locate(text, media_type, pointer) == expected


def test_malformed_json_gives_the_deepest_node_read() -> None:
    assert locate('{"a": {"b": [1, ', MediaTypes.json, "/a/b/5") == TextPosition(1, 8)


def test_empty_text_has_no_position() -> None:
    assert locate("", MediaTypes.yaml, "/a") is None


@pytest.mark.parametrize(
    ("doc_id", "pointer", "expected"),
    [
        ("file:///x/a.yaml", "/p", ("file:///x/a.yaml", "/p")),
        ("file:///x/a.yaml#/thing", "/properties/p", ("file:///x/a.yaml", "/thing/properties/p")),
        ("file:///x/a.yaml#/thing", None, ("file:///x/a.yaml", "/thing")),
        ("file:///x/a.yaml#anchor", "/p", ("file:///x/a.yaml#anchor", "/p")),
    ],
)
def test_a_virtual_document_id_splits_into_its_file_and_pointer(
    doc_id: str, pointer: str | None, expected: tuple[str, str]
) -> None:
    assert split_doc_id(doc_id, pointer) == expected


def test_the_locator_fills_in_a_location_in_a_split_file() -> None:
    """A schema carved out of a schema-map file is located in the file it came from."""
    doc = SchemaMapRawDoc(
        doc_id="file:///x/catalog.yaml",
        content=b"first:\n  type: string\nsecond:\n  properties:\n    p:\n      type: string\n",
        media_type=MediaTypes.yaml,
        display_name="catalog",
    )
    locator = DocumentLocator({doc.doc_id: doc})
    located = locator.fill(SourceLocation("file:///x/catalog.yaml#/second", "/properties/p"))
    assert (located.line, located.column) == (5, 5)


def test_the_locator_keeps_a_location_it_cannot_place() -> None:
    doc = JsonSchemaRawDoc(
        doc_id="file:///x/a.json", content=b"{}", media_type=MediaTypes.json, display_name="a"
    )
    locator = DocumentLocator({doc.doc_id: doc})
    unknown = SourceLocation("urn:somewhere-else", "/a")
    assert locator.fill(unknown) is unknown
    known = SourceLocation("file:///x/a.json", "", line=3, column=4)
    assert locator.fill(known) is known
