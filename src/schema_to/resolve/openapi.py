"""OpenAPI Reference Object resolver.

OpenAPI allows a `$ref` wherever a Parameter, Response, Header, Request Body,
Link, Example, Security Scheme, Path Item, or Media Type is expected.  The parser
records those as `Reference` nodes without following them, so a CST fresh from
`OpenApiParser` still says "look over there" in place of most of its content, and
a generator reading it sees a `Reference` it cannot act on.

This stage replaces each one with what it points at.  Two things make that cheap:

- The walk is driven by the same `NodePlan`s the parser and serializer run on, so
  a referenceable position added to the CST is covered without touching this
  module.  The plan also names which node types the position accepts, which is
  how a reference into the wrong kind of object is caught.
- A JSON Pointer is followed through the CST itself rather than through the raw
  document, by matching each segment against the plan's keys.

A schema `$ref` is left alone: that is `resolve.json_schema`'s job, and the two
run over disjoint parts of the tree.

Per [OAS 3.1](https://spec.openapis.org/oas/v3.1.0#reference-object), a
reference's own `summary` and `description` override the target's.  Where the
target has no such field the override cannot be honoured, and that is a warning
rather than an error: the description is prose, and losing it costs nothing that
generated code depends on.
"""

import urllib.parse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, cast, override

from schema_to.cst.base import CstNode
from schema_to.cst.openapi import OpenApiDocument, Reference
from schema_to.errors import ResolutionError, SourceLocation, TranspilationWarning
from schema_to.parse._plan import ListSpec, MapSpec, NodeSpec, OneOfSpec, SetSpec, plan_for
from schema_to.pipeline import RefResolver
from schema_to.result import Err, Ok, Result

if TYPE_CHECKING:
    from collections.abc import Set

    from _typeshed import DataclassInstance

    from schema_to.errors import TranspilationError
    from schema_to.parse._plan import FieldSpec

__all__ = ["OpenApiRefResolver"]

# Fields a `Reference` may override on whatever it points at.
_OVERRIDABLE = ("summary", "description")


@dataclass
class OpenApiRefResolver(RefResolver[OpenApiDocument]):
    """Replaces every `Reference` in an OpenAPI CST with the node it names.

    Resolution is transitive — a reference to a reference follows through — and
    cycle-guarded.  An unresolvable reference, or one naming a node of the wrong
    kind for the position it sits in, is a `ResolutionError`; errors accumulate,
    so one bad pointer does not hide the rest.

    Attributes:
        _documents: Registered documents, keyed by every URI they answer to.
    """

    _documents: dict[str, OpenApiDocument] = field(default_factory=dict, repr=False)

    @override
    def register(self, cst: OpenApiDocument) -> None:
        """Add a document so that references from elsewhere can name it."""
        for identity in _identities(cst):
            self._documents.setdefault(identity, cst)

    @override
    def apply(self, input: OpenApiDocument) -> Result[OpenApiDocument]:
        """Return `input` with every reference replaced by its target.

        Auto-registers the document, so a reference into the document's own
        `components` resolves without a prior registration pass.  Registering the
        other documents first is the caller's job; `registering()` composes the
        two passes when references cross files.
        """
        self.register(input)
        session = _Session(documents=self._documents, base_uri=_base_uri(input))
        resolved = session.node(input, frozenset())
        warnings = tuple(session.warnings)
        if session.errors:
            return Err(tuple(session.errors), warnings=warnings)
        return Ok(resolved, warnings=warnings)


def _identities(doc: OpenApiDocument) -> Sequence[str]:
    """Return the URIs a document answers to: its id, and its 3.2 `$self`."""
    return [uri for uri in (doc.source_id, doc.self_) if uri]


def _base_uri(doc: OpenApiDocument) -> str:
    """Return what a relative reference inside `doc` resolves against.

    `$self` wins where a 3.2 document sets one — declaring where the document
    lives is exactly what that keyword is for.
    """
    return doc.self_ or doc.source_id or ""


@dataclass
class _Session:
    """One pass over one document, accumulating what it could not resolve.

    Attributes:
        documents: Every registered document, keyed by the URIs it answers to.
        base_uri: What a relative reference in the document being walked resolves against.
        errors: References that named nothing, or named the wrong kind of node.
        warnings: Overrides that could not be honoured.
    """

    documents: Mapping[str, OpenApiDocument]
    base_uri: str
    errors: list[TranspilationError] = field(default_factory=list)
    warnings: list[TranspilationWarning] = field(default_factory=list)

    # -- Walk ---------------------------------------------------------------

    def node[N: CstNode](self, node: N, chain: Set[str]) -> N:
        """Return `node` with every reference beneath it resolved."""
        changed: dict[str, object] = {}
        for entry in plan_for(type(node)).entries:
            before = getattr(node, entry.name)
            after = self.value(entry.spec, before, chain)
            if after is not before:
                changed[entry.name] = after
        return _replace(node, changed) if changed else node

    def value(self, spec: FieldSpec, value: object, chain: Set[str]) -> object:
        """Return `value` with every reference inside it resolved.

        A value holding no reference is returned as-is rather than rebuilt, so
        `node` can tell an untouched field from a changed one by identity, and a
        document with nothing to resolve comes back unchanged.
        """
        match spec:
            case OneOfSpec(options=options):
                return self.alternative(options, value, chain)
            case NodeSpec() if isinstance(value, CstNode):
                return self.node(value, chain)
            case ListSpec(item=item) if isinstance(value, Sequence) and not isinstance(value, str):
                resolved = [self.value(item, element, chain) for element in value]
                return value if _all_same(resolved, value) else resolved
            case MapSpec(value=inner) if isinstance(value, Mapping):
                held = {name: self.value(inner, each, chain) for name, each in value.items()}
                return value if _all_same(held.values(), value.values()) else held
            case _:
                return value

    def alternative(self, options: Sequence[FieldSpec], value: object, chain: Set[str]) -> object:
        """Resolve `value` against whichever alternative of a union it is.

        A `Reference` is followed, provided the position admits one.  Anything
        else is walked under the first alternative whose shape it has — which is
        what carries the walk into a `Callback`, a bare map of path items that
        would otherwise be a blind spot.
        """
        others = [option for option in options if option != NodeSpec(Reference)]
        if isinstance(value, Reference) and len(others) < len(options):
            return self.dereference(value, others, chain)
        fitting = _fitting(others, value)
        return self.value(fitting, value, chain) if fitting is not None else value

    # -- Resolution ---------------------------------------------------------

    def dereference(self, ref: Reference, accepts: Sequence[FieldSpec], chain: Set[str]) -> object:
        """Follow `ref` to its target, resolving that target in turn."""
        if ref.ref in chain:
            self._fail(ref, f"Reference cycle: {ref.ref!r} points at itself, via {sorted(chain)}.")
            return ref
        target = self.lookup(ref.ref)
        if target is None:
            self._fail(ref, f"Cannot resolve {ref.ref!r}: no such document or pointer.")
            return ref
        onward = chain | {ref.ref}
        if isinstance(target, Reference):
            return self.dereference(target, accepts, onward)
        fitting = _fitting(accepts, target)
        if fitting is None:
            expected = " or ".join(sorted(_shape(option) for option in accepts))
            self._fail(
                ref, f"{ref.ref!r} resolves to a {_shape_of(target)}, but a {expected} is required."
            )
            return ref
        resolved = self.value(fitting, target, onward)
        return self.overlay(ref, resolved) if isinstance(resolved, CstNode) else resolved

    def lookup(self, ref: str) -> object | None:
        """Return whatever `ref` names, or `None` if nothing answers to it."""
        doc_uri, _, fragment = urllib.parse.urljoin(self.base_uri, ref).partition("#")
        document = self.documents.get(doc_uri or self.base_uri)
        if document is None:
            return None
        return _navigate(document, fragment)

    def overlay[N: CstNode](self, ref: Reference, target: N) -> N:
        """Apply the reference's `summary` and `description` overrides to `target`."""
        keys = {entry.key for entry in plan_for(type(target)).entries}
        overrides: dict[str, object] = {}
        for name in _OVERRIDABLE:
            override_ = getattr(ref, name)
            if override_ is None:
                continue
            if name in keys:
                overrides[name] = override_
            else:
                self._warn(ref, name, type(target).__name__)
        return _replace(target, overrides) if overrides else target

    # -- Diagnostics --------------------------------------------------------

    def _fail(self, ref: Reference, message: str) -> None:
        self.errors.append(ResolutionError(message, location=_location(ref)))

    def _warn(self, ref: Reference, name: str, target: str) -> None:
        self.warnings.append(
            TranspilationWarning(
                f"{ref.ref!r} overrides `{name}`, but a {target} has no such field, "
                f"so the override is dropped.",
                code="unhonoured-override",
                location=_location(ref),
            )
        )


def _all_same(resolved: Iterable[object], original: Iterable[object]) -> bool:
    """Return whether every element came back as the identical object."""
    return all(a is b for a, b in zip(resolved, original, strict=True))


def _replace[N: CstNode](node: N, changes: Mapping[str, object]) -> N:
    """Return `node` with `changes` applied.

    Every CST node is a frozen dataclass, but `CstNode` is a plain ABC, so that
    relationship has to be asserted rather than inferred.
    """
    return cast("N", replace(cast("DataclassInstance", node), **changes))


def _location(ref: Reference) -> SourceLocation | None:
    if ref.source_ref is None:
        return None
    return SourceLocation(ref.source_ref.source_id, ref.source_ref.json_pointer)


def _fitting(options: Sequence[FieldSpec], value: object) -> FieldSpec | None:
    """Return the first alternative whose shape `value` has, if any."""
    return next((option for option in options if _fits(option, value)), None)


def _fits(spec: FieldSpec, value: object) -> bool:
    """Return whether `value` could have been built from `spec`."""
    match spec:
        case NodeSpec(node=node):
            return isinstance(value, node)
        case MapSpec():
            return isinstance(value, Mapping)
        case ListSpec() | SetSpec():
            return isinstance(value, Sequence) and not isinstance(value, str)
        case _:
            return False


def _shape(spec: FieldSpec) -> str:
    """Name what an alternative accepts, for use in a diagnostic."""
    match spec:
        case NodeSpec(node=node):
            return f"{node.__name__} object"
        case MapSpec():
            return "map"
        case ListSpec() | SetSpec():
            return "array"
        case _:
            return "value"


def _shape_of(value: object) -> str:
    """Name what a resolved target turned out to be."""
    if isinstance(value, CstNode):
        return f"{type(value).__name__} object"
    if isinstance(value, Mapping):
        return "map"
    if isinstance(value, Sequence) and not isinstance(value, str):
        return "array"
    return type(value).__name__


def _navigate(document: OpenApiDocument, fragment: str) -> object | None:
    """Follow an RFC 6901 pointer through the CST, matching segments to plan keys."""
    if not fragment:
        return document
    if not fragment.startswith("/"):
        return None  # OpenAPI has no anchors; a bare-name fragment names nothing.
    found: object = document
    for segment in fragment.split("/")[1:]:
        found = _step(found, segment.replace("~1", "/").replace("~0", "~"))
        if found is None:
            return None
    return found


def _step(found: object, segment: str) -> object | None:
    """Descend one pointer segment into a node, map, or array."""
    if isinstance(found, Mapping):
        return found.get(segment)
    if isinstance(found, Sequence) and not isinstance(found, str):
        index = int(segment) if segment.isdigit() else None
        return found[index] if index is not None and index < len(found) else None
    if isinstance(found, CstNode):
        entry = next((e for e in plan_for(type(found)).entries if e.key == segment), None)
        return getattr(found, entry.name) if entry is not None else None
    return None
