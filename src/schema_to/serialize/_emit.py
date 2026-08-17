"""Emits JSON from CST nodes by interpreting their `NodePlan`.

The mirror image of `parse._build`: the same plan that says which key a field
reads says which key it writes, so a round trip cannot lose a keyword the parser
understood, and a keyword added to a CST class needs no change here.

Output is minimal but complete.  A field emits no key when its value is the way
the CST spells "the document did not say it" — `None`, a `False` flag, or an
empty container on a field that neither requires a value nor admits `None`.

A version-gated field emits no key either, when the document declares a version
that does not define it.  Emitting one would produce a document that this
parser, reading the same plans, would then reject.
"""

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, cast

from schema_to.cst.base import CstNode
from schema_to.cst.json_schema import BooleanSchema, ConstValue, DefaultValue, ObjectSchema
from schema_to.parse._plan import SpecVersion, plan_for

if TYPE_CHECKING:
    from schema_to.core import JsonObject, JsonValue
    from schema_to.parse._plan import FieldPlan

__all__ = ["emit_node", "emit_schema"]


@dataclass(frozen=True, slots=True)
class _Absent:
    """A field that contributes no key to the output."""


_ABSENT = _Absent()


def emit_node(node: CstNode, version: SpecVersion | None = None) -> JsonObject:
    """Emit one CST node as a JSON object, per its plan."""
    if isinstance(node, (BooleanSchema, ObjectSchema)):
        emitted = emit_schema(node)
        return emitted if isinstance(emitted, dict) else {}
    plan = plan_for(type(node))
    out: JsonObject = {}
    for entry in plan.entries:
        if not entry.applies_to(version):
            continue
        value = _entry_value(node, entry, version)
        if not isinstance(value, _Absent):
            out[entry.key] = value
    if plan.has_extensions:
        extensions = getattr(node, "extensions", None)
        if isinstance(extensions, Mapping):
            out.update(extensions)
    return out


def emit_schema(schema: BooleanSchema | ObjectSchema) -> JsonValue:
    """Emit a JSON Schema: `true`, `false`, or a keyword object."""
    if isinstance(schema, BooleanSchema):
        return schema.value
    out: JsonObject = {}
    for entry in plan_for(ObjectSchema).entries:
        value = _entry_value(schema, entry, None)
        if not isinstance(value, _Absent):
            out[entry.key] = value
    out.update(schema.extensions)
    return out


def _entry_value(
    node: CstNode, entry: FieldPlan, version: SpecVersion | None
) -> JsonValue | _Absent:
    """Emit one field, or `_ABSENT` when it contributes no key."""
    value = getattr(node, entry.name)
    if value is None:
        return _ABSENT
    if isinstance(value, bool) and not value and not entry.nullable:
        return _ABSENT
    emitted = _emit(value, version)
    # Emptiness is judged after emitting, so that a node whose every field is
    # absent — a defaulted `Components`, say — drops out along with an empty map.
    if _is_empty(emitted) and not entry.required and not entry.nullable:
        return _ABSENT
    return emitted


def _is_empty(value: JsonValue) -> bool:
    return isinstance(value, (Mapping, Sequence)) and not isinstance(value, str) and not value


def _emit(value: object, version: SpecVersion | None = None) -> JsonValue:
    """Emit a value that is known to contribute something."""
    match value:
        case Mapping():
            return {key: _emit(item, version) for key, item in value.items()}
        case Set():
            # Sets are unordered; sorting keeps the output stable across runs.
            # `list[str]` is a `JsonArray`, but `MutableSequence` is invariant,
            # so the subtype relationship needs asserting.
            return cast("JsonValue", sorted(str(item) for item in value))
        case str() | None:
            return value
        case Sequence():
            return [_emit(item, version) for item in value]
        case _:
            return _emit_leaf(value, version)


def _emit_leaf(value: object, version: SpecVersion | None) -> JsonValue:
    match value:
        case BooleanSchema() | ObjectSchema():
            return emit_schema(value)
        case DefaultValue(value=inner) | ConstValue(value=inner):
            return inner
        case CstNode():
            return emit_node(value, version)
        case Enum():
            return str(value.value)
        case bool() | int() | float():
            return value
        case _:  # pragma: no cover — no other value reaches a plan-driven field
            return None
