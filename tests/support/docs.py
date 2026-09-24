"""Builders for the raw documents that a pipeline test starts from.

One builder per `RawDoc` subclass.
Each serializes `data` as JSON, since the parsers accept JSON and YAML alike,
and JSON keeps the builders free of formatting concerns.
"""

import orjson
from tests.support.types import JsonLike

from schema_to.io.media_type import MediaType, MediaTypes
from schema_to.io.source import JsonSchemaRawDoc, OpenApiRawDoc, SchemaMapRawDoc

DEFAULT_SCHEMA_ID = "test://schema"
DEFAULT_OPENAPI_ID = "test://api"


def json_schema_doc(
    data: JsonLike,
    doc_id: str = DEFAULT_SCHEMA_ID,
    *,
    display_name: str = "Test",
    media_type: MediaType = MediaTypes.json,
) -> JsonSchemaRawDoc:
    """Return `data` as a document whose root is a JSON Schema 2020-12 schema."""
    return JsonSchemaRawDoc(
        doc_id=doc_id, content=orjson.dumps(data), media_type=media_type, display_name=display_name
    )


def openapi_doc(
    data: JsonLike,
    doc_id: str = DEFAULT_OPENAPI_ID,
    *,
    display_name: str = "Test",
    media_type: MediaType = MediaTypes.json,
) -> OpenApiRawDoc:
    """Return `data` as an OpenAPI 3.1/3.2 document."""
    return OpenApiRawDoc(
        doc_id=doc_id, content=orjson.dumps(data), media_type=media_type, display_name=display_name
    )


def schema_map_doc(
    data: JsonLike, name: str = "main", *, media_type: MediaType = MediaTypes.json
) -> SchemaMapRawDoc:
    """Return `data` as a document whose root maps names to schemas.

    The `doc_id` is derived from `name` as a `file:` URI,
    so that a relative `$ref` between two of these resolves the way it would on disk.
    """
    return SchemaMapRawDoc(
        doc_id=f"file:///{name}.yaml",
        content=orjson.dumps(data),
        media_type=media_type,
        display_name=name,
    )
