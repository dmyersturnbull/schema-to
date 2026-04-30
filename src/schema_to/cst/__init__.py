"""Concrete Syntax Trees for JSON Schema 2020-12 and OpenAPI 3.1.

The two sub-modules (`_json_schema` and `_openapi`) expose independent CST
hierarchies.  `OpenApiDocument` embeds `JsonSchema` nodes directly for its
`schema` fields, reflecting OpenAPI 3.1's full alignment with JSON Schema 2020-12.
"""

from schema_to.cst._base import CstNode, JsonValue, SourceRef
from schema_to.cst._json_schema import (
    ApplicatorKeywords,
    ArrayKeywords,
    BooleanSchema,
    ContentKeywords,
    CoreKeywords,
    FormatKeyword,
    JsonSchema,
    JsonSchemaDocument,
    JsonSchemaType,
    MetadataKeywords,
    NumericKeywords,
    ObjectKeywords,
    ObjectSchema,
    SchemaType,
    StringKeywords,
    UnevaluatedKeywords,
    ValidationKeywords,
)
from schema_to.cst._openapi import (
    Components,
    ExternalDocumentation,
    HttpMethod,
    Info,
    MediaTypeObject,
    OpenApiDocument,
    Operation,
    Parameter,
    ParameterLocation,
    PathItem,
    RequestBody,
    Response,
    SecurityScheme,
    SecuritySchemeType,
    Server,
    Tag,
)

__all__ = [
    # Base
    "CstNode",
    "JsonValue",
    "SourceRef",
    # JSON Schema
    "ApplicatorKeywords",
    "ArrayKeywords",
    "BooleanSchema",
    "ContentKeywords",
    "CoreKeywords",
    "FormatKeyword",
    "JsonSchema",
    "JsonSchemaDocument",
    "JsonSchemaType",
    "MetadataKeywords",
    "NumericKeywords",
    "ObjectKeywords",
    "ObjectSchema",
    "SchemaType",
    "StringKeywords",
    "UnevaluatedKeywords",
    "ValidationKeywords",
    # OpenAPI
    "Components",
    "ExternalDocumentation",
    "HttpMethod",
    "Info",
    "MediaTypeObject",
    "OpenApiDocument",
    "Operation",
    "Parameter",
    "ParameterLocation",
    "PathItem",
    "RequestBody",
    "Response",
    "SecurityScheme",
    "SecuritySchemeType",
    "Server",
    "Tag",
]
