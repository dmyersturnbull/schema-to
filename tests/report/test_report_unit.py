"""Rendering diagnostics as one styled line each."""

import re
from pathlib import Path

from schema_to.errors import ResolutionError, SourceLocation, TranspilationWarning
from schema_to.report import format_error, format_warning, where

_CWD = Path.cwd().resolve() / "work" / "project"
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def unstyle(text: str) -> str:
    return _ANSI.sub("", text)


def _uri(*parts: str) -> str:
    """A `file:` URI under the parent of `_CWD`, valid on any platform."""
    return _CWD.parent.joinpath(*parts).as_uri()


def test_a_file_under_the_cwd_is_shown_relative_to_it() -> None:
    location = SourceLocation(_uri("project", "in", "a.json"), "/x", line=3, column=5)
    assert where(location, _CWD) == f"{Path('in', 'a.json')}:3:5"


def test_a_file_outside_the_cwd_walks_up_to_it() -> None:
    location = SourceLocation(_uri("other", "a.json"), "/x", line=3)
    assert where(location, _CWD) == f"{Path('..', 'other', 'a.json')}:3"


def test_a_non_file_document_is_shown_as_is() -> None:
    assert where(SourceLocation("urn:schema-to:set", "/x"), _CWD) == "urn:schema-to:set"


def test_an_error_names_its_place_kind_and_pointer() -> None:
    location = SourceLocation(
        _uri("project", "catalog.yaml") + "#/thing", "/properties/t", line=6, column=7
    )
    error = ResolutionError("Cannot resolve $ref 'x'.", location=location)
    assert unstyle(format_error(error, cwd=_CWD)) == (
        "catalog.yaml:6:7: error: Cannot resolve $ref 'x'. [ResolutionError] "
        "(at /thing/properties/t)"
    )


def test_a_warning_without_a_location_is_just_its_message() -> None:
    warning = TranspilationWarning("Something odd.", code="odd")
    assert unstyle(format_warning(warning, cwd=_CWD)) == "warning: Something odd. [odd]"


def test_output_is_colored() -> None:
    """Whether the colors reach the terminal is left to `typer.echo`, which strips them when piped."""
    error = ResolutionError("Nope.", location=SourceLocation(_uri("project", "a.json")))
    warning = TranspilationWarning("Hmm.")
    assert "\x1b[31m" in format_error(error, cwd=_CWD)
    assert "\x1b[33m" in format_warning(warning, cwd=_CWD)
