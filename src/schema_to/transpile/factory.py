"""Composition root: build the `Transpiler`s for a target name.

The `--to` CLI option is a string that names a target format.  This module is the one
place that knows which stages a target is made of, which keeps every other module free
of target-specific wiring: a parser does not know what will consume its CST, and a
generator does not know where its AST will be written.

A target is a composed `Stage`, not a class.  All of them have the same shape —

```
Sequence[RawDoc] → parse → resolve → generate → reify → Sequence[Artifact]
```

— and differ only in which stages fill those slots, and in whether the batch or the
single document is the unit.  `Each` lifts a per-document chain over a batch; a target
whose output depends on the whole set (a migration, whose foreign keys cannot be
ordered until every table is known) uses a stage that takes the batch directly.

Shared state is threaded in from here rather than discovered at run time: the one
`JsonSchemaRefResolver` a target uses is constructed here and handed to every stage
that needs it, so no stage has to ask another whether it happens to have one.

Supported targets:

  - `pass-thru`
    Re-emit each schema normalised (JSON Schema → `.schema.json`,
    OpenAPI → `.json` / `.yaml`).
  - `pydantic`
    JSON Schema 2020-12 → Pydantic v2 `BaseModel` classes.
  - `postgres`
    JSON Schema 2020-12 → PostgreSQL DDL (`CREATE TABLE` statements).
  - `pg-jsonschema`
    Like `postgres`, plus `pg_jsonschema` `CHECK` constraints validating each
    JSON/JSONB column against its sub-schema.
  - `json-schema`
    OpenAPI 3.1 → one standalone `.schema.json` / `.schema.yaml` per
    `components/schemas` entry.
  - `fastapi`
    OpenAPI 3.1 → FastAPI application module (route stubs + security wiring).
    Route bodies are filled from each operation's `x-fastapi-body` Jinja extension when present,
    and left as `...` stubs otherwise;
    see `examples/postgres/` for a worked PostgreSQL set built on `query-dsl`.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar

from schema_to.generate.fastapi.fastapi import FastApiTransformer
from schema_to.generate.fastapi.template_body import TemplateBodyBackend
from schema_to.generate.postgres.sql import PostgresTransformer
from schema_to.generate.postgres.sql_tables import PostgresTableSetTransformer
from schema_to.generate.pydantic.pydantic import PydanticTransformer
from schema_to.io.media_type import MediaType
from schema_to.io.sink import JsonSchemaArtifact, OpenApiArtifact, PythonArtifact, SqlArtifact
from schema_to.io.source import JsonSchemaRawDoc, OpenApiRawDoc, SchemaMapRawDoc
from schema_to.parse.json_schema import JsonSchemaMapParser, JsonSchemaParser
from schema_to.parse.openapi import OpenApiParser
from schema_to.pipeline import Append, Each, Flatten, Stage, Transpiler
from schema_to.reify.json_schema import JsonSchemaReifier, OpenApiReifier
from schema_to.reify.python import PythonPackageAssembler, PythonPackageReifier, PythonReifier
from schema_to.reify.sql import SqlReifier
from schema_to.resolve.json_schema import JsonSchemaMapRefResolver, JsonSchemaRefResolver
from schema_to.transpile.extract import OpenApiComponentExtractor
from schema_to.transpile.schema_map import SchemaMapExpander, SchemaMapMerger

__all__ = ["RoutingError", "TranspilerRouter"]

# Targets whose unit of output is the whole document set rather than one schema.
_TABLE_SET_TARGETS: frozenset[str] = frozenset({"postgres", "pg-jsonschema"})


class RoutingError(Exception):
    """Raised if an unrecognised target name was provided."""

    def __init__(self, *, value: str) -> None:
        msg = (
            f"Target {value!r} is not supported; "
            f"choose one of: {', '.join(sorted(TranspilerRouter.SUPPORTED_TARGETS))}"
        )
        super().__init__(msg)


@dataclass(frozen=True, slots=True)
class TranspilerRouter:
    """Assembles the stages a target is made of into the transpilers that run it."""

    SUPPORTED_TARGETS: ClassVar[frozenset[str]] = frozenset(
        {"fastapi", "json-schema", "pass-thru", "pydantic", "postgres", "pg-jsonschema"}
    )

    def route(
        self,
        target_name: str,
        output_media_type: MediaType,
        *,
        templates: Mapping[str, str] | None = None,
        roots: frozenset[str] | None = None,
        schema_map: bool = False,
    ) -> Sequence[Transpiler]:
        """Return the ordered list of transpilers for target `target_name`.

        Args:
            target_name: The requested target format.
            output_media_type: Media type for re-emitted schema sources.
            templates: Named endpoint-body Jinja templates (`fastapi` target),
                registered from the CLI's `--template <name>=<path>`.
            roots: If given, restricts which named schema nodes become their own
                artifact — a `$defs` entry (JSON Schema), a schema-map entry, or a
                `components/schemas` entry (OpenAPI). Every other schema stays
                available for `$ref` resolution. `None` generates every one.
            schema_map: Read each source document as a map of named schemas rather
                than as one schema. Each target is then met on its own terms: one whose
                unit is the whole set consumes it directly, and one whose unit is a
                single schema is fed the schemas one at a time.

        Raises:
            RoutingError: If `target_name` is not recognized or supported.
        """
        if target_name not in self.SUPPORTED_TARGETS:
            raise RoutingError(value=target_name)
        if schema_map:
            return self._route_schema_maps(target_name, output_media_type, roots=roots)
        return self._route_documents(
            target_name, output_media_type, templates=templates, roots=roots
        )

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _route_documents(
        self,
        target_name: str,
        output_media_type: MediaType,
        *,
        templates: Mapping[str, str] | None,
        roots: frozenset[str] | None,
    ) -> Sequence[Transpiler]:
        """Route documents that each hold one schema (or one OpenAPI description)."""
        match target_name:
            case "fastapi":
                return [Transpiler(OpenApiRawDoc, self._fastapi(templates=templates, roots=roots))]
            case "json-schema":
                return [
                    Transpiler(OpenApiRawDoc, self._openapi_components(output_media_type, roots))
                ]
            case "pass-thru":
                return [
                    Transpiler(OpenApiRawDoc, self._openapi_pass_thru(output_media_type)),
                    Transpiler(JsonSchemaRawDoc, self._schema_pass_thru(output_media_type)),
                ]
            case "pydantic":
                models = self._pydantic(resolver=JsonSchemaRefResolver(), roots=roots)
                return [Transpiler(JsonSchemaRawDoc, models)]
            case _:
                sql = self._postgres(
                    resolver=JsonSchemaRefResolver(),
                    validate_json=target_name == "pg-jsonschema",
                    roots=roots,
                )
                return [Transpiler(JsonSchemaRawDoc, sql)]

    def _route_schema_maps(
        self, target_name: str, output_media_type: MediaType, *, roots: frozenset[str] | None
    ) -> Sequence[Transpiler]:
        """Route documents that each hold a map of named schemas.

        A target whose unit is the whole set consumes the documents as they are; one
        whose unit is a single schema gets `SchemaMapExpander` in front of the very
        same chain it would run on single-schema files.
        """
        if target_name in _TABLE_SET_TARGETS:
            validate_json = target_name == "pg-jsonschema"
            table_set = self._postgres_table_set(validate_json=validate_json, roots=roots)
            return [Transpiler(SchemaMapRawDoc, table_set)]
        if target_name in {"fastapi", "json-schema"}:
            # An OpenAPI description is not a map of named schemas, so there is nothing
            # here for these to read; every document falls through unclaimed.
            return []
        if target_name == "pass-thru":
            # Re-emitting a schema never follows a `$ref`, so there is nothing to seed.
            expand = Each(SchemaMapExpander(roots=roots)).then(Flatten())
            emit = expand.then(self._schema_pass_thru(output_media_type))
            return [Transpiler(SchemaMapRawDoc, emit)]
        resolver = JsonSchemaRefResolver()
        expand = Each(SchemaMapExpander(resolver=resolver, roots=roots)).then(Flatten())
        models = self._pydantic(resolver=resolver, roots=roots)
        return [Transpiler(SchemaMapRawDoc, expand.then(models))]

    # ------------------------------------------------------------------
    # Per-target stage chains
    # ------------------------------------------------------------------

    def _schema_pass_thru(
        self, output_media_type: MediaType
    ) -> Stage[Sequence[JsonSchemaRawDoc], Sequence[JsonSchemaArtifact]]:
        emit = JsonSchemaParser().then(JsonSchemaReifier(output_media_type=output_media_type))
        return Each(emit).then(Flatten())

    def _openapi_pass_thru(
        self, output_media_type: MediaType
    ) -> Stage[Sequence[OpenApiRawDoc], Sequence[OpenApiArtifact]]:
        emit = OpenApiParser().then(OpenApiReifier(output_media_type=output_media_type))
        return Each(emit).then(Flatten())

    def _openapi_components(
        self, output_media_type: MediaType, roots: frozenset[str] | None
    ) -> Stage[Sequence[OpenApiRawDoc], Sequence[JsonSchemaArtifact]]:
        """Each `components/schemas` entry, written as a standalone JSON Schema file."""
        emit = Each(JsonSchemaReifier(output_media_type=output_media_type)).then(Flatten())
        per_doc = OpenApiParser().then(OpenApiComponentExtractor(roots=roots)).then(emit)
        return Each(per_doc).then(Flatten())

    def _pydantic(
        self, *, resolver: JsonSchemaRefResolver, roots: frozenset[str] | None
    ) -> Stage[Sequence[JsonSchemaRawDoc], Sequence[PythonArtifact]]:
        """A module per schema, collected into the package they are written as."""
        per_schema = (
            JsonSchemaParser()
            .then(resolver)
            .then(PydanticTransformer(resolver=resolver, roots=roots))
        )
        return Each(per_schema).then(PythonPackageAssembler()).then(PythonPackageReifier())

    def _postgres(
        self, *, resolver: JsonSchemaRefResolver, validate_json: bool, roots: frozenset[str] | None
    ) -> Stage[Sequence[JsonSchemaRawDoc], Sequence[SqlArtifact]]:
        per_schema = (
            JsonSchemaParser()
            .then(resolver)
            .then(PostgresTransformer(validate_json=validate_json, roots=roots))
            .then(SqlReifier(artifact_name="schema.sql"))
        )
        return Each(per_schema).then(Flatten())

    def _postgres_table_set(
        self, *, validate_json: bool, roots: frozenset[str] | None
    ) -> Stage[Sequence[SchemaMapRawDoc], Sequence[SqlArtifact]]:
        """One migration for the whole set: an ordering needs every table to be known.

        Registration and validation are separate passes over the batch because a `$ref`
        into a sibling file cannot resolve until that file is registered, and the files
        are read in whatever order the directory gives.
        """
        maps = JsonSchemaMapRefResolver(inner=JsonSchemaRefResolver())
        return (
            Each(JsonSchemaMapParser())
            .then(Each(maps.registering()))
            .then(Each(maps))
            .then(SchemaMapMerger())
            .then(
                PostgresTableSetTransformer(
                    resolver=maps.inner, validate_json=validate_json, roots=roots
                )
            )
            .then(SqlReifier(artifact_name="schema.sql"))
        )

    def _fastapi(
        self, *, templates: Mapping[str, str] | None, roots: frozenset[str] | None
    ) -> Stage[Sequence[OpenApiRawDoc], Sequence[PythonArtifact]]:
        backend = TemplateBodyBackend(named_templates=templates or {})
        per_doc = (
            OpenApiParser()
            .then(FastApiTransformer(body_backend=backend, roots=roots))
            .then(PythonReifier())
        )
        # The support modules belong to the run rather than to any one document, so
        # they are appended once the batch is reified rather than once per document.
        return Each(per_doc).then(Flatten()).then(Append(backend.support_artifacts))
