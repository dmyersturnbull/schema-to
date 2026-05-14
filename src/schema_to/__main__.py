"""CLI entry point for `schema-to`.

Invoked as `schema-to <command> [options]` or `python -m schema_to`.
"""

import glob
from collections.abc import Iterator, Iterable

from schema_to import DataSource, OpenApiExtractTranspiler

from enum import StrEnum, auto
from pathlib import Path
from typing import Annotated, Final, Literal, override

from typer import Argument, Exit, Option, Typer, echo

from schema_to._pipeline import Pipeline
from schema_to._result import Err, Ok
from schema_to.io._file import FileDataSink, FileDataSource
from schema_to.io._source import MediaTypes
from schema_to.transpile._pass_thru import JsonSchemaPassThruTranspiler, OpenApiPassThruTranspiler


class CliEnum(StrEnum):
    @staticmethod
    @override
    def _generate_next_value_(name: str, start: int, count: int, last_values: list[str]) -> str:
        return name.lower().replace("_", "-")


class JsonschemaTarget(CliEnum):
    JSONSCHEMA = auto()
    POSTGRES = auto()
    TYPESCRIPT = auto()
    DATACLASS = auto()
    PYDANTIC = auto()
    COMMONMARK = auto()


class OpenapiTarget(CliEnum):
    JSONSCHEMA = auto()
    OPENAPI = auto()
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
    paths: Annotated[list[Path], Argument(help="Input sources files and/or directories.")],
    *,
    output: Annotated[Path, Option("-o", "--output", help="Output directory.")] = CWD,
    recursive: Annotated[
        bool, Option(help="Scan directories recursively (ignores dotfiles).")
    ] = False,
    to: Annotated[
        JsonschemaTarget | OpenapiTarget | Literal["pass-thru"],
        Option("-t", "--to", help="Target format."),
    ] = "pass-thru",
    yaml: Annotated[
        bool, Option("--yaml/--json", help="Emit YAML instead of pretty JSON.")
    ] = False,
) -> None:
    """Transpile one or more schema sources into the requested target formats."""
    doc_paths = _walk(paths, recursive=recursive)
    sources: list[DataSource] = []
    for path in doc_paths:
        mt = MediaTypes.source_from_suffix(path.suffix)
        sources.append(FileDataSource(path, mt))
    transpilers = [
        OpenApiPassThruTranspiler(use_yaml=yaml),
        JsonSchemaPassThruTranspiler(use_yaml=yaml),
        OpenApiExtractTranspiler(use_yaml=yaml),
    ]
    sink = FileDataSink(output)
    pipeline = Pipeline(sources=sources, transpilers=transpilers, sink=sink)

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


def _walk(roots: Iterable[Path], *, recursive: bool) -> Iterator[Path]:  # noqa: PTH207
    for root in roots:
        for suffix in (".json", ".yaml"):
            pattern = ("**/*" if recursive else "") + "*" + suffix
            for path in glob.iglob(pattern, root_dir=str(root), recursive=recursive):
                yield Path(path)


def cli() -> None:
    """Package entry point called by the `schema-to` script."""
    app()


if __name__ == "__main__":
    cli()
