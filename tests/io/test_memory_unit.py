"""The in-memory source and sink, which stand in for the filesystem in a pipeline test."""

from tests.support.docs import json_schema_doc

from schema_to.io.memory import InMemoryDataSink, InMemoryDataSource
from schema_to.io.sink import JsonSchemaJsonArtifact
from schema_to.io.source import JsonSchemaRawDoc


def _artifact(name: str) -> JsonSchemaJsonArtifact:
    return JsonSchemaJsonArtifact(artifact_id=name, content=b"{}")


def test_a_source_yields_what_was_added() -> None:
    source: InMemoryDataSource[JsonSchemaRawDoc] = InMemoryDataSource()
    source.add(json_schema_doc({"type": "object"}, "test://a"))
    source.add(json_schema_doc({"type": "string"}, "test://b"))
    assert [d.doc_id for d in source.documents()] == ["test://a", "test://b"]


def test_an_empty_source_yields_nothing() -> None:
    assert list(InMemoryDataSource().documents()) == []


def test_a_source_names_itself() -> None:
    assert InMemoryDataSource().source_id == "memory"


def test_a_sink_keeps_what_it_is_written() -> None:
    sink: InMemoryDataSink[JsonSchemaJsonArtifact] = InMemoryDataSink()
    sink.write(_artifact("a.json"))
    assert [a.artifact_id for a in sink.artifacts] == ["a.json"]


def test_a_sink_writes_a_whole_iterable_in_order() -> None:
    sink: InMemoryDataSink[JsonSchemaJsonArtifact] = InMemoryDataSink()
    sink.write_all([_artifact("a.json"), _artifact("b.json")])
    assert [a.artifact_id for a in sink.artifacts] == ["a.json", "b.json"]


def test_a_sink_names_itself() -> None:
    assert InMemoryDataSink().sink_id == "memory"
