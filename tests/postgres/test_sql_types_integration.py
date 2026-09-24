"""Mapping a JSON Schema property to a PostgreSQL column type.

Each case pins the whole column definition,
so a change in either the type or the nullability shows up as a diff rather than a silently different table.
"""

from tests.support.stages import postgres_source

# ---------------------------------------------------------------------------
# Type mappings — exact output
# ---------------------------------------------------------------------------


def test_required_string() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    x text NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_optional_string() -> None:
    schema = {"type": "object", "title": "T", "properties": {"x": {"type": "string"}}}
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    x text\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_integer_column() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"n": {"type": "integer"}},
        "required": ["n"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    n integer NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_number_column() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"v": {"type": "number"}},
        "required": ["v"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    v double precision NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_boolean_column() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"b": {"type": "boolean"}},
        "required": ["b"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    b boolean NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_varchar() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"s": {"type": "string", "maxLength": 10}},
        "required": ["s"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    s varchar(10) NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_timestamptz() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"ts": {"type": "string", "format": "date-time"}},
        "required": ["ts"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    ts timestamptz NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_date() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"d": {"type": "string", "format": "date"}},
        "required": ["d"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    d date NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_time() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"t": {"type": "string", "format": "time"}},
        "required": ["t"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    t time NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_uuid() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"id": {"type": "string", "format": "uuid"}},
        "required": ["id"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    id uuid NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_bytea() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"data": {"type": "string", "format": "byte"}},
        "required": ["data"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    data bytea NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_array_of_strings() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
        "required": ["tags"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    tags text[] NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_array_no_items_is_jsonb() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"data": {"type": "array"}},
        "required": ["data"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    data jsonb NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_nested_object_is_jsonb() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"meta": {"type": "object"}},
        "required": ["meta"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    meta jsonb NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_x_pg_type_override() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"loc": {"type": "string", "x-pg-type": "geometry(Point,4326)"}},
        "required": ["loc"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    loc geometry(Point,4326) NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


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
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    v text\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )
