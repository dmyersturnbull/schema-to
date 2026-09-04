"""Routing a target name to the transpilers that run it.

The router is the one place that knows what a target is made of, so what it
returns for each name — and which raw-document kinds those transpilers accept —
is what every other module depends on.
"""

import pytest
from tests.support.docs import json_schema_doc, openapi_doc, schema_map_doc

from schema_to.io.media_type import MediaTypes
from schema_to.io.source import JsonSchemaRawDoc, OpenApiRawDoc, SchemaMapRawDoc
from schema_to.transpile.factory import RoutingError, TranspilerRouter

_TARGETS = sorted(TranspilerRouter.SUPPORTED_TARGETS)


@pytest.mark.parametrize("target", _TARGETS)
def test_every_supported_target_routes_to_something(target: str) -> None:
    assert TranspilerRouter().route(target, MediaTypes.json)


@pytest.mark.parametrize("target", _TARGETS)
def test_a_routed_transpiler_accepts_the_documents_it_selects(target: str) -> None:
    """`selects` is what the pipeline groups documents by, so it has to agree with `accepts`."""
    for transpiler in TranspilerRouter().route(target, MediaTypes.json):
        doc = {
            JsonSchemaRawDoc: json_schema_doc({"type": "object"}),
            OpenApiRawDoc: openapi_doc(
                {"openapi": "3.1.0", "info": {"title": "T", "version": "1"}}
            ),
            SchemaMapRawDoc: schema_map_doc({"thing": {"type": "object"}}),
        }[transpiler.selects]
        assert transpiler.accepts(doc)


def test_an_unknown_target_names_the_ones_that_exist() -> None:
    """A typo should be answerable from the error alone."""
    with pytest.raises(RoutingError) as caught:
        TranspilerRouter().route("pydentic", MediaTypes.json)
    message = str(caught.value)
    assert "pydentic" in message
    assert "pydantic" in message


def test_pass_thru_routes_both_document_kinds() -> None:
    """A pass-through run may be handed a mix, so it claims each kind separately."""
    routed = TranspilerRouter().route("pass-thru", MediaTypes.json)
    assert {t.selects for t in routed} == {JsonSchemaRawDoc, OpenApiRawDoc}


@pytest.mark.parametrize("target", ["pydantic", "postgres", "pg-jsonschema"])
def test_a_schema_target_reads_one_schema_per_document(target: str) -> None:
    assert [t.selects for t in TranspilerRouter().route(target, MediaTypes.json)] == [
        JsonSchemaRawDoc
    ]


@pytest.mark.parametrize("target", ["fastapi", "json-schema"])
def test_an_openapi_target_reads_openapi_documents(target: str) -> None:
    assert [t.selects for t in TranspilerRouter().route(target, MediaTypes.json)] == [OpenApiRawDoc]


@pytest.mark.parametrize("target", ["pydantic", "postgres", "pg-jsonschema", "pass-thru"])
def test_a_schema_map_run_reads_schema_map_documents(target: str) -> None:
    routed = TranspilerRouter().route(target, MediaTypes.json, schema_map=True)
    assert [t.selects for t in routed] == [SchemaMapRawDoc]


@pytest.mark.parametrize("target", ["fastapi", "json-schema"])
def test_an_openapi_target_claims_nothing_in_a_schema_map_run(target: str) -> None:
    """An OpenAPI description is not a map of named schemas; the documents fall through."""
    assert TranspilerRouter().route(target, MediaTypes.json, schema_map=True) == []
