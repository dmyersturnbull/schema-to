"""CLI entry point for `schema-to`.

Invoked as `schema-to <command> [options]` or `python -m schema_to`.
"""

from __future__ import annotations

import enum
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Literal, override

import typer

from schema_to._pipeline import Pipeline
from schema_to._result import Err, Ok
from schema_to.io._file import DirectoryDataSource, FileDataSink, FileDataSource
from schema_to.io._source import MediaTypes
from schema_to.transpile._pass_thru import (
    JsonSchemaPassThruTranspiler,
    OpenApiExtractTranspiler,
    OpenApiPassThruTranspiler,
)


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
        typer.Option("-t", "--to", help="Target format."),
    ] = "pass-thru",
    yaml: Annotated[
        bool,
        typer.Option("--yaml/--json", help="Emit YAML instead of pretty JSON."),
    ] = False,
) -> None:
    """Transpile one or more schema sources into the requested target formats."""
    if to != "pass-thru":
        typer.echo(f"Target '{to}' is not yet implemented.", err=True)
        raise typer.Exit(1)

    sources = []
    for s in source:
        p = Path(s)
        if p.is_dir():
            sources.append(DirectoryDataSource(p, media_type=MediaTypes.json if not yaml else MediaTypes.yaml))
        else:
            sources.append(FileDataSource(p))

    transpilers = [
        OpenApiPassThruTranspiler(use_yaml=yaml),
        JsonSchemaPassThruTranspiler(use_yaml=yaml),
    ]
    sink = FileDataSink(output)
    pipeline = Pipeline(sources=sources, transpilers=transpilers, sink=sink)

    match pipeline.process():
        case Ok(summary):
            typer.echo(
                f"Wrote {summary.artifacts_written} artifact(s) from "
                f"{summary.documents_read} document(s)."
            )
            for w in summary.warnings:
                typer.echo(f"warning: {w.message}", err=True)
        case Err(errors):
            for e in errors:
                typer.echo(f"error: {e.message}", err=True)
            raise typer.Exit(1)


def cli() -> None:
    """Package entry point called by the `schema-to` script."""
    app()


if __name__ == "__main__":
    cli()
