"""CLI entry point for `schema-to`.

Invoked as `schema-to <command> [options]` or `python -m schema_to`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Final

from typer import Argument, Exit, Option, Typer, echo

from schema_to.io.file import FileDataSink, FileDataSourceFactory
from schema_to.pipeline import Pipeline
from schema_to.result import Err, Ok
from schema_to.transpile.factory import TranspilerRouter, RoutingError

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
        str,
        Option(
            "-t", "--to", help=f"Target format. Supported: {', '.join(sorted(TranspilerRouter.SUPPORTED_TARGETS))}."
        ),
    ] = "pass-thru",
    yaml: Annotated[bool, Option("--yaml/--json", help="Emit YAML instead of JSON.")] = False,
) -> None:
    """Transpile one or more schema sources into the requested target formats."""
    try:
        transpilers = TranspilerRouter().route(to, use_yaml=yaml)
    except RoutingError as exc:
        echo(f"error: {exc}", err=True)
        raise Exit(1) from exc

    try:
        sources = FileDataSourceFactory(recursive=recursive).get(paths)
    except ValueError as exc:
        echo(f"error: {exc}", err=True)
        raise Exit(1) from exc
    pipeline = Pipeline(sources=sources, transpilers=transpilers, sink=FileDataSink(output))
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


def cli() -> None:
    """Package entry point called by the `schema-to` script."""
    app()


if __name__ == "__main__":
    cli()
