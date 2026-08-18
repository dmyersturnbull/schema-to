"""schema-to: a modern transpiler for JSON Schema 2020-12 and OpenAPI 3.1+.

## Quick start

```python
from schema_to import Pipeline, TranspilerRouter, MediaTypes, Ok, Err

transpilers = TranspilerRouter().route("pydantic", MediaTypes.json)
pipeline = Pipeline(sources=[...], transpilers=transpilers, sink=...)

match pipeline.process():
    case Ok(summary):
        print(f"Wrote {summary.artifacts_written} artifacts.")
    case Err(errors):
        for err in errors:
            print(err.message)
```

## Module map

| Module | Purpose |
|--------|---------|
| `schema_to.io.source` | `DataSource`, `DataSink`, `RawDoc`, `Artifact` |
| `schema_to.cst.json_schema` | JSON Schema CST node types |
| `schema_to.cst.openapi` | OpenAPI CST node types |
| `schema_to.ast.python` | Python AST node types |
| `schema_to.ast.sql` | SQL AST node types |
| `schema_to.parse.json_schema` | `JsonSchemaParser` |
| `schema_to.parse.openapi` | `OpenApiParser` |
| `schema_to.serialize.json_schema` | `JsonSchemaSerializer` |
| `schema_to.serialize.openapi` | `OpenApiSerializer` |
| `schema_to.resolve.json_schema` | `JsonSchemaRefResolver` |
| `schema_to.resolve.openapi` | `OpenApiRefResolver` |
| `schema_to.generate.pydantic` | `PydanticGenerator` |
| `schema_to.generate.sql` | `PostgresGenerator` |
| `schema_to.reify.python` | `PythonReifier`, `PythonPackageReifier` |
| `schema_to.reify.sql` | `SqlReifier` |
| `schema_to.reify.json_schema` | `JsonSchemaReifier`, `OpenApiReifier` |
| `schema_to.transpile.factory` | `TranspilerRouter` — builds a `Transpiler` per target |
| `schema_to.transpile.schema_map` | `SchemaMapExpander`, `SchemaMapMerger` |
| `schema_to.transpile.extract` | `OpenApiComponentExtractor` |
| `schema_to.pipeline` | `Stage`, `Expander`, `Reducer`, `Each`, `Transpiler`, `Pipeline` |
| `schema_to.result` | `Ok`, `Err`, `Result` |
| `schema_to.errors` | `TranspilationError` subclasses |
"""

from schema_to.errors import (
    GenerationError,
    ParseError,
    ReificationError,
    ResolutionError,
    SchemaValidationError,
    SourceLocation,
    TranspilationError,
    TranspilationWarning,
)
from schema_to.generate.fastapi.endpoint_body import (
    EndpointBody,
    EndpointBodyBackend,
    EndpointContext,
    NullBodyBackend,
)
from schema_to.generate.fastapi.fastapi import FastApiTransformer
from schema_to.generate.fastapi.rest import RestOperation
from schema_to.generate.fastapi.template_body import TemplateBodyBackend
from schema_to.generate.postgres.sql import PostgresTransformer
from schema_to.generate.pydantic.pydantic import PydanticTransformer
from schema_to.io.core import DefaultJsonLikeReader, JsonLikeReader
from schema_to.io.file import (
    DirectoryDataSource,
    FileDataSink,
    FileDataSource,
    PeekingDirectorySource,
)
from schema_to.io.media_type import MediaType, MediaTypeParam, MediaTypes
from schema_to.io.memory import InMemoryDataSink, InMemoryDataSource
from schema_to.io.routing import DocType
from schema_to.io.sink import (
    Artifact,
    DataSink,
    JsonSchemaArtifact,
    JsonSchemaJsonArtifact,
    JsonSchemaYamlArtifact,
    OpenApiArtifact,
    OpenApiJsonArtifact,
    OpenApiYamlArtifact,
)
from schema_to.io.source import DataSource, JsonSchemaRawDoc, OpenApiRawDoc, RawDoc
from schema_to.parse.json_schema import JsonSchemaParser
from schema_to.parse.openapi import OpenApiParser
from schema_to.pipeline import (
    Append,
    Each,
    Expander,
    Flatten,
    Pipeline,
    ProcessSummary,
    Reducer,
    Reifier,
    Stage,
    Transformer,
    Transpiler,
)
from schema_to.reify.json_schema import JsonSchemaReifier, OpenApiReifier
from schema_to.reify.python import PythonPackageAssembler, PythonPackageReifier, PythonReifier
from schema_to.reify.sql import SqlReifier
from schema_to.resolve.json_schema import JsonSchemaMapRefResolver, JsonSchemaRefResolver
from schema_to.resolve.openapi import OpenApiRefResolver
from schema_to.result import Err, Ok, Result
from schema_to.serialize.json_schema import JsonSchemaSerializer
from schema_to.serialize.openapi import OpenApiSerializer
from schema_to.transpile.extract import OpenApiComponentExtractor
from schema_to.transpile.factory import RoutingError, TranspilerRouter
from schema_to.transpile.schema_map import SchemaMapExpander, SchemaMapMerger

__all__ = [
    "Append",
    "Artifact",
    # I/O
    "DataSink",
    "DataSource",
    "DefaultJsonLikeReader",
    "DirectoryDataSource",
    # Routing
    "DocType",
    # Stage combinators
    "Each",
    "EndpointBody",
    # Endpoint-body backends
    "EndpointBodyBackend",
    "EndpointContext",
    # Result
    "Err",
    "Expander",
    # Generators
    "FastApiTransformer",
    "FileDataSink",
    "FileDataSource",
    "Flatten",
    # Errors
    "GenerationError",
    "InMemoryDataSink",
    "InMemoryDataSource",
    "JsonLikeReader",
    # Artifacts
    "JsonSchemaArtifact",
    "JsonSchemaJsonArtifact",
    "JsonSchemaMapRefResolver",
    # Parsers
    "JsonSchemaParser",
    "JsonSchemaRawDoc",
    # Resolver
    "JsonSchemaRefResolver",
    "JsonSchemaReifier",
    # Serializers
    "JsonSchemaSerializer",
    "JsonSchemaYamlArtifact",
    "MediaType",
    "MediaTypeParam",
    "MediaTypes",
    "NullBodyBackend",
    "Ok",
    "OpenApiArtifact",
    "OpenApiComponentExtractor",
    "OpenApiJsonArtifact",
    "OpenApiParser",
    "OpenApiRawDoc",
    "OpenApiRefResolver",
    "OpenApiReifier",
    "OpenApiSerializer",
    "OpenApiYamlArtifact",
    "ParseError",
    "PeekingDirectorySource",
    # Pipeline
    "Pipeline",
    "PostgresTransformer",
    "ProcessSummary",
    "PydanticTransformer",
    "PythonPackageAssembler",
    "PythonPackageReifier",
    # Reifiers
    "PythonReifier",
    "RawDoc",
    "Reducer",
    "ReificationError",
    "Reifier",
    "ResolutionError",
    "RestOperation",
    "Result",
    # Composition root
    "RoutingError",
    "SchemaMapExpander",
    "SchemaMapMerger",
    "SchemaValidationError",
    "SourceLocation",
    "SqlReifier",
    "Stage",
    "TemplateBodyBackend",
    "Transformer",
    "TranspilationError",
    "TranspilationWarning",
    "Transpiler",
    "TranspilerRouter",
]
