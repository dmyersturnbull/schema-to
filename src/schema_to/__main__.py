"""CLI entry point for schema-to."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Final, NamedTuple, Self

from typer import Argument, BadParameter, Exit, Option, Typer, echo

from schema_to.errors import TranspilationError, TranspilationWarning
from schema_to.io.file import FileDataSink, FileDataSourceFactory, SchemaMapDirectorySource
from schema_to.io.media_type import MediaTypes
from schema_to.io.source import DataSource
from schema_to.pipeline import Pipeline
from schema_to.report import format_error, format_warning
from schema_to.result import Err, Ok
from schema_to.transpile.std_router import SupportedTarget, TranspilerRouter


class NamedTemplate(NamedTuple):
    name: str
    path: Path

    @classmethod
    def parse(cls, spec: str) -> Self:
        name, sep, path = spec.partition("=")
        if not sep or not name:
            msg = f"Invalid --template {spec}; expected NAME=PATH."
            raise ValueError(msg)
        return cls(name, Path(path))

    def __str__(self) -> str:
        return f"{self.name}={self.path}"


CWD: Final = Path.cwd()
cli = Typer(
    name="schema-to",
    help="Transpile JSON Schema 2020-12 and OpenAPI 3.1/3.2 into various code and documentation formats.",
    no_args_is_help=True,
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
)
ROUTER = TranspilerRouter()


@cli.command()
def transpile(
    paths: Annotated[list[Path], Argument(help="Input file and/or directory paths.")],
    *,
    recursive: Annotated[
        bool, Option("-r", "--recursive", help="Search for input files in subdirectories.")
    ] = False,
    include_hidden: Annotated[
        bool, Option(help="Include hidden files when scanning directories.")
    ] = False,
    output: Annotated[Path, Option("-o", "--output", help="Output directory.")] = CWD,
    to: Annotated[
        SupportedTarget, Option("-t", "--to", help="Target format.")
    ] = SupportedTarget.PASS_THRU,
    template: Annotated[
        list[NamedTemplate] | None,
        Option(
            parser=NamedTemplate.parse,
            metavar="name=path",
            help="Register a Jinja template to use with the extension keyword 'x-fastapi-template'.",
        ),
    ] = None,
    yaml: Annotated[bool, Option("--yaml/--json", help="Emit YAML instead of JSON.")] = False,
    schema_map: Annotated[
        bool,
        Option(
            help="Assume each input file contains an JSON object mapping names to schemas. "
            "This is a common pattern for OpenAPI components."
        ),
    ] = False,
    roots: Annotated[
        list[str] | None,
        Option(
            help="Only produce output artifacts for these named schema nodes."
            "Can be a `$defs` entry, a --schema-map schema name, or an OpenAPI component name."
        ),
    ] = None,
) -> None:
    """Transpile one or more schema sources into the requested target formats."""
    output_media_type = MediaTypes.yaml if yaml else MediaTypes.json
    root_set = frozenset(roots) if roots else None
    templates = _load_templates(template or [])
    transpilers = ROUTER.route(
        to, output_media_type, templates=templates, roots=root_set, schema_map=schema_map
    )
    sources = _sources(
        paths, recursive=recursive, schema_map=schema_map, include_hidden=include_hidden
    )
    pipeline = Pipeline(sources=sources, transpilers=transpilers, sink=FileDataSink(output))
    match pipeline.process():
        case Ok(summary):
            _report(summary.warnings, ())
            echo(
                f"Wrote {len(summary.artifacts_written)} artifact(s) from "
                f"{len(summary.docs_used)} document(s)."
            )
        case Err(errors, warnings=warnings):
            _report(warnings, errors)
            raise Exit(1)


def _report(
    warnings: Sequence[TranspilationWarning], errors: Sequence[TranspilationError]
) -> None:
    for w in warnings:
        echo(format_warning(w, cwd=Path.cwd()), err=True)
    for e in errors:
        echo(format_error(e, cwd=Path.cwd()), err=True)


def _sources(
    paths: Sequence[Path], *, recursive: bool, schema_map: bool, include_hidden: bool
) -> Sequence[DataSource]:
    """Build the data sources for the given paths.

    A schema map cannot be told from a single schema by file name,
    so the flag — not the extension — selects the source.
    """
    if not schema_map:
        return FileDataSourceFactory(recursive=recursive, include_hidden=include_hidden).get(paths)
    return [SchemaMapDirectorySource(path, recursive=recursive) for path in paths]


def _load_templates(templates: Sequence[NamedTemplate]) -> Mapping[str, str]:
    by_name = {name: set() for name, _ in templates}
    for t in templates:
        by_name[t.name].add(str(t))
    clashes = []
    for ts in by_name.values():
        if len(ts) > 1:
            clashes += ts
    if clashes:
        msg = f"Some templates share names: {', '.join(clashes)}"
        raise BadParameter(msg)
    return {name: Path(path).read_text(encoding="utf-8") for name, path in templates}


if __name__ == "__main__":
    cli()
