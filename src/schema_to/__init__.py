"""schema-to: a modern transpiler for JSON Schema 2020-12 and OpenAPI 3.1+.

## Quick start

```python
from schema_to import Pipeline, Ok, Err

pipeline = Pipeline(
    sources=[...],
    transpilers=[...],
    sink=...,
)

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
| `schema_to.io` | `DataSource`, `DataSink`, `RawDocument`, `OutputArtifact` |
| `schema_to.cst` | JSON Schema and OpenAPI CST node types |
| `schema_to.ast` | Python, TypeScript, and SQL AST node types |
| `schema_to.parse` | `JsonSchemaParser`, `OpenApiParser` |
| `schema_to.serialize` | `JsonSchemaSerializer`, `OpenApiSerializer` |
| `schema_to.transpile` | Pass-through `Transpiler` implementations |
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
from schema_to.io._file import DirectoryDataSource, FileDataSink, FileDataSource
from schema_to.io._memory import InMemoryDataSink, InMemoryDataSource
from schema_to.io._sink import DataSink, OutputArtifact
from schema_to.io._source import DataSource, MediaType, MediaTypeParam, MediaTypes, RawDocument
from schema_to.parse._json_schema import JsonSchemaParser
from schema_to.parse._openapi import OpenApiParser
from schema_to.serialize._json_schema import JsonSchemaSerializer
from schema_to.serialize._openapi import OpenApiSerializer
from schema_to.transpile._pass_thru import (
    JsonSchemaPassThruTranspiler,
    OpenApiExtractTranspiler,
    OpenApiPassThruTranspiler,
)

__all__ = [
    # I/O
    "DataSink",
    "DataSource",
    "DirectoryDataSource",
    "FileDataSink",
    "FileDataSource",
    "InMemoryDataSink",
    "InMemoryDataSource",
    "MediaType",
    "MediaTypeParam",
    "MediaTypes",
    "OutputArtifact",
    "RawDocument",
    # Pipeline
    "Pipeline",
    "ProcessSummary",
    "Transpiler",
    "TypedTranspiler",
    # Result
    "Err",
    "Ok",
    "Result",
    # Errors
    "GenerationError",
    "ParseError",
    "ReificationError",
    "ResolutionError",
    "SchemaValidationError",
    "SourceLocation",
    "TranspilationError",
    "TranspilationWarning",
    # Parsers
    "JsonSchemaParser",
    "OpenApiParser",
    # Serializers
    "JsonSchemaSerializer",
    "OpenApiSerializer",
    # Transpilers
    "JsonSchemaPassThruTranspiler",
    "OpenApiExtractTranspiler",
    "OpenApiPassThruTranspiler",
]
