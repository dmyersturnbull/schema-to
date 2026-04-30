"""Document parsers: JSON Schema 2020-12 and OpenAPI 3.1."""

from schema_to.parse._json_schema import JsonSchemaParser
from schema_to.parse._openapi import OpenApiParser

__all__ = ["JsonSchemaParser", "OpenApiParser"]
