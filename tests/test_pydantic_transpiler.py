"""Tests for the JSON Schema → Pydantic transpiler pipeline.

Covers:
* Property: generated Python source is always syntactically valid.
* Smoke tests: specific schemas produce expected class / field shapes.
* Integration: full parse → resolve → generate → reify pipeline.
* Failure: boolean root schema cannot be transpiled.
"""

from __future__ import annotations

import ast
import re

import orjson
import pytest
from hypothesis import HealthCheck, given, settings
from tests.strategies import json_schema_with_defs_st, object_schema_st

from schema_to._result import Err, Ok
from schema_to.generate._pydantic import PydanticGenerator
from schema_to.io._source import MediaTypes, RawDocument
from schema_to.parse._json_schema import JsonSchemaParser
from schema_to.reify._python import PythonReifier
from schema_to.resolve._json_schema import JsonSchemaRefResolver
from schema_to.transpile._pydantic import JsonSchemaToPydanticTranspiler

_PARSER = JsonSchemaParser()


def _doc(data: object, source_id: str = "test://schema") -> RawDocument:
    return RawDocument(
        source_id=source_id,
        content=orjson.dumps(data),
        media_type=MediaTypes.json,
        display_name="Test",
    )


def _transpile(data: object, source_id: str = "test://schema") -> str:
    """Run the full pipeline and return the emitted Python source."""
    transpiler = JsonSchemaToPydanticTranspiler()
    result = transpiler.transpile(_doc(data, source_id))
    assert isinstance(result, Ok), (
        f"Transpile failed: {[getattr(e, 'message', str(e)) for e in result.errors]}"
    )
    return result.value[0].content.decode("utf-8")


def _parse_and_generate(data: object) -> str:
    """Parse → resolve → generate → reify and return Python source."""
    cst_r = _PARSER.apply(_doc(data))
    assert isinstance(cst_r, Ok)
    resolver = JsonSchemaRefResolver()
    res_r = resolver.apply(cst_r.value)
    assert isinstance(res_r, Ok)
    gen = PydanticGenerator(resolver=resolver)
    ast_r = gen.apply(res_r.value)
    assert isinstance(ast_r, Ok), (
        f"Generation failed: {[getattr(e, 'message', str(e)) for e in ast_r.errors]}"
    )
    reify_r = PythonReifier(artifact_name="models.py").apply(ast_r.value)
    assert isinstance(reify_r, Ok)
    return reify_r.value[0].content.decode("utf-8")


# ---------------------------------------------------------------------------
# Property: generated source is always valid Python
# ---------------------------------------------------------------------------


@given(schema=object_schema_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_object_schema_generates_valid_python(schema: dict) -> None:
    """Any object-typed schema must produce syntactically valid Python."""
    src = _parse_and_generate(schema)
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
    cst_r = _PARSER.apply(_doc(schema))
    assert isinstance(cst_r, Ok)
    resolver = JsonSchemaRefResolver()
    res_r = resolver.apply(cst_r.value)
    assert isinstance(res_r, Ok)

    src1 = _parse_and_generate(schema)
    src2 = _parse_and_generate(schema)
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
    assert leaf_pos != -1 and root_pos != -1
    assert leaf_pos < root_pos, "Leaf should be defined before Root"


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
    assert "from typing import" in src and "Literal" in src


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
    doc = RawDocument(
        source_id="test://schema",
        content=orjson.dumps({"type": "object"}),
        media_type=MediaTypes.json,
        display_name="user_profile",
    )
    transpiler = JsonSchemaToPydanticTranspiler()
    result = transpiler.transpile(doc)
    assert isinstance(result, Ok)
    src = result.value[0].content.decode("utf-8")
    assert "class UserProfile(BaseModel):" in src


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
# Failure: boolean root schema
# ---------------------------------------------------------------------------


def test_boolean_true_schema_fails() -> None:
    """``true`` as the root schema cannot produce a Pydantic model."""
    cst_r = _PARSER.apply(_doc(True))
    assert isinstance(cst_r, Ok)
    gen = PydanticGenerator()
    result = gen.apply(cst_r.value)
    assert isinstance(result, Err)


def test_boolean_false_schema_fails() -> None:
    """``false`` as the root schema cannot produce a Pydantic model."""
    cst_r = _PARSER.apply(_doc(False))
    assert isinstance(cst_r, Ok)
    gen = PydanticGenerator()
    result = gen.apply(cst_r.value)
    assert isinstance(result, Err)


# ---------------------------------------------------------------------------
# Failure: transpiler rejects OpenAPI documents
# ---------------------------------------------------------------------------


def test_transpiler_rejects_openapi() -> None:
    openapi = {"openapi": "3.1.0", "info": {"title": "T", "version": "1"}}
    transpiler = JsonSchemaToPydanticTranspiler()
    doc = _doc(openapi)
    assert not transpiler.accepts(doc)


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
    assert "from __future__ import annotations" in src
    assert "from pydantic import BaseModel" in src
    assert "from typing import" in src and "Literal" in src

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
    assert re.search(r"tags:\s*list\[str\]\s*\|\s*None", src), "tags should be optional list[str]"
    # status is a required Literal (enum)
    assert re.search(r"status:\s*Literal\[", src), "status should be Literal"
    assert "'active'" in src or '"active"' in src
    assert "'inactive'" in src or '"inactive"' in src
