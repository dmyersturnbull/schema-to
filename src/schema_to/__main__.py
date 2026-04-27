"""CLI entry point for `schema-to`.

Invoked as `schema-to <command> [options]` or `python -m schema_to`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

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
    ] = Path("."),
    target: Annotated[
        list[str],
        typer.Option(
            "-t",
            "--target",
            help=(
                "Target format. May be repeated. "
                "Choices: postgres, typescript, python-dataclass, python-pydantic."
            ),
        ),
    ] = [],  # noqa: B006
) -> None:
    """Transpile one or more schema sources into the requested target formats."""
    ...


@app.command()
def validate(
    source: Annotated[
        list[str],
        typer.Argument(help="Schema files or directories to validate."),
    ],
) -> None:
    """Validate source documents against their meta-schemas without generating output."""
    ...


def cli() -> None:
    """Package entry point called by the `schema-to` script."""
    app()


if __name__ == "__main__":
    cli()
