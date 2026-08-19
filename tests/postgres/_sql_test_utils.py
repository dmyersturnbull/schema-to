"""Shared utilities for Postgres tests."""

import orjson
from tests._targets import transpiler_for

from schema_to.io.media_type import MediaTypes
from schema_to.io.source import SchemaMapRawDoc
from schema_to.result import Err, Ok


def get_doc(data: object, name: str = "main") -> SchemaMapRawDoc:
    """Creates a schema-map JSON Schema doc from `data`, with `doc_id` from `name`."""
    return SchemaMapRawDoc(
        doc_id=f"file:///{name}.yaml",
        content=orjson.dumps(data),
        media_type=MediaTypes.json,
        display_name=name,
    )


def get_sql(*docs: SchemaMapRawDoc) -> str:
    """Runs a Postgres transpiler, asserts that the result is an [Ok][], and returns the SQL."""
    transpiler = transpiler_for("postgres", selects=SchemaMapRawDoc, schema_map=True)
    result = transpiler.transpile_all(docs)
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    assert len(result.value) == 1
    return result.value[0].content.decode()


def get_warnings(*docs: SchemaMapRawDoc) -> list[str]:
    """Runs a Postgres transpiler, asserts that the result is an [Ok][], and returns warnings."""
    transpiler = transpiler_for("postgres", selects=SchemaMapRawDoc, schema_map=True)
    result = transpiler.transpile_all(docs)
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    assert len(result.value) == 1
    return [w.code for w in result.warnings if w.code]


def get_errors(*docs: SchemaMapRawDoc) -> list[str]:
    """Runs a Postgres transpiler, asserts that the result is an [Err][], and returns messages."""
    transpiler = transpiler_for("postgres", selects=SchemaMapRawDoc, schema_map=True)
    result = transpiler.transpile_all(docs)
    assert isinstance(result, Err)
    return [getattr(e, "message", str(e)) for e in result.errors]
