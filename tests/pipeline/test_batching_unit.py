"""Many-to-many routing between input documents and output artifacts.

`Each` lifts a per-document chain over a batch, so N documents give N artifacts;
a transpiler that takes the batch directly can turn N into one.
Documents are grouped by the first transpiler that accepts them,
and one that nothing accepts warns rather than failing the run.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import override

from tests.support.docs import json_schema_doc, schema_map_doc
from tests.support.drive import Route

from schema_to.io.media_type import MediaTypes
from schema_to.io.memory import InMemoryDataSink
from schema_to.io.sink import JsonSchemaJsonArtifact
from schema_to.io.source import DataSource, JsonSchemaRawDoc, RawDoc, SchemaMapRawDoc
from schema_to.pipeline import Each, Flatten, Pipeline, Stage, Transpiler
from schema_to.result import Ok, Result
from schema_to.transpile.schema_map import SchemaMapExpander

_PYDANTIC_MAP = Route("pydantic", SchemaMapRawDoc, schema_map=True)


@dataclass
class _Listing(DataSource):
    """A source yielding documents handed to it."""

    docs: list[RawDoc]

    @property
    @override
    def source_id(self) -> str:
        return "test://source"

    @override
    def documents(self) -> Iterator[RawDoc]:
        return iter(self.docs)


class _OneArtifact(Stage[JsonSchemaRawDoc, Sequence[JsonSchemaJsonArtifact]]):
    """One artifact per document, named after it."""

    @override
    def apply(self, input: JsonSchemaRawDoc) -> Result[Sequence[JsonSchemaJsonArtifact]]:
        return Ok([JsonSchemaJsonArtifact(artifact_id=f"{input.display_name}.json", content=b"{}")])


@dataclass
class _WholeSet(Stage[Sequence[JsonSchemaRawDoc], Sequence[JsonSchemaJsonArtifact]]):
    """One artifact for the whole batch, recording every batch size it was given."""

    batch_sizes: list[int] = field(default_factory=list)

    @override
    def apply(self, input: Sequence[JsonSchemaRawDoc]) -> Result[Sequence[JsonSchemaJsonArtifact]]:
        self.batch_sizes.append(len(input))
        return Ok([JsonSchemaJsonArtifact(artifact_id="combined.json", content=b"{}")])


def _per_doc() -> Transpiler[JsonSchemaRawDoc, JsonSchemaJsonArtifact]:
    return Transpiler(JsonSchemaRawDoc, Each(_OneArtifact()).then(Flatten()))


def _schema_doc(name: str) -> JsonSchemaRawDoc:
    return json_schema_doc({"type": "object"}, f"test://{name}", display_name=name)


def _run(docs: list[RawDoc], transpilers: list[Transpiler]) -> InMemoryDataSink:
    sink = InMemoryDataSink()
    result = Pipeline(sources=[_Listing(docs)], transpilers=transpilers, sink=sink).process()
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    return sink


def test_each_is_one_artifact_per_document() -> None:
    sink = _run([_schema_doc("a"), _schema_doc("b")], [_per_doc()])
    assert {a.artifact_id for a in sink.artifacts} == {"a.json", "b.json"}


def test_a_transpiler_sees_its_whole_batch() -> None:
    """Three documents, one artifact — the case a per-document pipeline cannot express."""
    whole = _WholeSet()
    sink = _run([_schema_doc(n) for n in "abc"], [Transpiler(JsonSchemaRawDoc, whole)])
    assert whole.batch_sizes == [3]
    assert [a.artifact_id for a in sink.artifacts] == ["combined.json"]


def test_documents_go_to_the_first_accepting_transpiler() -> None:
    first, second = _WholeSet(), _WholeSet()
    _run(
        [_schema_doc("a")],
        [Transpiler(JsonSchemaRawDoc, first), Transpiler(JsonSchemaRawDoc, second)],
    )
    assert first.batch_sizes == [1]
    assert second.batch_sizes == []


def test_unaccepted_documents_warn_without_failing() -> None:
    sink = InMemoryDataSink()
    doc = SchemaMapRawDoc(doc_id="test://map", content=b"{}", media_type=MediaTypes.json)
    result = Pipeline(sources=[_Listing([doc])], transpilers=[_per_doc()], sink=sink).process()
    assert isinstance(result, Ok)
    assert [w.code for w in result.value.warnings] == ["no-transpiler"]
    assert not sink.artifacts


def test_schema_map_expands_to_one_document_per_named_schema() -> None:
    doc = schema_map_doc({"a-data": {"type": "object"}, "b-data": {"type": "string"}}, "catalog")
    expand = Each(SchemaMapExpander()).then(Flatten())
    expanding = Transpiler(SchemaMapRawDoc, expand.then(Each(_OneArtifact()).then(Flatten())))
    sink = _run([doc], [expanding])
    assert {a.artifact_id for a in sink.artifacts} == {"a-data.json", "b-data.json"}
