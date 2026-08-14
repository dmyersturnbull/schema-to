"""Tests for many-to-many routing between input documents and output artifacts.

Covers:
- Targeted: `Each` treats documents independently, one artifact each.
- Targeted: a transpiler sees all of its documents at once, so N can yield one.
- Targeted: documents are grouped by the first transpiler that accepts them.
- Targeted: an unaccepted document warns rather than failing the run.
- Integration: schema-map expansion feeds a per-schema target one schema at a time.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import override

import orjson
from tests._targets import transpiler_for

from schema_to.io.media_type import MediaTypes
from schema_to.io.memory import InMemoryDataSink
from schema_to.io.sink import JsonSchemaJsonArtifact
from schema_to.io.source import DataSource, JsonSchemaRawDoc, RawDoc, SchemaMapRawDoc
from schema_to.pipeline import Each, Flatten, Pipeline, Stage, Transpiler
from schema_to.result import Ok, Result
from schema_to.transpile.schema_map import SchemaMapExpander


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
    doc = SchemaMapRawDoc(
        doc_id="file:///catalog.yaml",
        content=orjson.dumps({"a-data": {"type": "object"}, "b-data": {"type": "string"}}),
        media_type=MediaTypes.json,
        display_name="catalog",
    )
    expand = Each(SchemaMapExpander()).then(Flatten())
    expanding = Transpiler(SchemaMapRawDoc, expand.then(Each(_OneArtifact()).then(Flatten())))
    sink = _run([doc], [expanding])
    assert {a.artifact_id for a in sink.artifacts} == {"a-data.json", "b-data.json"}


def test_expanded_document_ids_name_the_file_and_the_schema() -> None:
    """A diagnostic should be able to say which file *and* which schema."""
    doc = SchemaMapRawDoc(
        doc_id="file:///catalog.yaml",
        content=orjson.dumps({"a-data": {"type": "object"}}),
        media_type=MediaTypes.json,
    )
    expanded = SchemaMapExpander().apply(doc)
    assert isinstance(expanded, Ok)
    [virtual] = expanded.value
    assert virtual.doc_id == "file:///catalog.yaml#/a-data"
    assert virtual.base_uri == "file:///catalog.yaml"
    assert virtual.display_name == "a-data"


def test_sibling_refs_resolve_after_expansion() -> None:
    """`#/other` means the sibling in the *file*, which splitting would otherwise break."""
    doc = SchemaMapRawDoc(
        doc_id="file:///catalog.yaml",
        content=orjson.dumps(
            {
                "stamp": {"type": "string", "pattern": "^2"},
                "thing": {"type": "object", "properties": {"at": {"$ref": "#/stamp"}}},
            }
        ),
        media_type=MediaTypes.json,
        display_name="catalog",
    )
    transpiler = transpiler_for("pydantic", selects=SchemaMapRawDoc, schema_map=True)
    result = transpiler.transpile_all([doc])
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    assert {a.artifact_id for a in result.value} == {"stamp.py", "thing.py"}


def test_roots_expands_only_named_schemas_but_siblings_still_resolve() -> None:
    """`roots` narrows which named schemas become artifacts, not which ones can be $ref'd."""
    doc = SchemaMapRawDoc(
        doc_id="file:///catalog.yaml",
        content=orjson.dumps(
            {
                "stamp": {"type": "string", "pattern": "^2"},
                "thing": {"type": "object", "properties": {"at": {"$ref": "#/stamp"}}},
            }
        ),
        media_type=MediaTypes.json,
        display_name="catalog",
    )
    transpiler = transpiler_for(
        "pydantic", selects=SchemaMapRawDoc, schema_map=True, roots=frozenset({"thing"})
    )
    result = transpiler.transpile_all([doc])
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    # `stamp` was filtered out, so only `thing` becomes a virtual document — and so
    # only its module is written, even though `stamp` still resolved.
    assert {a.artifact_id for a in result.value} == {"thing.py"}


def test_expansion_without_a_resolver_seeds_nothing() -> None:
    """A target that never follows a `$ref` is given no resolver, and needs none."""
    doc = SchemaMapRawDoc(
        doc_id="file:///catalog.yaml",
        content=orjson.dumps({"a": {"type": "object"}}),
        media_type=MediaTypes.json,
    )
    assert isinstance(SchemaMapExpander().apply(doc), Ok)


def test_a_module_is_named_after_its_document() -> None:
    doc = JsonSchemaRawDoc(
        doc_id="test://a",
        content=orjson.dumps({"type": "object"}),
        media_type=MediaTypes.json,
        display_name="thing",
    )
    result = transpiler_for("pydantic").transpile_all([doc])
    assert isinstance(result, Ok)
    assert [a.artifact_id for a in result.value] == ["thing.py"]


def test_several_documents_are_named_apart() -> None:
    """They would otherwise overwrite one another in the sink."""
    docs = [
        JsonSchemaRawDoc(
            doc_id=f"test://{n}",
            content=orjson.dumps({"type": "object"}),
            media_type=MediaTypes.json,
            display_name=n,
        )
        for n in ("thing-one", "thing-two")
    ]
    result = transpiler_for("pydantic").transpile_all(docs)
    assert isinstance(result, Ok)
    assert [a.artifact_id for a in result.value] == ["thing_one.py", "thing_two.py"]
