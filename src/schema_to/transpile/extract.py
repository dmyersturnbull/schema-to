"""Lifting the component schemas out of an OpenAPI document, as standalone schemas.

The stage's output is a JSON Schema document per `components/schemas` entry, which is
what the JSON Schema reifier writes and what any JSON-Schema-shaped target consumes.
Composing it in front of one of those is what turns "extract the schemas" into a
target, which is all `openapi_extract` does.

This target is not reachable from `--to`, so it is assembled here rather than in
`transpile.factory`; it stands as the worked example of building a `Transpiler` out of
stages by hand.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, override

from schema_to.cst.base import SourceRef
from schema_to.cst.json_schema import JsonSchemaDocument
from schema_to.cst.openapi import OpenApiDocument
from schema_to.io.sink import JsonSchemaArtifact
from schema_to.io.source import OpenApiRawDoc
from schema_to.parse.openapi import OpenApiParser
from schema_to.pipeline import Each, Flatten, Stage, Transpiler
from schema_to.reify.json_schema import JsonSchemaReifier
from schema_to.result import Ok, Result

if TYPE_CHECKING:
    from schema_to.io.media_type import MediaType

__all__ = ["OpenApiComponentExtractor", "openapi_extract"]


class OpenApiComponentExtractor(Stage[OpenApiDocument, Sequence[JsonSchemaDocument]]):
    """Yields one standalone JSON Schema document per `components/schemas` entry.

    Each carries the entry's name as its display name, which is what the reifier
    downstream names the file after, and a `SourceRef` back to the position it was
    lifted from, so a diagnostic can still point into the original document.
    """

    @override
    def apply(self, input: OpenApiDocument) -> Result[Sequence[JsonSchemaDocument]]:
        source_id = input.source_id or ""
        return Ok(
            [
                JsonSchemaDocument(
                    root=schema,
                    source_id=source_id,
                    display_name=name,
                    source_ref=SourceRef(source_id, f"/components/schemas/{name}"),
                )
                for name, schema in input.components.schemas.items()
            ]
        )


def openapi_extract(
    output_media_type: MediaType | None = None,
) -> Transpiler[OpenApiRawDoc, JsonSchemaArtifact]:
    """Build a transpiler writing each OpenAPI `components/schemas` entry to its own file.

    Each artifact is named `<schema-name>.schema.json` (or `.yaml`).
    """
    per_doc = (
        OpenApiParser()
        .then(OpenApiComponentExtractor())
        .then(Each(JsonSchemaReifier(output_media_type=output_media_type)).then(Flatten()))
    )
    return Transpiler(OpenApiRawDoc, Each(per_doc).then(Flatten()))
