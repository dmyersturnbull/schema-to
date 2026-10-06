"""Rendering errors and warnings for a person reading a terminal.

Each diagnostic is one line, led by `path:line:column:` as compilers write it,
so that terminals and editors can link it to the source.
The path is relative to the working directory when the document is a local file,
and the JSON Pointer to the offending node follows the message.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from typer import colors, style

from schema_to.io.locate import split_doc_id

if TYPE_CHECKING:
    from schema_to.errors import SourceLocation, TranspilationError, TranspilationWarning

__all__ = ["Severity", "format_error", "format_warning", "where"]


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"

    @property
    def color(self) -> str:
        return colors.RED if self is Severity.ERROR else colors.YELLOW


@dataclass(frozen=True, slots=True)
class _Diagnostic:
    severity: Severity
    message: str
    kind: str | None
    location: SourceLocation | None

    def render(self, cwd: Path) -> str:
        parts = []
        if self.location is not None:
            parts.append(style(where(self.location, cwd) + ":", bold=True))
        parts.extend((style(f"{self.severity}:", fg=self.severity.color, bold=True), self.message))
        if self.kind:
            parts.append(style(f"[{self.kind}]", dim=True))
        pointer = self._pointer()
        if pointer:
            parts.append(style(f"(at {pointer})", fg=colors.CYAN))
        return " ".join(parts)

    def _pointer(self) -> str:
        if self.location is None:
            return ""
        return split_doc_id(self.location.doc_id, self.location.json_pointer)[1]


def format_error(error: TranspilationError, *, cwd: Path) -> str:
    """Render `error` as one styled line."""
    diagnostic = _Diagnostic(Severity.ERROR, error.message, type(error).__name__, error.location)
    return diagnostic.render(cwd)


def format_warning(warning: TranspilationWarning, *, cwd: Path) -> str:
    """Render `warning` as one styled line."""
    diagnostic = _Diagnostic(Severity.WARNING, warning.message, warning.code, warning.location)
    return diagnostic.render(cwd)


def where(location: SourceLocation, cwd: Path) -> str:
    """Return `path:line:column` for `location`, omitting the parts that are unknown.

    A `file:` URI becomes a path relative to `cwd`.
    """
    file_id, _ = split_doc_id(location.doc_id)
    text = _display_path(file_id, cwd)
    if location.line is not None:
        text += f":{location.line}"
        if location.column is not None:
            text += f":{location.column}"
    return text


def _display_path(doc_id: str, cwd: Path) -> str:
    if not doc_id.startswith("file:"):
        return doc_id
    path = Path.from_uri(doc_id)
    try:
        return str(path.relative_to(cwd, walk_up=True))
    except ValueError:  # A different drive, on Windows.
        return str(path)
