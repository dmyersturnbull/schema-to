"""The `x-pydantic-frozen`, `x-pydantic-skip`, and `x-pydantic-class` extension keywords.

Each is addressed to this generator, so a malformed value is an error rather than an ignored key.
"""

from tests.support.docs import json_schema_doc
from tests.support.drive import PYDANTIC
from tests.support.source import read_write_slices
from tests.support.stages import pydantic_source


def test_x_pydantic_frozen_emits_config_dict() -> None:
    schema = {
        "type": "object",
        "title": "Point",
        "x-pydantic-frozen": True,
        "properties": {"x": {"type": "number"}},
        "required": ["x"],
    }
    src = pydantic_source(schema)
    assert "class Point(BaseModel):" in src
    assert "model_config = ConfigDict(frozen=True)" in src
    assert "from pydantic import BaseModel, ConfigDict" in src


def test_without_x_pydantic_frozen_no_config_dict() -> None:
    schema = {"type": "object", "title": "Point", "properties": {"x": {"type": "number"}}}
    src = pydantic_source(schema)
    assert "ConfigDict" not in src


def test_x_pydantic_frozen_bad_value_fails() -> None:
    schema = {"type": "object", "title": "Point", "x-pydantic-frozen": "yes"}
    assert PYDANTIC.errors(json_schema_doc(schema))


def test_x_pydantic_skip_omits_field() -> None:
    schema = {
        "type": "object",
        "title": "Foo",
        "properties": {
            "name": {"type": "string"},
            "internal": {"type": "string", "x-pydantic-skip": True},
        },
        "required": ["name", "internal"],
    }
    src = pydantic_source(schema)
    assert "name: str" in src
    assert "internal" not in src


def test_x_pydantic_skip_bad_value_fails() -> None:
    schema = {
        "type": "object",
        "title": "Foo",
        "properties": {"name": {"type": "string", "x-pydantic-skip": "yes"}},
    }
    assert PYDANTIC.errors(json_schema_doc(schema))


# ---------------------------------------------------------------------------
# Smoke: `x-pydantic-class` extension keyword
# ---------------------------------------------------------------------------


def test_x_pydantic_class_renames_object_def() -> None:
    schema = {
        "type": "object",
        "title": "Root",
        "$defs": {
            "internal_address": {
                "type": "object",
                "x-pydantic-class": "Address",
                "properties": {"street": {"type": "string"}},
            }
        },
        "properties": {"shipping": {"$ref": "#/$defs/internal_address"}},
        "required": ["shipping"],
    }
    src = pydantic_source(schema)
    assert "class Address(BaseModel):" in src
    assert "class InternalAddress(BaseModel):" not in src
    assert "shipping: Address" in src


def test_x_pydantic_class_renames_type_alias_def() -> None:
    schema = {
        "type": "object",
        "title": "Root",
        "$defs": {"customer_id": {"type": "string", "x-pydantic-class": "CustomerIdentifier"}},
        "properties": {"id": {"$ref": "#/$defs/customer_id"}},
        "required": ["id"],
    }
    src = pydantic_source(schema)
    assert "type CustomerIdentifier = str" in src
    assert "id: CustomerIdentifier" in src


def test_x_pydantic_class_renames_root() -> None:
    schema = {"type": "object", "title": "Root", "x-pydantic-class": "Overridden"}
    src = pydantic_source(schema)
    assert "class Overridden(BaseModel):" in src
    assert "class Root(BaseModel):" not in src


def test_x_pydantic_class_with_readonly_writeonly_split() -> None:
    schema = {
        "type": "object",
        "title": "Root",
        "$defs": {
            "internal_item": {
                "type": "object",
                "x-pydantic-class": "Item",
                "properties": {"sku": {"type": "string", "readOnly": True}},
            }
        },
        "properties": {"item": {"$ref": "#/$defs/internal_item", "readOnly": True}},
        "required": ["item"],
    }
    src = pydantic_source(schema)
    assert "class ItemRead(BaseModel):" in src
    assert "class ItemWrite(BaseModel):" in src
    read_body, _ = read_write_slices(src, "Root")
    assert "item: ItemRead" in read_body


def test_x_pydantic_class_bad_value_fails() -> None:
    schema = {"type": "object", "title": "Foo", "x-pydantic-class": ""}
    assert PYDANTIC.errors(json_schema_doc(schema))
