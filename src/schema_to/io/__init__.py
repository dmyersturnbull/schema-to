"""I/O abstractions: `DataSource`, `DataSink`, and their supporting types."""

from schema_to.io._sink import DataSink, OutputArtifact
from schema_to.io._source import DataSource, MediaType, RawDocument

__all__ = ["DataSink", "DataSource", "MediaType", "OutputArtifact", "RawDocument"]
