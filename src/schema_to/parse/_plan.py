"""Compiles a CST node class into the plan that describes its wire format.

A `NodePlan` says, for one `CstNode` subclass, which JSON key each field reads and writes,
what shape that key's value has, and whether it must be present.
Everything in it is *derived* from the class itself —
from `dataclasses.fields()` and `typing.get_type_hints()` —
so the annotation is the single description of a field,
and no hand-written tag can drift from it.

Three consumers share the plans:
the parser (`parse._build`),
the serializer,
and the sub-schema walk in `generate.inlining`.

Deriving from type hints requires the annotations to be resolvable at runtime,
so CST modules import their annotation types normally rather than under `TYPE_CHECKING`.
"""

import re
import types
import typing
from collections.abc import Mapping, Sequence, Set
from dataclasses import MISSING, dataclass, fields
from enum import Enum
from functools import cache
from typing import TYPE_CHECKING, ClassVar, cast

from schema_to.core import JsonArray, JsonObject, JsonPrimitive, JsonValue
from schema_to.cst.base import CstNode
from schema_to.cst.json_schema import ConstValue, DefaultValue, JsonSchema

if TYPE_CHECKING:
    from dataclasses import Field

    from _typeshed import DataclassInstance

__all__ = [
    "BoolSpec",
    "EnumSpec",
    "FieldPlan",
    "FieldSpec",
    "IntSpec",
    "ListSpec",
    "MapSpec",
    "NodePlan",
    "NodeSpec",
    "NumSpec",
    "OneOfSpec",
    "RawSpec",
    "SchemaSpec",
    "SetSpec",
    "SpecVersion",
    "StrSpec",
    "WrapSpec",
    "json_key",
    "plan_for",
    "sub_schema_fields",
]


# A resolved annotation. `get_type_hints` yields plain classes, PEP 604 unions,
# subscripted generics, and `type` aliases; this names that set so the compiler
# can pass annotations around without falling back to `Any`.
type Annotation = type | types.UnionType | types.GenericAlias | typing.TypeAliasType | None

# Aliases that stand for arbitrary JSON rather than for a structure to descend into.
_RAW_ALIASES = (JsonValue, JsonObject, JsonArray, JsonPrimitive)

# Container origins, grouped by the spec each produces.
_LIST_ORIGINS = (Sequence, list, tuple)
_MAP_ORIGINS = (Mapping, dict)
_SET_ORIGINS = (Set, frozenset, set)


# ---------------------------------------------------------------------------
# Field specs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StrSpec:
    """A JSON string."""


@dataclass(frozen=True, slots=True)
class BoolSpec:
    """A JSON boolean."""


@dataclass(frozen=True, slots=True)
class IntSpec:
    """A JSON integer, optionally bounded below.

    Attributes:
        minimum: Smallest accepted value, from the field's `min` metadata.
    """

    minimum: int | None = None


@dataclass(frozen=True, slots=True)
class NumSpec:
    """A JSON number; integers are widened to `float`."""


@dataclass(frozen=True, slots=True)
class RawSpec:
    """Arbitrary JSON, carried through unexamined."""


@dataclass(frozen=True, slots=True)
class EnumSpec:
    """A JSON string naming a member of `enum`."""

    enum: type[Enum]


@dataclass(frozen=True, slots=True)
class NodeSpec:
    """A nested CST node, built from its own plan."""

    node: type[CstNode]


@dataclass(frozen=True, slots=True)
class SchemaSpec:
    """An embedded JSON Schema — `true`, `false`, or a keyword object."""


@dataclass(frozen=True, slots=True)
class WrapSpec:
    """A single-field wrapper holding raw JSON, such as `DefaultValue`.

    The wire form is the bare value; the wrapper exists only to tell an explicit
    `null` apart from an absent keyword.
    """

    wrapper: type[DefaultValue | ConstValue]


@dataclass(frozen=True, slots=True)
class ListSpec:
    """A JSON array whose items all share one spec."""

    item: FieldSpec


@dataclass(frozen=True, slots=True)
class SetSpec:
    """A JSON array collected into a `frozenset`."""

    item: FieldSpec


@dataclass(frozen=True, slots=True)
class MapSpec:
    """A JSON object whose values all share one spec."""

    value: FieldSpec


@dataclass(frozen=True, slots=True)
class OneOfSpec:
    """Alternatives tried in order; the first that builds cleanly wins.

    Order is the order the union declares.  A member that can be recognised by a
    distinguishing key — a `Reference` by its `$ref` — belongs first, so the more
    permissive alternative does not swallow it.
    """

    options: Sequence[FieldSpec]


type FieldSpec = (
    StrSpec
    | BoolSpec
    | IntSpec
    | NumSpec
    | RawSpec
    | EnumSpec
    | NodeSpec
    | SchemaSpec
    | WrapSpec
    | ListSpec
    | SetSpec
    | MapSpec
    | OneOfSpec
)


# ---------------------------------------------------------------------------
# Specification versions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpecVersion:
    """A specification version a document declares or a field is gated on.

    OpenAPI 3.1 and 3.2 are one document type told apart by a version *string*
    in the payload, so a version cannot get its own CST the way a JSON Schema
    dialect could.  Gating a field on a range is what lets one set of classes
    describe both.
    """

    PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*)(?:-.+)?)?"
    )
    text: str
    parts: tuple[int, ...]

    @classmethod
    def parse(cls, text: str) -> SpecVersion:
        """Parses 2- or 3-segment version `text` using [PATTERN][], discarding any pre-release info.

        Raises:
            ValueError: If `text` is invalid
        """
        if m := cls.PATTERN.fullmatch(text):
            return cls(
                text, tuple(int(g) for g in m.groups() if g is not None and not g.startswith("-"))
            )
        msg = f"Invalid version string '{text}'"
        raise ValueError(msg)

    def __bool__(self) -> bool:
        return True

    def as_str(self) -> str:
        return ".".join(str(p) for p in self.parts)

    def at_least(self, minimum: SpecVersion) -> bool:
        """Return whether this version is `other` or later."""
        width = max(len(self.parts), len(minimum.parts))
        return self._padded(self.parts, width) >= self._padded(minimum.parts, width)

    def at_most(self, maximum: SpecVersion) -> bool:
        return maximum.at_least(self)

    @staticmethod
    def _padded(parts: tuple[int, ...], width: int) -> tuple[int, ...]:
        return parts + (0,) * (width - len(parts))


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldPlan:
    """How one CST field maps onto one JSON key.

    Attributes:
        name: The Python attribute name.
        key: The JSON key it reads and writes.
        spec: The shape of the key's value.
        required: Whether the key must be present.
            True exactly when the field declares no default,
            which across both CSTs coincides with the specification's own requiredness.
        nullable: Whether the annotation admits `None`, meaning the CST tells an
            absent key apart from a present one.
            A non-nullable `False` or empty container is how the CST spells absence,
            so it emits no key;
            a nullable one was really there and does.
        since: The first version defining this key, from the field's `since` metadata.
            `None` means every version this CST describes has it.
        until: The last version still defining it, from the field's `until` metadata.
            Inclusive: a key dropped in 3.3 is `until="3.2"`.
    """

    name: str
    key: str
    spec: FieldSpec
    required: bool
    nullable: bool
    since: SpecVersion | None = None
    until: SpecVersion | None = None

    def applies_to(self, version: SpecVersion | None) -> bool:
        """Return whether a document declaring `version` may carry this key."""
        return not version or (
            (not self.since or version.at_least(self.since))
            and (not self.until or version.at_most(self.until))
        )


@dataclass(frozen=True, slots=True)
class NodePlan:
    """The complete wire format of one CST node type.

    Attributes:
        node: The class this plan builds and emits.
        entries: One plan per wire-carrying field, in declaration order.
        has_extensions: Whether the node collects `x-*` keys.
        has_source_ref: Whether the node records where it came from.
    """

    node: type[CstNode]
    entries: Sequence[FieldPlan]
    has_extensions: bool
    has_source_ref: bool

    def keys(self) -> Set[str]:
        """Return every JSON key this node recognises."""
        return frozenset(entry.key for entry in self.entries)


def json_key(name: str) -> str:
    """Return the JSON key a Python field name stands for.

    Drops one trailing underscore and converts to camelCase.
    """
    head, *rest = name.removesuffix("_").split("_")
    return head + "".join(word.capitalize() for word in rest)


@cache
def plan_for(node: type[CstNode]) -> NodePlan:
    """Compile and memoise the plan for one CST node type."""
    hints = cast("Mapping[str, Annotation]", typing.get_type_hints(node))
    entries: list[FieldPlan] = []
    has_extensions = False
    has_source_ref = False
    for f in fields(cast("type[DataclassInstance]", node)):
        if f.metadata.get("synthetic"):
            has_extensions |= f.name == "extensions"
            has_source_ref |= f.name == "source_ref"
            continue
        entries.append(_field_plan(f, hints[f.name]))
    return NodePlan(
        node=node,
        entries=tuple(entries),
        has_extensions=has_extensions,
        has_source_ref=has_source_ref,
    )


def _field_plan(f: Field[object], hint: Annotation) -> FieldPlan:
    required = f.default is MISSING and f.default_factory is MISSING
    minimum = f.metadata.get("min")
    spec = _spec_of(hint, minimum=minimum if isinstance(minimum, int) else None)
    key = f.metadata.get("key")
    return FieldPlan(
        name=f.name,
        key=key if isinstance(key, str) else json_key(f.name),
        spec=spec,
        required=required,
        nullable=_admits_none(hint),
        since=_bound(f, "since"),
        until=_bound(f, "until"),
    )


def _bound(f: Field[object], name: str) -> SpecVersion | None:
    text = f.metadata.get(name)
    return SpecVersion.parse(text) if isinstance(text, str) else None


def _admits_none(hint: Annotation) -> bool:
    if isinstance(hint, typing.TypeAliasType):
        return _admits_none(cast("Annotation", hint.__value__))
    return _is_union(hint) and any(arg is type(None) for arg in typing.get_args(hint))


def _spec_of(hint: Annotation, *, minimum: int | None) -> FieldSpec:
    """Map one resolved annotation onto its spec."""
    for alias in _RAW_ALIASES:
        if hint is alias:
            return RawSpec()
    if hint is JsonSchema:
        return SchemaSpec()
    if isinstance(hint, typing.TypeAliasType):
        return _spec_of(cast("Annotation", hint.__value__), minimum=minimum)
    if _is_union(hint):
        return _union_spec(hint, minimum=minimum)
    if (container := _container_spec(hint, minimum=minimum)) is not None:
        return container
    return _leaf_spec(hint, minimum=minimum)


def _is_union(hint: Annotation) -> bool:
    return isinstance(hint, types.UnionType) or typing.get_origin(hint) is typing.Union


def _union_spec(hint: Annotation, *, minimum: int | None) -> FieldSpec:
    """Drop `None` — optionality lives in `FieldPlan.required` — and fold the rest."""
    options = [
        _spec_of(cast("Annotation", arg), minimum=minimum)
        for arg in typing.get_args(hint)
        if arg is not type(None)
    ]
    if len(options) == 1:
        return options[0]
    return OneOfSpec(tuple(options))


def _container_spec(hint: Annotation, *, minimum: int | None) -> FieldSpec | None:
    """Return the spec for a subscripted container, or `None` if `hint` is not one."""
    origin = typing.get_origin(hint)
    if origin is None:
        return None
    args = [cast("Annotation", arg) for arg in typing.get_args(hint)]
    if origin in _MAP_ORIGINS:
        return MapSpec(_spec_of(args[1], minimum=minimum))
    if origin in _SET_ORIGINS:
        return SetSpec(_spec_of(args[0], minimum=minimum))
    if origin in _LIST_ORIGINS:
        return ListSpec(_spec_of(args[0], minimum=minimum))
    msg = f"Unsupported container in a CST annotation: {hint!r}."
    raise TypeError(msg)


def _leaf_spec(hint: Annotation, *, minimum: int | None) -> FieldSpec:
    if isinstance(hint, type):
        spec = _scalar_spec(hint, minimum=minimum) or _object_spec(hint)
        if spec is not None:
            return spec
    msg = f"Unsupported CST annotation: {hint!r}."
    raise TypeError(msg)


def _scalar_spec(hint: type, *, minimum: int | None) -> FieldSpec | None:
    # `StrEnum` is a `str` and `bool` is an `int`, so the narrower test comes first.
    if issubclass(hint, Enum):
        return EnumSpec(hint)
    if issubclass(hint, bool):
        return BoolSpec()
    if issubclass(hint, str):
        return StrSpec()
    if issubclass(hint, int):
        return IntSpec(minimum)
    if issubclass(hint, float):
        return NumSpec()
    return None


def _object_spec(hint: type) -> FieldSpec | None:
    if issubclass(hint, CstNode):
        return NodeSpec(hint)
    if hint is DefaultValue:
        return WrapSpec(DefaultValue)
    if hint is ConstValue:
        return WrapSpec(ConstValue)
    return None


def sub_schema_fields(node: type[CstNode]) -> Sequence[FieldPlan]:
    """Return the fields of `node` whose value holds one or more JSON Schemas."""
    return tuple(entry for entry in plan_for(node).entries if _holds_schema(entry.spec))


def _holds_schema(spec: FieldSpec) -> bool:
    match spec:
        case SchemaSpec():
            return True
        case ListSpec(item=inner) | SetSpec(item=inner) | MapSpec(value=inner):
            return _holds_schema(inner)
        case OneOfSpec(options=options):
            return any(_holds_schema(option) for option in options)
        case _:
            return False
