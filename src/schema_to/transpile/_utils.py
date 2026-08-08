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
    from schema_to.io.source import RawDoc


class OutputInfo[A: Artifact](NamedTuple):
    filename: str
    artifact_type: type[A]


@overload
def choose_output(
    doc: RawDoc,
    output_media_type: MediaType | None,
    *,
    kind: Literal["openapi"],
    stem: str | None = None,
) -> OutputInfo[OpenApiArtifact]: ...


@overload
def choose_output(
    doc: RawDoc,
    output_media_type: MediaType | None,
    *,
    kind: Literal["schema"],
    stem: str | None = None,
) -> OutputInfo[JsonSchemaArtifact]: ...


def choose_output(
    doc: RawDoc,
    output_media_type: MediaType | None,
    *,
    kind: Literal["openapi", "schema"],
    stem: str | None = None,
) -> OutputInfo[OpenApiArtifact | JsonSchemaArtifact]:
    """Chooses a filename and the correct artifact type for JSON Schema or OpenAPI.

    Args:
        doc: The source document.
        output_media_type: A required media-type, currently required to be a YAML or JSON type.
          If `None`, uses YAML if `doc.doc_id.endswith(".yaml")`, otherwise uses JSON.
        kind: OpenAPI or JSON Schema.
        stem: Base filename, overriding the one derived from `doc`.
          Required when one source document yields several artifacts,
          which would otherwise share a filename.
    """
    # TODO: `writer` can support more, but this forces `.yaml` or `.json`.
    if output_media_type:
        is_yaml = output_media_type.type in {
            "application",
            "text",
        } and output_media_type.subtype.endswith(("+yaml", "yaml"))
    else:
        is_yaml = doc.doc_id.endswith(".yaml")
    ext = ".yaml" if is_yaml else ".json"
    artifact_type: type[Artifact]
    if kind == "openapi":
        artifact_type = OpenApiYamlArtifact if is_yaml else OpenApiJsonArtifact
    else:
        artifact_type = JsonSchemaYamlArtifact if is_yaml else JsonSchemaJsonArtifact
    base = (stem or doc.display_name or kind).removesuffix(f".{kind}")
    return OutputInfo(f"{base}.{kind}{ext}", artifact_type)
