"""Factory: build a list of `Transpiler` instances from a target name.

The `--to` CLI option is a string that names a target format.  This module
maps those names to the concrete `Transpiler` objects that implement them,
keeping the CLI free of target-specific imports and logic.

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
  - `fastapi`
    OpenAPI 3.1 → FastAPI application module (route stubs + security wiring).
    Route bodies are filled from each operation's `x-fastapi-body` Jinja
    extension when present, and left as `...` stubs otherwise; see
    `examples/postgres/` for a worked PostgreSQL set built on `query-dsl`.
"""


from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from schema_to.generate.fastapi import FastApiTransformer
from schema_to.generate.sql import PostgresTransformer
from schema_to.generate.template_body import TemplateBodyBackend
from schema_to.transpile.fastapi import OpenApiToFastApiTranspiler
from schema_to.transpile.pass_thru import JsonSchemaPassThruTranspiler, OpenApiPassThruTranspiler
from schema_to.transpile.pydantic import JsonSchemaToPydanticTranspiler
from schema_to.transpile.sql import JsonSchemaToPostgresTranspiler

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from schema_to.io.media_type import MediaType
    from schema_to.pipeline import Transpiler

__all__ = ["RoutingError", "TranspilerRouter"]


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
    SUPPORTED_TARGETS: ClassVar[frozenset[str]] = frozenset(
        {"fastapi", "pass-thru", "pydantic", "postgres", "pg-jsonschema"}
    )

    def route(
        self,
        target_name: str,
        output_media_type: MediaType,
        *,
        templates: Mapping[str, str] | None = None,
    ) -> Sequence[Transpiler]:
        """Return the ordered list of transpilers for target `to`.

        Args:
            target_name: The requested target format.
            output_media_type: Media type for re-emitted schema sources.
            templates: Named endpoint-body Jinja templates (`fastapi` target),
                registered from the CLI's `--template <name>=<path>`.

        Raises:
            RoutingError: If `target_name` is not recognized or supported.
        """
        match target_name:
            case "fastapi":
                backend = TemplateBodyBackend(named_templates=templates or {})
                return [
                    OpenApiToFastApiTranspiler(generator=FastApiTransformer(body_backend=backend))
                ]
            case "pass-thru":
                return [
                    OpenApiPassThruTranspiler(),
                    JsonSchemaPassThruTranspiler(output_media_type=output_media_type),
                ]
            case "pydantic":
                return [JsonSchemaToPydanticTranspiler()]
            case "postgres":
                return [JsonSchemaToPostgresTranspiler()]
            case "pg-jsonschema":
                return [
                    JsonSchemaToPostgresTranspiler(
                        generator=PostgresTransformer(validate_json=True)
                    )
                ]
            case _:
                raise RoutingError(value=target_name)
