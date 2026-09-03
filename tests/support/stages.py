"""Running individual pipeline stages, for tests below the end-to-end layer.

An integration test composes the stages it cares about and asserts on what comes out,
rather than routing a target and reading the finished artifact.
These helpers do the composing and unwrap each `Result` along the way.
"""

from collections.abc import Sequence

from tests.support.asserts import ok
from tests.support.docs import json_schema_doc, openapi_doc, schema_map_doc
from tests.support.types import JsonLike

from schema_to.ast.python import PythonModule
from schema_to.cst.json_schema import JsonSchemaDocument, JsonSchemaMapDocument
from schema_to.cst.openapi import OpenApiDocument
from schema_to.generate.fastapi.fastapi import FastApiTransformer
from schema_to.generate.postgres.sql import PostgresTransformer
from schema_to.generate.postgres.sql_tables import PostgresTableSetTransformer
from schema_to.generate.pydantic.pydantic import PydanticTransformer
from schema_to.io.sink import Artifact
from schema_to.parse.json_schema import JsonSchemaMapParser, JsonSchemaParser
from schema_to.parse.openapi import OpenApiParser
from schema_to.reify.python import PythonReifier
from schema_to.reify.sql import SqlReifier
from schema_to.resolve.json_schema import JsonSchemaRefResolver


def json_schema_cst(data: JsonLike, doc_id: str = "test://schema") -> JsonSchemaDocument:
    """Parse `data` as a JSON Schema document."""
    return ok(JsonSchemaParser().apply(json_schema_doc(data, doc_id)))


def openapi_cst(data: JsonLike, doc_id: str = "test://api") -> OpenApiDocument:
    """Parse `data` as an OpenAPI document."""
    return ok(OpenApiParser().apply(openapi_doc(data, doc_id)))


def schema_map_cst(data: JsonLike, name: str = "main") -> JsonSchemaMapDocument:
    """Parse `data` as a document mapping names to schemas."""
    return ok(JsonSchemaMapParser().apply(schema_map_doc(data, name)))


def resolved_json_schema(
    data: JsonLike, doc_id: str = "test://schema"
) -> tuple[JsonSchemaDocument, JsonSchemaRefResolver]:
    """Parse and resolve `data`, returning the document and the resolver that holds it.

    The resolver is returned alongside because a generator needs the same one
    to follow a `$ref` that survives resolution.
    """
    resolver = JsonSchemaRefResolver()
    return ok(resolver.apply(json_schema_cst(data, doc_id))), resolver


def pydantic_source(data: JsonLike, doc_id: str = "test://schema") -> str:
    """Parse, resolve, generate, and reify `data` into Pydantic source."""
    document, resolver = resolved_json_schema(data, doc_id)
    module = ok(PydanticTransformer(resolver=resolver).apply(document))
    return _one_artifact_text(ok(PythonReifier().apply(module)))


def postgres_source(data: JsonLike, doc_id: str = "test://schema") -> str:
    """Parse, resolve, generate, and reify `data` into PostgreSQL DDL."""
    document, resolver = resolved_json_schema(data, doc_id)
    script = ok(PostgresTransformer(resolver=resolver).apply(document))
    return _one_artifact_text(ok(SqlReifier("schema.sql").apply(script)))


def table_set_source(data: JsonLike, name: str = "main") -> str:
    """Parse, resolve, generate, and reify a named-schema map into PostgreSQL DDL."""
    resolver = JsonSchemaRefResolver()
    document = ok(resolver.apply_map(schema_map_cst(data, name)))
    script = ok(PostgresTableSetTransformer(resolver=resolver).apply(document))
    return _one_artifact_text(ok(SqlReifier("schema.sql").apply(script)))


def fastapi_module(data: JsonLike, doc_id: str = "test://api") -> PythonModule:
    """Parse `data` and generate the FastAPI module for it, without reifying."""
    return ok(FastApiTransformer().apply(openapi_cst(data, doc_id)))


def fastapi_source(data: JsonLike, doc_id: str = "test://api") -> str:
    """Parse, generate, and reify `data` into FastAPI application source."""
    return _one_artifact_text(ok(PythonReifier().apply(fastapi_module(data, doc_id))))


def _one_artifact_text(artifacts: Sequence[Artifact]) -> str:
    assert len(artifacts) == 1, f"Expected one artifact, got {len(artifacts)}"
    return artifacts[0].content.decode()
