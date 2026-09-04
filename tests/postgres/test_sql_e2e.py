"""Whole postgres target runs: JSON Schema document in, DDL script out.

Covers what only the routed transpiler decides —
which documents it accepts, `roots` filtering, and a script built from a full schema.
"""

from dataclasses import replace

import pytest
from hypothesis import HealthCheck, given, settings
from tests.strategies.restricted import object_schema_st, sql_object_schema_st
from tests.support.docs import DEFAULT_SCHEMA_ID, json_schema_doc
from tests.support.drive import POSTGRES
from tests.support.types import JsonLike

from schema_to import MediaTypes, OpenApiRawDoc, RawDoc


def _transpile(data: JsonLike, doc_id: str = DEFAULT_SCHEMA_ID) -> str:
    """Run the routed postgres target and return the emitted SQL."""
    return POSTGRES.text(json_schema_doc(data, doc_id))


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
# Transpiler accepts / rejects
# ---------------------------------------------------------------------------


def test_accepts_json_schema_document() -> None:
    assert POSTGRES.transpiler().accepts(json_schema_doc({}))


def test_rejects_openapi_document() -> None:
    doc = OpenApiRawDoc(doc_id="test://s", content=b"{}", media_type=MediaTypes.json)
    assert not POSTGRES.transpiler().accepts(doc)


def test_rejects_raw_document() -> None:
    doc = RawDoc(doc_id="test://s", content=b"{}", media_type=MediaTypes.json)
    assert not POSTGRES.transpiler().accepts(doc)


# ---------------------------------------------------------------------------
# Failure: non-transpilable schemas
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("schema", [True, False], ids=["true", "false"])
def test_boolean_root_fails(schema: JsonLike) -> None:
    """A boolean root schema names no columns, so no table can come of it."""
    [message] = POSTGRES.errors(json_schema_doc(schema))
    assert "boolean" in message.lower()


@pytest.mark.parametrize("type_", ["string", "integer"])
def test_non_object_root_fails(type_: str) -> None:
    """Only an object root maps to a table; the error names what it found instead."""
    [message] = POSTGRES.errors(json_schema_doc({"type": type_}))
    assert "object" in message.lower()


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


def test_roots_keeps_only_named_defs() -> None:
    """`roots` narrows generated `$defs` tables; the root table is unaffected."""
    schema = {
        "type": "object",
        "title": "Root",
        "$defs": {"Kept": {"type": "object"}, "Dropped": {"type": "object"}},
    }
    src = replace(POSTGRES, roots=frozenset({"Kept"})).text(json_schema_doc(schema))
    assert "CREATE TABLE IF NOT EXISTS kept" in src
    assert "CREATE TABLE IF NOT EXISTS dropped" not in src
    assert "CREATE TABLE IF NOT EXISTS root" in src


# ---------------------------------------------------------------------------
# COMMENT ON emission
# ---------------------------------------------------------------------------
