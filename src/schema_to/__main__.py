"""CLI entry point for `schema-to`.

Invoked as `schema-to <command> [options]` or `python -m schema_to`.
"""

from __future__ import annotations

import enum
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Literal, override

import typer


class CliEnum(StrEnum):
    @staticmethod
    @override
    def _generate_next_value_(name: str, start: int, count: int, last_values: list[str]) -> str:
        return name.lower().replace("_", "-")


class JsonschemaTarget(CliEnum):
    POSTGRES = enum.auto()
    TYPESCRIPT = enum.auto()
    DATACLASS = enum.auto()
    PYDANTIC = enum.auto()
    COMMONMARK = enum.auto()


class OpenapiTarget(CliEnum):
    FASTAPI = enum.auto()
    COMMONMARK = enum.auto()


CWD: Final = Path.cwd()
app = typer.Typer(
    name="schema-to",
    help="Transpile JSON Schema 2020-12 and OpenAPI 3.1 into code and SQL.",
    no_args_is_help=True,
)


@app.command()
def transpile(
    source: Annotated[
        list[str],
        typer.Argument(help="Input sources: file paths, directory paths, or URLs."),
    ],
    output: Annotated[
        Path,
        typer.Option("-o", "--output", help="Output directory."),
    ] = CWD,
    to: Annotated[
        JsonschemaTarget | OpenapiTarget | Literal["pass-thru"],
        typer.Option(
            "-t",
            "--to",
            help="Target format.",
        ),
    ] = "pass-thru",
) -> None:
    """Transpile one or more schema sources into the requested target formats."""
    ...


def cli() -> None:
    """Package entry point called by the `schema-to` script."""
    app()


if __name__ == "__main__":
    cli()
