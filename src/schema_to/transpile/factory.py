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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from schema_to.transpile.pass_thru import JsonSchemaPassThruTranspiler, OpenApiPassThruTranspiler
from schema_to.transpile.pydantic import JsonSchemaToPydanticTranspiler
from schema_to.transpile.sql import JsonSchemaToPostgresTranspiler

if TYPE_CHECKING:
    from collections.abc import Sequence

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
    SUPPORTED_TARGETS: ClassVar[frozenset[str]] = frozenset({"pass-thru", "pydantic", "postgres"})

    def route(self, target_name: str, output_media_type: MediaType) -> Sequence[Transpiler]:
        """Return the ordered list of transpilers for target `to`.

        Raises:
            RoutingError: If `target_name` is not recognized or supported.
        """
        match target_name:
            case "pass-thru":
                return [
                    OpenApiPassThruTranspiler(),
                    JsonSchemaPassThruTranspiler(output_media_type=output_media_type),
                ]
            case "pydantic":
                return [JsonSchemaToPydanticTranspiler()]
            case "postgres":
                return [JsonSchemaToPostgresTranspiler()]
            case _:
                raise RoutingError(value=target_name)
