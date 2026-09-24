"""The `x-pydantic-enum` extension keyword.

Chooses `StrEnum`, `IntEnum`, or a plain `Enum` from the enum's values,
and falls back to a `Literal` for values no enum member can hold.
"""

from tests.support.docs import json_schema_doc
from tests.support.drive import PYDANTIC
from tests.support.source import read_write_slices
from tests.support.stages import pydantic_source

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
    src = pydantic_source(schema)
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
    src = pydantic_source(schema)
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
    src = pydantic_source(schema)
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
    src = pydantic_source(schema)
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
    src = pydantic_source(schema)
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
    src = pydantic_source(schema)
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
    src = pydantic_source(schema)
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
    src = pydantic_source(schema)
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
    src = pydantic_source(schema)
    assert "class ItemRead(BaseModel):" in src
    assert "class ItemWrite(BaseModel):" in src
    assert src.count("class ItemStatus(StrEnum):") == 1
    read_body, write_body = read_write_slices(src, "Item")
    assert "status: ItemStatus" in read_body
    assert "status: ItemStatus" in write_body


def test_x_pydantic_enum_mixed_scalar_uses_plain_enum() -> None:
    schema = {
        "type": "object",
        "title": "Order",
        "properties": {"flag": {"enum": [1, "a", True], "x-pydantic-enum": True}},
        "required": ["flag"],
    }
    src = pydantic_source(schema)
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
    src = pydantic_source(schema)
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
