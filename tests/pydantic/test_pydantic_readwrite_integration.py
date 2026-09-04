"""Splitting a schema with `readOnly` / `writeOnly` properties into Read and Write classes.

A property marked one way belongs to only one variant,
and a `$ref` to a split definition has to name the variant that matches its own side.
"""

import ast

from tests.support.source import read_write_slices
from tests.support.stages import pydantic_source

# ---------------------------------------------------------------------------
# Smoke: readOnly / writeOnly split into Read/Write classes
# ---------------------------------------------------------------------------


def test_no_split_when_no_readonly_writeonly() -> None:
    schema = {"type": "object", "title": "Foo", "properties": {"name": {"type": "string"}}}
    src = pydantic_source(schema)
    assert "class Foo(BaseModel):" in src
    assert "FooRead" not in src
    assert "FooWrite" not in src


def test_readonly_writeonly_splits_into_two_classes() -> None:
    schema = {
        "type": "object",
        "title": "Foo",
        "properties": {
            "id": {"type": "string", "readOnly": True},
            "password": {"type": "string", "writeOnly": True},
            "name": {"type": "string"},
        },
    }
    src = pydantic_source(schema)
    assert "class FooRead(BaseModel):" in src
    assert "class FooWrite(BaseModel):" in src
    assert "class Foo(BaseModel):" not in src


def test_readonly_excluded_from_write_writeonly_excluded_from_read() -> None:
    schema = {
        "type": "object",
        "title": "Foo",
        "properties": {
            "id": {"type": "string", "readOnly": True},
            "password": {"type": "string", "writeOnly": True},
        },
    }
    src = pydantic_source(schema)
    read_body, write_body = read_write_slices(src, "Foo")
    assert "id" in read_body
    assert "password" not in read_body
    assert "password" in write_body
    assert "id" not in write_body


def test_plain_properties_appear_in_both_variants() -> None:
    schema = {
        "type": "object",
        "title": "Foo",
        "properties": {"id": {"type": "string", "readOnly": True}, "name": {"type": "string"}},
    }
    src = pydantic_source(schema)
    read_body, write_body = read_write_slices(src, "Foo")
    assert "name" in read_body
    assert "name" in write_body


def test_split_applies_to_defs_and_root() -> None:
    schema = {
        "type": "object",
        "title": "Root",
        "$defs": {
            "Item": {"type": "object", "properties": {"sku": {"type": "string", "readOnly": True}}}
        },
        "properties": {"secret": {"type": "string", "writeOnly": True}},
    }
    src = pydantic_source(schema)
    for name in ("ItemRead", "ItemWrite", "RootRead", "RootWrite"):
        assert f"class {name}(BaseModel):" in src


def test_read_variant_emitted_before_write_variant() -> None:
    schema = {
        "type": "object",
        "title": "Foo",
        "properties": {"id": {"type": "string", "readOnly": True}},
    }
    src = pydantic_source(schema)
    assert src.find("class FooRead(BaseModel):") < src.find("class FooWrite(BaseModel):")


def test_ref_to_split_def_resolves_to_matching_variant() -> None:
    schema = {
        "type": "object",
        "title": "Root",
        "$defs": {
            "Bar": {
                "type": "object",
                "properties": {"secret": {"type": "string", "writeOnly": True}},
            }
        },
        "properties": {"bar": {"$ref": "#/$defs/Bar", "writeOnly": True}},
        "required": ["bar"],
    }
    src = pydantic_source(schema)
    _, write_body = read_write_slices(src, "Root")
    assert "bar: BarWrite" in write_body


def test_ref_from_nonsplit_class_to_split_def_defaults_to_read() -> None:
    schema = {
        "type": "object",
        "title": "Root",
        "$defs": {
            "Bar": {
                "type": "object",
                "properties": {"secret": {"type": "string", "writeOnly": True}},
            }
        },
        "properties": {"bar": {"$ref": "#/$defs/Bar"}},
        "required": ["bar"],
    }
    src = pydantic_source(schema)
    assert "bar: BarRead" in src


def test_all_properties_writeonly_yields_empty_read_class() -> None:
    schema = {
        "type": "object",
        "title": "Foo",
        "properties": {"secret": {"type": "string", "writeOnly": True}},
    }
    src = pydantic_source(schema)
    read_body, _ = read_write_slices(src, "Foo")
    assert "secret" not in read_body
    ast.parse(src)


def test_required_writeonly_field_absent_from_read_variant() -> None:
    schema = {
        "type": "object",
        "title": "Foo",
        "properties": {"secret": {"type": "string", "writeOnly": True}},
        "required": ["secret"],
    }
    src = pydantic_source(schema)
    read_body, write_body = read_write_slices(src, "Foo")
    assert "secret" not in read_body
    assert "secret: str" in write_body
