"""OpenAPI 3.1 document parser.

Converts a `RawDoc` (JSON or YAML bytes) into an `OpenApiDocument` CST.

Every object in the document is built by the shared plan interpreter,
driven by the field annotations on
[schema_to.cst.openapi][].
What remains here is
decoding the bytes,
checking the version string,
and attaching provenance from the [RawDoc].

Like the JSON Schema parser, this is **non-resolving**.
A `$ref` inside a schema stays a string,
and a `$ref` standing in for a
Parameter, Response, Header, Request Body, Link, Example, Security Scheme, or Path Item
becomes a
[schema_to.cst.openapi.Reference][]
node for a later stage to inline.

Errors are accumulated, so a single parse call yields the complete diagnostic set.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from schema_to.core import as_object
from schema_to.cst.openapi import OpenApiDocument
from schema_to.errors import ParseError, TranspilationError
from schema_to.io.core import DefaultJsonLikeReader
from schema_to.io.source import OpenApiRawDoc
from schema_to.parse._build import Cursor, Failed, build_root
from schema_to.parse._plan import SpecVersion
from schema_to.parse._utils import decode_raw_doc
from schema_to.pipeline import DocParser
from schema_to.result import Err, Ok, Result

if TYPE_CHECKING:
    from collections.abc import Mapping

    from schema_to.core import JsonValue
    from schema_to.io.core import JsonLikeReader

__all__ = ["OpenApiParser"]

_SUPPORTED_MAJOR = "3."


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenApiParser(DocParser[OpenApiRawDoc, OpenApiDocument]):
    """Parses JSON or YAML bytes into an `OpenApiDocument` CST.

    Accepts documents whose root object contains an `"openapi"` field starting with `"3."`.
    JSON Schema embedded in `schema` fields is parsed by the same interpreter,
    from the same `ObjectSchema` plan the JSON Schema parser uses.

    The parser is stateless: a single instance may be reused across documents.
    """

    reader: JsonLikeReader = field(default_factory=DefaultJsonLikeReader)

    def apply(self, input: OpenApiRawDoc) -> Result[OpenApiDocument]:
        try:
            data = decode_raw_doc(input, self.reader)
        except TranspilationError as exc:
            return Err((exc,))
        root = as_object(data)
        if root is None:
            return Err.of(
                ParseError("OpenAPI document must be a JSON object.", location=input.location(""))
            )
        at = Cursor.of(input, _declared_version(root))
        _check_version(root, at)
        doc = build_root(
            OpenApiDocument, data, at, source_id=input.uri, display_name=input.display_name
        )
        if at.errors:
            return Err(tuple(at.errors), warnings=tuple(at.warnings))
        if isinstance(doc, Failed):  # pragma: no cover — a failure always records an error
            return Err.of(ParseError("Malformed OpenAPI document.", location=input.location("")))
        return Ok(doc, warnings=tuple(at.warnings))


def _declared_version(root: Mapping[str, JsonValue]) -> SpecVersion | None:
    """Return the version the document declares, for gating version-scoped keys."""
    version = root.get("openapi")
    return SpecVersion.parse(version) if isinstance(version, str) else None


def _check_version(root: Mapping[str, JsonValue], at: Cursor) -> None:
    """Reject a document this parser's plans do not describe.

    Absence is left to the plan, which reports `openapi` as required;
    only a present-but-unsupported version is diagnosed here.
    """
    version = root.get("openapi")
    if version is None:
        return
    if not isinstance(version, str) or not version.startswith(_SUPPORTED_MAJOR):
        at.at("openapi").fail(f"openapi must be a '3.x' version string, got {version!r}.")
