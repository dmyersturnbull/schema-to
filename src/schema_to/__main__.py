"""CLI entry point for `schema-to`.

Invoked as `schema-to <command> [options]` or `python -m schema_to`.
"""

from __future__ import annotations

from enum import StrEnum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final, override

from typer import Argument, Exit, Option, Typer, echo

from schema_to.io.file import FileDataSink, FileDataSourceFactory
from schema_to.pipeline import Pipeline
from schema_to.result import Err, Ok
from schema_to.transpile.pass_thru import JsonSchemaPassThruTranspiler, OpenApiPassThruTranspiler

if TYPE_CHECKING:
    from collections.abc import Sequence

    from schema_to import DataSource, RawDoc


class CliEnum(StrEnum):
    @staticmethod
    @override
    def _generate_next_value_(name: str, start: int, count: int, last_values: list[str]) -> str:
        return name.lower().replace("_", "-")


class JsonschemaTarget(CliEnum):
    POSTGRES = auto()
    TYPESCRIPT = auto()
    DATACLASS = auto()
    PYDANTIC = auto()
    COMMONMARK = auto()


class OpenapiTarget(CliEnum):
    FASTAPI = auto()
    COMMONMARK = auto()


CWD: Final = Path.cwd()
app = Typer(
    name="schema-to",
    help="Transpile JSON Schema 2020-12 and OpenAPI 3.1 into code and SQL.",
    no_args_is_help=True,
)


@app.command()
def transpile(
    paths: Annotated[list[Path], Argument(help="Input file and/or directory paths.")],
    *,
    recursive: Annotated[
        bool, Option("-r", "--recursive", help="Search for input files in subdirectories")
    ] = False,
    output: Annotated[Path, Option("-o", "--output", help="Output directory.")] = CWD,
    to: Annotated[
        str, Option("-t", "--to", help="Target format (currently only 'pass-thru' is supported).")
    ] = "pass-thru",
    yaml: Annotated[bool, Option("--yaml/--json", help="Emit YAML instead of JSON.")] = False,
) -> None:
    """Transpile one or more schema sources into the requested target formats."""
    if to != "pass-thru":
        echo(f"error: target {to!r} is not yet supported; only 'pass-thru' is available.", err=True)
        raise Exit(1)
    sources = FileDataSourceFactory(recursive=recursive).get(paths)
    pipeline = _build_pipeline(output, sources, yaml=yaml)
    match pipeline.process():
        case Ok(summary):
            echo(
                f"Wrote {summary.artifacts_written} artifact(s) from "
                f"{summary.docs_read} document(s)."
            )
            for w in summary.warnings:
                echo(f"warning: {w.message}", err=True)
        case Err(errors):
            for e in errors:
                echo(f"error: {e.message}", err=True)
            raise Exit(1)


def _build_pipeline(output: Path, sources: Sequence[DataSource[RawDoc]], *, yaml: bool) -> Pipeline:
    transpilers = [
        OpenApiPassThruTranspiler(use_yaml=yaml),
        JsonSchemaPassThruTranspiler(use_yaml=yaml),
    ]
    sink = FileDataSink(output)
    return Pipeline(sources=sources, transpilers=transpilers, sink=sink)


def cli() -> None:
    """Package entry point called by the `schema-to` script."""
    app()


if __name__ == "__main__":
    cli()
