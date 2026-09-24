"""Table naming, `$defs` tables, and `COMMENT ON` emission."""

from tests.support.docs import json_schema_doc
from tests.support.drive import POSTGRES
from tests.support.stages import postgres_source


def test_empty_object() -> None:
    """Schema with title but no properties produces a skeleton table with comment."""
    schema = {"type": "object", "title": "T"}
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    -- (no columns)\n);\n\nCOMMENT ON TABLE t IS 'T';\n"
    )


def test_no_title_no_comment() -> None:
    """Schema with no title and no description produces no COMMENT ON."""
    schema = {"type": "object"}
    # source_id "test://schema" → safe_sql_identifier → "test_schema"
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS test_schema (\n    -- (no columns)\n);\n"
    )


def test_table_name_from_title() -> None:
    schema = {"type": "object", "title": "UserProfile"}
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS user_profile (\n    -- (no columns)\n);\n\nCOMMENT ON TABLE user_profile IS 'UserProfile';\n"
    )


def test_table_name_from_source_id() -> None:
    """When there is no title, source_id determines the table name."""
    doc = json_schema_doc({"type": "object"}, "https://example.com/product.json")
    assert "CREATE TABLE IF NOT EXISTS https_example_com_product_json" in POSTGRES.text(doc)


def test_defs_object_gets_own_table() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "$defs": {"A": {"type": "object"}},
        "properties": {"a": {"$ref": "#/$defs/A"}},
        "required": ["a"],
    }
    assert postgres_source(schema) == (
        "CREATE TABLE IF NOT EXISTS a (\n    -- (no columns)\n);\n"
        "\n"
        "CREATE TABLE IF NOT EXISTS t (\n    a jsonb NOT NULL\n);\n"
        "\n"
        "COMMENT ON TABLE t IS 'T';\n"
    )


def test_defs_table_precedes_root() -> None:
    """$defs tables are emitted before the root table."""
    schema = {"type": "object", "title": "Root", "$defs": {"Leaf": {"type": "object"}}}
    src = postgres_source(schema)
    assert src.index("leaf") < src.index("root")


def test_table_description_comment() -> None:
    schema = {"type": "object", "title": "T", "description": "A table"}
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS t (\n    -- (no columns)\n);\n\nCOMMENT ON TABLE t IS 'A table';\n"
    )


def test_table_title_fallback_comment() -> None:
    """When only title (no description) is set, title is used for the COMMENT."""
    schema = {"type": "object", "title": "Foo"}
    assert (
        postgres_source(schema)
        == "CREATE TABLE IF NOT EXISTS foo (\n    -- (no columns)\n);\n\nCOMMENT ON TABLE foo IS 'Foo';\n"
    )


def test_column_description_comment() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"x": {"type": "string", "description": "The x value"}},
    }
    assert postgres_source(schema) == (
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
    assert postgres_source(schema) == (
        "CREATE TABLE IF NOT EXISTS t (\n    sku text\n);\n"
        "\n"
        "COMMENT ON TABLE t IS 'T';\n"
        "\n"
        "COMMENT ON COLUMN t.sku IS 'SKU code';\n"
    )
