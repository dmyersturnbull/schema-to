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
from dataclasses import dataclass

from schema_to.ast.base import AstNode
from schema_to.cst.base import CstNode
from schema_to.errors import TranspilationError, TranspilationWarning
from schema_to.io.sink import DataSink, OutputArtifact
from schema_to.io.source import DataSource, RawDocument
from schema_to.result import Err, Ok, Result

__all__ = [
    "DocumentParser",
    "Generator",
    "Pipeline",
    "ProcessSummary",
    "RefResolver",
    "Reifier",
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
    def apply(self, /, input: A) -> Result[B]:
        """Run this stage, returning `Ok[B]` on success or `Err` on failure."""
        raise NotImplementedError

    def then[C](self, /, other: Stage[B, C]) -> Stage[A, C]:
        """Compose `self` with `other`, running `other` only if `self` succeeds."""
        return _ComposedStage(self, other)

    def recover(self, /, f: Callable[[Err], A]) -> Stage[A, B]:
        """Attempt to recover an error from `self` using `recover`."""
        return _RecoverStage(self, f)

    def map_errors(self, /, f: Callable[[TranspilationError], TranspilationError]) -> Stage[A, B]:
        """Transform every error produced by this stage without changing its type."""
        return _MappedErrorStage(self, f)


# `Stage.then` and `Stage.map_error` reference these helpers by name; the
# references are resolved at *call* time (not class-definition time), so it is
# safe to define the helpers here, after `Stage`.


class _ComposedStage[A, B, C](Stage):
    """Internal: result of `Stage.then()`."""

    def __init__(self, /, first: Stage[A, B], second: Stage[B, C]) -> None:
        self.first = first
        self.second = second

    def apply(self, /, input: A) -> C:
        r = self.first.apply(input)
        if isinstance(r, Err):
            return r
        return self.second.apply(r.value)


class _MappedErrorStage[A, B](Stage):
    """Internal: result of `Stage.map_error()`."""

    def __init__(self, /, first: Stage[A, B], if_error: Callable[[TranspilationError], TranspilationError]) -> None:
        self.inner = first
        self.if_error = if_error

    def apply(self, /, input: A) -> B:
        r = self.inner.apply(input)
        if isinstance(r, Err):
            return Err(tuple(self.if_error(e) for e in r.errors))
        return r


class _RecoverStage[A, B](Stage):
    """Internal: result of `Stage.recover()`."""

    def __init__(self, /, first: Stage[A, B], f: Callable[Err, B]) -> None:
        self.first = first
        self.f = f

    def apply(self, /, input: A) -> B:
        r = self.first.apply(input)
        if isinstance(r, Err):
            return self.f.apply(r)
        return r


# ---------------------------------------------------------------------------
# Specialised stage types
# ---------------------------------------------------------------------------


class DocumentParser[T : RawDocument, CstT: CstNode](Stage[T, CstT]):
    """Parses a `RawDocument` into a typed `CstT`.

    A parser is responsible for:
    1. Decoding bytes according to `RawDocument.media_type` (JSON or YAML).
    2. Constructing the full CST, preserving all source positions via `SourceRef`.

    Implementations are format-specific (`JsonSchemaParser`, `OpenApiParser`).
    """

    @abstractmethod
    def apply(self, input: T) -> Result[CstT]:
        raise NotImplementedError

    @abstractmethod
    def accepts(self, document: T) -> bool:
        """Return `True` if this parser can process the given document."""
        raise NotImplementedError


class RefResolver[CstT: CstNode](Stage[CstT, CstT]):
    """Resolves `$ref` and `$dynamicRef` links within a CST.

    Resolution is performed against a registry of all CSTs produced so far in
    the pipeline run, enabling cross-document references.  The output CST is
    structurally identical to the input but with every `$ref` replaced by the
    inlined target schema (or a resolved reference node, depending on strategy).
    """

    @abstractmethod
    def apply(self, input: CstT) -> Result[CstT]:
        raise NotImplementedError

    @abstractmethod
    def register(self, cst: CstT) -> None:
        """Add a parsed CST to the resolution registry."""
        raise NotImplementedError


class Generator[CstT: CstNode, AstT: AstNode](Stage[CstT, AstT]):
    """Transforms a resolved `CstT` into a target-language `AstT`.

    The generator is the heart of the transpilation: it maps JSON Schema
    constructs (types, properties, applicators, …) onto the equivalent
    structures in the target language.  Keywords that cannot be represented
    emit `TranspilationWarning`s rather than hard errors where possible.
    """

    @abstractmethod
    def apply(self, input: CstT) -> Result[AstT]:
        raise NotImplementedError

    @property
    @abstractmethod
    def warnings(self) -> Sequence[TranspilationWarning]:
        """Warnings accumulated across all `apply` calls since construction."""
        raise NotImplementedError


class Reifier[AstT: AstNode](Stage[AstT, Sequence[OutputArtifact]]):
    """Serialises an `AstT` into one or more `OutputArtifact`s.

    A single AST root (e.g. `PythonModule`) typically produces one artifact,
    but a reifier may split output across multiple files (e.g. one `.py` per
    top-level class, or a `.sql` plus a `.ts` twin).
    """

    @abstractmethod
    def apply(self, input: AstT) -> Result[Sequence[OutputArtifact]]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Transpiler contract
# ---------------------------------------------------------------------------


class Transpiler[T : RawDocument](ABC):
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
    def accepts(self, document: T) -> bool:
        """Return `True` if this transpiler can process `document`."""
        raise NotImplementedError

    @abstractmethod
    def transpile(self, document: T) -> Result[Sequence[OutputArtifact]]:
        """Run the full parse → resolve → generate → reify pipeline."""
        raise NotImplementedError

    @property
    def warnings(self) -> Sequence[TranspilationWarning]:
        """Non-fatal diagnostics from the most recent `transpile` call."""
        return ()


class TypedTranspiler[T : RawDocument, CstT: CstNode, AstT: AstNode](Transpiler):
    """A fully typed transpiler with individually-overridable stage methods.

    Subclasses override `parse`, `resolve`, `generate`, and `reify`; the
    provided `transpile` implementation chains them via `Result.flat_map`.

    Example:
        ```python
        class JsonSchemaToSqlTranspiler(TypedTranspiler[RawJsonSchemaDocument, JsonSchemaDocument, SqlScript]):
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
    def parse(self, document: T) -> Result[CstT]:
        """Stage 1: decode bytes and construct the CST."""
        raise NotImplementedError

    @abstractmethod
    def resolve(self, cst: CstT) -> Result[CstT]:
        """Stage 2: resolve `$ref` and validate against the meta-schema."""
        raise NotImplementedError

    @abstractmethod
    def generate(self, cst: CstT) -> Result[AstT]:
        """Stage 3: transform the CST into a target-language AST."""
        raise NotImplementedError

    @abstractmethod
    def reify(self, ast: AstT) -> Result[Sequence[OutputArtifact]]:
        """Stage 4: serialise the AST to output bytes."""
        raise NotImplementedError

    def transpile(self, document: T) -> Result[Sequence[OutputArtifact]]:
        """Run all four stages sequentially, short-circuiting on any `Err`."""
        r1 = self.parse(document)
        if isinstance(r1, Err):
            return r1
        r2 = self.resolve(r1.value)
        if isinstance(r2, Err):
            return r2
        r3 = self.generate(r2.value)
        if isinstance(r3, Err):
            return r3
        return self.reify(r3.value)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
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
class Pipeline[T : RawDocument]:
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
            sources=[DirectoryDataSource("schemas/")],
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

    sources: Sequence[DataSource[T]]
    transpilers: Sequence[Transpiler]
    sink: DataSink

    def process(self) -> Result[ProcessSummary]:
        """Execute the pipeline: read all sources, transpile, write to sink.

        Returns `Ok[ProcessSummary]` if every document was transpiled without
        fatal errors, or `Err` with all accumulated errors otherwise.
        """
        documents_read = 0
        artifacts_written = 0
        errors: list[TranspilationError] = []
        warnings: list[TranspilationWarning] = []

        for source in self.sources:
            for document in source.documents():
                documents_read += 1
                transpiler = next((t for t in self.transpilers if t.accepts(document)), None)
                if transpiler is None:
                    warnings.append(
                        TranspilationWarning(
                            f"No transpiler accepts {document.source_id!r}; skipping.",
                            code="no-transpiler",
                        )
                    )
                    continue
                result = transpiler.transpile(document)
                warnings.extend(transpiler.warnings)
                if isinstance(result, Err):
                    errors.extend(result.errors)
                    continue
                for artifact in result.value:
                    self.sink.write(artifact)
                    artifacts_written += 1

        if errors:
            return Err(tuple(errors))
        return Ok(
            ProcessSummary(
                documents_read=documents_read,
                artifacts_written=artifacts_written,
                warnings=tuple(warnings),
            )
        )
