"""Whole pydantic target runs: raw document in, Python module out.

Covers what only the routed transpiler decides:
`roots` filtering, which documents it accepts, and the shape of a full multi-definition module.
"""

import ast
import re
from dataclasses import replace

import pytest
from hypothesis import HealthCheck, given, settings
from tests.strategies.restricted import json_schema_with_defs_st, object_schema_st
from tests.support.docs import DEFAULT_SCHEMA_URI, json_schema_doc, openapi_doc
from tests.support.drive import PYDANTIC
from tests.support.stages import pydantic_source
from tests.support.types import JsonLike


def _transpile(data: JsonLike, uri: str = DEFAULT_SCHEMA_URI) -> str:
    """Run the routed pydantic target and return the emitted Python source."""
    return PYDANTIC.text(json_schema_doc(data, uri))


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
    assert _transpile(schema) == _transpile(schema), "Generation is not stable across two calls"


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
# Failure: boolean root schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("schema", [True, False], ids=["true", "false"])
def test_boolean_root_schema_fails(schema: JsonLike) -> None:
    """A boolean root schema names no properties, so no model can come of it."""
    [message] = PYDANTIC.errors(json_schema_doc(schema))
    assert "boolean schema" in message


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
