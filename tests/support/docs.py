"""Builders for the raw documents that a pipeline test starts from.

One builder per `RawDoc` subclass.
Each serializes `data` as JSON, since the parsers accept JSON and YAML alike,
and JSON keeps the builders free of formatting concerns.

A document's display name is computed from its URI,
so a test that cares about the name chooses a URI that ends in it.
"""

import orjson
from tests.support.types import JsonLike

from schema_to.io.media_type import MediaType, MediaTypes
from schema_to.io.source import JsonSchemaRawDoc, OpenApiRawDoc, SchemaMapRawDoc

DEFAULT_SCHEMA_URI = "test:///Test"
DEFAULT_OPENAPI_URI = "test:///api/Test"


def json_schema_doc(
    data: JsonLike, uri: str = DEFAULT_SCHEMA_URI, *, media_type: MediaType = MediaTypes.json
) -> JsonSchemaRawDoc:
    """Return `data` as a document whose root is a JSON Schema 2020-12 schema."""
    return JsonSchemaRawDoc(uri=uri, content=orjson.dumps(data), media_type=media_type)


def openapi_doc(
    data: JsonLike, uri: str = DEFAULT_OPENAPI_URI, *, media_type: MediaType = MediaTypes.json
) -> OpenApiRawDoc:
    """Return `data` as an OpenAPI 3.1/3.2 document."""
    return OpenApiRawDoc(uri=uri, content=orjson.dumps(data), media_type=media_type)


def schema_map_doc(
    data: JsonLike, name: str = "main", *, media_type: MediaType = MediaTypes.json
) -> SchemaMapRawDoc:
    """Return `data` as a document whose root maps names to schemas.

    The `uri` is derived from `name` as a `file:` URI,
    so that a relative `$ref` between two of these resolves the way it would on disk.
    """
    return SchemaMapRawDoc(
        uri=f"file:///{name}.yaml", content=orjson.dumps(data), media_type=media_type
    )
