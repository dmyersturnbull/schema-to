"""Pipeline: stage algebra, transpiler contract, and orchestration.

## Stage algebra

A `Stage[A, B]` is a Kleisli arrow `A → Result[B]`.
Stages compose left-to-right via `then`, short-circuiting on the first `Err`:

```python
parse = JsonSchemaParser()
resolve = JsonSchemaRefResolver()
full: Stage[RawDoc, JsonSchemaDocument] = parse.then(resolve)
```

`Each` and `Flatten` lift a stage over one document to a stage over a batch of them,
so a whole target is one composed `Stage`, not a class that re-implements the chaining:

```python
batch: Stage[Sequence[RawDoc], Sequence[Artifact]] = Each(full.then(gen).then(reify)).then(
    Flatten()
)
```

## Transpiler

A `Transpiler` is a value, not a base class: it binds a `RawDoc` subclass to the batch
stage that handles documents of that type.
`Pipeline` uses the binding to dispatch each source document to the right stage at runtime.
Building one is the composition root's job — see `schema_to.transpile.factory`.

```
Sequence[RawDoc]
  →[parse]→   CST
  →[resolve]→ CST   (with $ref / $dynamicRef links resolved)
  →[generate]→ AST
  →[reify]→   Sequence[Artifact]
```

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
from typing import final, override

from schema_to.ast.base import AstNode
from schema_to.cst.base import CstNode
from schema_to.errors import TranspilationError, TranspilationWarning
from schema_to.io.sink import Artifact, DataSink
from schema_to.io.source import DataSource, RawDoc
from schema_to.result import Err, Ok, Result

__all__ = [
    "Append",
    "DocParser",
    "Each",
    "Expander",
    "Flatten",
    "Pipeline",
    "ProcessSummary",
    "Reducer",
    "RefResolver",
    "Reifier",
    "Stage",
    "Transformer",
    "Transpiler",
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

    Errors are fatal and short-circuit; warnings are not. Both travel inside the
    `Result` itself — a stage that diagnoses something without failing raises it as a
    warning on the `Result` it returns, and composition carries every warning forward,
    so a caller reads the whole chain's diagnostics off the final `Result` alone,
    without needing to keep the `Stage` around afterward.
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

    @override
    def apply(self, /, input: X) -> Result[Z]:
        r = self.first.apply(input)
        if isinstance(r, Err):
            return r
        return self.second.apply(r.value).with_warnings(r.warnings)


class _MappedErrorStage[X, Y](Stage[X, Y]):
    """Internal: result of `Stage.map_error()`."""

    def __init__(
        self, /, first: Stage[X, Y], if_error: Callable[[TranspilationError], TranspilationError]
    ) -> None:
        self.inner = first
        self.if_error = if_error

    @override
    def apply(self, /, input: X) -> Result[Y]:
        r = self.inner.apply(input)
        if isinstance(r, Err):
            return Err(tuple(self.if_error(e) for e in r.errors), warnings=r.warnings)
        return r


class _RecoverStage[X, Y](Stage[X, Y]):
    """Internal: result of `Stage.recover()`."""

    def __init__(self, /, first: Stage[X, Y], f: Callable[[Err], Result[Y]]) -> None:
        self.first = first
        self.f = f

    @override
    def apply(self, /, input: X) -> Result[Y]:
        r = self.first.apply(input)
        if isinstance(r, Err):
            return self.f(r).with_warnings(r.warnings)
        return r


class _RegisteringStage[C: CstNode](Stage[C, C]):
    """Internal: result of `RefResolver.registering()`."""

    def __init__(self, /, resolver: RefResolver[C]) -> None:
        self.resolver = resolver

    @override
    def apply(self, /, input: C) -> Result[C]:
        self.resolver.register(input)
        return Ok(input)


# ---------------------------------------------------------------------------
# Cardinality kinds
# ---------------------------------------------------------------------------


class Expander[X, Y](Stage[X, Sequence[Y]]):
    """A stage that produces many outputs from one input.

    The dual of `Reducer`, and the Kleisli arrow of the list monad: `X → Result[[Y]]`.
    `Each(e).then(Flatten())` lifts one over a batch, mapping and then joining.

    Splitting a schema-map file into its named schemas is one, and so is reifying an
    AST root into the several files it describes — `Reifier` is the specialisation of
    this kind whose outputs are artifacts.
    """

    @abstractmethod
    def apply(self, input: X) -> Result[Sequence[Y]]:
        raise NotImplementedError


class Reducer[X, Y](Stage[Sequence[X], Y]):
    """A stage that produces one output from many inputs.

    The dual of `Expander`, and a fold over the batch.  It is the only kind that can
    express an output the whole set determines: a migration whose foreign keys cannot
    be ordered until every table is known has no per-document formulation.
    """

    @abstractmethod
    def apply(self, input: Sequence[X]) -> Result[Y]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Batch combinators
# ---------------------------------------------------------------------------


@final
@dataclass(frozen=True, slots=True)
class Each[X, Y](Stage[Sequence[X], Sequence[Y]]):
    """Runs `inner` over every item of a batch, accumulating errors across all of them.

    One bad document should not hide the rest, so every item is attempted and the
    failures are reported together rather than at the first one.
    Warnings accumulate the same way, across every item's `Result`.
    """

    inner: Stage[X, Y]

    @override
    def apply(self, /, input: Sequence[X]) -> Result[Sequence[Y]]:
        values: list[Y] = []
        errors: list[TranspilationError] = []
        warnings: list[TranspilationWarning] = []
        for item in input:
            result = self.inner.apply(item)
            warnings.extend(result.warnings)
            if isinstance(result, Err):
                errors.extend(result.errors)
            else:
                values.append(result.value)
        if errors:
            return Err(tuple(errors), warnings=tuple(warnings))
        return Ok(values, warnings=tuple(warnings))


@final
@dataclass(frozen=True, slots=True)
class Flatten[Y](Reducer[Sequence[Y], Sequence[Y]]):
    """Concatenates the batches produced by `Each` over an `Expander`.

    `Each(e)` where `e` is an `Expander` gives a batch of batches; this is the join
    that flattens it back to one, so `Each(e).then(Flatten())` is an expansion lifted
    over a whole batch.
    """

    @override
    def apply(self, /, input: Sequence[Sequence[Y]]) -> Result[Sequence[Y]]:
        return Ok([item for batch in input for item in batch])


@final
@dataclass(frozen=True, slots=True)
class Append[Y](Stage[Sequence[Y], Sequence[Y]]):
    """Appends whatever `supply` returns to what the preceding stage produced.

    The supplier is called once per batch, which is what makes it the right place for
    an output that belongs to the run rather than to any one document — a support
    module a generated application imports, say.

    Attributes:
        supply: Called after the batch is built; typically a bound method of the
            component that knows what extra outputs it needs.
    """

    supply: Callable[[], Sequence[Y]]

    @override
    def apply(self, /, input: Sequence[Y]) -> Result[Sequence[Y]]:
        return Ok([*input, *self.supply()])


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

    def accepts(self, doc: I) -> bool:  # ruff:ignore[unused-method-argument]  # Subclasses might use it.
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

    def registering(self) -> Stage[C, C]:
        """Return a stage that registers each document and passes it through unchanged.

        Registration and validation are separate passes because a reference may point
        from any document in a set into any other: checking one before the last is
        registered would fail on a forward reference.  Splitting them into two stages
        is what lets a caller write `Each(r.registering()).then(Each(r))` and get the
        two passes in the right order, without a class that hard-codes both.
        """
        return _RegisteringStage(self)


class Transformer[C: CstNode, A: AstNode](Stage[C, A]):
    """Transforms a resolved `CstT` into a target-language `AstT`.

    The generator is the heart of the transpilation:
    It maps JSON Schema constructs (types, properties, applicators, …)
    onto the equivalent structures in the target language.
    Keywords that cannot be represented emit `TranspilationWarning`s on the returned `Result`
    rather than hard errors where possible.
    """

    @abstractmethod
    def apply(self, input: C) -> Result[A]:
        raise NotImplementedError


class Reifier[X, O: Artifact](Expander[X, O]):
    """Serialises a generated root node into one or more `Artifact`s.

    The input is normally an AST root (`PythonModule`, `SqlScript`),
    but a target that re-emits its input — a pass-through — reifies a CST document instead.

    A single root typically produces one artifact,
    but a reifier may split output across multiple files
    (e.g. one `.py` per module of a package, or a `.sql` plus a `.ts` twin),
    which is why this is an `Expander` rather than a plain one-to-one stage.
    """

    @abstractmethod
    def apply(self, input: X) -> Result[Sequence[O]]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Transpiler
# ---------------------------------------------------------------------------


@final
@dataclass(frozen=True, slots=True)
class Transpiler[I: RawDoc, O: Artifact]:
    """A document type bound to the batch stage that transpiles documents of that type.

    A transpiler is a value, not an abstraction to subclass: everything specific to a
    target lives in the `Stage` it holds, and everything specific to *routing* lives in
    `selects`.  Assembling the two is the composition root's job — see
    `schema_to.transpile.factory.TranspilerRouter`.

    Documents and artifacts are related many-to-many, not one-to-one.  One document
    may yield several artifacts (a schema per `components/schemas` entry), and several
    documents may yield one (a migration for a whole directory of schemas, whose
    foreign keys cannot be ordered until every table is known).  The stage takes the
    whole batch, so which of those a target does is the stage's own business:
    `Each(...)` treats documents independently, and a batch-native stage does not.

    Attributes:
        selects: The `RawDoc` subclass this transpiler consumes.
        stage: Transforms a batch of accepted documents into the artifacts to write.
    """

    selects: type[I]
    stage: Stage[Sequence[I], Sequence[O]]

    def accepts(self, doc: RawDoc) -> bool:
        """Return `True` if this transpiler can process `doc`."""
        return isinstance(doc, self.selects)

    def transpile(self, doc: I) -> Result[Sequence[O]]:
        """Transpile a single document, as a batch of one."""
        return self.transpile_all([doc])

    def transpile_all(self, docs: Sequence[I]) -> Result[Sequence[O]]:
        """Transpile every accepted document, as one batch.

        Non-fatal diagnostics travel on the returned `Result`'s `warnings`, whether it
        is `Ok` or `Err`.
        """
        return self.stage.apply(docs)


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

    A `Pipeline` is configured once — sources, transpilers, and sink —
    and executed by calling `process()`.
    All state is local to a single `process()` call;
    the same `Pipeline` instance may be reused.

    Holds a heterogeneous list of `Transpiler`s
    and dispatches each document to the first one that `accepts` it.

    Attributes:
        sources: Ordered list of `DataSource`s; each is iterated exactly once.
        transpilers: Ordered list of `Transpiler`s;
          each document is dispatched to the first transpiler whose `accepts()` returns `True`.
        sink: Destination for all `Artifact`s produced during the run.

    Example:
        ```python
        pipeline = Pipeline(
            sources=[DirectoryDataSource("schemas/")],
            transpilers=TranspilerRouter().route("postgres", MediaTypes.json),
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
    transpilers: Sequence[Transpiler[I, O]]
    sink: DataSink[O]

    def process(self) -> Result[ProcessSummary]:
        """Execute the pipeline: read all sources, transpile, write to sink.

        Every document is read and routed before anything is transpiled.  A transpiler
        then sees all of its documents at once, which is what lets an artifact depend
        on more than one of them — a `$ref` into a sibling file cannot be resolved
        until that file has been read.

        Returns `Ok[ProcessSummary]` if every document was transpiled without
        fatal errors, or `Err` with all accumulated errors otherwise.
        """
        helper = _PipelineHelper()
        for index, documents in self._route(helper):
            self._transpile_batch(self.transpilers[index], documents, helper)
        if helper.errors:
            return Err(tuple(helper.errors))
        return Ok(
            ProcessSummary(
                docs_used=helper.docs_used,
                artifacts_written=helper.artifacts_written,
                warnings=tuple(helper.warnings),
            )
        )

    def _route(self, helper: _PipelineHelper) -> list[tuple[int, list[I]]]:
        """Group every source document under the first transpiler that accepts it.

        Batches are keyed by position rather than by the transpiler itself, which need
        not be hashable — the stage it holds is a perfectly ordinary mutable object.
        Order follows the transpiler list and then the order documents were read, so
        output is stable across runs.
        """
        batches: list[list[I]] = [[] for _ in self.transpilers]
        for source in self.sources:
            for document in source.documents():
                index = next(
                    (i for i, t in enumerate(self.transpilers) if t.accepts(document)), None
                )
                if index is None:
                    helper.warnings.append(
                        TranspilationWarning(
                            f"No transpiler accepts {document.doc_id!r}; skipping.",
                            code="no-transpiler",
                        )
                    )
                    continue
                helper.docs_used.append(document.doc_id)
                batches[index].append(document)
        return [(i, docs) for i, docs in enumerate(batches) if docs]

    def _transpile_batch(
        self, transpiler: Transpiler[I, O], documents: Sequence[I], helper: _PipelineHelper
    ) -> None:
        result = transpiler.transpile_all(documents)
        helper.warnings.extend(result.warnings)
        match result:
            case Err(errs):
                helper.errors += errs
            case Ok(val):
                for artifact in val:
                    helper.artifacts_written.append(artifact.artifact_id)
                    self.sink.write(artifact)
