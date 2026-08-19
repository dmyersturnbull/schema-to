"""End-to-end tests for pass-through transpilation.

Verifies invertibility: `transpile(transpile(doc)) == transpile(doc)`.
"""

import orjson
from hypothesis import HealthCheck, given, settings
from tests._strategies import json_schema_st, openapi_doc_st
from tests._targets import transpiler_for

from schema_to import JsonSchemaRawDoc, MediaType, MediaTypes, Ok, OpenApiRawDoc
from schema_to.io.sink import JsonSchemaYamlArtifact, OpenApiYamlArtifact
from schema_to.pipeline import Transpiler


def _json_schema_pass_thru(output_media_type: MediaType = MediaTypes.json) -> Transpiler:
    return transpiler_for(
        "pass-thru", selects=JsonSchemaRawDoc, output_media_type=output_media_type
    )


def _openapi_pass_thru(output_media_type: MediaType = MediaTypes.json) -> Transpiler:
    return transpiler_for("pass-thru", selects=OpenApiRawDoc, output_media_type=output_media_type)


def _make_json_schema_doc(data: object, source_id: str = "test://doc") -> JsonSchemaRawDoc:
    return JsonSchemaRawDoc(
        doc_id=source_id,
        content=orjson.dumps(data),
        media_type=MediaTypes.json_schema,
        display_name="test",
    )


def _make_openapi_doc(data: object, source_id: str = "test://doc") -> OpenApiRawDoc:
    return OpenApiRawDoc(
        doc_id=source_id,
        content=orjson.dumps(data),
        media_type=MediaTypes.openapi,
        display_name="test",
    )


# ---------------------------------------------------------------------------
# Invertibility
# ---------------------------------------------------------------------------


@given(schema=json_schema_st())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_json_schema_pass_thru_invertible(schema: object) -> None:
    """transpile(doc) and transpile(transpile(doc)) must produce identical output."""
    doc = _make_json_schema_doc(schema)
    transpiler = _json_schema_pass_thru()

    r1 = transpiler.transpile(doc)
    assert isinstance(r1, Ok), f"First transpile failed: {r1}"
    artifact1 = r1.value[0]

    doc2 = JsonSchemaRawDoc(
        doc_id="test://doc2",
        content=artifact1.content,
        media_type=artifact1.media_type,
        display_name="test2",
    )
    r2 = transpiler.transpile(doc2)
    assert isinstance(r2, Ok), f"Second transpile failed: {r2}"
    artifact2 = r2.value[0]

    assert artifact1.content == artifact2.content, (
        f"Not invertible.\n"
        f"  1st output: {artifact1.content.decode('utf-8')!r:.300}\n"
        f"  2nd output: {artifact2.content.decode('utf-8')!r:.300}"
    )


@given(openapi=openapi_doc_st())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_openapi_pass_thru_invertible(openapi: dict) -> None:
    """transpile(doc) and transpile(transpile(doc)) must produce identical output."""
    doc = _make_openapi_doc(openapi)
    transpiler = _openapi_pass_thru()

    r1 = transpiler.transpile(doc)
    assert isinstance(r1, Ok), f"First transpile failed: {r1}"
    artifact1 = r1.value[0]

    doc2 = OpenApiRawDoc(
        doc_id="test://doc2",
        content=artifact1.content,
        media_type=artifact1.media_type,
        display_name="test2",
    )
    r2 = transpiler.transpile(doc2)
    assert isinstance(r2, Ok), f"Second transpile failed: {r2}"
    artifact2 = r2.value[0]

    assert artifact1.content == artifact2.content, (
        f"Not invertible.\n"
        f"  1st output: {artifact1.content.decode('utf-8')!r:.300}\n"
        f"  2nd output: {artifact2.content.decode('utf-8')!r:.300}"
    )


# ---------------------------------------------------------------------------
# Discriminator: accepts() must agree with document type
# ---------------------------------------------------------------------------


@given(schema=json_schema_st())
@settings(max_examples=50)
def test_json_schema_not_accepted_as_openapi(schema: object) -> None:
    """A `JsonSchemaRawDoc` must not be claimed by the OpenAPI transpiler."""
    doc = _make_json_schema_doc(schema)
    assert not _openapi_pass_thru().accepts(doc)
    assert _json_schema_pass_thru().accepts(doc)


@given(openapi=openapi_doc_st())
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_openapi_not_accepted_as_json_schema(openapi: dict) -> None:
    """An `OpenApiRawDoc` must not be claimed by the JSON Schema transpiler."""
    doc = _make_openapi_doc(openapi)
    assert _openapi_pass_thru().accepts(doc)
    assert not _json_schema_pass_thru().accepts(doc)


# ---------------------------------------------------------------------------
# YAML output smoke tests
# ---------------------------------------------------------------------------


def test_json_schema_yaml_output() -> None:
    schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
    doc = _make_json_schema_doc(schema)
    transpiler = _json_schema_pass_thru(MediaTypes.yaml)
    result = transpiler.transpile(doc)
    assert isinstance(result, Ok)
    artifact = result.value[0]
    assert artifact.artifact_id.endswith(".schema.yaml")
    assert isinstance(artifact, JsonSchemaYamlArtifact)
    assert artifact.media_type == MediaTypes.json_schema_yaml
    assert "type" in artifact.content.decode()


def test_openapi_yaml_output() -> None:
    openapi = {"openapi": "3.1.0", "info": {"title": "Test", "version": "1.0"}}
    doc = _make_openapi_doc(openapi)
    transpiler = _openapi_pass_thru(MediaTypes.yaml)
    result = transpiler.transpile(doc)
    assert isinstance(result, Ok)
    artifact = result.value[0]
    assert artifact.artifact_id.endswith(".yaml")
    assert isinstance(artifact, OpenApiYamlArtifact)
    assert artifact.media_type == MediaTypes.openapi_yaml
    assert "openapi" in artifact.content.decode()
