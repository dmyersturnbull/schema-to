"""Property, field, and annotation mapping from JSON Schema to Pydantic.

One property becomes one annotated field.
These compose the parse → resolve → generate → reify stages directly,
so what they assert on is the generator's output rather than the routed target's.
"""

import ast
import re
from dataclasses import replace

from tests.support.docs import json_schema_doc
from tests.support.drive import PYDANTIC
from tests.support.stages import pydantic_source


def test_simple_object_produces_base_model() -> None:
    schema = {"type": "object", "title": "User"}
    src = pydantic_source(schema)
    assert "class User(BaseModel):" in src
    assert "from pydantic import BaseModel" in src


def test_required_field_has_no_default() -> None:
    schema = {
        "type": "object",
        "title": "Item",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    src = pydantic_source(schema)
    # Required field: `name: str` with no `= None`
    assert re.search(r"name:\s*str(?!\s*\|)", src)
    assert "name: str = None" not in src


def test_optional_field_has_none_default() -> None:
    schema = {
        "type": "object",
        "title": "Item",
        "properties": {"age": {"type": "integer"}},
        "required": [],
    }
    src = pydantic_source(schema)
    assert "age: int | None = None" in src


def test_array_field_type() -> None:
    schema = {
        "type": "object",
        "title": "Collection",
        "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
        "required": ["tags"],
    }
    src = pydantic_source(schema)
    assert "list[str]" in src


def test_array_field_no_items_is_list_any() -> None:
    schema = {
        "type": "object",
        "title": "Bag",
        "properties": {"items": {"type": "array"}},
        "required": ["items"],
    }
    src = pydantic_source(schema)
    assert "list[Any]" in src
    assert "from typing import Any" in src


def test_boolean_field() -> None:
    schema = {
        "type": "object",
        "title": "Flag",
        "properties": {"active": {"type": "boolean"}},
        "required": ["active"],
    }
    src = pydantic_source(schema)
    assert "active: bool" in src


def test_number_field() -> None:
    schema = {
        "type": "object",
        "title": "Measurement",
        "properties": {"value": {"type": "number"}},
        "required": ["value"],
    }
    src = pydantic_source(schema)
    assert "value: float" in src


def test_ref_to_defs_generates_class_name() -> None:
    schema = {
        "type": "object",
        "title": "Order",
        "$defs": {"Address": {"type": "object", "properties": {"street": {"type": "string"}}}},
        "properties": {"shipping": {"$ref": "#/$defs/Address"}},
        "required": ["shipping"],
    }
    src = pydantic_source(schema)
    # The Address class must be generated.
    assert "class Address(BaseModel):" in src
    # The shipping field must reference Address.
    assert "shipping: Address" in src


def test_defs_classes_generated_before_root() -> None:
    """$defs declarations appear before the root class in the output."""
    schema = {"type": "object", "title": "Root", "$defs": {"Leaf": {"type": "object"}}}
    src = pydantic_source(schema)
    leaf_pos = src.find("class Leaf(BaseModel):")
    root_pos = src.find("class Root(BaseModel):")
    assert leaf_pos != -1
    assert root_pos != -1
    assert leaf_pos < root_pos, "Leaf should be defined before Root"


def test_roots_keeps_only_named_defs() -> None:
    """`roots` narrows generated `$defs` classes; the root class is unaffected."""
    schema = {
        "type": "object",
        "title": "Root",
        "$defs": {
            "Kept": {"type": "object", "properties": {"a": {"type": "string"}}},
            "Dropped": {"type": "object", "properties": {"b": {"type": "string"}}},
        },
    }
    route = replace(PYDANTIC, roots=frozenset({"Kept"}))
    src = route.text(json_schema_doc(schema))
    assert "class Kept(BaseModel):" in src
    assert "class Dropped(BaseModel):" not in src
    assert "class Root(BaseModel):" in src


def test_roots_none_keeps_every_def() -> None:
    """Omitting `roots` keeps today's behaviour of emitting every `$defs` entry."""
    schema = {"type": "object", "title": "Root", "$defs": {"A": {"type": "object"}}}
    src = replace(PYDANTIC, roots=None).text(json_schema_doc(schema))
    assert "class A(BaseModel):" in src


def test_anyof_nullable_produces_union_none() -> None:
    schema = {
        "type": "object",
        "title": "Nullable",
        "properties": {"val": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
        "required": ["val"],
    }
    src = pydantic_source(schema)
    assert "str | None" in src


def test_oneof_nullable_produces_union_none() -> None:
    schema = {
        "type": "object",
        "title": "OneOfNull",
        "properties": {"val": {"oneOf": [{"type": "integer"}, {"type": "null"}]}},
        "required": ["val"],
    }
    src = pydantic_source(schema)
    assert "int | None" in src


def test_enum_produces_literal() -> None:
    schema = {
        "type": "object",
        "title": "Status",
        "properties": {"state": {"enum": ["active", "inactive", "pending"]}},
        "required": ["state"],
    }
    src = pydantic_source(schema)
    assert "Literal" in src
    assert "from typing import" in src
    assert "Literal" in src


def test_const_produces_literal() -> None:
    schema = {
        "type": "object",
        "title": "Fixed",
        "properties": {"version": {"const": 1}},
        "required": ["version"],
    }
    src = pydantic_source(schema)
    assert "Literal[1]" in src


def test_type_array_with_null() -> None:
    schema = {
        "type": "object",
        "title": "Maybe",
        "properties": {"x": {"type": ["string", "null"]}},
        "required": ["x"],
    }
    src = pydantic_source(schema)
    assert "str | None" in src


def test_field_with_string_constraints() -> None:
    schema = {
        "type": "object",
        "title": "Constrained",
        "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 100}},
        "required": ["name"],
    }
    src = pydantic_source(schema)
    assert "Field(" in src
    assert "min_length=1" in src
    assert "max_length=100" in src


def test_field_is_imported_from_pydantic() -> None:
    """`Field` is used in a default, so it has to be imported from somewhere real."""
    schema = {
        "type": "object",
        "title": "Constrained",
        "properties": {"name": {"type": "string", "minLength": 1}},
        "required": ["name"],
    }
    src = pydantic_source(schema)
    assert "Field(" in src
    assert "from pydantic import BaseModel, Field" in src


def test_field_with_numeric_constraints() -> None:
    schema = {
        "type": "object",
        "title": "BoundedInt",
        "properties": {"count": {"type": "integer", "minimum": 0, "maximum": 1000}},
        "required": ["count"],
    }
    src = pydantic_source(schema)
    assert "Field(" in src
    assert "ge=0" in src
    assert "le=1000" in src


def test_title_becomes_class_name() -> None:
    schema = {"type": "object", "title": "MySpecialModel"}
    src = pydantic_source(schema)
    assert "class MySpecialModel(BaseModel):" in src


def test_display_name_fallback() -> None:
    """When there is no title, display_name is used as a fallback."""
    doc = json_schema_doc({"type": "object"}, "test://schema", display_name="user_profile")
    assert "class UserProfile(BaseModel):" in PYDANTIC.text(doc)


def test_empty_object_produces_valid_class() -> None:
    schema = {"type": "object", "title": "Empty"}
    src = pydantic_source(schema)
    assert "class Empty(BaseModel):" in src
    # Must be syntactically valid even with no fields.
    ast.parse(src)
