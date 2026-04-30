"""Pass-through transpilers that parse and re-emit documents without structural change.

Three concrete `Transpiler` implementations:

- `JsonSchemaPassThruTranspiler` — JSON Schema → JSON Schema (identity round-trip).
- `OpenApiPassThruTranspiler` — OpenAPI 3.1 → OpenAPI 3.1 (identity round-trip).
- `OpenApiExtractTranspiler` — OpenAPI 3.1 → one `JsonSchemaDocument` per
  `components/schemas` entry.

All three accept a `pretty` flag (pretty-print JSON, default `True`) and a
`use_yaml` flag (emit YAML instead of JSON, default `False`).
"""

from __future__ import annotations

from collections.abc import Sequence

import orjson

from schema_to._errors import TranspilationError
from schema_to._pipeline import Transpiler
from schema_to._result import Err, Ok, Result
from schema_to.cst._base import SourceRef
from schema_to.cst._json_schema import JsonSchemaDocument
from schema_to.io._sink import OutputArtifact
from schema_to.io._source import MediaType, MediaTypes, RawDocument
from schema_to.parse._json_schema import JsonSchemaParser
from schema_to.parse._openapi import OpenApiParser
from schema_to.serialize._json_schema import JsonSchemaSerializer
from schema_to.serialize._openapi import OpenApiSerializer

__all__ = [
    "JsonSchemaPassThruTranspiler",
    "OpenApiExtractTranspiler",
    "OpenApiPassThruTranspiler",
]

_JS_ESSENCES = frozenset({"application/json", "application/yaml", "text/yaml"})


def _encode(data: object, *, pretty: bool, use_yaml: bool) -> tuple[bytes, MediaType]:
    """Serialize `data` to bytes, returning content and the appropriate media type."""
    if use_yaml:
        from yaml12 import format_yaml  # noqa: PLC0415

        return format_yaml(data).encode(), MediaTypes.yaml
    option = orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE if pretty else orjson.OPT_APPEND_NEWLINE
    return orjson.dumps(data, option=option), MediaTypes.json


def _peek_is_openapi(document: RawDocument) -> bool:
    """Return `True` if the document root object has an `openapi` version string."""
    if document.media_type.essence not in _JS_ESSENCES:
        return False
    try:
        if document.media_type.essence == "application/json":
            data = orjson.loads(document.content)
        else:
            from yaml12 import parse_yaml  # noqa: PLC0415

            data = parse_yaml(document.content.decode())
        return isinstance(data, dict) and isinstance(data.get("openapi"), str)
    except Exception:  # noqa: BLE001
        return False


class JsonSchemaPassThruTranspiler(Transpiler):
    """Parse a JSON Schema document and emit it back as normalised JSON or YAML.

    The output is semantically equivalent to the input: keywords are preserved
    and re-serialised, but cosmetic differences (key order, whitespace) may change.

    Attributes:
        pretty: Pretty-print JSON output (default `True`).
        use_yaml: Emit YAML instead of JSON (default `False`).
    """

    def __init__(self, *, pretty: bool = True, use_yaml: bool = False) -> None:
        self._pretty = pretty
        self._use_yaml = use_yaml
        self._parser = JsonSchemaParser()
        self._serializer = JsonSchemaSerializer()

    def accepts(self, document: RawDocument) -> bool:
        return (
            document.media_type.essence in _JS_ESSENCES
            and not _peek_is_openapi(document)
        )

    def transpile(self, document: RawDocument) -> Result[Sequence[OutputArtifact]]:
        result = self._parser.apply(document)
        if isinstance(result, Err):
            return result
        cst = result.value
        data = self._serializer.serialize_document(cst)
        content, media_type = _encode(data, pretty=self._pretty, use_yaml=self._use_yaml)
        ext = ".yaml" if self._use_yaml else ".json"
        stem = document.display_name or "schema"
        return Ok(
            [
                OutputArtifact(
                    artifact_id=f"{stem}.schema{ext}",
                    content=content,
                    media_type=media_type,
                    source_ids=(document.source_id,),
                )
            ]
        )


class OpenApiPassThruTranspiler(Transpiler):
    """Parse an OpenAPI 3.1 document and emit it back as normalised JSON or YAML.

    Attributes:
        pretty: Pretty-print JSON output (default `True`).
        use_yaml: Emit YAML instead of JSON (default `False`).
    """

    def __init__(self, *, pretty: bool = True, use_yaml: bool = False) -> None:
        self._pretty = pretty
        self._use_yaml = use_yaml
        self._parser = OpenApiParser()
        self._serializer = OpenApiSerializer()

    def accepts(self, document: RawDocument) -> bool:
        return _peek_is_openapi(document)

    def transpile(self, document: RawDocument) -> Result[Sequence[OutputArtifact]]:
        result = self._parser.apply(document)
        if isinstance(result, Err):
            return result
        cst = result.value
        data = self._serializer.serialize(cst)
        content, media_type = _encode(data, pretty=self._pretty, use_yaml=self._use_yaml)
        ext = ".yaml" if self._use_yaml else ".json"
        stem = document.display_name or "openapi"
        return Ok(
            [
                OutputArtifact(
                    artifact_id=f"{stem}{ext}",
                    content=content,
                    media_type=media_type,
                    source_ids=(document.source_id,),
                )
            ]
        )


class OpenApiExtractTranspiler(Transpiler):
    """Extract `components/schemas` from an OpenAPI document as standalone JSON Schema files.

    Each named schema in `components/schemas` becomes a separate `OutputArtifact`
    whose `artifact_id` is `<schema-name>.schema.json` (or `.yaml`).

    Attributes:
        pretty: Pretty-print JSON output (default `True`).
        use_yaml: Emit YAML instead of JSON (default `False`).
    """

    def __init__(self, *, pretty: bool = True, use_yaml: bool = False) -> None:
        self._pretty = pretty
        self._use_yaml = use_yaml
        self._parser = OpenApiParser()
        self._js_serializer = JsonSchemaSerializer()

    def accepts(self, document: RawDocument) -> bool:
        return _peek_is_openapi(document)

    def transpile(self, document: RawDocument) -> Result[Sequence[OutputArtifact]]:
        result = self._parser.apply(document)
        if isinstance(result, Err):
            return result
        cst = result.value
        errors: list[TranspilationError] = []
        artifacts: list[OutputArtifact] = []
        ext = ".yaml" if self._use_yaml else ".json"

        for name, schema in cst.components.schemas.items():
            # Wrap in a JsonSchemaDocument so callers have full provenance.
            doc_cst = JsonSchemaDocument(
                root=schema,
                source_id=document.source_id,
                display_name=name,
                source_ref=SourceRef(document.source_id, f"/components/schemas/{name}"),
            )
            data = self._js_serializer.serialize_document(doc_cst)
            content, media_type = _encode(data, pretty=self._pretty, use_yaml=self._use_yaml)
            artifacts.append(
                OutputArtifact(
                    artifact_id=f"{name}.schema{ext}",
                    content=content,
                    media_type=media_type,
                    source_ids=(document.source_id,),
                )
            )

        if errors:
            return Err(tuple(errors))
        return Ok(artifacts)
