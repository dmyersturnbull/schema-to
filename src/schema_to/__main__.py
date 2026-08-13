"""CLI entry point for `schema-to`.

Invoked as `schema-to <command> [options]` or `python -m schema_to`.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Final

from typer import Argument, Exit, Option, Typer, echo

from schema_to.io.file import FileDataSink, FileDataSourceFactory, SchemaMapDirectorySource
from schema_to.io.media_type import MediaTypes
from schema_to.io.source import DataSource
from schema_to.pipeline import Pipeline
from schema_to.result import Err, Ok
from schema_to.transpile.factory import RoutingError, TranspilerRouter

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
            "-t",
            "--to",
            help=f"Target format. Supported: {', '.join(sorted(TranspilerRouter.SUPPORTED_TARGETS))}.",
        ),
    ] = "pass-thru",
    template: Annotated[
        list[str] | None,
        Option(
            "--template",
            help="Register an endpoint-body template as NAME=PATH (repeatable; "
            "referenced by an operation's x-fastapi-template extension).",
        ),
    ] = None,
    yaml: Annotated[bool, Option("--yaml/--json", help="Emit YAML instead of JSON.")] = False,
    schema_map: Annotated[
        bool,
        Option(
            "--schema-map",
            help="Treat each input file as a map of named schemas rather than as one "
            "schema. Works with any target: a target whose unit is the whole set "
            "(postgres) reads it directly, and a per-schema target sees each named "
            "schema in turn.",
        ),
    ] = False,
    roots: Annotated[
        list[str] | None,
        Option(
            "--roots",
            help="Restrict output to these named schema nodes (repeatable): a `$defs` "
            "entry, a --schema-map schema name, or an OpenAPI components/schemas name. "
            "Every other schema in the input stays available for $ref resolution; only "
            "which ones become their own artifact changes. Omit to generate every "
            "named schema, as before.",
        ),
    ] = None,
) -> None:
    """Transpile one or more schema sources into the requested target formats."""
    output_media_type = MediaTypes.yaml if yaml else MediaTypes.json
    root_set = frozenset(roots) if roots else None
    router = TranspilerRouter()
    try:
        templates = _load_templates(template or [])
        transpilers = router.route(
            to, output_media_type, templates=templates, roots=root_set, schema_map=schema_map
        )
    except (RoutingError, ValueError, OSError) as exc:
        echo(f"error: {exc}", err=True)
        raise Exit(1) from exc

    try:
        sources = _sources(paths, recursive=recursive, schema_map=schema_map)
    except (ValueError, OSError) as exc:
        echo(f"error: {exc}", err=True)
        raise Exit(1) from exc
    pipeline = Pipeline(sources=sources, transpilers=transpilers, sink=FileDataSink(output))
    match pipeline.process():
        case Ok(summary):
            echo(
                f"Wrote {summary.artifacts_written} artifact(s) from "
                f"{summary.docs_used} document(s)."
            )
            for w in summary.warnings:
                echo(f"warning: {w.message}", err=True)
        case Err(errors):
            for e in errors:
                echo(f"error: {e.message}", err=True)
            raise Exit(1)


def _sources(paths: list[Path], *, recursive: bool, schema_map: bool) -> Sequence[DataSource]:
    """Build the data sources for the given paths.

    A schema map cannot be told from a single schema by file name, so the flag — not
    the extension — selects the source.
    """
    if not schema_map:
        return FileDataSourceFactory(recursive=recursive).get(paths)
    return [SchemaMapDirectorySource(path, recursive=recursive) for path in paths]


def _load_templates(specs: list[str]) -> dict[str, str]:
    """Parse `NAME=PATH` template specs into a `{name: source}` mapping."""
    templates: dict[str, str] = {}
    for spec in specs:
        name, sep, path = spec.partition("=")
        if not sep or not name:
            msg = f"Invalid --template {spec!r}; expected NAME=PATH."
            raise ValueError(msg)
        templates[name] = Path(path).read_text(encoding="utf-8")
    return templates


def cli() -> None:
    """Package entry point called by the `schema-to` script."""
    app()


if __name__ == "__main__":
    cli()
