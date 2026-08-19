"""Builds CST nodes from decoded JSON by interpreting their `NodePlan`.

One walk covers every node type in both CSTs:
The plan says which keys to read and what shape each value has,
and this module turns that into either a node or an accumulated diagnostic.
Adding a field to a CST class is therefore enough to make the parser read it.

Errors never abort the walk.
They collect in the `Cursor`'s shared list so that one parse reports every fault,
and a node is abandoned —
yielding `FAILED` —
only when a field it cannot be constructed without is missing or unusable.
"""

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from enum import Enum
from typing import final

from schema_to.core import JsonValue, as_array, as_object
from schema_to.cst.base import CstNode, SourceRef
from schema_to.cst.json_schema import (
    BooleanSchema,
    ConstValue,
    DefaultValue,
    JsonSchema,
    ObjectSchema,
)
from schema_to.errors import SchemaValidationError, SourceLocation, TranspilationError
from schema_to.parse._plan import (
    BoolSpec,
    EnumSpec,
    FieldPlan,
    FieldSpec,
    IntSpec,
    ListSpec,
    MapSpec,
    NodeSpec,
    NumSpec,
    OneOfSpec,
    RawSpec,
    SchemaSpec,
    SetSpec,
    SpecVersion,
    StrSpec,
    WrapSpec,
    plan_for,
)
from schema_to.parse._utils import enum_member, ptr

__all__ = [
    "FAILED",
    "Cursor",
    "Failed",
    "ParsedValue",
    "build_node",
    "build_schema",
    "build_value",
    "describe",
]


@final
@dataclass(frozen=True, slots=True)
class Failed:
    """The outcome of a value that could not be built.

    Distinct from `None`, which is a legitimate JSON value.
    """


FAILED = Failed()


# Every value a spec can produce.  The parser moves these generically, so it
# needs one type covering all of them rather than `Any`.
type ParsedValue = (
    str
    | bool
    | int
    | float
    | Enum
    | CstNode
    | DefaultValue
    | ConstValue
    | SourceRef
    | Sequence[ParsedValue]
    | Set[ParsedValue]
    | Mapping[str, ParsedValue]
    | JsonValue
    | None
)


@dataclass(frozen=True, slots=True)
class Cursor:
    """A position in a source document, plus the diagnostics gathered so far.

    Replaces threading `source_id`, `pointer`, and an error list through every builder:
    pointer arithmetic happens in `at` alone,
    so an error can only be reported against the node it belongs to.

    Attributes:
        source_id: Identifier matching `RawDoc.doc_id`.
        pointer: RFC 6901 pointer to the value under construction.
        errors: Accumulator shared by every cursor derived from this one.
        version: The specification version the document declares,
            against which version-gated keys are checked.
            `None` gates nothing.
    """

    source_id: str
    pointer: str
    errors: list[TranspilationError]
    version: SpecVersion | None = None

    @classmethod
    def root(cls, source_id: str, version: SpecVersion | None = None) -> Cursor:
        """Return a cursor at the document root with a fresh accumulator."""
        return cls(source_id, "", [], version)

    def at(self, *segments: str | int) -> Cursor:
        """Return a cursor descended into `segments`, sharing this accumulator."""
        return Cursor(self.source_id, ptr(self.pointer, *segments), self.errors, self.version)

    def probe(self) -> Cursor:
        """Return a cursor at this position with a throwaway accumulator.

        Used to try an alternative without leaving diagnostics behind.
        Everything else — position and declared version — carries over,
        so a rejected alternative is judged under the same rules as an accepted one.
        """
        return Cursor(self.source_id, self.pointer, [], self.version)

    def fail(self, message: str) -> Failed:
        """Record a validation error here and return `FAILED`, for use in a `return`."""
        self.errors.append(
            SchemaValidationError(message, location=SourceLocation(self.source_id, self.pointer))
        )
        return FAILED

    def ref(self) -> SourceRef:
        """Return the provenance link for the value under construction."""
        return SourceRef(self.source_id, self.pointer)

    @property
    def label(self) -> str:
        """Name the value under construction, for use in a message."""
        _, _, last = self.pointer.rpartition("/")
        return last or "The document root"


def build_node[N: CstNode](node: type[N], data: JsonValue, at: Cursor) -> N | Failed:
    """Build one CST node of type `node` from `data`, per its plan."""
    obj = as_object(data)
    if obj is None:
        return at.fail(f"{at.label} must be an object.")
    plan = plan_for(node)
    kwargs: dict[str, ParsedValue] = {}
    incomplete = False
    for entry in plan.entries:
        incomplete |= _build_field_into(kwargs, entry, obj, at)
    if incomplete:
        return FAILED
    if plan.has_extensions:
        kwargs["extensions"] = {k: v for k, v in obj.items() if k.startswith("x-")}
    if plan.has_source_ref:
        kwargs["source_ref"] = at.ref()
    return node(**kwargs)


def _build_field_into(
    kwargs: dict[str, ParsedValue], entry: FieldPlan, obj: Mapping[str, JsonValue], at: Cursor
) -> bool:
    """Deposit one field into `kwargs`; return whether the node became unbuildable."""
    if not entry.applies_to(at.version):
        if entry.key in obj:
            at.at(entry.key).fail(_out_of_range(entry, at.version))
        return False
    if entry.key not in obj:
        if entry.required:
            at.at(entry.key).fail(f"{entry.key} is required.")
            return True
        return False
    value = build_value(entry.spec, obj[entry.key], at.at(entry.key))
    if isinstance(value, Failed):
        return entry.required
    kwargs[entry.name] = value
    return False


def build_schema(data: JsonValue, at: Cursor) -> JsonSchema | Failed:
    """Build an embedded JSON Schema: `true`, `false`, or a keyword object."""
    if isinstance(data, bool):
        return BooleanSchema(value=data, source_ref=at.ref())
    if as_object(data) is None:
        return at.fail(f"{at.label} must be `true`, `false`, or an object.")
    return build_node(ObjectSchema, data, at)


def build_value(spec: FieldSpec, data: JsonValue, at: Cursor) -> ParsedValue | Failed:
    """Build the value of one field from `data`, per `spec`."""
    match spec:
        case NodeSpec(node=node):
            built = build_node(node, data, at)
        case SchemaSpec():
            built = build_schema(data, at)
        case ListSpec(item=item):
            built = _build_list(item, data, at, spec=spec)
        case SetSpec(item=item):
            items = _build_list(item, data, at, spec=spec)
            built = items if isinstance(items, Failed) else frozenset(items)
        case MapSpec(value=value):
            built = _build_map(value, data, at, spec=spec)
        case OneOfSpec(options=options):
            built = _build_one_of(options, data, at, spec=spec)
        case _:
            built = _build_leaf(spec, data, at)
    return built


def _build_leaf(spec: FieldSpec, data: JsonValue, at: Cursor) -> ParsedValue | Failed:
    """Build a value that holds no other value."""
    match spec:
        case StrSpec():
            built = data if isinstance(data, str) else _reject(spec, at)
        case BoolSpec():
            built = data if isinstance(data, bool) else _reject(spec, at)
        case IntSpec(minimum=minimum):
            built = _build_int(minimum, data, at, spec=spec)
        case NumSpec():
            built = _build_num(data, at, spec=spec)
        case RawSpec():
            built = data
        case WrapSpec(wrapper=wrapper):
            built = wrapper(data)
        case EnumSpec(enum=enum):
            member = enum_member(enum, data)
            built = member if member is not None else _reject(spec, at)
        case _:  # pragma: no cover — every leaf spec is matched above
            built = _reject(spec, at)
    return built


def _build_num(data: JsonValue, at: Cursor, *, spec: FieldSpec) -> float | Failed:
    if not isinstance(data, (int, float)) or isinstance(data, bool):
        return _reject(spec, at)
    return float(data)


def _build_int(
    minimum: int | None, data: JsonValue, at: Cursor, *, spec: FieldSpec
) -> int | Failed:
    if not isinstance(data, int) or isinstance(data, bool):
        return _reject(spec, at)
    if minimum is not None and data < minimum:
        return _reject(spec, at)
    return data


def _build_list(
    item: FieldSpec, data: JsonValue, at: Cursor, *, spec: FieldSpec
) -> list[ParsedValue] | Failed:
    array = as_array(data)
    if array is None:
        return _reject(spec, at)
    built: list[ParsedValue] = []
    for i, element in enumerate(array):
        value = build_value(item, element, at.at(i))
        if not isinstance(value, Failed):
            built.append(value)
    return built


def _build_map(
    value_spec: FieldSpec, data: JsonValue, at: Cursor, *, spec: FieldSpec
) -> dict[str, ParsedValue] | Failed:
    obj = as_object(data)
    if obj is None:
        return _reject(spec, at)
    built: dict[str, ParsedValue] = {}
    for name, element in obj.items():
        value = build_value(value_spec, element, at.at(name))
        if not isinstance(value, Failed):
            built[name] = value
    return built


def _build_one_of(
    options: Sequence[FieldSpec], data: JsonValue, at: Cursor, *, spec: FieldSpec
) -> ParsedValue | Failed:
    """Return the first alternative that builds with no diagnostics at all.

    Each is tried against a throwaway accumulator, so a rejected alternative leaves no trace.
    When none succeeds, the diagnostics of the *last* one are surfaced:
    A union therefore declares its fallback interpretation last,
    and the alternative recognised by a distinguishing key first.
    """
    probe = at.probe()
    built: ParsedValue | Failed = FAILED
    for option in options:
        probe = at.probe()
        built = build_value(option, data, probe)
        if not isinstance(built, Failed) and not probe.errors:
            return built
    at.errors.extend(probe.errors)
    return built if probe.errors else _reject(spec, at)


def _out_of_range(entry: FieldPlan, version: SpecVersion | None) -> str:
    """Explain that a key exists in the specification, but not in this version."""
    declared = version.text if version is not None else "an unknown version"
    if entry.since is not None and (version is None or not version.at_least(entry.since)):
        return (
            f"{entry.key} was introduced in OpenAPI {entry.since.text}, "
            f"but this document declares {declared}."
        )
    until = entry.until.text if entry.until is not None else "an earlier version"
    return f"{entry.key} was removed after OpenAPI {until}, but this document declares {declared}."


def _reject(spec: FieldSpec, at: Cursor) -> Failed:
    return at.fail(f"{at.label} must be {describe(spec)}.")


def describe(spec: FieldSpec) -> str:
    """Describe what `spec` accepts, for use in a diagnostic."""
    match spec:
        case ListSpec(item=item) | SetSpec(item=item):
            return f"an array of {describe(item)}"
        case MapSpec(value=value):
            return f"an object whose values are {describe(value)}"
        case OneOfSpec(options=options):
            return " or ".join(describe(option) for option in options)
        case _:
            return _describe_leaf(spec)


def _describe_leaf(spec: FieldSpec) -> str:
    match spec:
        case StrSpec():
            described = "a string"
        case BoolSpec():
            described = "a boolean"
        case IntSpec(minimum=None):
            described = "an integer"
        case IntSpec(minimum=0):
            described = "a non-negative integer"
        case IntSpec(minimum=minimum):
            described = f"an integer no less than {minimum}"
        case NumSpec():
            described = "a number"
        case EnumSpec(enum=enum):
            described = "one of " + ", ".join(repr(member.value) for member in enum)
        case NodeSpec(node=node):
            described = f"a {node.__name__} object"
        case SchemaSpec():
            described = "`true`, `false`, or an object"
        case _:
            described = "any JSON value"
    return described
