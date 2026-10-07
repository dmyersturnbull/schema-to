"""Error and warning types for the transpilation pipeline."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextRange:
    """A span of raw text.

    Attributes:
        line: 1-based line number of the start.
        column: 1-based column number of the start.
        end_line: 1-based line number of the end, or `None` if only a point is known.
        end_column: 1-based column number of the end, or `None` if only a point is known.
    """

    line: int
    column: int
    end_line: int | None = None
    end_column: int | None = None

    def __str__(self) -> str:
        return f"{self.line}:{self.column}"


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """A position within a source document.

    Attributes:
        uri: URI of the document as the user wrote it, matching `RawDoc.uri`
            or, for a document derived from another, `Origin.uri`.
        json_pointer: [RFC 6901](https://www.rfc-editor.org/rfc/rfc6901)
            pointer to the offending node within the document at `uri`.
        range: Where the node sits in the raw text, if known.
    """

    uri: str
    json_pointer: str | None = None
    range: TextRange | None = None

    @property
    def line(self) -> int | None:
        """The 1-based line the location starts on, if known."""
        return self.range.line if self.range is not None else None

    @property
    def column(self) -> int | None:
        """The 1-based column the location starts on, if known."""
        return self.range.column if self.range is not None else None

    def __str__(self) -> str:
        return (
            self.uri
            + (f":{self.json_pointer}" if self.json_pointer else "")
            + (f":{self.range}" if self.range is not None else "")
        )


@dataclass(frozen=True, slots=True)
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

    def __str__(self) -> str:
        return (
            self.message
            + (f" [{self.code}]" if self.code else "")
            + (f" at {self.location}" if self.location else "")
        )


class TranspilationError(Exception):
    """Base class for all fatal errors produced by the transpilation pipeline.

    Subclasses correspond to the pipeline stage that raised them,
    making it easy to determine where a failure occurred without inspecting the stack trace.
    """

    def __init__(self, message: str, *, location: SourceLocation | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.location = location

    def __str__(self) -> str:
        return self.message + (f" at {self.location}" if self.location is not None else "")


class ParseError(TranspilationError):
    """A source document could not be parsed as valid JSON or YAML."""


class ResolutionError(TranspilationError):
    """A `$ref`, `$dynamicRef`, or `$anchor` target could not be resolved."""


class SchemaValidationError(TranspilationError):
    """A source document does not conform to its declared meta-schema."""


class GenerationError(TranspilationError):
    """A CST node could not be converted to a target-language AST node.

    Typically raised when the input uses a JSON Schema keyword that is not expressible in the requested target language.
    """


class KeywordError(GenerationError):
    """A target-specific extension keyword carries a value of the wrong shape.

    Distinct from a schema that a target merely cannot express:
    This is a keyword written for the target, addressed to it, and malformed.
    Silently ignoring one would drop the very instruction it was written to give.
    """


class ReificationError(TranspilationError):
    """An AST node could not be serialised to final output text."""
