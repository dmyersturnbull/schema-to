"""Every diagnostic that has a document or a node to point at says where it is.

A location names the file the user wrote, and a pointer into it,
including for a schema that a stage carved out of a larger file along the way.
"""

from tests.support.asserts import ok
from tests.support.docs import json_schema_doc, openapi_doc, schema_map_doc
from tests.support.drive import FASTAPI, JSON_SCHEMA, POSTGRES_TABLE_SET, PYDANTIC
from tests.support.types import JsonLike

from schema_to.cst.json_schema import JsonSchemaDocument
from schema_to.errors import SourceLocation
from schema_to.parse.json_schema import JsonSchemaMapParser, JsonSchemaParser
from schema_to.resolve.json_schema import JsonSchemaRefResolver
from schema_to.result import Err, Ok, Result
from schema_to.transpile.schema_map import SchemaMapExpander

_THING: JsonLike = {
    "type": "object",
    "x-pg-table": "thing",
    "properties": {"id": {"type": "string"}},
}


def _error_locations[T](result: Result[T]) -> list[SourceLocation | None]:
    assert isinstance(result, Err)
    return [e.location for e in result.errors]


def _warning_locations[T](result: Result[T], code: str) -> list[SourceLocation | None]:
    return [w.location for w in result.warnings if w.code == code]


def test_a_duplicate_table_is_located_at_the_schema_that_repeats_it() -> None:
    doc = schema_map_doc({"a-data": _THING, "b-data": _THING}, "catalog")
    result = POSTGRES_TABLE_SET.run(doc)
    assert _error_locations(result) == [SourceLocation("file:///catalog.yaml", "/b-data")]


def test_a_table_that_is_not_an_object_is_located_at_its_schema() -> None:
    doc = schema_map_doc({"thing": {"type": "string", "x-pg-table": "thing"}}, "catalog")
    result = POSTGRES_TABLE_SET.run(doc)
    assert _error_locations(result) == [SourceLocation("file:///catalog.yaml", "/thing")]


def test_a_table_warning_is_located_at_its_schema() -> None:
    keyless = {"type": "object", "x-pg-table": "thing", "properties": {"n": {"type": "string"}}}
    result = POSTGRES_TABLE_SET.run(schema_map_doc({"thing": keyless}, "catalog"))
    assert isinstance(result, Ok)
    assert _warning_locations(result, "no-primary-key") == [
        SourceLocation("file:///catalog.yaml", "/thing")
    ]


def test_a_boolean_root_is_located_at_the_document() -> None:
    result = PYDANTIC.run(json_schema_doc(True, "file:///flag.schema.json"))  # ruff: ignore[boolean-positional-value-in-call]
    assert _error_locations(result) == [SourceLocation("file:///flag.schema.json", "")]


def test_an_unsupported_security_scheme_is_located_at_the_scheme() -> None:
    spec: JsonLike = {
        "openapi": "3.1.0",
        "info": {"title": "T", "version": "1"},
        "components": {"securitySchemes": {"tls": {"type": "mutualTLS"}}},
        "paths": {},
    }
    result = FASTAPI.run(openapi_doc(spec, "file:///api.yaml"))
    assert isinstance(result, Ok)
    assert _warning_locations(result, "security-unsupported") == [
        SourceLocation("file:///api.yaml", "/components/securitySchemes/tls")
    ]


def test_a_route_security_warning_is_located_at_its_operation() -> None:
    spec: JsonLike = {
        "openapi": "3.1.0",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/things": {
                "get": {"security": [{"nope": []}], "responses": {"200": {"description": "ok"}}}
            }
        },
    }
    result = FASTAPI.run(openapi_doc(spec, "file:///api.yaml"))
    assert isinstance(result, Ok)
    here = SourceLocation("file:///api.yaml", "/paths/~1things/get")
    assert _warning_locations(result, "security-unknown-scheme") == [here]


def test_a_lifted_component_is_unique_but_still_points_into_the_openapi_document() -> None:
    spec: JsonLike = {
        "openapi": "3.1.0",
        "info": {"title": "T", "version": "1"},
        "components": {"schemas": {"Pet": {"type": "object"}, "Owner": {"type": "object"}}},
        "paths": {},
    }
    artifacts = JSON_SCHEMA.artifacts(openapi_doc(spec, "file:///api.yaml"))
    assert {a.artifact_id for a in artifacts} == {"Pet.schema.json", "Owner.schema.json"}
    assert {a.source_ids for a in artifacts} == {
        ("file:///api.yaml#/components/schemas/Pet",),
        ("file:///api.yaml#/components/schemas/Owner",),
    }


def test_a_ref_in_a_carved_out_document_resolves_against_the_original_file() -> None:
    """`#/stamp` in `catalog.yaml#/thing` means `catalog.yaml#/stamp`, not a pointer inside `thing`."""
    catalog = schema_map_doc(
        {
            "stamp": {"type": "string"},
            "thing": {"type": "object", "properties": {"at": {"$ref": "#/stamp"}}},
        },
        "catalog",
    )
    resolver = JsonSchemaRefResolver()
    resolver.register_map(ok(JsonSchemaMapParser().apply(catalog)))
    [thing] = ok(SchemaMapExpander(roots=frozenset({"thing"})).apply(catalog))
    parsed: JsonSchemaDocument = ok(JsonSchemaParser().apply(thing))
    assert parsed.source_id == "file:///catalog.yaml#/thing"
    assert isinstance(resolver.apply(parsed), Ok)
