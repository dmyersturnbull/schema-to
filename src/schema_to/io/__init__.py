"""I/O abstractions: `DataSource`, `DataSink`, and their supporting types."""

from schema_to.io._file import FileDataSink, FileDataSource
from schema_to.io._memory import InMemoryDataSink, InMemoryDataSource
from schema_to.io._sink import DataSink, OutputArtifact
from schema_to.io._source import DataSource, MediaType, MediaTypeParam, MediaTypes, RawDocument

__all__ = [
    "DataSink",
    "DataSource",
    "FileDataSink",
    "FileDataSource",
    "InMemoryDataSink",
    "InMemoryDataSource",
    "MediaType",
    "MediaTypeParam",
    "MediaTypes",
    "OutputArtifact",
    "RawDocument",
]
