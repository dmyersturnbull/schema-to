"""`CHECK` constraints derived from JSON Schema validation keywords.

A constraint the column type already enforces is left off,
so these also pin the cases where no `CHECK` is emitted at all.
"""

from tests.support.stages import postgres_source


def test_check_minimum() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"n": {"type": "integer", "minimum": 0}},
        "required": ["n"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    n integer NOT NULL CHECK ((n >= 0))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_check_maximum() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"n": {"type": "integer", "maximum": 100}},
        "required": ["n"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    n integer NOT NULL CHECK ((n <= 100))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_check_exclusive_minimum() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"x": {"type": "number", "exclusiveMinimum": 0}},
        "required": ["x"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    x double precision NOT NULL CHECK ((x > 0))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_check_exclusive_maximum() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"x": {"type": "number", "exclusiveMaximum": 1}},
        "required": ["x"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    x double precision NOT NULL CHECK ((x < 1))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_check_combined_min_max() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"n": {"type": "integer", "minimum": 0, "maximum": 150}},
        "required": ["n"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    n integer NOT NULL CHECK ((n >= 0) AND (n <= 150))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_check_minimum_float() -> None:
    """Non-integer minimum must preserve the decimal point."""
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"n": {"type": "number", "minimum": 0.5}},
        "required": ["n"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    n double precision NOT NULL CHECK ((n >= 0.5))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_check_min_length() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"s": {"type": "string", "minLength": 3}},
        "required": ["s"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    s text NOT NULL CHECK ((char_length(s) >= 3))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_varchar_no_max_length_check() -> None:
    """VARCHAR already enforces maxLength; no redundant char_length CHECK is emitted."""
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"s": {"type": "string", "minLength": 3, "maxLength": 20}},
        "required": ["s"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    s varchar(20) NOT NULL CHECK ((char_length(s) >= 3))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_check_pattern() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"s": {"type": "string", "pattern": "^[A-Z]+$"}},
        "required": ["s"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    s text NOT NULL CHECK ((s ~ '^[A-Z]+$'))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_check_pattern_single_quote_escaped() -> None:
    """Single quotes inside a pattern must be doubled for SQL safety."""
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"s": {"type": "string", "pattern": "it's"}},
        "required": ["s"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    s text NOT NULL CHECK ((s ~ 'it''s'))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_check_enum() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"s": {"type": "string", "enum": ["a", "b"]}},
        "required": ["s"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    s text NOT NULL CHECK ((s IN ('a', 'b')))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_check_enum_with_null_filters_null() -> None:
    """Null entries in enum are excluded from the IN list."""
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"s": {"type": "string", "enum": [None, "active"]}},
        "required": ["s"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    s text NOT NULL CHECK ((s IN ('active')))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_check_enum_all_null_no_check() -> None:
    """An enum containing only null produces no IN constraint."""
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"s": {"type": "string", "enum": [None]}},
        "required": ["s"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    s text NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_check_enum_empty_no_check() -> None:
    """An empty enum array produces no IN constraint."""
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"s": {"type": "string", "enum": []}},
        "required": ["s"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    s text NOT NULL\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_check_const_string() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"v": {"type": "string", "const": "fixed"}},
        "required": ["v"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    v text NOT NULL CHECK ((v = 'fixed'))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_check_const_empty_string() -> None:
    """const: '' must emit an equality check against the empty string literal."""
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"v": {"type": "string", "const": ""}},
        "required": ["v"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    v text NOT NULL CHECK ((v = ''))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_check_const_integer() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"v": {"type": "integer", "const": 42}},
        "required": ["v"],
    }
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    v integer NOT NULL CHECK ((v = 42))\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )
