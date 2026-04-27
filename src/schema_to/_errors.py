"""Error and warning types for the transpilation pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceLocation:
    """A position within a source document.

    Attributes:
        source_id: Opaque identifier matching `RawDocument.source_id`.
        json_pointer: [RFC 6901](https://www.rfc-editor.org/rfc/rfc6901) pointer to the
            offending node within the parsed document.
        line: 1-based line number in the raw text, if available.
        column: 1-based column number in the raw text, if available.
    """

    source_id: str
    json_pointer: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True)
class TranspilationWarning:
    """A non-fatal diagnostic emitted during transpilation.

    Attributes:
        message: Human-readable description.
        code: Machine-readable warning code, e.g. `"unsupported-keyword"`.
        location: Origin in the source document, if known.
    """

    message: str
    code: str | None = None
    location: SourceLocation | None = None


class TranspilationError(Exception):
    """Base class for all fatal errors produced by the transpilation pipeline.

    Subclasses correspond to the pipeline stage that raised them, making it easy
    to determine where a failure occurred without inspecting the stack trace.
    """

    def __init__(
        self,
        message: str,
        *,
        location: SourceLocation | None = None,
        cause: BaseException | None = None,
    ) -> None: ...

    @property
    def message(self) -> str: ...

    @property
    def location(self) -> SourceLocation | None: ...


class ParseError(TranspilationError):
    """A source document could not be parsed as valid JSON or YAML."""


class ResolutionError(TranspilationError):
    """A `$ref`, `$dynamicRef`, or `$anchor` target could not be resolved."""


class SchemaValidationError(TranspilationError):
    """A source document does not conform to its declared meta-schema."""


class GenerationError(TranspilationError):
    """A CST node could not be converted to a target-language AST node.

    Typically raised when the input uses a JSON Schema keyword that is not
    expressible in the requested target language.
    """


class ReificationError(TranspilationError):
    """An AST node could not be serialised to final output text."""
