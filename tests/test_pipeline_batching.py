"""Tests for many-to-many routing between input documents and output artifacts.

Covers:
- Targeted: `transpile_all` defaults to treating documents independently.
- Targeted: a transpiler sees all of its documents at once, so N can yield one.
- Targeted: documents are grouped by the first transpiler that accepts them.
- Targeted: an unaccepted document warns rather than failing the run.
- Integration: schema-map expansion feeds a per-schema target one schema at a time.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import override

import orjson

from schema_to.io.media_type import MediaTypes
from schema_to.io.memory import InMemoryDataSink
from schema_to.io.sink import JsonSchemaJsonArtifact
from schema_to.io.source import DataSource, JsonSchemaRawDoc, RawDoc, SchemaMapRawDoc
from schema_to.pipeline import Pipeline, Transpiler
from schema_to.result import Ok, Result
from schema_to.transpile.schema_map import SchemaMapExpandingTranspiler


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


@dataclass
class _PerDoc(Transpiler[JsonSchemaRawDoc, JsonSchemaJsonArtifact]):
    """One artifact per document, using the inherited `transpile_all`."""

    seen: list[int] = field(default_factory=list)

    @override
    def accepts(self, doc: RawDoc) -> bool:
        return isinstance(doc, JsonSchemaRawDoc)

    @override
    def transpile(self, doc: JsonSchemaRawDoc) -> Result[Sequence[JsonSchemaJsonArtifact]]:
        return Ok([JsonSchemaJsonArtifact(artifact_id=f"{doc.display_name}.json", content=b"{}")])


@dataclass
class _WholeSet(Transpiler[JsonSchemaRawDoc, JsonSchemaJsonArtifact]):
    """One artifact for the whole batch, overriding `transpile_all`."""

    batch_sizes: list[int] = field(default_factory=list)

    @override
    def accepts(self, doc: RawDoc) -> bool:
        return isinstance(doc, JsonSchemaRawDoc)

    @override
    def transpile(self, doc: JsonSchemaRawDoc) -> Result[Sequence[JsonSchemaJsonArtifact]]:
        return self.transpile_all([doc])

    @override
    def transpile_all(
        self, docs: Sequence[JsonSchemaRawDoc]
    ) -> Result[Sequence[JsonSchemaJsonArtifact]]:
        self.batch_sizes.append(len(docs))
        return Ok([JsonSchemaJsonArtifact(artifact_id="combined.json", content=b"{}")])


def _schema_doc(name: str) -> JsonSchemaRawDoc:
    return JsonSchemaRawDoc(
        doc_id=f"test://{name}",
        content=orjson.dumps({"type": "object"}),
        media_type=MediaTypes.json,
        display_name=name,
    )


def _run(docs: list[RawDoc], transpilers: list[Transpiler]) -> InMemoryDataSink:
    sink = InMemoryDataSink()
    result = Pipeline(sources=[_Listing(docs)], transpilers=transpilers, sink=sink).process()
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    return sink


def test_default_transpile_all_is_one_artifact_per_document() -> None:
    sink = _run([_schema_doc("a"), _schema_doc("b")], [_PerDoc()])
    assert {a.artifact_id for a in sink.artifacts} == {"a.json", "b.json"}


def test_a_transpiler_sees_its_whole_batch() -> None:
    """Three documents, one artifact — the case a per-document pipeline cannot express."""
    whole = _WholeSet()
    sink = _run([_schema_doc(n) for n in "abc"], [whole])
    assert whole.batch_sizes == [3]
    assert [a.artifact_id for a in sink.artifacts] == ["combined.json"]


def test_documents_go_to_the_first_accepting_transpiler() -> None:
    first, second = _WholeSet(), _WholeSet()
    _run([_schema_doc("a")], [first, second])
    assert first.batch_sizes == [1]
    assert second.batch_sizes == []


def test_unaccepted_documents_warn_without_failing() -> None:
    sink = InMemoryDataSink()
    doc = SchemaMapRawDoc(doc_id="test://map", content=b"{}", media_type=MediaTypes.json)
    result = Pipeline(sources=[_Listing([doc])], transpilers=[_PerDoc()], sink=sink).process()
    assert isinstance(result, Ok)
    assert [w.code for w in result.value.warnings] == ["no-transpiler"]
    assert not sink.artifacts


def test_schema_map_expands_to_one_document_per_named_schema() -> None:
    inner = _PerDoc()
    doc = SchemaMapRawDoc(
        doc_id="file:///catalog.yaml",
        content=orjson.dumps({"a-data": {"type": "object"}, "b-data": {"type": "string"}}),
        media_type=MediaTypes.json,
        display_name="catalog",
    )
    sink = _run([doc], [SchemaMapExpandingTranspiler(inner=inner)])
    assert {a.artifact_id for a in sink.artifacts} == {"a-data.json", "b-data.json"}


def test_expanded_document_ids_name_the_file_and_the_schema() -> None:
    """A diagnostic should be able to say which file *and* which schema."""
    expander = SchemaMapExpandingTranspiler(inner=_PerDoc())
    doc = SchemaMapRawDoc(
        doc_id="file:///catalog.yaml",
        content=orjson.dumps({"a-data": {"type": "object"}}),
        media_type=MediaTypes.json,
    )
    expanded = expander.expand(doc)
    assert isinstance(expanded, Ok)
    [virtual] = expanded.value
    assert virtual.doc_id == "file:///catalog.yaml#/a-data"
    assert virtual.base_uri == "file:///catalog.yaml"
    assert virtual.display_name == "a-data"
