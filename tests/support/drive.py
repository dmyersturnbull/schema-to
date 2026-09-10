"""Running a whole routed target, for tests at the end-to-end layer.

`TranspilerRouter` is the only thing that knows how a target is assembled,
so a test that wants one asks it, exactly as the CLI does.
A `Route` names the target and the routing options,
and its methods run that target over one or more documents.

The module-level routes are the ones the suite uses repeatedly.
Vary one with `dataclasses.replace`, e.g. `replace(POSTGRES, roots={"Thing"})`.
"""

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, field

from tests.support.asserts import failure, ok, warning_codes

from schema_to.io.media_type import MediaType, MediaTypes
from schema_to.io.sink import Artifact
from schema_to.io.source import JsonSchemaRawDoc, OpenApiRawDoc, RawDoc, SchemaMapRawDoc
from schema_to.pipeline import Transpiler
from schema_to.result import Result
from schema_to.transpile.std_router import TranspilerRouter


@dataclass(frozen=True, slots=True)
class Route:
    """A target name plus everything `TranspilerRouter` needs to build it.

    Attributes:
        target: The `--to` target name.
        selects: The `RawDoc` subclass the wanted transpiler consumes.
            A target may be routed to more than one, e.g. `pass-thru`.
        output_media_type: Encoding of the artifacts the target emits.
        templates: Named Jinja templates, for targets that fill bodies from them.
        roots: If given, the only named schemas to generate.
        schema_map: Whether input documents map names to schemas.
    """

    target: str
    selects: type[RawDoc] = JsonSchemaRawDoc
    output_media_type: MediaType = MediaTypes.json
    templates: Mapping[str, str] | None = field(default=None, kw_only=True)
    roots: Set[str] | None = field(default=None, kw_only=True)
    schema_map: bool = field(default=False, kw_only=True)

    def transpiler(self) -> Transpiler:
        """Return the routed transpiler that consumes `selects` documents."""
        routed = TranspilerRouter().route(
            self.target,
            self.output_media_type,
            templates=self.templates,
            roots=self.roots,
            schema_map=self.schema_map,
        )
        [chosen] = [t for t in routed if t.selects is self.selects]
        return chosen

    def run(self, *docs: RawDoc) -> Result[Sequence[Artifact]]:
        """Transpile `docs` as one batch and return the result unexamined."""
        return self.transpiler().transpile_all(docs)

    def artifacts(self, *docs: RawDoc) -> Sequence[Artifact]:
        """Transpile `docs` and return the artifacts, failing if the run did not succeed."""
        return ok(self.run(*docs))

    def text(self, *docs: RawDoc) -> str:
        """Transpile `docs` and return the single artifact's decoded content."""
        artifacts = self.artifacts(*docs)
        assert len(artifacts) == 1, f"Expected one artifact, got {len(artifacts)}"
        return artifacts[0].content.decode()

    def texts(self, *docs: RawDoc) -> Sequence[str]:
        """Transpile `docs` and return every artifact's decoded content."""
        return [a.content.decode() for a in self.artifacts(*docs)]

    def warnings(self, *docs: RawDoc) -> Sequence[str]:
        """Transpile `docs` and return the codes of the warnings a successful run raised."""
        result = self.run(*docs)
        ok(result)
        return warning_codes(result)

    def errors(self, *docs: RawDoc) -> Sequence[str]:
        """Transpile `docs` and return the messages of the errors, failing if it succeeded."""
        return failure(self.run(*docs))


PYDANTIC = Route("pydantic")
POSTGRES = Route("postgres")
PG_JSONSCHEMA = Route("pg-jsonschema")
POSTGRES_TABLE_SET = Route("postgres", SchemaMapRawDoc, schema_map=True)
PG_JSONSCHEMA_TABLE_SET = Route("pg-jsonschema", SchemaMapRawDoc, schema_map=True)
FASTAPI = Route("fastapi", OpenApiRawDoc)
JSON_SCHEMA = Route("json-schema", OpenApiRawDoc)
PASS_THRU_JSON_SCHEMA = Route("pass-thru")
PASS_THRU_OPENAPI = Route("pass-thru", OpenApiRawDoc)
