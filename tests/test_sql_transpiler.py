"""Tests for the JSON Schema → PostgreSQL DDL transpiler pipeline.

Covers:
* Property: generated SQL always contains a CREATE TABLE statement.
* Property: generation is stable (idempotent across two calls).
* Property: $defs object entries produce extra tables.
* Targeted: type mappings with exact output comparisons.
* Targeted: CHECK constraint generation and edge cases.
* Targeted: nullable / required semantics.
* Targeted: $defs → separate tables.
* Targeted: COMMENT ON emission.
* Targeted: transpiler accepts/rejects document types.
* Failure: boolean and non-object root schemas.
* Integration: full schema exercising all supported features.
"""

from __future__ import annotations

import orjson
from hypothesis import HealthCheck, given, settings
from tests.strategies import object_schema_st, sql_object_schema_st

from schema_to._result import Err, Ok
from schema_to.generate._sql import PostgresGenerator
from schema_to.io._source import JsonSchemaRawDocument, MediaTypes, OpenApiRawDocument, RawDocument
from schema_to.parse._json_schema import JsonSchemaParser
from schema_to.transpile._sql import JsonSchemaToPostgresTranspiler

_PARSER = JsonSchemaParser()


def _doc(data: object, source_id: str = "test://schema") -> JsonSchemaRawDocument:
    return JsonSchemaRawDocument(
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


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@given(schema=object_schema_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_object_schema_generates_create_table(schema: dict) -> None:
    """Any object-typed schema must produce output containing CREATE TABLE."""
    src = _transpile(schema)
    assert "CREATE TABLE" in src


@given(schema=object_schema_st())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_generation_is_stable(schema: dict) -> None:
    """Generating from the same schema twice yields identical SQL."""
    assert _transpile(schema) == _transpile(schema)


@given(schema=sql_object_schema_st())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_object_defs_produce_multiple_tables(schema: dict) -> None:
    """Each object-typed $defs entry produces its own CREATE TABLE statement."""
    defs = schema.get("$defs", {})
    object_defs = [k for k, v in defs.items() if isinstance(v, dict) and v.get("type") == "object"]
    src = _transpile(schema)
    assert src.count("CREATE TABLE") >= 1 + len(object_defs)


# ---------------------------------------------------------------------------
# Type mappings — exact output
# ---------------------------------------------------------------------------


def test_required_string() -> None:
    schema = {"type": "object", "title": "T", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    x text NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_optional_string() -> None:
    schema = {"type": "object", "title": "T", "properties": {"x": {"type": "string"}}}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    x text\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_integer_column() -> None:
    schema = {"type": "object", "title": "T", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    n integer NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_number_column() -> None:
    schema = {"type": "object", "title": "T", "properties": {"v": {"type": "number"}}, "required": ["v"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    v double precision NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_boolean_column() -> None:
    schema = {"type": "object", "title": "T", "properties": {"b": {"type": "boolean"}}, "required": ["b"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    b boolean NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_varchar() -> None:
    schema = {"type": "object", "title": "T", "properties": {"s": {"type": "string", "maxLength": 10}}, "required": ["s"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    s varchar(10) NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_timestamptz() -> None:
    schema = {"type": "object", "title": "T", "properties": {"ts": {"type": "string", "format": "date-time"}}, "required": ["ts"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    ts timestamptz NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_date() -> None:
    schema = {"type": "object", "title": "T", "properties": {"d": {"type": "string", "format": "date"}}, "required": ["d"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    d date NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_time() -> None:
    schema = {"type": "object", "title": "T", "properties": {"t": {"type": "string", "format": "time"}}, "required": ["t"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    t time NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_uuid() -> None:
    schema = {"type": "object", "title": "T", "properties": {"id": {"type": "string", "format": "uuid"}}, "required": ["id"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    id uuid NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_bytea() -> None:
    schema = {"type": "object", "title": "T", "properties": {"data": {"type": "string", "format": "byte"}}, "required": ["data"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    data bytea NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_array_of_strings() -> None:
    schema = {"type": "object", "title": "T", "properties": {"tags": {"type": "array", "items": {"type": "string"}}}, "required": ["tags"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    tags text[] NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_array_no_items_is_jsonb() -> None:
    schema = {"type": "object", "title": "T", "properties": {"data": {"type": "array"}}, "required": ["data"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    data jsonb NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_nested_object_is_jsonb() -> None:
    schema = {"type": "object", "title": "T", "properties": {"meta": {"type": "object"}}, "required": ["meta"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    meta jsonb NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_x_pg_type_override() -> None:
    schema = {"type": "object", "title": "T", "properties": {"loc": {"type": "string", "x-pg-type": "geometry(Point,4326)"}}, "required": ["loc"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    loc geometry(Point,4326) NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


# ---------------------------------------------------------------------------
# Nullable / required semantics
# ---------------------------------------------------------------------------


def test_anyof_nullable() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"v": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
        "required": ["v"],
    }
    # required but anyOf [T, null] → nullable, effective type TEXT
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    v text\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


# ---------------------------------------------------------------------------
# CHECK constraints — exact output
# ---------------------------------------------------------------------------


def test_check_minimum() -> None:
    schema = {"type": "object", "title": "T", "properties": {"n": {"type": "integer", "minimum": 0}}, "required": ["n"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    n integer NOT NULL CHECK ((n >= 0))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_check_maximum() -> None:
    schema = {"type": "object", "title": "T", "properties": {"n": {"type": "integer", "maximum": 100}}, "required": ["n"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    n integer NOT NULL CHECK ((n <= 100))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_check_exclusive_minimum() -> None:
    schema = {"type": "object", "title": "T", "properties": {"x": {"type": "number", "exclusiveMinimum": 0}}, "required": ["x"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    x double precision NOT NULL CHECK ((x > 0))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_check_exclusive_maximum() -> None:
    schema = {"type": "object", "title": "T", "properties": {"x": {"type": "number", "exclusiveMaximum": 1}}, "required": ["x"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    x double precision NOT NULL CHECK ((x < 1))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_check_combined_min_max() -> None:
    schema = {"type": "object", "title": "T", "properties": {"n": {"type": "integer", "minimum": 0, "maximum": 150}}, "required": ["n"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    n integer NOT NULL CHECK ((n >= 0) AND (n <= 150))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_check_minimum_float() -> None:
    """Non-integer minimum must preserve the decimal point."""
    schema = {"type": "object", "title": "T", "properties": {"n": {"type": "number", "minimum": 0.5}}, "required": ["n"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    n double precision NOT NULL CHECK ((n >= 0.5))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_check_min_length() -> None:
    schema = {"type": "object", "title": "T", "properties": {"s": {"type": "string", "minLength": 3}}, "required": ["s"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    s text NOT NULL CHECK ((char_length(s) >= 3))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_varchar_no_max_length_check() -> None:
    """VARCHAR already enforces maxLength; no redundant char_length CHECK is emitted."""
    schema = {"type": "object", "title": "T", "properties": {"s": {"type": "string", "minLength": 3, "maxLength": 20}}, "required": ["s"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    s varchar(20) NOT NULL CHECK ((char_length(s) >= 3))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_check_pattern() -> None:
    schema = {"type": "object", "title": "T", "properties": {"s": {"type": "string", "pattern": "^[A-Z]+$"}}, "required": ["s"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    s text NOT NULL CHECK ((s ~ '^[A-Z]+$'))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_check_pattern_single_quote_escaped() -> None:
    """Single quotes inside a pattern must be doubled for SQL safety."""
    schema = {"type": "object", "title": "T", "properties": {"s": {"type": "string", "pattern": "it's"}}, "required": ["s"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    s text NOT NULL CHECK ((s ~ 'it''s'))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_check_enum() -> None:
    schema = {"type": "object", "title": "T", "properties": {"s": {"type": "string", "enum": ["a", "b"]}}, "required": ["s"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    s text NOT NULL CHECK ((s IN ('a', 'b')))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_check_enum_with_null_filters_null() -> None:
    """Null entries in enum are excluded from the IN list."""
    schema = {"type": "object", "title": "T", "properties": {"s": {"type": "string", "enum": [None, "active"]}}, "required": ["s"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    s text NOT NULL CHECK ((s IN ('active')))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_check_enum_all_null_no_check() -> None:
    """An enum containing only null produces no IN constraint."""
    schema = {"type": "object", "title": "T", "properties": {"s": {"type": "string", "enum": [None]}}, "required": ["s"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    s text NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_check_enum_empty_no_check() -> None:
    """An empty enum array produces no IN constraint."""
    schema = {"type": "object", "title": "T", "properties": {"s": {"type": "string", "enum": []}}, "required": ["s"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    s text NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_check_const_string() -> None:
    schema = {"type": "object", "title": "T", "properties": {"v": {"type": "string", "const": "fixed"}}, "required": ["v"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    v text NOT NULL CHECK ((v = 'fixed'))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_check_const_empty_string() -> None:
    """const: '' must emit an equality check against the empty string literal."""
    schema = {"type": "object", "title": "T", "properties": {"v": {"type": "string", "const": ""}}, "required": ["v"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    v text NOT NULL CHECK ((v = ''))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_check_const_integer() -> None:
    schema = {"type": "object", "title": "T", "properties": {"v": {"type": "integer", "const": 42}}, "required": ["v"]}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    v integer NOT NULL CHECK ((v = 42))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


# ---------------------------------------------------------------------------
# Table structure and naming
# ---------------------------------------------------------------------------


def test_empty_object() -> None:
    """Schema with title but no properties produces a skeleton table with comment."""
    schema = {"type": "object", "title": "T"}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    -- (no columns)\n);\n\nCOMMENT ON TABLE t IS 'T';\n"


def test_no_title_no_comment() -> None:
    """Schema with no title and no description produces no COMMENT ON."""
    schema = {"type": "object"}
    # source_id "test://schema" → safe_sql_identifier → "test_schema"
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS test_schema (\n    -- (no columns)\n);\n"


def test_table_name_from_title() -> None:
    schema = {"type": "object", "title": "UserProfile"}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS user_profile (\n    -- (no columns)\n);\n\nCOMMENT ON TABLE user_profile IS 'UserProfile';\n"


def test_table_name_from_source_id() -> None:
    """When there is no title, source_id determines the table name."""
    doc = JsonSchemaRawDocument(
        source_id="https://example.com/product.json",
        content=orjson.dumps({"type": "object"}),
        media_type=MediaTypes.json,
    )
    result = JsonSchemaToPostgresTranspiler().transpile(doc)
    assert isinstance(result, Ok)
    src = result.value[0].content.decode("utf-8")
    assert "CREATE TABLE IF NOT EXISTS https_example_com_product_json" in src


def test_defs_object_gets_own_table() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "$defs": {"A": {"type": "object"}},
        "properties": {"a": {"$ref": "#/$defs/A"}},
        "required": ["a"],
    }
    assert _transpile(schema) == (
        "CREATE TABLE IF NOT EXISTS a (\n    -- (no columns)\n);\n"
        "\n"
        "CREATE TABLE IF NOT EXISTS t (\n    a jsonb NOT NULL\n);\n"
        "\n"
        "COMMENT ON TABLE t IS 'T';\n"
    )


def test_defs_table_precedes_root() -> None:
    """$defs tables are emitted before the root table."""
    schema = {"type": "object", "title": "Root", "$defs": {"Leaf": {"type": "object"}}}
    src = _transpile(schema)
    assert src.index("leaf") < src.index("root")


# ---------------------------------------------------------------------------
# COMMENT ON emission
# ---------------------------------------------------------------------------


def test_table_description_comment() -> None:
    schema = {"type": "object", "title": "T", "description": "A table"}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS t (\n    -- (no columns)\n);\n\nCOMMENT ON TABLE t IS 'A table';\n"


def test_table_title_fallback_comment() -> None:
    """When only title (no description) is set, title is used for the COMMENT."""
    schema = {"type": "object", "title": "Foo"}
    assert _transpile(schema) == "CREATE TABLE IF NOT EXISTS foo (\n    -- (no columns)\n);\n\nCOMMENT ON TABLE foo IS 'Foo';\n"


def test_column_description_comment() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"x": {"type": "string", "description": "The x value"}},
    }
    assert _transpile(schema) == (
        "CREATE TABLE IF NOT EXISTS t (\n    x text\n);\n"
        "\n"
        "COMMENT ON TABLE t IS 'T';\n"
        "\n"
        "COMMENT ON COLUMN t.x IS 'The x value';\n"
    )


def test_column_title_fallback_comment() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"sku": {"type": "string", "title": "SKU code"}},
    }
    assert _transpile(schema) == (
        "CREATE TABLE IF NOT EXISTS t (\n    sku text\n);\n"
        "\n"
        "COMMENT ON TABLE t IS 'T';\n"
        "\n"
        "COMMENT ON COLUMN t.sku IS 'SKU code';\n"
    )


# ---------------------------------------------------------------------------
# Transpiler accepts / rejects
# ---------------------------------------------------------------------------


def test_accepts_json_schema_document() -> None:
    assert JsonSchemaToPostgresTranspiler().accepts(_doc({}))


def test_rejects_openapi_document() -> None:
    doc = OpenApiRawDocument(source_id="test://s", content=b"{}", media_type=MediaTypes.json)
    assert not JsonSchemaToPostgresTranspiler().accepts(doc)


def test_rejects_raw_document() -> None:
    doc = RawDocument(source_id="test://s", content=b"{}", media_type=MediaTypes.json)
    assert not JsonSchemaToPostgresTranspiler().accepts(doc)


# ---------------------------------------------------------------------------
# Failure: non-transpilable schemas
# ---------------------------------------------------------------------------


def test_boolean_true_root_fails() -> None:
    cst_r = _PARSER.apply(_doc(True))
    assert isinstance(cst_r, Ok)
    result = PostgresGenerator().apply(cst_r.value)
    assert isinstance(result, Err)
    assert any("boolean" in e.message.lower() for e in result.errors)


def test_boolean_false_root_fails() -> None:
    cst_r = _PARSER.apply(_doc(False))
    assert isinstance(cst_r, Ok)
    assert isinstance(PostgresGenerator().apply(cst_r.value), Err)


def test_string_root_fails() -> None:
    cst_r = _PARSER.apply(_doc({"type": "string"}))
    assert isinstance(cst_r, Ok)
    result = PostgresGenerator().apply(cst_r.value)
    assert isinstance(result, Err)
    assert any("object" in e.message.lower() for e in result.errors)


def test_integer_root_fails() -> None:
    cst_r = _PARSER.apply(_doc({"type": "integer"}))
    assert isinstance(cst_r, Ok)
    assert isinstance(PostgresGenerator().apply(cst_r.value), Err)


# ---------------------------------------------------------------------------
# Integration: full schema exercising all supported features
# ---------------------------------------------------------------------------


def test_integration_full_pipeline() -> None:
    schema = {
        "$defs": {
            "Address": {
                "type": "object",
                "description": "Postal address",
                "properties": {
                    "street": {"type": "string", "maxLength": 100, "description": "Street line"},
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
    expected = (
        "CREATE TABLE IF NOT EXISTS address (\n"
        "    street varchar(100) NOT NULL,\n"
        "    city text NOT NULL,\n"
        "    zip text CHECK ((zip ~ '^\\d{5}$'))\n"
        ");\n"
        "\n"
        "COMMENT ON TABLE address IS 'Postal address';\n"
        "\n"
        "COMMENT ON COLUMN address.street IS 'Street line';\n"
        "\n"
        "CREATE TABLE IF NOT EXISTS person (\n"
        "    id integer NOT NULL CHECK ((id >= 1)),\n"
        "    name varchar(255) NOT NULL,\n"
        "    age integer CHECK ((age >= 0) AND (age <= 150)),\n"
        "    created_at timestamptz,\n"
        "    address jsonb,\n"
        "    status text NOT NULL CHECK ((status IN ('active', 'inactive')))\n"
        ");\n"
        "\n"
        "COMMENT ON TABLE person IS 'Person record';\n"
    )
    assert _transpile(schema) == expected
