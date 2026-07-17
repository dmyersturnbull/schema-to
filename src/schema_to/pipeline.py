"""Pipeline: stage algebra, transpiler contract, and orchestration.

## Stage algebra

A `Stage[A, B]` is a Kleisli arrow `A → Result[B]`.
Stages compose left-to-right via `then`, short-circuiting on the first `Err`:

```python
parse = JsonSchemaParser()
resolve = JsonSchemaRefResolver()
full: Stage[RawDoc, JsonSchemaDocument] = parse.then(resolve)
```

## Transpiler contract

A `Transpiler` bundles four ordered stages for a specific `(CstT, AstT)` pair:

```
RawDoc
  →[parse]→   CstT
  →[resolve]→ CstT   (with $ref / $dynamicRef links resolved)
  →[generate]→ AstT
  →[reify]→   Sequence[Artifact]
```

The type-erased `accepts(document)` predicate allows a `Pipeline` to dispatch each source document to the correct `Transpiler` at runtime.

## Pipeline

`Pipeline` is immutable once constructed.

It drives the full process:

1. Iterate each `DataSource` to obtain `RawDoc`s.
2. Dispatch each document to the first `Transpiler` that `accepts` it.
3. Pass all `Artifact`s to the shared `DataSink`.
4. Return a `Result[ProcessSummary]` with counts and accumulated warnings.
"""


from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import override

from schema_to.ast.base import AstNode
from schema_to.cst.base import CstNode
from schema_to.errors import TranspilationError, TranspilationWarning
from schema_to.io.sink import Artifact, DataSink
from schema_to.io.source import DataSource, RawDoc
from schema_to.result import Err, Ok, Result

__all__ = [
    "DocParser",
    "Pipeline",
    "ProcessSummary",
    "RefResolver",
    "Reifier",
    "Stage",
    "Transformer",
    "Transpiler",
    "TypedTranspiler",
]


# ---------------------------------------------------------------------------
# Stage algebra
# ---------------------------------------------------------------------------


class Stage[X, Y](ABC):
    """A pure, composable transformation `A → Result[B]`.

    `Stage` forms a **category** under `then`-composition:

    - *Identity*: there exists a `Stage[A, A]` that wraps any value in `Ok`.
    - *Composition*: `s.then(t)` runs `s`, and on success feeds the result to `t`.
    - *Short-circuit*: an `Err` from `s` bypasses `t` and propagates unchanged.

    This matches the structure of a Kleisli category over the `Result` monad.
    """

    @abstractmethod
    def apply(self, /, input: X) -> Result[Y]:
        """Run this stage, returning `Ok[B]` on success or `Err` on failure."""
        raise NotImplementedError

    def then[Z](self, /, other: Stage[Y, Z]) -> Stage[X, Z]:
        """Compose `self` with `other`, running `other` only if `self` succeeds."""
        return _ComposedStage(self, other)

    def recover(self, /, f: Callable[[Err], Result[Y]]) -> Stage[X, Y]:
        """Attempt to recover an error from `self` using `recover`."""
        return _RecoverStage(self, f)

    def map_errors(self, /, f: Callable[[TranspilationError], TranspilationError]) -> Stage[X, Y]:
        """Transform every error produced by this stage without changing its type."""
        return _MappedErrorStage(self, f)


# `Stage.then` and `Stage.map_error` reference these helpers by name;
# the references are resolved at *call* time (not class-definition time),
# so it is safe to define the helpers here, after `Stage`.


class _ComposedStage[X, Y, Z](Stage[X, Z]):
    """Internal: result of `Stage.then()`."""

    def __init__(self, /, first: Stage[X, Y], second: Stage[Y, Z]) -> None:
        self.first = first
        self.second = second

    def apply(self, /, input: X) -> Result[Z]:
        r = self.first.apply(input)
        if isinstance(r, Err):
            return r
        return self.second.apply(r.value)


class _MappedErrorStage[X, Y](Stage[X, Y]):
    """Internal: result of `Stage.map_error()`."""

    def __init__(
        self, /, first: Stage[X, Y], if_error: Callable[[TranspilationError], TranspilationError]
    ) -> None:
        self.inner = first
        self.if_error = if_error

    def apply(self, /, input: X) -> Result[Y]:
        r = self.inner.apply(input)
        if isinstance(r, Err):
            return Err(tuple(self.if_error(e) for e in r.errors))
        return r


class _RecoverStage[X, Y](Stage[X, Y]):
    """Internal: result of `Stage.recover()`."""

    def __init__(self, /, first: Stage[X, Y], f: Callable[[Err], Result[Y]]) -> None:
        self.first = first
        self.f = f

    def apply(self, /, input: X) -> Result[Y]:
        r = self.first.apply(input)
        if isinstance(r, Err):
            return self.f(r)
        return r


# ---------------------------------------------------------------------------
# Specialised stage types
# ---------------------------------------------------------------------------


class DocParser[I: RawDoc, C: CstNode](Stage[I, C]):
    """Parses a `RawDoc` into a typed `CstT`.

    A parser is responsible for:
    1. Decoding bytes according to `RawDoc.media_type` (JSON or YAML).
    2. Constructing the full CST, preserving all source positions via `SourceRef`.

    Implementations are format-specific (`JsonSchemaParser`, `OpenApiParser`).
    """

    @abstractmethod
    def apply(self, input: I) -> Result[C]:
        raise NotImplementedError

    def accepts(self, doc: I) -> bool:  # ruff:ignore[unused-method-argument]  # Concrete subclasses might use it.
        """Return `True` if this parser can process `doc`."""
        return True


class RefResolver[C: CstNode](Stage[C, C]):
    """Resolves `$ref` and `$dynamicRef` links within a CST.

    Resolution is performed against a registry of all CSTs produced so far in the pipeline run,
    enabling cross-document references.
    The output CST is structurally identical to the input but with every `$ref` replaced by the inlined target schema
    (or a resolved reference node, depending on strategy).
    """

    @abstractmethod
    def apply(self, input: C) -> Result[C]:
        raise NotImplementedError

    @abstractmethod
    def register(self, cst: C) -> None:
        """Add a parsed CST to the resolution registry."""
        raise NotImplementedError


class Transformer[C: CstNode, A: AstNode](Stage[C, A]):
    """Transforms a resolved `CstT` into a target-language `AstT`.

    The generator is the heart of the transpilation: it maps JSON Schema
    constructs (types, properties, applicators, …) onto the equivalent
    structures in the target language.  Keywords that cannot be represented
    emit `TranspilationWarning`s rather than hard errors where possible.
    """

    @abstractmethod
    def apply(self, input: C) -> Result[A]:
        raise NotImplementedError

    @property
    @abstractmethod
    def warnings(self) -> Sequence[TranspilationWarning]:
        """Warnings accumulated across all `apply` calls since construction."""
        raise NotImplementedError


class Reifier[A: AstNode, O: Artifact](Stage[A, Sequence[O]]):
    """Serialises an `AstT` into one or more `Artifact`s.

    A single AST root (e.g. `PythonModule`) typically produces one artifact,
    but a reifier may split output across multiple files (e.g. one `.py` per
    top-level class, or a `.sql` plus a `.ts` twin).
    """

    @abstractmethod
    def apply(self, input: A) -> Result[Sequence[O]]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Transpiler contract
# ---------------------------------------------------------------------------


class Transpiler[I: RawDoc, O: Artifact](ABC):
    """Type-erased base for a complete single-document transpilation unit.

    Prefer subclassing `TypedTranspiler[CstT, AstT]` for new implementations;
    use `Transpiler` directly only when the CST or AST types are not statically known
    (e.g. a plugin loaded at runtime).
    """

    @abstractmethod
    def accepts(self, doc: I) -> bool:
        """Return `True` if this transpiler can process `doc`."""
        raise NotImplementedError

    @abstractmethod
    def transpile(self, doc: I) -> Result[Sequence[O]]:
        """Run the full parse → resolve → generate → reify pipeline."""
        raise NotImplementedError

    @property
    def warnings(self) -> Sequence[TranspilationWarning]:
        """Non-fatal diagnostics from the most recent `transpile` call."""
        return ()


class TypedTranspiler[I: RawDoc, O: Artifact, C: CstNode, A: AstNode](Transpiler[I, O]):
    """A fully typed transpiler with individually-overridable stage methods.

    Subclasses override `parse`, `resolve`, `generate`, and `reify`; the
    provided `transpile` implementation chains them via `Result.flat_map`.
    """

    @abstractmethod
    def parse(self, doc: I) -> Result[C]:
        """Stage 1: decode bytes and construct the CST."""
        raise NotImplementedError

    @abstractmethod
    def resolve(self, cst: C) -> Result[C]:
        """Stage 2: resolve `$ref` and validate against the meta-schema."""
        raise NotImplementedError

    @abstractmethod
    def generate(self, cst: C) -> Result[A]:
        """Stage 3: transform the CST into a target-language AST."""
        raise NotImplementedError

    @abstractmethod
    def reify(self, ast: A) -> Result[Sequence[O]]:
        """Stage 4: serialise the AST to output bytes."""
        raise NotImplementedError

    @override
    def transpile(self, doc: I) -> Result[Sequence[O]]:
        """Run all four stages sequentially."""
        doc: Result[C] = self.parse(doc)
        if isinstance(doc, Err):
            return doc
        cst: Result[C] = self.resolve(doc.value)
        if isinstance(cst, Err):
            return cst
        ast: Result[A] = self.generate(cst.value)
        if isinstance(ast, Err):
            return ast
        return self.reify(ast.value)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProcessSummary:
    """Summary of a completed `Pipeline.process()` run.

    Attributes:
        docs_used: `doc_id`s of `RawDoc`s that a transpiler consumed.
        artifacts_written: `artifact_id`s of `Artifact`s written to the sink.
        warnings: Non-fatal diagnostics accumulated during transpilation.
    """

    docs_used: list[str]
    artifacts_written: list[str]
    warnings: tuple[TranspilationWarning, ...] = ()


@dataclass(slots=True)
class _PipelineHelper:
    """Internal helper to track pipeline progress for `ProcessSummary`."""

    docs_used: list[str] = field(default_factory=list, init=False)
    artifacts_written: list[str] = field(default_factory=list, init=False)
    errors: list[TranspilationError] = field(default_factory=list, init=False)
    warnings: list[TranspilationWarning] = field(default_factory=list, init=False)


@dataclass(frozen=True, slots=True)
class Pipeline[I: RawDoc, O: Artifact]:
    """Immutable transpilation pipeline.

    A `Pipeline` is configured once — sources, transpilers, and sink — and
    executed by calling `process()`.  All state is local to a single `process()`
    call; the same `Pipeline` instance may be reused.

    Holds a heterogeneous list of `Transpiler`s
    and dispatches each document to the first one that `accepts` it.

    Attributes:
        sources: Ordered list of `DataSource`s; each is iterated exactly once.
        transpilers: Ordered list of `Transpiler`s; each document is dispatched
            to the first transpiler whose `accepts()` returns `True`.
        sink: Destination for all `Artifact`s produced during the run.

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

    sources: Sequence[DataSource[I]]
    # TODO: Each Transpiler in `transpilers` will have different generic args. Is that compatible with the generic args on `Pipeline`?
    transpilers: Sequence[Transpiler[I, O]]
    sink: DataSink[O]

    def process(self) -> Result[ProcessSummary]:
        """Execute the pipeline: read all sources, transpile, write to sink.

        Returns `Ok[ProcessSummary]` if every document was transpiled without
        fatal errors, or `Err` with all accumulated errors otherwise.
        """
        helper = _PipelineHelper()
        for source in self.sources:
            for document in source.documents():
                self._next_doc(document, helper)
        if helper.errors:
            return Err(tuple(helper.errors))
        return Ok(
            ProcessSummary(
                docs_used=helper.docs_used,
                artifacts_written=helper.artifacts_written,
                warnings=tuple(helper.warnings),
            )
        )

    def _next_doc(self, document: I, helper: _PipelineHelper) -> None:
        transpiler = next((t for t in self.transpilers if t.accepts(document)), None)
        if transpiler:
            helper.docs_used.append(document.doc_id)
            self._transpile_doc(document, helper, transpiler)
        else:
            helper.warnings.append(
                TranspilationWarning(
                    f"No transpiler accepts {document.doc_id!r}; skipping.", code="no-transpiler"
                )
            )

    def _transpile_doc(
        self, document: I, helper: _PipelineHelper, transpiler: Transpiler[I, O]
    ) -> None:
        result = transpiler.transpile(document)
        helper.warnings.extend(transpiler.warnings)
        match result:
            case Err(errs):
                helper.errors += errs
            case Ok(val):
                for artifact in val:
                    helper.artifacts_written.append(artifact.artifact_id)
                    self.sink.write(artifact)
