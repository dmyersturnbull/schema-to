"""Factory: build a list of `Transpiler` instances from a target name.

The `--to` CLI option is a string that names a target format.  This module
maps those names to the concrete `Transpiler` objects that implement them,
keeping the CLI free of target-specific imports and logic.

Supported targets
-----------------
``pass-thru``
    Re-emit each schema normalised (JSON Schema → ``.schema.json``,
    OpenAPI → ``.json`` / ``.yaml``).

``pydantic``
    JSON Schema 2020-12 → Pydantic v2 ``BaseModel`` classes.

``postgres``
    JSON Schema 2020-12 → PostgreSQL DDL (``CREATE TABLE`` statements).
"""

from __future__ import annotations

from schema_to.transpile.pass_thru import JsonSchemaPassThruTranspiler, OpenApiPassThruTranspiler
from schema_to.transpile.pydantic import JsonSchemaToPydanticTranspiler
from schema_to.transpile.sql import JsonSchemaToPostgresTranspiler

__all__ = ["SUPPORTED_TARGETS", "build_transpilers"]

SUPPORTED_TARGETS: frozenset[str] = frozenset({"pass-thru", "pydantic", "postgres"})


def build_transpilers(to: str, *, use_yaml: bool = False) -> list:
    """Return the ordered list of transpilers for target *to*.

    Parameters
    ----------
    to:
        Target format name (e.g. ``"pass-thru"``, ``"pydantic"``).
    use_yaml:
        Emit YAML output instead of JSON where the transpiler supports it.

    Raises:
    ------
    ValueError
        If *to* is not a recognised target name.
    """
    match to:
        case "pass-thru":
            return [
                OpenApiPassThruTranspiler(use_yaml=use_yaml),
                JsonSchemaPassThruTranspiler(use_yaml=use_yaml),
            ]
        case "pydantic":
            return [JsonSchemaToPydanticTranspiler()]
        case "postgres":
            return [JsonSchemaToPostgresTranspiler()]
        case _:
            msg = (
                f"target {to!r} is not yet supported; "
                f"choose one of: {', '.join(sorted(SUPPORTED_TARGETS))}"
            )
            raise ValueError(msg)
