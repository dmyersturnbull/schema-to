"""Transpiler: a directory of named-schema files → one PostgreSQL migration script.

Unlike the single-document transpilers, this one consumes the whole document set
before generating anything: a table's foreign keys are only orderable once every
table in the set is known, and a `$ref` into a sibling file only resolves once
that file is registered.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from schema_to.generate.sql_tables import PostgresTableSetTransformer
from schema_to.parse.json_schema import JsonSchemaMapParser
from schema_to.reify.sql import SqlReifier
from schema_to.resolve.json_schema import JsonSchemaRefResolver
from schema_to.result import Err, Ok, Result

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from schema_to.cst.json_schema import JsonSchemaMapDocument
    from schema_to.errors import TranspilationError, TranspilationWarning
    from schema_to.io.sink import SqlArtifact
    from schema_to.io.source import SchemaMapRawDoc

__all__ = ["SchemaMapSetToPostgresTranspiler"]


@dataclass
class SchemaMapSetToPostgresTranspiler:
    """End-to-end transpiler: a set of schema-map documents → one `.sql` artifact.

    Attributes:
        parser: Parses each raw document.
        generator: Builds the DDL AST from the parsed set.
        output_name: Artifact name for the emitted script.
    """

    parser: JsonSchemaMapParser = field(default_factory=JsonSchemaMapParser)
    generator: PostgresTableSetTransformer = field(default_factory=PostgresTableSetTransformer)
    output_name: str = "schema.sql"

    @property
    def warnings(self) -> Sequence[TranspilationWarning]:
        return list(self.generator.warnings)

    def transpile_all(self, docs: Iterable[SchemaMapRawDoc]) -> Result[Sequence[SqlArtifact]]:
        """Parse, resolve, and generate one script from every document in `docs`."""
        parsed = self._parse_all(docs)
        if isinstance(parsed, Err):
            return parsed
        resolver = JsonSchemaRefResolver()
        for doc in parsed.value:
            resolver.register_map(doc)
        errors = self._validate_refs(parsed.value, resolver)
        if errors:
            return Err(tuple(errors))
        self.generator.resolver = resolver
        script = self.generator.apply(parsed.value)
        if isinstance(script, Err):
            return script
        return SqlReifier(artifact_name=self.output_name).apply(script.value)

    def _parse_all(
        self, docs: Iterable[SchemaMapRawDoc]
    ) -> Result[Sequence[JsonSchemaMapDocument]]:
        """Parse every document, accumulating errors across all of them."""
        parsed: list[JsonSchemaMapDocument] = []
        errors: list[TranspilationError] = []
        for doc in docs:
            result = self.parser.apply(doc)
            if isinstance(result, Err):
                errors.extend(result.errors)
            else:
                parsed.append(result.value)
        if errors:
            return Err(tuple(errors))
        return Ok(parsed)

    def _validate_refs(
        self, docs: Sequence[JsonSchemaMapDocument], resolver: JsonSchemaRefResolver
    ) -> list[TranspilationError]:
        """Check every `$ref` only after all documents are registered.

        Validating during registration would fail on any forward reference to a
        file that happens to sort later.
        """
        errors: list[TranspilationError] = []
        for doc in docs:
            result = resolver.apply_map(doc)
            if isinstance(result, Err):
                errors.extend(result.errors)
        return errors
