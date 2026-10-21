"""Filename and artifact-type selection for the schema-shaped targets."""

from typing import TYPE_CHECKING, Literal, NamedTuple, overload

from schema_to.cst.json_schema import JsonSchemaDocument
from schema_to.cst.openapi import OpenApiDocument
from schema_to.io.sink import (
    Artifact,
    JsonSchemaArtifact,
    JsonSchemaJsonArtifact,
    JsonSchemaYamlArtifact,
    OpenApiArtifact,
    OpenApiJsonArtifact,
    OpenApiYamlArtifact,
)
from schema_to.io.uri import Uri

if TYPE_CHECKING:
    from schema_to.io.media_type import MediaType

__all__ = ["OutputInfo", "choose_output"]


class OutputInfo[A: Artifact](NamedTuple):
    filename: str
    artifact_type: type[A]


@overload
def choose_output(
    doc: OpenApiDocument | JsonSchemaDocument,
    output_media_type: MediaType | None,
    *,
    kind: Literal["openapi"],
) -> OutputInfo[OpenApiArtifact]: ...


@overload
def choose_output(
    doc: OpenApiDocument | JsonSchemaDocument,
    output_media_type: MediaType | None,
    *,
    kind: Literal["schema"],
) -> OutputInfo[JsonSchemaArtifact]: ...


def choose_output(
    doc: OpenApiDocument | JsonSchemaDocument,
    output_media_type: MediaType | None,
    *,
    kind: Literal["openapi", "schema"],
) -> OutputInfo[OpenApiArtifact | JsonSchemaArtifact]:
    """Chooses a filename and the correct artifact type for JSON Schema or OpenAPI.

    Args:
        doc: The parsed document being re-emitted.  Both its URI and its display name
            are carried over from the `RawDoc` it was parsed from.
        output_media_type: A required media-type, currently required to be a YAML or JSON type.
            If `None`, uses YAML if the path of `doc.source_id` ends with `.yaml`,
            otherwise uses JSON.
        kind: OpenAPI or JSON Schema.
    """
    # TODO: `writer` can support more, but this forces `.yaml` or `.json`.
    if output_media_type:
        is_yaml = output_media_type.type in {
            "application",
            "text",
        } and output_media_type.subtype.endswith(("+yaml", "yaml"))
    else:
        is_yaml = Uri.parse(doc.source_id).path.endswith(".yaml")
    ext = ".yaml" if is_yaml else ".json"
    artifact_type: type[Artifact]
    if kind == "openapi":
        artifact_type = OpenApiYamlArtifact if is_yaml else OpenApiJsonArtifact
    else:
        artifact_type = JsonSchemaYamlArtifact if is_yaml else JsonSchemaJsonArtifact
    base = doc.display_name.removesuffix(f".{kind}")
    return OutputInfo(f"{base}.{kind}{ext}", artifact_type)
