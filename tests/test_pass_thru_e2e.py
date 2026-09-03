"""End-to-end tests for pass-through transpilation.

Verifies invertibility: `transpile(transpile(doc)) == transpile(doc)`.
"""

from dataclasses import replace
from functools import partial

from hypothesis import HealthCheck, given, settings
from tests.strategies.json_schema import json_schema_st
from tests.strategies.openapi import openapi_doc_st
from tests.support.docs import json_schema_doc, openapi_doc
from tests.support.drive import PASS_THRU_JSON_SCHEMA, PASS_THRU_OPENAPI
from tests.support.types import JsonLike

from schema_to import JsonSchemaRawDoc, MediaTypes, Ok, OpenApiRawDoc
from schema_to.io.sink import JsonSchemaYamlArtifact, OpenApiYamlArtifact

_make_json_schema_doc = partial(json_schema_doc, media_type=MediaTypes.json_schema)
_make_openapi_doc = partial(openapi_doc, media_type=MediaTypes.openapi)


# ---------------------------------------------------------------------------
# Invertibility
# ---------------------------------------------------------------------------


@given(schema=json_schema_st())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_json_schema_pass_thru_invertible(schema: JsonLike) -> None:
    """transpile(doc) and transpile(transpile(doc)) must produce identical output."""
    doc = _make_json_schema_doc(schema)
    transpiler = PASS_THRU_JSON_SCHEMA.transpiler()

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
        f"  1st output: {artifact1.content.decode()!r:.300}\n"
        f"  2nd output: {artifact2.content.decode()!r:.300}"
    )


@given(openapi=openapi_doc_st())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_openapi_pass_thru_invertible(openapi: JsonLike) -> None:
    """transpile(doc) and transpile(transpile(doc)) must produce identical output."""
    doc = _make_openapi_doc(openapi)
    transpiler = PASS_THRU_OPENAPI.transpiler()

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
        f"  1st output: {artifact1.content.decode()!r:.300}\n"
        f"  2nd output: {artifact2.content.decode()!r:.300}"
    )


# ---------------------------------------------------------------------------
# Discriminator: accepts() must agree with document type
# ---------------------------------------------------------------------------


@given(schema=json_schema_st())
@settings(max_examples=50)
def test_json_schema_not_accepted_as_openapi(schema: JsonLike) -> None:
    """A `JsonSchemaRawDoc` must not be claimed by the OpenAPI transpiler."""
    doc = _make_json_schema_doc(schema)
    assert not PASS_THRU_OPENAPI.transpiler().accepts(doc)
    assert PASS_THRU_JSON_SCHEMA.transpiler().accepts(doc)


@given(openapi=openapi_doc_st())
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_openapi_not_accepted_as_json_schema(openapi: JsonLike) -> None:
    """An `OpenApiRawDoc` must not be claimed by the JSON Schema transpiler."""
    doc = _make_openapi_doc(openapi)
    assert PASS_THRU_OPENAPI.transpiler().accepts(doc)
    assert not PASS_THRU_JSON_SCHEMA.transpiler().accepts(doc)


# ---------------------------------------------------------------------------
# YAML output smoke tests
# ---------------------------------------------------------------------------


def test_json_schema_yaml_output() -> None:
    schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
    doc = _make_json_schema_doc(schema)
    transpiler = replace(PASS_THRU_JSON_SCHEMA, output_media_type=MediaTypes.yaml).transpiler()
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
    transpiler = replace(PASS_THRU_OPENAPI, output_media_type=MediaTypes.yaml).transpiler()
    result = transpiler.transpile(doc)
    assert isinstance(result, Ok)
    artifact = result.value[0]
    assert artifact.artifact_id.endswith(".yaml")
    assert isinstance(artifact, OpenApiYamlArtifact)
    assert artifact.media_type == MediaTypes.openapi_yaml
    assert "openapi" in artifact.content.decode()
