"""Pipeline: stage algebra, transpiler contract, and orchestration.

## Stage algebra

A `Stage[A, B]` is a Kleisli arrow `A → Result[B]`.  Stages compose
left-to-right via `then`, short-circuiting on the first `Err`:

```python
parse = JsonSchemaParser()
resolve = JsonSchemaRefResolver()
full: Stage[RawDocument, JsonSchemaDocument] = parse.then(resolve)
```

## Transpiler contract

A `Transpiler` bundles four ordered stages for a specific `(CstT, AstT)` pair:

```
RawDocument
  →[parse]→   CstT
  →[resolve]→ CstT   (with $ref / $dynamicRef links resolved)
  →[generate]→ AstT
  →[reify]→   Sequence[OutputArtifact]
```

The type-erased `accepts(document)` predicate allows a `Pipeline` to dispatch
each source document to the correct `Transpiler` at runtime.

## Pipeline

`Pipeline` is immutable once constructed.  It drives the full process:

1. Iterate each `DataSource` to obtain `RawDocument`s.
2. Dispatch each document to the first `Transpiler` that `accepts` it.
3. Pass all `OutputArtifact`s to the shared `DataSink`.
4. Return a `Result[ProcessSummary]` with counts and accumulated warnings.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from schema_to._errors import TranspilationError, TranspilationWarning
from schema_to._result import Err, Ok, Result
from schema_to.ast._base import AstNode
from schema_to.cst._base import CstNode
from schema_to.io._sink import DataSink, OutputArtifact
from schema_to.io._source import DataSource, RawDocument

__all__ = [
    "DocumentParser",
    "Generator",
    "Pipeline",
    "ProcessSummary",
    "Reifier",
    "RefResolver",
    "Stage",
    "Transpiler",
    "TypedTranspiler",
]


# ---------------------------------------------------------------------------
# Stage algebra
# ---------------------------------------------------------------------------


class Stage[A, B](ABC):
    """A pure, composable transformation `A → Result[B]`.

    `Stage` forms a **category** under `then`-composition:

    - *Identity*: there exists a `Stage[A, A]` that wraps any value in `Ok`.
    - *Composition*: `s.then(t)` runs `s`, and on success feeds the result to `t`.
    - *Short-circuit*: an `Err` from `s` bypasses `t` and propagates unchanged.

    This matches the structure of a Kleisli category over the `Result` monad.
    """

    @abstractmethod
    def apply(self, input: A) -> Result[B]:
        """Run this stage, returning `Ok[B]` on success or `Err` on failure."""
        ...

    def then[C](self, other: Stage[B, C]) -> Stage[A, C]:
        """Compose `self` with `other`, running `other` only if `self` succeeds."""
        ...

    def map_error(
        self,
        f: Callable[[TranspilationError], TranspilationError],
    ) -> Stage[A, B]:
        """Transform every error produced by this stage without changing its type."""
        ...


# ---------------------------------------------------------------------------
# Specialised stage types
# ---------------------------------------------------------------------------


class DocumentParser[CstT: CstNode](Stage[RawDocument, CstT]):
    """Parses a `RawDocument` into a typed `CstT`.

    A parser is responsible for:
    1. Decoding bytes according to `RawDocument.media_type` (JSON or YAML).
    2. Constructing the full CST, preserving all source positions via `SourceRef`.

    Implementations are format-specific (`JsonSchemaParser`, `OpenApiParser`).
    """

    @abstractmethod
    def apply(self, input: RawDocument) -> Result[CstT]: ...

    @abstractmethod
    def supports(self, document: RawDocument) -> bool:
        """Return `True` if this parser can process the given document."""
        ...


class RefResolver[CstT: CstNode](Stage[CstT, CstT]):
    """Resolves `$ref` and `$dynamicRef` links within a CST.

    Resolution is performed against a registry of all CSTs produced so far in
    the pipeline run, enabling cross-document references.  The output CST is
    structurally identical to the input but with every `$ref` replaced by the
    inlined target schema (or a resolved reference node, depending on strategy).
    """

    @abstractmethod
    def apply(self, input: CstT) -> Result[CstT]: ...

    @abstractmethod
    def register(self, cst: CstT) -> None:
        """Add a parsed CST to the resolution registry."""
        ...


class Generator[CstT: CstNode, AstT: AstNode](Stage[CstT, AstT]):
    """Transforms a resolved `CstT` into a target-language `AstT`.

    The generator is the heart of the transpilation: it maps JSON Schema
    constructs (types, properties, applicators, …) onto the equivalent
    structures in the target language.  Keywords that cannot be represented
    emit `TranspilationWarning`s rather than hard errors where possible.
    """

    @abstractmethod
    def apply(self, input: CstT) -> Result[AstT]: ...

    @property
    @abstractmethod
    def warnings(self) -> Sequence[TranspilationWarning]:
        """Warnings accumulated across all `apply` calls since construction."""
        ...


class Reifier[AstT: AstNode](Stage[AstT, Sequence[OutputArtifact]]):
    """Serialises an `AstT` into one or more `OutputArtifact`s.

    A single AST root (e.g. `PythonModule`) typically produces one artifact,
    but a reifier may split output across multiple files (e.g. one `.py` per
    top-level class, or a `.sql` plus a `.ts` twin).
    """

    @abstractmethod
    def apply(self, input: AstT) -> Result[Sequence[OutputArtifact]]: ...


# ---------------------------------------------------------------------------
# Transpiler contract
# ---------------------------------------------------------------------------


class Transpiler(ABC):
    """Type-erased base for a complete single-document transpilation unit.

    A `Transpiler` accepts a `RawDocument` and produces zero or more
    `OutputArtifact`s.  The `Pipeline` holds a heterogeneous list of
    `Transpiler`s and dispatches each document to the first one that
    `accepts` it.

    Prefer subclassing `TypedTranspiler[CstT, AstT]` for new implementations;
    use `Transpiler` directly only when the CST or AST types are not statically
    known (e.g. a plugin loaded at runtime).
    """

    @abstractmethod
    def accepts(self, document: RawDocument) -> bool:
        """Return `True` if this transpiler can process `document`."""
        ...

    @abstractmethod
    def transpile(self, document: RawDocument) -> Result[Sequence[OutputArtifact]]:
        """Run the full parse → resolve → generate → reify pipeline."""
        ...


class TypedTranspiler[CstT: CstNode, AstT: AstNode](Transpiler):
    """A fully-typed transpiler with individually-overridable stage methods.

    Subclasses override `parse`, `resolve`, `generate`, and `reify`; the
    provided `transpile` implementation chains them via `Result.flat_map`.

    Example:

    ```python
    class JsonSchemaToSqlTranspiler(
        TypedTranspiler[JsonSchemaDocument, SqlScript]
    ):
        def accepts(self, doc):
            return doc.media_type == MediaType.json()

        def parse(self, doc):
            return JsonSchemaParser().apply(doc)

        def resolve(self, cst):
            return JsonSchemaRefResolver().apply(cst)

        def generate(self, cst):
            return JsonSchemaToSqlGenerator().apply(cst)

        def reify(self, ast):
            return SqlReifier().apply(ast)
    ```
    """

    @abstractmethod
    def parse(self, document: RawDocument) -> Result[CstT]:
        """Stage 1: decode bytes and construct the CST."""
        ...

    @abstractmethod
    def resolve(self, cst: CstT) -> Result[CstT]:
        """Stage 2: resolve `$ref` and validate against the meta-schema."""
        ...

    @abstractmethod
    def generate(self, cst: CstT) -> Result[AstT]:
        """Stage 3: transform the CST into a target-language AST."""
        ...

    @abstractmethod
    def reify(self, ast: AstT) -> Result[Sequence[OutputArtifact]]:
        """Stage 4: serialise the AST to output bytes."""
        ...

    def transpile(self, document: RawDocument) -> Result[Sequence[OutputArtifact]]:
        """Run all four stages sequentially, short-circuiting on any `Err`."""
        ...


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessSummary:
    """Summary of a completed `Pipeline.process()` run.

    Attributes:
        documents_read: Total number of `RawDocument`s consumed across all sources.
        artifacts_written: Total number of `OutputArtifact`s written to the sink.
        warnings: Non-fatal diagnostics accumulated during transpilation.
    """

    documents_read: int
    artifacts_written: int
    warnings: tuple[TranspilationWarning, ...] = ()


@dataclass
class Pipeline:
    """Immutable transpilation pipeline.

    A `Pipeline` is configured once — sources, transpilers, and sink — and
    executed by calling `process()`.  All state is local to a single `process()`
    call; the same `Pipeline` instance may be reused.

    Attributes:
        sources: Ordered list of `DataSource`s; each is iterated exactly once.
        transpilers: Ordered list of `Transpiler`s; each document is dispatched
            to the first transpiler whose `accepts()` returns `True`.
        sink: Destination for all `OutputArtifact`s produced during the run.

    Example:

    ```python
    pipeline = Pipeline(
        sources=[FileDataSource("schemas/")],
        transpilers=[JsonSchemaToSqlTranspiler(), JsonSchemaToTypeScriptTranspiler()],
        sink=DirectoryDataSink("out/"),
    )
    match pipeline.process():
        case Ok(summary):
            print(f"Wrote {summary.artifacts_written} artifacts.")
        case Err(errors):
            for err in errors:
                print(err.message)
    ```
    """

    sources: Sequence[DataSource]
    transpilers: Sequence[Transpiler]
    sink: DataSink

    def process(self) -> Result[ProcessSummary]:
        """Execute the pipeline: read all sources, transpile, write to sink.

        Returns `Ok[ProcessSummary]` if every document was transpiled without
        fatal errors, or `Err` with all accumulated errors otherwise.
        """
        ...
