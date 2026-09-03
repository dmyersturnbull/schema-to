"""Tests for the JSON Schema → Pydantic transpiler pipeline.

Covers:

- Property: generated Python source is always syntactically valid.
- Smoke tests: specific schemas produce expected class / field shapes.
- Smoke tests: `x-pydantic-enum` generates `Enum`/`StrEnum`/`IntEnum` classes.
- Integration: full parse → resolve → generate → reify pipeline.
- Failure: boolean root schema cannot be transpiled.
"""

import ast
import re
from dataclasses import replace

import pytest
from hypothesis import HealthCheck, given, settings
from tests.strategies.restricted import json_schema_with_defs_st, object_schema_st
from tests.support.docs import DEFAULT_SCHEMA_ID, json_schema_doc, openapi_doc
from tests.support.drive import PYDANTIC
from tests.support.stages import pydantic_source
from tests.support.types import JsonLike

from schema_to import Err, JsonSchemaParser, JsonSchemaRefResolver, Ok, PydanticTransformer

_PARSER = JsonSchemaParser()


def _transpile(data: JsonLike, doc_id: str = DEFAULT_SCHEMA_ID) -> str:
    """Run the full pipeline and return the emitted Python source."""
    return PYDANTIC.text(json_schema_doc(data, doc_id))


# ---------------------------------------------------------------------------
# Property: generated source is always valid Python
# ---------------------------------------------------------------------------


@given(schema=object_schema_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_object_schema_generates_valid_python(schema: dict) -> None:
    """Any object-typed schema must produce syntactically valid Python."""
    src = pydantic_source(schema)
    try:
        ast.parse(src)
    except SyntaxError as exc:
        pytest.fail(f"Generated invalid Python:\n{src}\nError: {exc}")


@given(schema=json_schema_with_defs_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_schema_with_defs_generates_valid_python(schema: dict) -> None:
    """Schemas with $defs and $ref pointers must produce syntactically valid Python."""
    src = _transpile(schema)
    try:
        ast.parse(src)
    except SyntaxError as exc:
        pytest.fail(f"Generated invalid Python:\n{src}\nError: {exc}")


# ---------------------------------------------------------------------------
# Property: generation is idempotent (second parse of output produces same AST)
# ---------------------------------------------------------------------------


@given(schema=object_schema_st())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_generation_is_stable(schema: dict) -> None:
    """Generating from the same CST twice yields identical source."""
    cst_r = _PARSER.apply(json_schema_doc(schema))
    assert isinstance(cst_r, Ok)
    resolver = JsonSchemaRefResolver()
    res_r = resolver.apply(cst_r.value)
    assert isinstance(res_r, Ok)

    src1 = pydantic_source(schema)
    src2 = pydantic_source(schema)
    assert src1 == src2, "Generation is not stable across two calls"


# ---------------------------------------------------------------------------
# Smoke: simple object → BaseModel
# ---------------------------------------------------------------------------


def test_simple_object_produces_base_model() -> None:
    schema = {"type": "object", "title": "User"}
    src = _transpile(schema)
    assert "class User(BaseModel):" in src
    assert "from pydantic import BaseModel" in src


def test_required_field_has_no_default() -> None:
    schema = {
        "type": "object",
        "title": "Item",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    src = _transpile(schema)
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
    src = _transpile(schema)
    assert "age: int | None = None" in src


def test_array_field_type() -> None:
    schema = {
        "type": "object",
        "title": "Collection",
        "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
        "required": ["tags"],
    }
    src = _transpile(schema)
    assert "list[str]" in src


def test_array_field_no_items_is_list_any() -> None:
    schema = {
        "type": "object",
        "title": "Bag",
        "properties": {"items": {"type": "array"}},
        "required": ["items"],
    }
    src = _transpile(schema)
    assert "list[Any]" in src
    assert "from typing import Any" in src


def test_boolean_field() -> None:
    schema = {
        "type": "object",
        "title": "Flag",
        "properties": {"active": {"type": "boolean"}},
        "required": ["active"],
    }
    src = _transpile(schema)
    assert "active: bool" in src


def test_number_field() -> None:
    schema = {
        "type": "object",
        "title": "Measurement",
        "properties": {"value": {"type": "number"}},
        "required": ["value"],
    }
    src = _transpile(schema)
    assert "value: float" in src


# ---------------------------------------------------------------------------
# Smoke: $ref to $defs
# ---------------------------------------------------------------------------


def test_ref_to_defs_generates_class_name() -> None:
    schema = {
        "type": "object",
        "title": "Order",
        "$defs": {"Address": {"type": "object", "properties": {"street": {"type": "string"}}}},
        "properties": {"shipping": {"$ref": "#/$defs/Address"}},
        "required": ["shipping"],
    }
    src = _transpile(schema)
    # The Address class must be generated.
    assert "class Address(BaseModel):" in src
    # The shipping field must reference Address.
    assert "shipping: Address" in src


def test_defs_classes_generated_before_root() -> None:
    """$defs declarations appear before the root class in the output."""
    schema = {"type": "object", "title": "Root", "$defs": {"Leaf": {"type": "object"}}}
    src = _transpile(schema)
    leaf_pos = src.find("class Leaf(BaseModel):")
    root_pos = src.find("class Root(BaseModel):")
    assert leaf_pos != -1
    assert root_pos != -1
    assert leaf_pos < root_pos, "Leaf should be defined before Root"


# ---------------------------------------------------------------------------
# Smoke: `roots` restricts which $defs get their own declaration
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Smoke: readOnly / writeOnly split into Read/Write classes
# ---------------------------------------------------------------------------


def _split_slices(src: str, name: str) -> tuple[str, str]:
    """Return the (Read body, Write body) source slices for *name*."""
    read_pos = src.find(f"class {name}Read(BaseModel):")
    write_pos = src.find(f"class {name}Write(BaseModel):")
    assert read_pos != -1
    assert write_pos != -1
    if read_pos < write_pos:
        return src[read_pos:write_pos], src[write_pos:]
    return src[read_pos:], src[write_pos:read_pos]


def test_no_split_when_no_readonly_writeonly() -> None:
    schema = {"type": "object", "title": "Foo", "properties": {"name": {"type": "string"}}}
    src = _transpile(schema)
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
    src = _transpile(schema)
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
    src = _transpile(schema)
    read_body, write_body = _split_slices(src, "Foo")
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
    src = _transpile(schema)
    read_body, write_body = _split_slices(src, "Foo")
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
    src = _transpile(schema)
    for name in ("ItemRead", "ItemWrite", "RootRead", "RootWrite"):
        assert f"class {name}(BaseModel):" in src


def test_read_variant_emitted_before_write_variant() -> None:
    schema = {
        "type": "object",
        "title": "Foo",
        "properties": {"id": {"type": "string", "readOnly": True}},
    }
    src = _transpile(schema)
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
    src = _transpile(schema)
    _, write_body = _split_slices(src, "Root")
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
    src = _transpile(schema)
    assert "bar: BarRead" in src


def test_all_properties_writeonly_yields_empty_read_class() -> None:
    schema = {
        "type": "object",
        "title": "Foo",
        "properties": {"secret": {"type": "string", "writeOnly": True}},
    }
    src = _transpile(schema)
    read_body, _ = _split_slices(src, "Foo")
    assert "secret" not in read_body
    ast.parse(src)


def test_required_writeonly_field_absent_from_read_variant() -> None:
    schema = {
        "type": "object",
        "title": "Foo",
        "properties": {"secret": {"type": "string", "writeOnly": True}},
        "required": ["secret"],
    }
    src = _transpile(schema)
    read_body, write_body = _split_slices(src, "Foo")
    assert "secret" not in read_body
    assert "secret: str" in write_body


# ---------------------------------------------------------------------------
# Smoke: anyOf / oneOf nullable union
# ---------------------------------------------------------------------------


def test_anyof_nullable_produces_union_none() -> None:
    schema = {
        "type": "object",
        "title": "Nullable",
        "properties": {"val": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
        "required": ["val"],
    }
    src = _transpile(schema)
    assert "str | None" in src


def test_oneof_nullable_produces_union_none() -> None:
    schema = {
        "type": "object",
        "title": "OneOfNull",
        "properties": {"val": {"oneOf": [{"type": "integer"}, {"type": "null"}]}},
        "required": ["val"],
    }
    src = _transpile(schema)
    assert "int | None" in src


# ---------------------------------------------------------------------------
# Smoke: enum / const → Literal
# ---------------------------------------------------------------------------


def test_enum_produces_literal() -> None:
    schema = {
        "type": "object",
        "title": "Status",
        "properties": {"state": {"enum": ["active", "inactive", "pending"]}},
        "required": ["state"],
    }
    src = _transpile(schema)
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
    src = _transpile(schema)
    assert "Literal[1]" in src


# ---------------------------------------------------------------------------
# Smoke: type array [X, null] → X | None
# ---------------------------------------------------------------------------


def test_type_array_with_null() -> None:
    schema = {
        "type": "object",
        "title": "Maybe",
        "properties": {"x": {"type": ["string", "null"]}},
        "required": ["x"],
    }
    src = _transpile(schema)
    assert "str | None" in src


# ---------------------------------------------------------------------------
# Smoke: pydantic Field constraints
# ---------------------------------------------------------------------------


def test_field_with_string_constraints() -> None:
    schema = {
        "type": "object",
        "title": "Constrained",
        "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 100}},
        "required": ["name"],
    }
    src = _transpile(schema)
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
    src = _transpile(schema)
    assert "Field(" in src
    assert "from pydantic import BaseModel, Field" in src


def test_field_with_numeric_constraints() -> None:
    schema = {
        "type": "object",
        "title": "BoundedInt",
        "properties": {"count": {"type": "integer", "minimum": 0, "maximum": 1000}},
        "required": ["count"],
    }
    src = _transpile(schema)
    assert "Field(" in src
    assert "ge=0" in src
    assert "le=1000" in src


# ---------------------------------------------------------------------------
# Smoke: title used as class name
# ---------------------------------------------------------------------------


def test_title_becomes_class_name() -> None:
    schema = {"type": "object", "title": "MySpecialModel"}
    src = _transpile(schema)
    assert "class MySpecialModel(BaseModel):" in src


def test_display_name_fallback() -> None:
    """When there is no title, display_name is used as a fallback."""
    doc = json_schema_doc({"type": "object"}, "test://schema", display_name="user_profile")
    assert "class UserProfile(BaseModel):" in PYDANTIC.text(doc)


# ---------------------------------------------------------------------------
# Smoke: no-property object
# ---------------------------------------------------------------------------


def test_empty_object_produces_valid_class() -> None:
    schema = {"type": "object", "title": "Empty"}
    src = _transpile(schema)
    assert "class Empty(BaseModel):" in src
    # Must be syntactically valid even with no fields.
    ast.parse(src)


# ---------------------------------------------------------------------------
# Smoke: `x-pydantic-frozen` and `x-pydantic-skip` extension keywords
# ---------------------------------------------------------------------------


def test_x_pydantic_frozen_emits_config_dict() -> None:
    schema = {
        "type": "object",
        "title": "Point",
        "x-pydantic-frozen": True,
        "properties": {"x": {"type": "number"}},
        "required": ["x"],
    }
    src = _transpile(schema)
    assert "class Point(BaseModel):" in src
    assert "model_config = ConfigDict(frozen=True)" in src
    assert "from pydantic import BaseModel, ConfigDict" in src


def test_without_x_pydantic_frozen_no_config_dict() -> None:
    schema = {"type": "object", "title": "Point", "properties": {"x": {"type": "number"}}}
    src = _transpile(schema)
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
    src = _transpile(schema)
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
    src = _transpile(schema)
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
    src = _transpile(schema)
    assert "type CustomerIdentifier = str" in src
    assert "id: CustomerIdentifier" in src


def test_x_pydantic_class_renames_root() -> None:
    schema = {"type": "object", "title": "Root", "x-pydantic-class": "Overridden"}
    src = _transpile(schema)
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
    src = _transpile(schema)
    assert "class ItemRead(BaseModel):" in src
    assert "class ItemWrite(BaseModel):" in src
    read_body, _ = _split_slices(src, "Root")
    assert "item: ItemRead" in read_body


def test_x_pydantic_class_bad_value_fails() -> None:
    schema = {"type": "object", "title": "Foo", "x-pydantic-class": ""}
    assert PYDANTIC.errors(json_schema_doc(schema))


# ---------------------------------------------------------------------------
# Smoke: `x-pydantic-enum` extension keyword
# ---------------------------------------------------------------------------


def test_x_pydantic_enum_true_str_generates_strenum_with_auto() -> None:
    schema = {
        "type": "object",
        "title": "Order",
        "properties": {
            "status": {"type": "string", "enum": ["active", "inactive"], "x-pydantic-enum": True}
        },
        "required": ["status"],
    }
    src = _transpile(schema)
    assert "class OrderStatus(StrEnum):" in src
    assert "ACTIVE = auto()" in src
    assert "INACTIVE = auto()" in src
    assert "from enum import StrEnum, auto" in src
    assert "status: OrderStatus" in src


def test_x_pydantic_enum_int_sequential_uses_intenum_auto() -> None:
    schema = {
        "type": "object",
        "title": "Priority",
        "properties": {"level": {"type": "integer", "enum": [1, 2, 3], "x-pydantic-enum": True}},
        "required": ["level"],
    }
    src = _transpile(schema)
    assert "class PriorityLevel(IntEnum):" in src
    assert "VALUE_1 = auto()" in src
    assert "VALUE_2 = auto()" in src
    assert "VALUE_3 = auto()" in src
    assert "from enum import IntEnum, auto" in src


def test_x_pydantic_enum_int_nonsequential_uses_explicit_values() -> None:
    schema = {
        "type": "object",
        "title": "Priority",
        "properties": {"level": {"type": "integer", "enum": [1, 5, 10], "x-pydantic-enum": True}},
        "required": ["level"],
    }
    src = _transpile(schema)
    assert "class PriorityLevel(IntEnum):" in src
    assert "VALUE_1 = 1" in src
    assert "VALUE_5 = 5" in src
    assert "VALUE_10 = 10" in src
    assert "auto" not in src


def test_x_pydantic_enum_string_class_name() -> None:
    schema = {
        "type": "object",
        "title": "Order",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["active", "inactive"],
                "x-pydantic-enum": "Status",
            }
        },
        "required": ["status"],
    }
    src = _transpile(schema)
    assert "class Status(StrEnum):" in src
    assert "OrderStatus" not in src
    assert "status: Status" in src


def test_x_pydantic_enum_object_form_custom_base() -> None:
    schema = {
        "type": "object",
        "title": "Order",
        "properties": {
            "flavor": {
                "type": "string",
                "enum": ["sweet", "sour"],
                "x-pydantic-enum": {"name": "Flavor", "base": "DashReplacingEnum"},
            }
        },
        "required": ["flavor"],
    }
    src = _transpile(schema)
    assert "class Flavor(DashReplacingEnum):" in src
    assert "from enum import" not in src


def test_x_pydantic_enum_object_form_base_only() -> None:
    schema = {
        "type": "object",
        "title": "Order",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["active", "inactive"],
                "x-pydantic-enum": {"base": "Enum"},
            }
        },
        "required": ["status"],
    }
    src = _transpile(schema)
    assert "class OrderStatus(Enum):" in src
    assert "ACTIVE = 'active'" in src
    assert "from enum import Enum" in src


def test_x_pydantic_enum_defs_entry_top_level() -> None:
    schema = {
        "type": "object",
        "title": "Root",
        "$defs": {
            "status_kind": {
                "type": "string",
                "enum": ["active", "inactive"],
                "x-pydantic-enum": True,
            }
        },
        "properties": {"status": {"$ref": "#/$defs/status_kind"}},
        "required": ["status"],
    }
    src = _transpile(schema)
    assert src.count("class StatusKind(StrEnum):") == 1
    assert "status: StatusKind" in src


def test_x_pydantic_enum_name_ignored_at_defs_level() -> None:
    """`x-pydantic-enum.name` has no effect on a `$defs` entry; only `x-pydantic-class` renames it."""
    schema = {
        "type": "object",
        "title": "Root",
        "$defs": {
            "status_kind": {
                "type": "string",
                "enum": ["active", "inactive"],
                "x-pydantic-enum": {"name": "ShouldBeIgnored"},
            }
        },
        "properties": {"status": {"$ref": "#/$defs/status_kind"}},
        "required": ["status"],
    }
    src = _transpile(schema)
    assert "class StatusKind(StrEnum):" in src
    assert "ShouldBeIgnored" not in src


def test_x_pydantic_enum_shared_across_read_write_split() -> None:
    schema = {
        "type": "object",
        "title": "Item",
        "properties": {
            "sku": {"type": "string", "readOnly": True},
            "status": {"type": "string", "enum": ["active", "inactive"], "x-pydantic-enum": True},
        },
        "required": ["sku", "status"],
    }
    src = _transpile(schema)
    assert "class ItemRead(BaseModel):" in src
    assert "class ItemWrite(BaseModel):" in src
    assert src.count("class ItemStatus(StrEnum):") == 1
    read_body, write_body = _split_slices(src, "Item")
    assert "status: ItemStatus" in read_body
    assert "status: ItemStatus" in write_body


def test_x_pydantic_enum_mixed_scalar_uses_plain_enum() -> None:
    schema = {
        "type": "object",
        "title": "Order",
        "properties": {"flag": {"enum": [1, "a", True], "x-pydantic-enum": True}},
        "required": ["flag"],
    }
    src = _transpile(schema)
    assert "class OrderFlag(Enum):" in src
    assert "VALUE_1 = 1" in src
    assert "A = 'a'" in src
    assert "TRUE = True" in src


def test_x_pydantic_enum_list_values_falls_back_to_literal_with_warning() -> None:
    schema = {
        "type": "object",
        "title": "Order",
        "properties": {"tags": {"enum": [["a"], ["b"]], "x-pydantic-enum": True}},
        "required": ["tags"],
    }
    doc = json_schema_doc(schema)
    assert "Literal[" in PYDANTIC.text(doc)
    assert "enum-value-unsupported" in PYDANTIC.warnings(doc)


def test_x_pydantic_enum_false_uses_literal() -> None:
    schema = {
        "type": "object",
        "title": "Order",
        "properties": {"status": {"type": "string", "enum": ["a", "b"], "x-pydantic-enum": False}},
        "required": ["status"],
    }
    src = _transpile(schema)
    assert "Literal[" in src
    assert "StrEnum" not in src


def test_x_pydantic_enum_bad_value_fails() -> None:
    schema = {
        "type": "object",
        "title": "Order",
        "properties": {"status": {"type": "string", "enum": ["a"], "x-pydantic-enum": 123}},
    }
    assert PYDANTIC.errors(json_schema_doc(schema))


def test_x_pydantic_enum_empty_string_fails() -> None:
    schema = {
        "type": "object",
        "title": "Order",
        "properties": {"status": {"type": "string", "enum": ["a"], "x-pydantic-enum": ""}},
    }
    assert PYDANTIC.errors(json_schema_doc(schema))


def test_x_pydantic_enum_object_unknown_key_fails() -> None:
    schema = {
        "type": "object",
        "title": "Order",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["a"],
                "x-pydantic-enum": {"name": "Foo", "oops": 1},
            }
        },
    }
    assert PYDANTIC.errors(json_schema_doc(schema))


def test_x_pydantic_enum_object_empty_fails() -> None:
    schema = {
        "type": "object",
        "title": "Order",
        "properties": {"status": {"type": "string", "enum": ["a"], "x-pydantic-enum": {}}},
    }
    assert PYDANTIC.errors(json_schema_doc(schema))


# ---------------------------------------------------------------------------
# Failure: boolean root schema
# ---------------------------------------------------------------------------


def test_boolean_true_schema_fails() -> None:
    """`true` as the root schema cannot produce a Pydantic model."""
    cst_r = _PARSER.apply(json_schema_doc(data=True))
    assert isinstance(cst_r, Ok)
    gen = PydanticTransformer()
    result = gen.apply(cst_r.value)
    assert isinstance(result, Err)


def test_boolean_false_schema_fails() -> None:
    """`false` as the root schema cannot produce a Pydantic model."""
    cst_r = _PARSER.apply(json_schema_doc(data=False))
    assert isinstance(cst_r, Ok)
    gen = PydanticTransformer()
    result = gen.apply(cst_r.value)
    assert isinstance(result, Err)


# ---------------------------------------------------------------------------
# Failure: transpiler rejects OpenAPI documents
# ---------------------------------------------------------------------------


def test_transpiler_rejects_openapi() -> None:
    openapi = {"openapi": "3.1.0", "info": {"title": "T", "version": "1"}}
    assert not PYDANTIC.transpiler().accepts(openapi_doc(openapi, "test://schema"))


# ---------------------------------------------------------------------------
# Integration: full pipeline produces importable-looking output
# ---------------------------------------------------------------------------


def test_integration_full_pipeline() -> None:
    schema = {
        "$defs": {
            "Address": {
                "type": "object",
                "properties": {
                    "street": {"type": "string"},
                    "city": {"type": "string"},
                    "zip_code": {"type": "string", "pattern": r"^\d{5}$"},
                },
                "required": ["street", "city"],
            }
        },
        "type": "object",
        "title": "Person",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer", "minimum": 0},
            "email": {"type": "string", "format": "email"},
            "address": {"$ref": "#/$defs/Address"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "status": {"enum": ["active", "inactive"]},
        },
        "required": ["name", "status"],
    }
    src = _transpile(schema)

    # Must parse as valid Python.
    ast.parse(src)

    # --- Boilerplate ---
    assert "from pydantic import BaseModel" in src
    assert "from typing import" in src
    assert "Literal" in src

    # --- Class structure and ordering ---
    address_pos = src.find("class Address(BaseModel):")
    person_pos = src.find("class Person(BaseModel):")
    assert address_pos != -1, "Address class not generated"
    assert person_pos != -1, "Person class not generated"
    assert address_pos < person_pos, "Address must be defined before Person"

    # --- Address fields ---
    # street and city are required → no None default
    assert re.search(r"street:\s*str(?!\s*\|)", src), "street should be required str"
    assert re.search(r"city:\s*str(?!\s*\|)", src), "city should be required str"
    # zip_code is optional → str | None = None; also has pattern constraint → Field
    assert "zip_code" in src
    assert "pattern=" in src

    # --- Person fields ---
    # name is required str
    assert re.search(r"name:\s*str(?!\s*\|)", src), "name should be required str"
    # age is optional int with minimum=0 → int | None = Field(None, ge=0)
    assert "age" in src
    assert "ge=0" in src
    # email is optional str
    assert re.search(r"email:\s*str\s*\|\s*None", src), "email should be optional str"
    # address is optional $ref to Address
    assert re.search(r"address:\s*Address\s*\|\s*None", src), "address should be optional Address"
    # tags is optional list[str]
    assert re.search(r"tags:\s*list\[str]\s*\|\s*None", src), "tags should be optional list[str]"
    # status is a required Literal (enum)
    assert re.search(r"status:\s*Literal\[", src), "status should be Literal"
    assert "'active'" in src or '"active"' in src
    assert "'inactive'" in src or '"inactive"' in src


def test_all_of_composed_schema_becomes_a_model() -> None:
    """Composition used to fall back to `Any`, losing every field."""
    doc = json_schema_doc(
        {
            "title": "battery",
            "description": "A battery.",
            "allOf": [
                {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}},
                {"type": "object", "properties": {"count": {"type": "integer"}}},
            ],
        },
        "test://schema",
    )
    src = PYDANTIC.text(doc)
    assert "class Battery(BaseModel):" in src
    assert "id: str" in src
    assert "count: int | None = None" in src
    assert "= Any" not in src


def test_composition_does_not_inline_referenced_models() -> None:
    """The branches merge, but a property pointing at a named schema stays a reference."""
    doc = json_schema_doc(
        {
            "title": "thing",
            "$defs": {"stamp": {"type": "string", "pattern": "^2"}},
            "allOf": [{"type": "object", "properties": {"at": {"$ref": "#/$defs/stamp"}}}],
        },
        "test://schema",
    )
    src = PYDANTIC.text(doc)
    # The shared definition keeps its own declaration, and the field names it.
    assert "type Stamp = str" in src
    assert "at: Stamp | None = None" in src


def test_a_bare_ref_declaration_stays_an_alias() -> None:
    """Flattening one of these would replace the alias with a copy of its target."""
    doc = json_schema_doc(
        {
            "title": "alias",
            "$defs": {"named": {"type": "object", "properties": {"a": {"type": "string"}}}},
            "$ref": "#/$defs/named",
        },
        "test://schema",
    )
    src = PYDANTIC.text(doc)
    assert "class Named(BaseModel):" in src
    assert "type Alias = Named" in src
