"""Set of transpilation pipelines undertood by the CLI.

Concrete analog to [schema_to.transpile.factory][];
see that module for further info.

The `--to` CLI option is a string that names a target format.
This module is the one place that knows which stages a target is made of,
which keeps every other module free of target-specific wiring:
A parser does not know what will consume its CST,
and a generator does not know where its AST will be written.

Supported targets:

  - `pass-thru`
    Re-emit each schema normalised (JSON Schema → `.schema.json`,
    OpenAPI → `.json` / `.yaml`).
  - `pydantic`
    JSON Schema 2020-12 → Pydantic v2 `BaseModel` classes.
  - `postgres`
    JSON Schema 2020-12 → PostgreSQL DDL (`CREATE TABLE` statements).
  - `pg-jsonschema`
    Like `postgres`, plus `pg_jsonschema` `CHECK` constraints validating each JSON/JSONB column against its sub-schema.
  - `json-schema`
    OpenAPI 3.1/3.2 → one standalone `.schema.json` / `.schema.yaml` per `components/schemas` entry.
  - `fastapi`
    OpenAPI 3.1/3.2 → FastAPI application module (route stubs + security wiring).
    Route bodies are filled from each operation's `x-fastapi-body` Jinja extension when present,
    and left as `...` stubs otherwise.
"""

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Self, override

from schema_to.cst.json_schema import JsonSchemaDocument
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
from schema_to.resolve.openapi import OpenApiRefResolver
from schema_to.transpile.extract import OpenApiComponentExtractor
from schema_to.transpile.factory import AbstractTranspilerRouter
from schema_to.transpile.schema_map import SchemaMapExpander, SchemaMapMerger

__all__ = ["SupportedTarget", "TranspilerRouter"]


class _ForgivingHyphenEnum(StrEnum):
    @staticmethod
    @override
    def _generate_next_value_(name: str, start: int, count: int, last_values: list[str]) -> str:
        return name.lower().replace("_", "-")

    @classmethod
    def _missing_(cls, value: object) -> Self | None:
        members = cls.__members__
        match value:
            case str(s):
                s = s.upper().replace("_", "-")
                return members.get(s)
        raise TypeError(value)


class SupportedTarget(_ForgivingHyphenEnum):
    FASTAPI = auto()
    JSON_SCHEMA = auto()
    PASS_THRU = auto()
    PYDANTIC = auto()
    POSTGRES = auto()
    PG_JSONSCHEMA = auto()


@dataclass(frozen=True, slots=True)
class TranspilerRouter(AbstractTranspilerRouter[SupportedTarget]):
    @override
    def _route(
        self,
        target: SupportedTarget,
        output_media_type: MediaType,
        templates: Mapping[str, str] | None,
        roots: Set[str] | None,
        *,
        schema_map: bool,
    ) -> Sequence[Transpiler]:
        if schema_map:
            return self._route_schema_maps(target, output_media_type, roots=roots)
        return self._route_documents(target, output_media_type, templates=templates, roots=roots)

    def _route_documents(
        self,
        target: SupportedTarget,
        output_media_type: MediaType,
        *,
        templates: Mapping[str, str] | None,
        roots: Set[str] | None,
    ) -> Sequence[Transpiler]:
        """Route documents that each hold one schema (or one OpenAPI description)."""
        match target:
            case SupportedTarget.FASTAPI:
                return [Transpiler(OpenApiRawDoc, self._fastapi(templates=templates, roots=roots))]
            case SupportedTarget.JSON_SCHEMA:
                return [
                    Transpiler(OpenApiRawDoc, self._openapi_components(output_media_type, roots))
                ]
            case SupportedTarget.PASS_THRU:
                return [
                    Transpiler(OpenApiRawDoc, self._openapi_pass_thru(output_media_type)),
                    Transpiler(JsonSchemaRawDoc, self._schema_pass_thru(output_media_type)),
                ]
            case SupportedTarget.PYDANTIC:
                models = self._pydantic(resolver=JsonSchemaRefResolver(), roots=roots)
                return [Transpiler(JsonSchemaRawDoc, models)]
            case _:
                sql = self._postgres(
                    resolver=JsonSchemaRefResolver(),
                    validate_json=target is SupportedTarget.PG_JSONSCHEMA,
                    roots=roots,
                )
                return [Transpiler(JsonSchemaRawDoc, sql)]

    def _route_schema_maps(
        self, target: SupportedTarget, output_media_type: MediaType, *, roots: Set[str] | None
    ) -> Sequence[Transpiler]:
        """Route documents that each hold a map of named schemas.

        A target whose unit is the whole set consumes the documents as they are.
        One whose unit is a single schema gets [SchemaMapExpander][] in front of the same chain it would run on single-schema files.
        """
        match target:
            case SupportedTarget.POSTGRES | SupportedTarget.PG_JSONSCHEMA:
                validate_json = target is SupportedTarget.PG_JSONSCHEMA
                table_set = self._postgres_table_set(validate_json=validate_json, roots=roots)
                return [Transpiler(SchemaMapRawDoc, table_set)]
            case SupportedTarget.FASTAPI | SupportedTarget.JSON_SCHEMA:
                # An OpenAPI description is not a map of named schemas, so there is nothing
                # here for these to read; every document falls through unclaimed.
                return []
            case SupportedTarget.PASS_THRU:
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
        self, output_media_type: MediaType, roots: Set[str] | None
    ) -> Stage[Sequence[OpenApiRawDoc], Sequence[JsonSchemaArtifact]]:
        """Each `components/schemas` entry, written as a standalone JSON Schema file."""
        emit = Each(JsonSchemaReifier(output_media_type=output_media_type)).then(Flatten())
        per_doc = OpenApiParser().then(OpenApiComponentExtractor(roots=roots)).then(emit)
        return Each(per_doc).then(Flatten())

    def _pydantic(
        self, *, resolver: JsonSchemaRefResolver, roots: Set[str] | None
    ) -> Stage[Sequence[JsonSchemaRawDoc], Sequence[PythonArtifact]]:
        """A module per schema, collected into the package they are written as."""
        per_schema = resolver.then(PydanticTransformer(resolver=resolver, roots=roots))
        return (
            self._parse_and_register(resolver)
            .then(Each(per_schema))
            .then(PythonPackageAssembler())
            .then(PythonPackageReifier())
        )

    def _postgres(
        self, *, resolver: JsonSchemaRefResolver, validate_json: bool, roots: Set[str] | None
    ) -> Stage[Sequence[JsonSchemaRawDoc], Sequence[SqlArtifact]]:
        per_schema = resolver.then(
            PostgresTransformer(validate_json=validate_json, roots=roots)
        ).then(SqlReifier(artifact_name="schema.sql"))
        return self._parse_and_register(resolver).then(Each(per_schema)).then(Flatten())

    def _parse_and_register(
        self, resolver: JsonSchemaRefResolver
    ) -> Stage[Sequence[JsonSchemaRawDoc], Sequence[JsonSchemaDocument]]:
        """Parse every document, then register them all before any is resolved.

        A `$ref` into a sibling file cannot resolve until that file is registered,
        so resolving each document as soon as it is parsed would depend on the order the files were read.
        """
        return Each(JsonSchemaParser()).then(Each(resolver.registering()))

    def _postgres_table_set(
        self, *, validate_json: bool, roots: Set[str] | None
    ) -> Stage[Sequence[SchemaMapRawDoc], Sequence[SqlArtifact]]:
        """One migration for the whole set: an ordering needs every table to be known.

        Registration and validation are separate passes over the batch
        because a `$ref` into a sibling file cannot resolve until that file is registered,
        and the files are read in whatever order the directory gives.
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
        self, *, templates: Mapping[str, str] | None, roots: Set[str] | None
    ) -> Stage[Sequence[OpenApiRawDoc], Sequence[PythonArtifact]]:
        backend = TemplateBodyBackend(named_templates=templates or {})
        resolver = OpenApiRefResolver()
        # References are resolved before generation: a `$ref` standing in for a
        # parameter or a response is something the generator cannot act on, and
        # skipping it would silently drop a route's inputs.
        # Registration and resolution are separate passes over the batch, because a
        # `$ref` into a sibling document cannot resolve until that document is
        # registered, and documents are parsed in whatever order the source gives.
        generate = FastApiTransformer(body_backend=backend, roots=roots).then(PythonReifier())
        pipeline = (
            Each(OpenApiParser())
            .then(Each(resolver.registering()))
            .then(Each(resolver.then(generate)))
            .then(Flatten())
        )
        # The support modules belong to the run rather than to any one document, so
        # they are appended once the batch is reified rather than once per document.
        return pipeline.then(Append(backend.support_artifacts))
