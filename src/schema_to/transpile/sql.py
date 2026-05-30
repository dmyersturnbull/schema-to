"""Transpiler: JSON Schema 2020-12 → PostgreSQL DDL."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from schema_to.generate.sql import PostgresTransformer
from schema_to.io.source import JsonSchemaRawDoc, RawDoc
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
    from schema_to.io.sink import Artifact

__all__ = ["JsonSchemaToPostgresTranspiler"]


@dataclass(frozen=True, slots=True)
class JsonSchemaToPostgresTranspiler(Transpiler):
    """End-to-end transpiler: JSON Schema 2020-12 → PostgreSQL DDL.

    The four pipeline stages are:

    1. **parse** — `JsonSchemaParser` decodes JSON/YAML to a `JsonSchemaDocument` CST.
    2. **resolve** — `JsonSchemaRefResolver` validates all `$ref` / `$dynamicRef` links.
    3. **generate** — `PostgresGenerator` maps the CST to a `SqlScript` AST.
    4. **reify** — `SqlReifier` serialises the AST to `.sql` bytes.

    Attributes:
        parser: JSON Schema parser (injected for testability).
        resolver: Ref resolver shared across documents (injected for testability).
        generator: PostgreSQL DDL generator (injected for testability).
        output_name: Base name for the emitted `.sql` artifact.
    """

    parser: JsonSchemaParser = field(default_factory=JsonSchemaParser)
    resolver: JsonSchemaRefResolver = field(default_factory=JsonSchemaRefResolver)
    generator: PostgresTransformer = field(default_factory=PostgresTransformer)
    output_name: str = "schema.sql"

    @property
    def warnings(self) -> Sequence[TranspilationWarning]:
        return list(self.generator.warnings)

    def accepts(self, doc: RawDoc) -> bool:
        return isinstance(doc, JsonSchemaRawDoc)

    def transpile(self, doc: RawDoc) -> Result[Sequence[Artifact]]:
        assert isinstance(doc, JsonSchemaRawDoc)  # noqa: S101  # guaranteed by accepts()
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

        # Stage 4: reify
        return cast(
            "Result[Sequence[Artifact]]", SqlReifier(artifact_name=self.output_name).apply(script)
        )  # SqlArtifact IS Artifact; Ok[T] is invariant
