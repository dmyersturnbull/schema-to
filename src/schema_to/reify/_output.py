"""Filename and artifact-type selection for the schema-shaped targets."""

from typing import TYPE_CHECKING, Literal, NamedTuple, overload

from schema_to.io.sink import (
    Artifact,
    JsonSchemaArtifact,
    JsonSchemaJsonArtifact,
    JsonSchemaYamlArtifact,
    OpenApiArtifact,
    OpenApiJsonArtifact,
    OpenApiYamlArtifact,
)

if TYPE_CHECKING:
    from schema_to.io.media_type import MediaType

__all__ = ["OutputInfo", "choose_output"]


class OutputInfo[A: Artifact](NamedTuple):
    filename: str
    artifact_type: type[A]


@overload
def choose_output(
    *,
    source_id: str,
    display_name: str | None,
    output_media_type: MediaType | None,
    kind: Literal["openapi"],
) -> OutputInfo[OpenApiArtifact]: ...


@overload
def choose_output(
    *,
    source_id: str,
    display_name: str | None,
    output_media_type: MediaType | None,
    kind: Literal["schema"],
) -> OutputInfo[JsonSchemaArtifact]: ...


def choose_output(
    *,
    source_id: str,
    display_name: str | None,
    output_media_type: MediaType | None,
    kind: Literal["openapi", "schema"],
) -> OutputInfo[OpenApiArtifact | JsonSchemaArtifact]:
    """Chooses a filename and the correct artifact type for JSON Schema or OpenAPI.

    Args:
        source_id: Identifies the document being re-emitted.
        display_name: Short name for the document, used as the filename stem.
        output_media_type: A required media-type, currently required to be a YAML or JSON type.
          If `None`, uses YAML if `source_id.endswith(".yaml")`, otherwise uses JSON.
        kind: OpenAPI or JSON Schema.
    """
    # TODO: `writer` can support more, but this forces `.yaml` or `.json`.
    if output_media_type:
        is_yaml = output_media_type.type in {
            "application",
            "text",
        } and output_media_type.subtype.endswith(("+yaml", "yaml"))
    else:
        is_yaml = source_id.endswith(".yaml")
    ext = ".yaml" if is_yaml else ".json"
    artifact_type: type[Artifact]
    if kind == "openapi":
        artifact_type = OpenApiYamlArtifact if is_yaml else OpenApiJsonArtifact
    else:
        artifact_type = JsonSchemaYamlArtifact if is_yaml else JsonSchemaJsonArtifact
    base = (display_name or kind).removesuffix(f".{kind}")
    return OutputInfo(f"{base}.{kind}{ext}", artifact_type)
