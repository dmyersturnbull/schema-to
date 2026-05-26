"""Tests for the OpenAPI → JSON Schema extraction transpiler."""

from __future__ import annotations

import orjson
from hypothesis import HealthCheck, given, settings
from tests.strategies import openapi_doc_st

from schema_to import JsonSchemaParser, MediaTypes, Ok, OpenApiExtractTranspiler, RawDocument

_JS_PARSER = JsonSchemaParser()


def _make_json_doc(data: object, source_id: str = "test://doc") -> RawDocument:
    return RawDocument(
        source_id=source_id,
        content=orjson.dumps(data),
        media_type=MediaTypes.json,
        display_name="test",
    )


@given(openapi=openapi_doc_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_openapi_extract_schemas(openapi: dict) -> None:
    """Extracted artifact count matches component schema count, IDs match names, and
    each extracted schema re-parses successfully.
    """
    doc = _make_json_doc(openapi)
    transpiler = OpenApiExtractTranspiler()

    result = transpiler.transpile(doc)
    assert isinstance(result, Ok), f"Extract failed: {result}"

    component_schemas = openapi.get("components", {}).get("schemas", {})
    assert len(result.value) == len(component_schemas)

    artifact_stems = {a.artifact_id.removesuffix(".schema.json") for a in result.value}
    assert artifact_stems == set(component_schemas.keys())

    for artifact in result.value:
        assert artifact.artifact_id.endswith(".schema.json")
        doc2 = _make_json_doc(orjson.loads(artifact.content))
        r = _JS_PARSER.apply(doc2)
        assert isinstance(r, Ok), (
            f"Extracted schema {artifact.artifact_id!r} failed to re-parse: "
            f"{[e.message for e in r.errors]}"
        )


def test_openapi_extract_yaml_output() -> None:
    openapi = {
        "openapi": "3.1.0",
        "info": {"title": "Test", "version": "1.0"},
        "components": {"schemas": {"Foo": {"type": "object"}}},
    }
    transpiler = OpenApiExtractTranspiler(use_yaml=True)
    result = transpiler.transpile(_make_json_doc(openapi))
    assert isinstance(result, Ok)
    artifact = result.value[0]
    assert artifact.artifact_id.endswith(".schema.yaml")
    assert b"type" in artifact.content
