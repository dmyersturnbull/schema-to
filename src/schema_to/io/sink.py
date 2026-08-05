"""Abstract data-sink types.

A `DataSink` is the write-side dual of `DataSource`:
It accepts `Artifact`s produced by the pipeline without exposing how or where they are stored.
Concrete implementations may write to a directory, accumulate in memory, upload to an object store, etc.
"""


from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from schema_to.io.media_type import MediaType, MediaTypes

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "Artifact",
    "DataSink",
    "JsonSchemaArtifact",
    "JsonSchemaJsonArtifact",
    "JsonSchemaYamlArtifact",
    "OpenApiArtifact",
    "OpenApiJsonArtifact",
    "OpenApiYamlArtifact",
    "PythonArtifact",
    "SqlArtifact",
]


@dataclass(frozen=True, slots=True)
class Artifact(ABC):  # ClassVar[media_type] acts as an abstract class attribute
    """A single output document ready to be written to a sink.

    Attributes:
        artifact_id: Suggested name for the artifact within the sink,
            typically a relative path such as `"migrations/001_users.sql"`.
        content: Serialised output bytes.
        media_type: Content type of the output; defined as a class variable on each subclass.
        source_ids: `source_id`s of the `RawDoc`s that contributed to this artifact, for traceability.
    """

    artifact_id: str
    content: bytes
    source_ids: tuple[str, ...] = ()
    media_type: ClassVar[MediaType]


@dataclass(frozen=True, slots=True)
class JsonSchemaArtifact(Artifact):
    """A JSON Schema output document (JSON or YAML encoding)."""


@dataclass(frozen=True, slots=True)
class JsonSchemaJsonArtifact(JsonSchemaArtifact):
    """A JSON Schema document serialised as JSON."""

    media_type: ClassVar[MediaType] = MediaTypes.json_schema


@dataclass(frozen=True, slots=True)
class JsonSchemaYamlArtifact(JsonSchemaArtifact):
    """A JSON Schema document serialised as YAML."""

    media_type: ClassVar[MediaType] = MediaTypes.json_schema_yaml


@dataclass(frozen=True, slots=True)
class OpenApiArtifact(Artifact):
    """An OpenAPI output document (JSON or YAML encoding)."""


@dataclass(frozen=True, slots=True)
class OpenApiJsonArtifact(OpenApiArtifact):
    """An OpenAPI document serialised as JSON."""

    media_type: ClassVar[MediaType] = MediaTypes.openapi


@dataclass(frozen=True, slots=True)
class OpenApiYamlArtifact(OpenApiArtifact):
    """An OpenAPI document serialised as YAML."""

    media_type: ClassVar[MediaType] = MediaTypes.openapi_yaml


@dataclass(frozen=True, slots=True)
class PythonArtifact(Artifact):
    """A `.py` file."""

    media_type: ClassVar[MediaType] = MediaTypes.python


@dataclass(frozen=True, slots=True)
class SqlArtifact(Artifact):
    """A `.sql` file."""

    media_type: ClassVar[MediaType] = MediaTypes.sql


class DataSink[O: Artifact](ABC):
    """An abstract destination for output artifacts produced by the pipeline."""

    @property
    @abstractmethod
    def sink_id(self) -> str:
        """Stable identifier for this sink (e.g. an output directory path or URL)."""
        raise NotImplementedError

    @abstractmethod
    def write(self, artifact: O) -> None:
        """Persist or collect a single output artifact."""
        raise NotImplementedError

    def write_all(self, artifacts: Iterable[O]) -> None:
        """Write every artifact from an iterable by delegating to `write`."""
        for artifact in artifacts:
            self.write(artifact)
