"""Concrete Syntax Trees for JSON Schema 2020-12 and OpenAPI 3.1.

The two sub-modules (`_json_schema` and `_openapi`) expose independent CST
hierarchies.  `OpenApiDocument` embeds `JsonSchema` nodes directly for its
`schema` fields, reflecting OpenAPI 3.1's full alignment with JSON Schema 2020-12.
"""

from schema_to.cst._base import CstNode, JsonValue, SourceRef
from schema_to.cst._json_schema import (
    BooleanSchema,
    ConstValue,
    DefaultValue,
    JsonSchema,
    JsonSchemaDocument,
    JsonSchemaType,
    ObjectSchema,
    SchemaType,
)
from schema_to.cst._openapi import (
    ApiKeyLocation,
    Components,
    Contact,
    Encoding,
    ExternalDocumentation,
    Header,
    HttpMethod,
    Info,
    License,
    Link,
    MediaTypeObject,
    OAuthFlow,
    OAuthFlows,
    OpenApiDocument,
    Operation,
    Parameter,
    ParameterLocation,
    PathItem,
    RequestBody,
    Response,
    SecurityRequirement,
    SecurityScheme,
    SecuritySchemeType,
    Server,
    ServerVariable,
    Tag,
)

__all__ = [
    # Base
    "CstNode",
    "JsonValue",
    "SourceRef",
    # JSON Schema
    "BooleanSchema",
    "ConstValue",
    "DefaultValue",
    "JsonSchema",
    "JsonSchemaDocument",
    "JsonSchemaType",
    "ObjectSchema",
    "SchemaType",
    # OpenAPI
    "ApiKeyLocation",
    "Components",
    "Contact",
    "Encoding",
    "ExternalDocumentation",
    "Header",
    "HttpMethod",
    "Info",
    "License",
    "Link",
    "MediaTypeObject",
    "OAuthFlow",
    "OAuthFlows",
    "OpenApiDocument",
    "Operation",
    "Parameter",
    "ParameterLocation",
    "PathItem",
    "RequestBody",
    "Response",
    "SecurityRequirement",
    "SecurityScheme",
    "SecuritySchemeType",
    "Server",
    "ServerVariable",
    "Tag",
]
