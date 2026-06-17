"""Transpiler: JSON Schema 2020-12 → PostgreSQL DDL."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override

from schema_to.generate.sql import PostgresTransformer
from schema_to.io.core import DefaultJsonLikeReader
from schema_to.io.sink import SqlArtifact
from schema_to.io.source import JsonSchemaRawDoc
from schema_to.parse.json_schema import JsonSchemaParser
from schema_to.pipeline import Transpiler
from schema_to.reify.sql import SqlReifier
from schema_to.resolve.json_schema import JsonSchemaRefResolver
from schema_to.result import Err, Result

if TYPE_CHECKING:
    from collections.abc import Sequence

    from schema_to.ast.sql import SqlScript
    from schema_to.cst.json_schema import JsonSchemaDocument
    from schema_to.errors import TranspilationWarning

__all__ = ["JsonSchemaToPostgresTranspiler"]


@dataclass(frozen=True, slots=True)
class JsonSchemaToPostgresTranspiler(Transpiler[JsonSchemaRawDoc, SqlArtifact]):
    """End-to-end transpiler: JSON Schema 2020-12 → PostgreSQL DDL."""

    parser: JsonSchemaParser = field(default_factory=lambda: JsonSchemaParser(reader=DefaultJsonLikeReader()))
    resolver: JsonSchemaRefResolver = field(default_factory=JsonSchemaRefResolver)
    generator: PostgresTransformer = field(default_factory=PostgresTransformer)
    output_name: str = "schema.sql"

    @override
    @property
    def warnings(self) -> Sequence[TranspilationWarning]:
        return list(self.generator.warnings)

    @override
    def accepts(self, doc: JsonSchemaRawDoc) -> bool:
        return isinstance(doc, JsonSchemaRawDoc)

    @override
    def transpile(self, doc: JsonSchemaRawDoc) -> Result[Sequence[SqlArtifact]]:
        # Stage 1: parse
        r1 = self.parser.apply(doc)
        if isinstance(r1, Err):
            return r1
        cst: JsonSchemaDocument = r1.value
        # Stage 2: resolve
        r2 = self.resolver.apply(cst)
        if isinstance(r2, Err):
            return r2
        # Stage 3: generate
        r3 = self.generator.apply(r2.value)
        if isinstance(r3, Err):
            return r3
        script: SqlScript = r3.value
        return SqlReifier(artifact_name=self.output_name).apply(script)
