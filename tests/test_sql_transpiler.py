"""Tests for the JSON Schema → PostgreSQL DDL transpiler pipeline.

Covers:
* Property: generated SQL always contains a CREATE TABLE statement.
* Property: generation is stable (idempotent across two calls).
* Smoke tests: type mappings, constraints, $defs, comments.
* Integration: full parse → resolve → generate → reify pipeline.
* Failure: boolean and non-object root schemas cannot be transpiled.
"""

from __future__ import annotations

import re

import orjson
from hypothesis import HealthCheck, given, settings
from tests.strategies import object_schema_st, sql_object_schema_st

from schema_to._result import Err, Ok
from schema_to.generate._sql import PostgresGenerator
from schema_to.io._source import MediaTypes, RawDocument
from schema_to.parse._json_schema import JsonSchemaParser
from schema_to.reify._sql import SqlReifier
from schema_to.resolve._json_schema import JsonSchemaRefResolver
from schema_to.transpile._sql import JsonSchemaToPostgresTranspiler

_PARSER = JsonSchemaParser()


def _doc(data: object, source_id: str = "test://schema") -> RawDocument:
    return RawDocument(
        source_id=source_id,
        content=orjson.dumps(data),
        media_type=MediaTypes.json,
        display_name="Test",
    )


def _transpile(data: object, source_id: str = "test://schema") -> str:
    """Run the full SQL pipeline and return the emitted SQL source."""
    transpiler = JsonSchemaToPostgresTranspiler()
    result = transpiler.transpile(_doc(data, source_id))
    assert isinstance(result, Ok), (
        f"Transpile failed: {[getattr(e, 'message', str(e)) for e in result.errors]}"
    )
    return result.value[0].content.decode("utf-8")


def _generate(data: object) -> str:
    """Parse → resolve → generate → reify and return SQL source."""
    cst_r = _PARSER.apply(_doc(data))
    assert isinstance(cst_r, Ok)
    resolver = JsonSchemaRefResolver()
    res_r = resolver.apply(cst_r.value)
    assert isinstance(res_r, Ok)
    gen = PostgresGenerator()
    ast_r = gen.apply(res_r.value)
    assert isinstance(ast_r, Ok), (
        f"Generation failed: {[getattr(e, 'message', str(e)) for e in ast_r.errors]}"
    )
    reify_r = SqlReifier(artifact_name="schema.sql").apply(ast_r.value)
    assert isinstance(reify_r, Ok)
    return reify_r.value[0].content.decode("utf-8")


# ---------------------------------------------------------------------------
# Property: generated SQL always has CREATE TABLE
# ---------------------------------------------------------------------------


@given(schema=object_schema_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_object_schema_generates_create_table(schema: dict) -> None:
    """Any object-typed schema must produce output containing CREATE TABLE."""
    src = _generate(schema)
    assert "CREATE TABLE" in src


@given(schema=sql_object_schema_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_sql_schema_generates_create_table(schema: dict) -> None:
    """Object schemas with object $defs must produce one CREATE TABLE per table."""
    src = _transpile(schema)
    assert "CREATE TABLE" in src


# ---------------------------------------------------------------------------
# Property: generation is stable
# ---------------------------------------------------------------------------


@given(schema=object_schema_st())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_generation_is_stable(schema: dict) -> None:
    """Generating from the same schema twice yields identical SQL."""
    src1 = _generate(schema)
    src2 = _generate(schema)
    assert src1 == src2, "SQL generation is not stable across two calls"


# ---------------------------------------------------------------------------
# Property: $defs with object entries produce extra tables
# ---------------------------------------------------------------------------


@given(schema=sql_object_schema_st())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_object_defs_produce_multiple_tables(schema: dict) -> None:
    """Each object-typed $defs entry produces its own CREATE TABLE statement."""
    defs = schema.get("$defs", {})
    object_defs = [k for k, v in defs.items() if isinstance(v, dict) and v.get("type") == "object"]
    src = _transpile(schema)
    count = src.count("CREATE TABLE")
    # At least 1 table for root + 1 per object def.
    assert count >= 1 + len(object_defs)


# ---------------------------------------------------------------------------
# Smoke: simple object → CREATE TABLE
# ---------------------------------------------------------------------------


def test_simple_object_produces_create_table() -> None:
    schema = {"type": "object", "title": "Users"}
    src = _transpile(schema)
    assert "CREATE TABLE IF NOT EXISTS users (" in src
    assert src.strip().endswith(";")


def test_table_name_from_title() -> None:
    schema = {"type": "object", "title": "UserProfile"}
    src = _transpile(schema)
    assert "user_profile" in src


def test_display_name_fallback() -> None:
    """When there is no title, display_name is used as the table name."""
    doc = RawDocument(
        source_id="test://schema",
        content=orjson.dumps({"type": "object"}),
        media_type=MediaTypes.json,
        display_name="order_items",
    )
    transpiler = JsonSchemaToPostgresTranspiler()
    result = transpiler.transpile(doc)
    assert isinstance(result, Ok)
    src = result.value[0].content.decode("utf-8")
    assert "order_items" in src


# ---------------------------------------------------------------------------
# Smoke: type mappings
# ---------------------------------------------------------------------------


def test_string_field_is_text() -> None:
    schema = {
        "type": "object",
        "title": "Item",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    src = _transpile(schema)
    assert "name text NOT NULL" in src


def test_integer_field_is_integer() -> None:
    schema = {
        "type": "object",
        "title": "Item",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
    }
    src = _transpile(schema)
    assert "count integer NOT NULL" in src


def test_number_field_is_double_precision() -> None:
    schema = {
        "type": "object",
        "title": "Item",
        "properties": {"price": {"type": "number"}},
        "required": ["price"],
    }
    src = _transpile(schema)
    assert "price double precision NOT NULL" in src


def test_boolean_field_is_boolean() -> None:
    schema = {
        "type": "object",
        "title": "Flag",
        "properties": {"active": {"type": "boolean"}},
        "required": ["active"],
    }
    src = _transpile(schema)
    assert "active boolean NOT NULL" in src


def test_string_with_maxlength_is_varchar() -> None:
    schema = {
        "type": "object",
        "title": "Item",
        "properties": {"code": {"type": "string", "maxLength": 10}},
        "required": ["code"],
    }
    src = _transpile(schema)
    assert "varchar(10)" in src
    assert "code varchar(10) NOT NULL" in src


def test_string_format_datetime_is_timestamptz() -> None:
    schema = {
        "type": "object",
        "title": "Event",
        "properties": {"created_at": {"type": "string", "format": "date-time"}},
        "required": ["created_at"],
    }
    src = _transpile(schema)
    assert "created_at timestamptz NOT NULL" in src


def test_string_format_date_is_date() -> None:
    schema = {
        "type": "object",
        "title": "Event",
        "properties": {"birthday": {"type": "string", "format": "date"}},
        "required": ["birthday"],
    }
    src = _transpile(schema)
    assert "birthday date NOT NULL" in src


def test_string_format_time_is_time() -> None:
    schema = {
        "type": "object",
        "title": "Event",
        "properties": {"start_time": {"type": "string", "format": "time"}},
        "required": ["start_time"],
    }
    src = _transpile(schema)
    assert "start_time time NOT NULL" in src


def test_string_format_uuid_is_uuid() -> None:
    schema = {
        "type": "object",
        "title": "Entity",
        "properties": {"id": {"type": "string", "format": "uuid"}},
        "required": ["id"],
    }
    src = _transpile(schema)
    assert "id uuid NOT NULL" in src


def test_array_of_string_is_text_array() -> None:
    schema = {
        "type": "object",
        "title": "Tag",
        "properties": {"labels": {"type": "array", "items": {"type": "string"}}},
        "required": ["labels"],
    }
    src = _transpile(schema)
    assert "text[]" in src


def test_array_no_items_is_jsonb() -> None:
    schema = {
        "type": "object",
        "title": "Bag",
        "properties": {"data": {"type": "array"}},
        "required": ["data"],
    }
    src = _transpile(schema)
    assert "jsonb" in src


def test_x_pg_type_override() -> None:
    schema = {
        "type": "object",
        "title": "Geo",
        "properties": {"location": {"type": "string", "x-pg-type": "geometry(Point, 4326)"}},
        "required": ["location"],
    }
    src = _transpile(schema)
    assert "geometry(Point, 4326)" in src


# ---------------------------------------------------------------------------
# Smoke: required vs optional columns
# ---------------------------------------------------------------------------


def test_required_field_has_not_null() -> None:
    schema = {
        "type": "object",
        "title": "Item",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    src = _transpile(schema)
    assert "NOT NULL" in src


def test_optional_field_has_no_not_null() -> None:
    schema = {
        "type": "object",
        "title": "Item",
        "properties": {"nickname": {"type": "string"}},
    }
    src = _transpile(schema)
    assert "NOT NULL" not in src


def test_anyof_nullable_column_has_no_not_null() -> None:
    schema = {
        "type": "object",
        "title": "Maybe",
        "properties": {"val": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
        "required": ["val"],
    }
    src = _transpile(schema)
    # Required but anyOf [string, null] → nullable
    assert "NOT NULL" not in src
    assert "val text" in src


# ---------------------------------------------------------------------------
# Smoke: CHECK constraints
# ---------------------------------------------------------------------------


def test_minimum_produces_check() -> None:
    schema = {
        "type": "object",
        "title": "BoundedInt",
        "properties": {"age": {"type": "integer", "minimum": 0}},
        "required": ["age"],
    }
    src = _transpile(schema)
    assert "CHECK" in src
    assert "age >= 0" in src


def test_maximum_produces_check() -> None:
    schema = {
        "type": "object",
        "title": "BoundedInt",
        "properties": {"pct": {"type": "number", "maximum": 100}},
        "required": ["pct"],
    }
    src = _transpile(schema)
    assert "pct <= 100" in src


def test_exclusive_minimum_produces_check() -> None:
    schema = {
        "type": "object",
        "title": "Positive",
        "properties": {"x": {"type": "number", "exclusiveMinimum": 0}},
        "required": ["x"],
    }
    src = _transpile(schema)
    assert "x > 0" in src


def test_min_and_max_combined_in_single_check() -> None:
    schema = {
        "type": "object",
        "title": "BoundedInt",
        "properties": {"age": {"type": "integer", "minimum": 0, "maximum": 150}},
        "required": ["age"],
    }
    src = _transpile(schema)
    assert "age >= 0" in src
    assert "age <= 150" in src
    assert "AND" in src


def test_pattern_produces_check() -> None:
    schema = {
        "type": "object",
        "title": "Code",
        "properties": {"code": {"type": "string", "pattern": "^[A-Z]+$"}},
        "required": ["code"],
    }
    src = _transpile(schema)
    assert "CHECK" in src
    assert "code ~ '^[A-Z]+$'" in src


def test_min_length_produces_check() -> None:
    schema = {
        "type": "object",
        "title": "Item",
        "properties": {"slug": {"type": "string", "minLength": 3}},
        "required": ["slug"],
    }
    src = _transpile(schema)
    assert "char_length(slug) >= 3" in src


def test_varchar_maxlength_no_extra_check() -> None:
    """String maxLength becomes VARCHAR(n); no redundant length CHECK is emitted."""
    schema = {
        "type": "object",
        "title": "Item",
        "properties": {"name": {"type": "string", "maxLength": 50}},
        "required": ["name"],
    }
    src = _transpile(schema)
    assert "varchar(50)" in src
    # Should NOT have a char_length check for maxLength since VARCHAR enforces it.
    assert "char_length(name) <= 50" not in src


def test_enum_produces_in_check() -> None:
    schema = {
        "type": "object",
        "title": "Status",
        "properties": {"state": {"type": "string", "enum": ["active", "inactive", "pending"]}},
        "required": ["state"],
    }
    src = _transpile(schema)
    assert "CHECK" in src
    assert "state IN" in src
    assert "'active'" in src
    assert "'inactive'" in src
    assert "'pending'" in src


def test_const_produces_equality_check() -> None:
    schema = {
        "type": "object",
        "title": "Fixed",
        "properties": {"version": {"type": "integer", "const": 1}},
        "required": ["version"],
    }
    src = _transpile(schema)
    assert "version = 1" in src


# ---------------------------------------------------------------------------
# Smoke: $defs → separate tables
# ---------------------------------------------------------------------------


def test_defs_object_produces_separate_table() -> None:
    schema = {
        "type": "object",
        "title": "Order",
        "$defs": {
            "Address": {
                "type": "object",
                "properties": {"street": {"type": "string"}},
            }
        },
        "properties": {"shipping": {"$ref": "#/$defs/Address"}},
    }
    src = _transpile(schema)
    assert "CREATE TABLE IF NOT EXISTS address" in src
    assert "CREATE TABLE IF NOT EXISTS order" in src


def test_defs_tables_generated_before_root() -> None:
    """$defs tables must appear before the root table in the output."""
    schema = {
        "type": "object",
        "title": "Root",
        "$defs": {"Leaf": {"type": "object"}},
    }
    src = _transpile(schema)
    leaf_pos = src.find("leaf")
    root_pos = src.find("root")
    assert leaf_pos != -1 and root_pos != -1
    assert leaf_pos < root_pos, "Leaf table should be defined before Root"


def test_ref_column_is_jsonb() -> None:
    """$ref to a $defs object produces a JSONB column."""
    schema = {
        "type": "object",
        "title": "Order",
        "$defs": {"Address": {"type": "object"}},
        "properties": {"shipping": {"$ref": "#/$defs/Address"}},
        "required": ["shipping"],
    }
    src = _transpile(schema)
    assert re.search(r"shipping\s+jsonb\s+NOT NULL", src)


# ---------------------------------------------------------------------------
# Smoke: COMMENT ON
# ---------------------------------------------------------------------------


def test_table_description_produces_comment() -> None:
    schema = {"type": "object", "title": "Users", "description": "User accounts"}
    src = _transpile(schema)
    assert "COMMENT ON TABLE users IS 'User accounts';" in src


def test_table_title_only_produces_comment() -> None:
    """When only title (no description) is present, emit COMMENT using title."""
    schema = {"type": "object", "title": "Products"}
    src = _transpile(schema)
    assert "COMMENT ON TABLE products IS 'Products';" in src


def test_no_doc_produces_no_comment() -> None:
    schema = {"type": "object"}
    src = _transpile(schema)
    assert "COMMENT ON" not in src


def test_column_description_produces_comment() -> None:
    schema = {
        "type": "object",
        "title": "Items",
        "properties": {"name": {"type": "string", "description": "The item name"}},
    }
    src = _transpile(schema)
    assert "COMMENT ON COLUMN items.name IS 'The item name';" in src


def test_column_title_only_produces_comment() -> None:
    schema = {
        "type": "object",
        "title": "Items",
        "properties": {"sku": {"type": "string", "title": "SKU code"}},
    }
    src = _transpile(schema)
    assert "COMMENT ON COLUMN items.sku IS 'SKU code';" in src


# ---------------------------------------------------------------------------
# Smoke: empty object produces valid skeleton
# ---------------------------------------------------------------------------


def test_empty_object_produces_valid_skeleton() -> None:
    schema = {"type": "object", "title": "Empty"}
    src = _transpile(schema)
    assert "CREATE TABLE IF NOT EXISTS empty (" in src
    assert ");" in src


# ---------------------------------------------------------------------------
# Failure: boolean root schema
# ---------------------------------------------------------------------------


def test_boolean_true_root_fails() -> None:
    cst_r = _PARSER.apply(_doc(True))
    assert isinstance(cst_r, Ok)
    gen = PostgresGenerator()
    result = gen.apply(cst_r.value)
    assert isinstance(result, Err)
    assert any("boolean" in e.message.lower() for e in result.errors)


def test_boolean_false_root_fails() -> None:
    cst_r = _PARSER.apply(_doc(False))
    assert isinstance(cst_r, Ok)
    gen = PostgresGenerator()
    result = gen.apply(cst_r.value)
    assert isinstance(result, Err)


# ---------------------------------------------------------------------------
# Failure: non-object root schema
# ---------------------------------------------------------------------------


def test_string_root_fails() -> None:
    cst_r = _PARSER.apply(_doc({"type": "string"}))
    assert isinstance(cst_r, Ok)
    gen = PostgresGenerator()
    result = gen.apply(cst_r.value)
    assert isinstance(result, Err)
    assert any("object" in e.message.lower() for e in result.errors)


def test_integer_root_fails() -> None:
    cst_r = _PARSER.apply(_doc({"type": "integer"}))
    assert isinstance(cst_r, Ok)
    gen = PostgresGenerator()
    result = gen.apply(cst_r.value)
    assert isinstance(result, Err)


# ---------------------------------------------------------------------------
# Failure: transpiler rejects OpenAPI documents
# ---------------------------------------------------------------------------


def test_transpiler_rejects_openapi() -> None:
    openapi = {"openapi": "3.1.0", "info": {"title": "T", "version": "1"}}
    transpiler = JsonSchemaToPostgresTranspiler()
    doc = _doc(openapi)
    assert not transpiler.accepts(doc)


# ---------------------------------------------------------------------------
# Integration: full pipeline with a realistic schema
# ---------------------------------------------------------------------------


def test_integration_full_pipeline() -> None:
    schema = {
        "$defs": {
            "Address": {
                "type": "object",
                "description": "Postal address",
                "properties": {
                    "street": {
                        "type": "string",
                        "maxLength": 100,
                        "description": "Street line",
                    },
                    "city": {"type": "string"},
                    "zip": {"type": "string", "pattern": r"^\d{5}$"},
                },
                "required": ["street", "city"],
            }
        },
        "type": "object",
        "title": "Person",
        "description": "Person record",
        "properties": {
            "id": {"type": "integer", "minimum": 1},
            "name": {"type": "string", "maxLength": 255},
            "age": {"type": "integer", "minimum": 0, "maximum": 150},
            "created_at": {"type": "string", "format": "date-time"},
            "address": {"$ref": "#/$defs/Address"},
            "status": {"type": "string", "enum": ["active", "inactive"]},
        },
        "required": ["id", "name", "status"],
    }
    src = _transpile(schema)

    # --- Ordering: address table before person table ---
    addr_pos = src.find("CREATE TABLE IF NOT EXISTS address")
    person_pos = src.find("CREATE TABLE IF NOT EXISTS person")
    assert addr_pos != -1, "Address table not generated"
    assert person_pos != -1, "Person table not generated"
    assert addr_pos < person_pos, "Address must be defined before Person"

    # --- Address table columns ---
    # street is required + maxLength=100 → VARCHAR(100) NOT NULL
    assert re.search(r"street\s+varchar\(100\)\s+NOT NULL", src), "street should be varchar(100) NOT NULL"
    # city is required → TEXT NOT NULL
    assert re.search(r"city\s+text\s+NOT NULL", src), "city should be text NOT NULL"
    # zip is optional → no NOT NULL; has pattern → CHECK
    assert "zip" in src
    assert re.search(r"zip ~ '.*\\d{5}.*'", src) or "zip ~" in src, "zip should have pattern check"

    # --- Person table columns ---
    # id is required integer with minimum=1
    assert re.search(r"id\s+integer\s+NOT NULL", src), "id should be integer NOT NULL"
    assert "id >= 1" in src, "id should have CHECK id >= 1"
    # name is required varchar(255)
    assert re.search(r"name\s+varchar\(255\)\s+NOT NULL", src), "name should be varchar(255) NOT NULL"
    # age is optional integer with range
    assert "age" in src
    assert "age >= 0" in src
    assert "age <= 150" in src
    # created_at is optional timestamptz
    assert re.search(r"created_at\s+timestamptz", src), "created_at should be timestamptz"
    # address is optional $ref → JSONB
    assert re.search(r"address\s+jsonb", src), "address should be jsonb"
    # status is required with enum
    assert re.search(r"status\s+text\s+NOT NULL", src), "status should be text NOT NULL"
    assert "status IN" in src
    assert "'active'" in src
    assert "'inactive'" in src

    # --- COMMENT ON ---
    assert "COMMENT ON TABLE address IS 'Postal address';" in src
    assert "COMMENT ON TABLE person IS 'Person record';" in src
    assert "COMMENT ON COLUMN address.street IS 'Street line';" in src
