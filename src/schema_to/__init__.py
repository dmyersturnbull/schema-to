"""schema-to: a modern transpiler for JSON Schema 2020-12 and OpenAPI 3.1+.

## Quick start

```python
from schema_to import Pipeline, Ok, Err

pipeline = Pipeline(sources=[...], transpilers=[...], sink=...)

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
| `schema_to.io.source` | `DataSource`, `DataSink`, `RawDocument`, `OutputArtifact` |
| `schema_to.cst.json_schema` | JSON Schema CST node types |
| `schema_to.cst.openapi` | OpenAPI CST node types |
| `schema_to.ast.python` | Python AST node types |
| `schema_to.ast.sql` | SQL AST node types |
| `schema_to.parse.json_schema` | `JsonSchemaParser` |
| `schema_to.parse.openapi` | `OpenApiParser` |
| `schema_to.serialize.json_schema` | `JsonSchemaSerializer` |
| `schema_to.serialize.openapi` | `OpenApiSerializer` |
| `schema_to.resolve.json_schema` | `JsonSchemaRefResolver` |
| `schema_to.generate.pydantic` | `PydanticGenerator` |
| `schema_to.generate.sql` | `PostgresGenerator` |
| `schema_to.reify.python` | `PythonReifier` |
| `schema_to.reify.sql` | `SqlReifier` |
| `schema_to.transpile.pass_thru` | Pass-through `Transpiler` implementations |
| `schema_to.transpile.extract` | `OpenApiExtractTranspiler` |
| `schema_to.transpile.pydantic` | `JsonSchemaToPydanticTranspiler` |
| `schema_to.transpile.sql` | `JsonSchemaToPostgresTranspiler` |
| `schema_to.pipeline` | `Stage`, `Transpiler`, `Pipeline` |
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
from schema_to.generate.pydantic import PydanticGenerator
from schema_to.generate.sql import PostgresGenerator
from schema_to.io.file import DirectoryDataSource, FileDataSink, FileDataSource
from schema_to.io.media_type import MediaType, MediaTypeParam, MediaTypes
from schema_to.io.memory import InMemoryDataSink, InMemoryDataSource
from schema_to.io.sink import DataSink, OutputArtifact
from schema_to.io.source import DataSource, JsonSchemaRawDocument, OpenApiRawDocument, RawDocument
from schema_to.parse.json_schema import JsonSchemaParser
from schema_to.parse.openapi import OpenApiParser
from schema_to.pipeline import Pipeline, ProcessSummary, Transpiler, TypedTranspiler
from schema_to.reify.python import PythonReifier
from schema_to.reify.sql import SqlReifier
from schema_to.resolve.json_schema import JsonSchemaRefResolver
from schema_to.result import Err, Ok, Result
from schema_to.serialize.json_schema import JsonSchemaSerializer
from schema_to.serialize.openapi import OpenApiSerializer
from schema_to.transpile.extract import OpenApiExtractTranspiler
from schema_to.transpile.pass_thru import JsonSchemaPassThruTranspiler, OpenApiPassThruTranspiler
from schema_to.transpile.pydantic import JsonSchemaToPydanticTranspiler
from schema_to.transpile.sql import JsonSchemaToPostgresTranspiler

__all__ = [
    # I/O
    "DataSink",
    "DataSource",
    "DirectoryDataSource",
    # Result
    "Err",
    "FileDataSink",
    "FileDataSource",
    # Errors
    "GenerationError",
    "InMemoryDataSink",
    "InMemoryDataSource",
    # Parsers
    "JsonSchemaParser",
    # Transpilers
    "JsonSchemaPassThruTranspiler",
    "JsonSchemaRawDocument",
    # Resolver
    "JsonSchemaRefResolver",
    # Serializers
    "JsonSchemaSerializer",
    # Typed transpilers
    "JsonSchemaToPostgresTranspiler",
    "JsonSchemaToPydanticTranspiler",
    "MediaType",
    "MediaTypeParam",
    "MediaTypes",
    "Ok",
    "OpenApiExtractTranspiler",
    "OpenApiParser",
    "OpenApiPassThruTranspiler",
    "OpenApiRawDocument",
    "OpenApiSerializer",
    "OutputArtifact",
    "ParseError",
    # Pipeline
    "Pipeline",
    # Generators
    "PostgresGenerator",
    "ProcessSummary",
    "PydanticGenerator",
    # Reifiers
    "PythonReifier",
    "RawDocument",
    "ReificationError",
    "ResolutionError",
    "Result",
    "SchemaValidationError",
    "SourceLocation",
    "SqlReifier",
    "TranspilationError",
    "TranspilationWarning",
    "Transpiler",
    "TypedTranspiler",
]
