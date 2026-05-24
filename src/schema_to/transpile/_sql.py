"""Transpiler: JSON Schema 2020-12 → PostgreSQL DDL."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from schema_to._errors import TranspilationWarning
from schema_to._pipeline import Transpiler
from schema_to._result import Err, Result
from schema_to.ast._sql import SqlScript
from schema_to.cst._json_schema import JsonSchemaDocument
from schema_to.generate._sql import PostgresGenerator
from schema_to.io._sink import OutputArtifact
from schema_to.io._source import JsonSchemaRawDocument, RawDocument
from schema_to.parse._json_schema import JsonSchemaParser
from schema_to.reify._sql import SqlReifier
from schema_to.resolve._json_schema import JsonSchemaRefResolver

__all__ = ["JsonSchemaToPostgresTranspiler"]


@dataclass(frozen=True)
class JsonSchemaToPostgresTranspiler(Transpiler):
    """End-to-end transpiler: JSON Schema 2020-12 → PostgreSQL DDL.

    The four pipeline stages are:

    1. **parse** — ``JsonSchemaParser`` decodes JSON/YAML to a ``JsonSchemaDocument`` CST.
    2. **resolve** — ``JsonSchemaRefResolver`` validates all ``$ref`` / ``$dynamicRef`` links.
    3. **generate** — ``PostgresGenerator`` maps the CST to a ``SqlScript`` AST.
    4. **reify** — ``SqlReifier`` serialises the AST to ``.sql`` bytes.

    Attributes:
        parser: JSON Schema parser (injected for testability).
        resolver: Ref resolver shared across documents (injected for testability).
        generator: PostgreSQL DDL generator (injected for testability).
        output_name: Base name for the emitted ``.sql`` artifact.
    """

    parser: JsonSchemaParser = field(default_factory=JsonSchemaParser)
    resolver: JsonSchemaRefResolver = field(default_factory=JsonSchemaRefResolver)
    generator: PostgresGenerator = field(default_factory=PostgresGenerator)
    output_name: str = "schema.sql"

    @property
    def warnings(self) -> Sequence[TranspilationWarning]:
        return list(self.generator.warnings)

    def accepts(self, document: RawDocument) -> bool:
        return isinstance(document, JsonSchemaRawDocument)

    def transpile(self, document: RawDocument) -> Result[Sequence[OutputArtifact]]:
        # Stage 1: parse
        r1 = self.parser.apply(document)
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

        # Stage 4: reify
        return SqlReifier(artifact_name=self.output_name).apply(script)
