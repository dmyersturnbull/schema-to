"""End-to-end property tests for pass-through transpilation.

Three properties are verified with Hypothesis:

1. **JSON Schema round-trip** — `serialize(parse(doc))` is stable: parsing the
   serialized form and re-serializing gives the same JSON value.

2. **OpenAPI round-trip** — same property for OpenAPI 3.1 documents.

3. **OpenAPI → JSON Schema extract** — the schemas extracted from
   `components/schemas` match the schemas that were placed there.
"""

from __future__ import annotations

import json

import orjson
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from schema_to._result import Err, Ok
from schema_to.io._source import MediaTypes, RawDocument
from schema_to.parse._json_schema import JsonSchemaParser
from schema_to.parse._openapi import OpenApiParser
from schema_to.serialize._json_schema import JsonSchemaSerializer
from schema_to.serialize._openapi import OpenApiSerializer
from schema_to.transpile._pass_thru import (
    JsonSchemaPassThruTranspiler,
    OpenApiExtractTranspiler,
    OpenApiPassThruTranspiler,
)

from tests.strategies import json_schema_st, openapi_doc_st

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_JS_PARSER = JsonSchemaParser()
_JS_SERIALIZER = JsonSchemaSerializer()
_OA_PARSER = OpenApiParser()
_OA_SERIALIZER = OpenApiSerializer()


def _make_json_doc(data: object, source_id: str = "test://doc") -> RawDocument:
    return RawDocument(
        source_id=source_id,
        content=orjson.dumps(data),
        media_type=MediaTypes.json,
        display_name="test",
    )


def _serialize_json(obj: object) -> bytes:
    """Stable, deterministic JSON bytes (sorted keys, no trailing whitespace)."""
    return orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)


# ---------------------------------------------------------------------------
# JSON Schema round-trip
# ---------------------------------------------------------------------------


@given(schema=json_schema_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_json_schema_round_trip(schema: object) -> None:
    """parse → serialize → re-parse → re-serialize must be idempotent."""
    doc = _make_json_doc(schema)

    r1 = _JS_PARSER.apply(doc)
    assert isinstance(r1, Ok), f"First parse failed: {[e.message for e in r1.errors]}"
    serialized1 = _JS_SERIALIZER.serialize_document(r1.value)

    doc2 = _make_json_doc(serialized1)
    r2 = _JS_PARSER.apply(doc2)
    assert isinstance(r2, Ok), f"Second parse failed: {[e.message for e in r2.errors]}"
    serialized2 = _JS_SERIALIZER.serialize_document(r2.value)

    assert _serialize_json(serialized1) == _serialize_json(serialized2), (
        f"Round-trip not idempotent.\n"
        f"  after 1st serialize: {serialized1}\n"
        f"  after 2nd serialize: {serialized2}"
    )


@given(schema=json_schema_st())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_json_schema_pass_thru_transpiler(schema: object) -> None:
    """JsonSchemaPassThruTranspiler produces output that re-parses without errors."""
    doc = _make_json_doc(schema)
    transpiler = JsonSchemaPassThruTranspiler()
    assert transpiler.accepts(doc)

    result = transpiler.transpile(doc)
    assert isinstance(result, Ok), f"Transpile failed: {result}"

    artifacts = result.value
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.artifact_id.endswith(".schema.json")

    doc2 = _make_json_doc(orjson.loads(artifact.content))
    r2 = _JS_PARSER.apply(doc2)
    assert isinstance(r2, Ok), f"Re-parse failed: {[e.message for e in r2.errors]}"


# ---------------------------------------------------------------------------
# OpenAPI round-trip
# ---------------------------------------------------------------------------


@given(openapi=openapi_doc_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_openapi_round_trip(openapi: dict) -> None:
    """parse → serialize → re-parse → re-serialize must be idempotent."""
    doc = _make_json_doc(openapi)

    r1 = _OA_PARSER.apply(doc)
    assert isinstance(r1, Ok), f"First parse failed: {[e.message for e in r1.errors]}"
    serialized1 = _OA_SERIALIZER.serialize(r1.value)

    doc2 = _make_json_doc(serialized1)
    r2 = _OA_PARSER.apply(doc2)
    assert isinstance(r2, Ok), f"Second parse failed: {[e.message for e in r2.errors]}"
    serialized2 = _OA_SERIALIZER.serialize(r2.value)

    assert _serialize_json(serialized1) == _serialize_json(serialized2), (
        f"Round-trip not idempotent.\n"
        f"  after 1st serialize: {json.dumps(serialized1, indent=2)[:500]}\n"
        f"  after 2nd serialize: {json.dumps(serialized2, indent=2)[:500]}"
    )


@given(openapi=openapi_doc_st())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_openapi_pass_thru_transpiler(openapi: dict) -> None:
    """OpenApiPassThruTranspiler produces output that re-parses without errors."""
    doc = _make_json_doc(openapi)
    transpiler = OpenApiPassThruTranspiler()
    assert transpiler.accepts(doc)

    result = transpiler.transpile(doc)
    assert isinstance(result, Ok), f"Transpile failed: {result}"

    artifacts = result.value
    assert len(artifacts) == 1
    doc2 = _make_json_doc(orjson.loads(artifacts[0].content))
    r2 = _OA_PARSER.apply(doc2)
    assert isinstance(r2, Ok), f"Re-parse failed: {[e.message for e in r2.errors]}"


# ---------------------------------------------------------------------------
# OpenAPI → JSON Schema extract
# ---------------------------------------------------------------------------


@given(openapi=openapi_doc_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_openapi_extract_schema_count(openapi: dict) -> None:
    """Extracted artifact count equals the number of component schemas."""
    doc = _make_json_doc(openapi)
    transpiler = OpenApiExtractTranspiler()

    result = transpiler.transpile(doc)
    assert isinstance(result, Ok), f"Extract failed: {result}"

    expected_count = len(openapi.get("components", {}).get("schemas", {}))
    assert len(result.value) == expected_count


@given(openapi=openapi_doc_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_openapi_extract_schemas_round_trip(openapi: dict) -> None:
    """Each extracted schema artifact must re-parse successfully."""
    doc = _make_json_doc(openapi)
    transpiler = OpenApiExtractTranspiler()

    result = transpiler.transpile(doc)
    assert isinstance(result, Ok)

    for artifact in result.value:
        assert artifact.artifact_id.endswith(".schema.json")
        doc2 = _make_json_doc(orjson.loads(artifact.content))
        r = _JS_PARSER.apply(doc2)
        assert isinstance(r, Ok), (
            f"Extracted schema {artifact.artifact_id!r} failed to re-parse: "
            f"{[e.message for e in r.errors]}"
        )


@given(openapi=openapi_doc_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_openapi_extract_schema_names(openapi: dict) -> None:
    """Artifact IDs must correspond 1-to-1 with component schema names."""
    doc = _make_json_doc(openapi)
    transpiler = OpenApiExtractTranspiler()

    result = transpiler.transpile(doc)
    assert isinstance(result, Ok)

    component_names = set(openapi.get("components", {}).get("schemas", {}).keys())
    artifact_stems = {a.artifact_id.removesuffix(".schema.json") for a in result.value}
    assert artifact_stems == component_names


# ---------------------------------------------------------------------------
# Discriminator: accepts() must agree with document content
# ---------------------------------------------------------------------------


@given(schema=json_schema_st())
@settings(max_examples=50)
def test_json_schema_not_accepted_as_openapi(schema: object) -> None:
    """A plain JSON Schema document must not be claimed by the OpenAPI transpiler."""
    doc = _make_json_doc(schema)
    assert not OpenApiPassThruTranspiler().accepts(doc)
    assert JsonSchemaPassThruTranspiler().accepts(doc)


@given(openapi=openapi_doc_st())
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_openapi_not_accepted_as_json_schema(openapi: dict) -> None:
    """An OpenAPI document must not be claimed by the JSON Schema transpiler."""
    doc = _make_json_doc(openapi)
    assert OpenApiPassThruTranspiler().accepts(doc)
    assert not JsonSchemaPassThruTranspiler().accepts(doc)


# ---------------------------------------------------------------------------
# YAML output smoke test (not property-based — just verifies encoding)
# ---------------------------------------------------------------------------


def test_json_schema_yaml_output() -> None:
    schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
    doc = _make_json_doc(schema)
    transpiler = JsonSchemaPassThruTranspiler(use_yaml=True)
    result = transpiler.transpile(doc)
    assert isinstance(result, Ok)
    artifact = result.value[0]
    assert artifact.artifact_id.endswith(".schema.yaml")
    assert artifact.media_type == MediaTypes.yaml
    # YAML should be decodable text
    text = artifact.content.decode()
    assert "type" in text


def test_openapi_yaml_output() -> None:
    openapi = {"openapi": "3.1.0", "info": {"title": "Test", "version": "1.0"}}
    doc = _make_json_doc(openapi)
    transpiler = OpenApiPassThruTranspiler(use_yaml=True)
    result = transpiler.transpile(doc)
    assert isinstance(result, Ok)
    artifact = result.value[0]
    assert artifact.artifact_id.endswith(".yaml")
    assert artifact.media_type == MediaTypes.yaml
    assert b"openapi" in artifact.content
