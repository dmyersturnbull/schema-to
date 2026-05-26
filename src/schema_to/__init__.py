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
| `schema_to.io._source` | `DataSource`, `DataSink`, `RawDocument`, `OutputArtifact` |
| `schema_to.cst._json_schema` | JSON Schema CST node types |
| `schema_to.cst._openapi` | OpenAPI CST node types |
| `schema_to.ast._python` | Python AST node types |
| `schema_to.ast._sql` | SQL AST node types |
| `schema_to.parse._json_schema` | `JsonSchemaParser` |
| `schema_to.parse._openapi` | `OpenApiParser` |
| `schema_to.serialize._json_schema` | `JsonSchemaSerializer` |
| `schema_to.serialize._openapi` | `OpenApiSerializer` |
| `schema_to.resolve._json_schema` | `JsonSchemaRefResolver` |
| `schema_to.generate._pydantic` | `PydanticGenerator` |
| `schema_to.generate._sql` | `PostgresGenerator` |
| `schema_to.reify._python` | `PythonReifier` |
| `schema_to.reify._sql` | `SqlReifier` |
| `schema_to.transpile._pass_thru` | Pass-through `Transpiler` implementations |
| `schema_to.transpile._extract` | `OpenApiExtractTranspiler` |
| `schema_to.transpile._pydantic` | `JsonSchemaToPydanticTranspiler` |
| `schema_to.transpile._sql` | `JsonSchemaToPostgresTranspiler` |
| `schema_to._pipeline` | `Stage`, `Transpiler`, `Pipeline` |
| `schema_to._result` | `Ok`, `Err`, `Result` |
| `schema_to._errors` | `TranspilationError` subclasses |
"""

from schema_to._errors import (
    GenerationError,
    ParseError,
    ReificationError,
    ResolutionError,
    SchemaValidationError,
    SourceLocation,
    TranspilationError,
    TranspilationWarning,
)
from schema_to._pipeline import Pipeline, ProcessSummary, Transpiler, TypedTranspiler
from schema_to._result import Err, Ok, Result
from schema_to.generate._pydantic import PydanticGenerator
from schema_to.generate._sql import PostgresGenerator
from schema_to.io._file import DirectoryDataSource, FileDataSink, FileDataSource
from schema_to.io._memory import InMemoryDataSink, InMemoryDataSource
from schema_to.io._sink import DataSink, OutputArtifact
from schema_to.io._source import (
    DataSource,
    JsonSchemaRawDocument,
    MediaType,
    MediaTypeParam,
    MediaTypes,
    OpenApiRawDocument,
    RawDocument,
)
from schema_to.parse._json_schema import JsonSchemaParser
from schema_to.parse._openapi import OpenApiParser
from schema_to.reify._python import PythonReifier
from schema_to.reify._sql import SqlReifier
from schema_to.resolve._json_schema import JsonSchemaRefResolver
from schema_to.serialize._json_schema import JsonSchemaSerializer
from schema_to.serialize._openapi import OpenApiSerializer
from schema_to.transpile._extract import OpenApiExtractTranspiler
from schema_to.transpile._pass_thru import JsonSchemaPassThruTranspiler, OpenApiPassThruTranspiler
from schema_to.transpile._pydantic import JsonSchemaToPydanticTranspiler
from schema_to.transpile._sql import JsonSchemaToPostgresTranspiler

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
    # Resolver
    "JsonSchemaRefResolver",
    "Result",
    "SchemaValidationError",
    "SqlReifier",
    "SourceLocation",
    "TranspilationError",
    "TranspilationWarning",
    "Transpiler",
    "TypedTranspiler",
]
