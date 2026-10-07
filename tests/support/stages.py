"""Running individual pipeline stages, for tests below the end-to-end layer.

An integration test composes the stages it cares about and asserts on what comes out,
rather than routing a target and reading the finished artifact.
These helpers do the composing and unwrap each `Result` along the way.
"""

from collections.abc import Sequence

from tests.support.asserts import ok
from tests.support.docs import (
    DEFAULT_OPENAPI_URI,
    DEFAULT_SCHEMA_URI,
    json_schema_doc,
    openapi_doc,
    schema_map_doc,
)
from tests.support.types import JsonLike

from schema_to.ast.python import PythonModule
from schema_to.cst.json_schema import JsonSchemaDocument, JsonSchemaMapDocument, ObjectSchema
from schema_to.cst.openapi import OpenApiDocument, Operation, PathItem
from schema_to.generate.fastapi.fastapi import FastApiTransformer
from schema_to.generate.inlining import FlatteningResult, SchemaFlattener
from schema_to.generate.postgres.sql import PostgresTransformer
from schema_to.generate.postgres.sql_tables import PostgresTableSetTransformer
from schema_to.generate.pydantic.pydantic import PydanticTransformer
from schema_to.io.sink import Artifact
from schema_to.parse.json_schema import JsonSchemaMapParser, JsonSchemaParser
from schema_to.parse.openapi import OpenApiParser
from schema_to.reify.python import PythonReifier
from schema_to.reify.sql import SqlReifier
from schema_to.resolve.json_schema import JsonSchemaRefResolver
from schema_to.result import Result


def json_schema_cst(data: JsonLike, uri: str = DEFAULT_SCHEMA_URI) -> JsonSchemaDocument:
    """Parse `data` as a JSON Schema document."""
    return ok(JsonSchemaParser().apply(json_schema_doc(data, uri)))


def openapi_cst(data: JsonLike, uri: str = DEFAULT_OPENAPI_URI) -> OpenApiDocument:
    """Parse `data` as an OpenAPI document."""
    return ok(OpenApiParser().apply(openapi_doc(data, uri)))


def schema_map_cst(data: JsonLike, name: str = "main") -> JsonSchemaMapDocument:
    """Parse `data` as a document mapping names to schemas."""
    return ok(JsonSchemaMapParser().apply(schema_map_doc(data, name)))


def resolved_json_schema(
    data: JsonLike, uri: str = DEFAULT_SCHEMA_URI
) -> tuple[JsonSchemaDocument, JsonSchemaRefResolver]:
    """Parse and resolve `data`, returning the document and the resolver that holds it.

    The resolver is returned alongside because a generator needs the same one
    to follow a `$ref` that survives resolution.
    """
    resolver = JsonSchemaRefResolver()
    return ok(resolver.apply(json_schema_cst(data, uri))), resolver


def pydantic_source(data: JsonLike, uri: str = DEFAULT_SCHEMA_URI) -> str:
    """Parse, resolve, generate, and reify `data` into Pydantic source."""
    document, resolver = resolved_json_schema(data, uri)
    module = ok(PydanticTransformer(resolver=resolver).apply(document))
    return _one_artifact_text(ok(PythonReifier().apply(module)))


def postgres_source(data: JsonLike, uri: str = DEFAULT_SCHEMA_URI) -> str:
    """Parse, resolve, generate, and reify `data` into PostgreSQL DDL."""
    document, resolver = resolved_json_schema(data, uri)
    script = ok(PostgresTransformer(resolver=resolver).apply(document))
    return _one_artifact_text(ok(SqlReifier("schema.sql").apply(script)))


def table_set_source(data: JsonLike, name: str = "main") -> str:
    """Parse, resolve, generate, and reify a named-schema map into PostgreSQL DDL."""
    resolver = JsonSchemaRefResolver()
    document = ok(resolver.apply_map(schema_map_cst(data, name)))
    script = ok(PostgresTableSetTransformer(resolver=resolver).apply(document))
    return _one_artifact_text(ok(SqlReifier("schema.sql").apply(script)))


def fastapi_module(data: JsonLike, uri: str = DEFAULT_OPENAPI_URI) -> PythonModule:
    """Parse `data` and generate the FastAPI module for it, without reifying."""
    return ok(FastApiTransformer().apply(openapi_cst(data, uri)))


def fastapi_source(data: JsonLike, uri: str = DEFAULT_OPENAPI_URI) -> str:
    """Parse, generate, and reify `data` into FastAPI application source."""
    return _one_artifact_text(ok(PythonReifier().apply(fastapi_module(data, uri))))


def _one_artifact_text(artifacts: Sequence[Artifact]) -> str:
    assert len(artifacts) == 1, f"Expected one artifact, got {len(artifacts)}"
    return artifacts[0].content.decode()


def object_schema(data: JsonLike, uri: str = DEFAULT_SCHEMA_URI) -> ObjectSchema:
    """Parse `data` and return its root, which must be an object schema."""
    root = json_schema_cst(data, uri).root
    assert isinstance(root, ObjectSchema), f"Root is {type(root).__name__}, not an ObjectSchema"
    return root


def flattened(
    data: JsonLike, *, resolve: bool = False, uri: str = DEFAULT_SCHEMA_URI
) -> FlatteningResult:
    """Flatten `data`'s `allOf` branches, following `$ref` only when `resolve` is set.

    Without a resolver the flattener leaves a `$ref` where it is,
    which is how a target that never follows one sees the schema.
    """
    resolver = None
    if resolve:
        resolver = JsonSchemaRefResolver()
        resolver.register(json_schema_cst(data, uri))
    return SchemaFlattener(resolver=resolver).flatten(object_schema(data, uri), base_uri=uri)


def flat_schema(data: JsonLike, *, resolve: bool = False) -> ObjectSchema:
    """Return the flattened schema itself, discarding the warnings alongside it."""
    schema = flattened(data, resolve=resolve).schema
    assert isinstance(schema, ObjectSchema), f"Flattened to {type(schema).__name__}"
    return schema


def flatten_warnings(data: JsonLike, *, resolve: bool = False) -> Sequence[str]:
    """Return the codes of the warnings raised while flattening `data`."""
    return [w.code for w in flattened(data, resolve=resolve).warnings if w.code]


def openapi_result(data: JsonLike, uri: str = "test:///d") -> Result[OpenApiDocument]:
    """Parse `data` as an OpenAPI document without asserting that it succeeded."""
    return OpenApiParser().apply(openapi_doc(data, uri))


def minimal_openapi(**extra: JsonLike) -> JsonLike:
    """Return the smallest OpenAPI 3.1 document the parser accepts, plus `extra` keys."""
    return {"openapi": "3.1.0", "info": {"title": "T", "version": "1"}, **extra}


def operation_at(doc: OpenApiDocument, path: str = "/x", method: str = "get") -> Operation:
    """Return the operation `document` declares at `path` for `method`."""
    item = doc.paths[path]
    assert isinstance(item, PathItem), f"{path} holds a {type(item).__name__}"
    found = getattr(item, method)
    assert found is not None, f"No {method} operation at {path}"
    return found
