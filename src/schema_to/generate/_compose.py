"""Flattening of `allOf` composition and `$ref` indirection into a single schema.

Targets that map one schema to one flat structure — a SQL table, a dataclass —
cannot act on `allOf` directly:
the keywords they read (`properties`, `required`) live on the branches, not the composed schema.
This module merges a composition tree into one `ObjectSchema` carrying every keyword
the branches contribute.

Merging follows JSON Schema semantics where a target can express them
and falls back to a documented choice where it cannot:

- `properties` are unioned; a name defined by more than one branch keeps its first
  definition and raises a warning, since a column has exactly one type.
- `required` is unioned, matching `allOf` exactly.
- `type` is intersected across the branches that declare it, matching `allOf` exactly.
- Single-valued keywords (`description`, `propertyNames`, …) take the first branch that sets one.
- Extensions merge with the outer schema winning, so a `$ref`ed schema cannot
  override an `x-pg-*` keyword written at the point of use.
"""

from dataclasses import dataclass, field, fields, replace
from typing import TYPE_CHECKING

from schema_to.cst.json_schema import BooleanSchema, JsonSchema, ObjectSchema
from schema_to.errors import SourceLocation, TranspilationWarning
from schema_to.serialize.json_schema import JsonSchemaSerializer

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from schema_to.core import JsonValue
    from schema_to.cst.json_schema import ConstValue, JsonSchemaType, SchemaType
    from schema_to.resolve.json_schema import JsonSchemaRefResolver

__all__ = ["FlattenedSchema", "SchemaFlattener"]

# Guards against a `$ref` cycle that `_seen` cannot catch, e.g. one built from `$dynamicRef`.
_MAX_DEPTH = 32

# The parse kinds whose values hold sub-schemas, and so need inlining in turn.
_SUB_SCHEMA_KINDS = frozenset({"optional_schema", "schema_list", "schema_map"})

# What `_inline_children` puts back on a schema, matching those three kinds.
type _SubSchemaValue = JsonSchema | Sequence[JsonSchema] | Mapping[str, JsonSchema]

# Union of the keyword values `_first_set` copies between schemas.
type _KeywordValue = (
    str
    | bool
    | int
    | float
    | JsonSchema
    | Mapping[str, JsonSchema]
    | Sequence[JsonValue]
    | ConstValue
    | None
)


@dataclass(frozen=True, slots=True)
class FlattenedSchema:
    """A composition tree merged into one schema, with any warnings raised on the way."""

    schema: JsonSchema
    warnings: Sequence[TranspilationWarning] = ()


@dataclass
class SchemaFlattener:
    """Merges `allOf` branches and `$ref` targets into a single `ObjectSchema`.

    Attributes:
        resolver: Resolves `$ref` strings to CST nodes.
            Without one, a `$ref` is left in place and its target contributes nothing.
    """

    resolver: JsonSchemaRefResolver | None = None
    _warnings: list[TranspilationWarning] = field(default_factory=list, repr=False)

    def flatten(self, schema: JsonSchema, *, base_uri: str) -> FlattenedSchema:
        """Merge `schema`'s `allOf` branches and `$ref` target into one schema.

        Only this schema's own composition is resolved; sub-schemas are left as written.
        Use `inline` when the result must stand alone.
        """
        self._warnings.clear()
        merged = self._flatten(schema, base_uri=base_uri, seen=frozenset(), depth=0)
        return FlattenedSchema(schema=merged, warnings=tuple(self._warnings))

    def inline(self, schema: JsonSchema, *, base_uri: str) -> FlattenedSchema:
        """Flatten `schema` and every sub-schema, leaving no `$ref` anywhere in the result.

        Needed wherever a schema is handed to something that cannot follow a reference —
        `pg_jsonschema`, for instance, validates against a literal embedded in the DDL
        and has no way to fetch `./other-file.yaml#/thing`.
        """
        self._warnings.clear()
        merged = self._inline(schema, base_uri=base_uri, seen=frozenset(), depth=0)
        return FlattenedSchema(schema=merged, warnings=tuple(self._warnings))

    # ------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------

    def _flatten(
        self, schema: JsonSchema, *, base_uri: str, seen: frozenset[str], depth: int
    ) -> JsonSchema:
        if isinstance(schema, BooleanSchema) or depth > _MAX_DEPTH:
            return schema
        own = replace(schema, ref=None, all_of=None)
        parts = self._parts(schema, base_uri=base_uri, seen=seen, depth=depth)
        for part in parts:
            own = self._merge(own, part)
        return own

    def _inline(
        self, schema: JsonSchema, *, base_uri: str, seen: frozenset[str], depth: int
    ) -> JsonSchema:
        flat = self._flatten(schema, base_uri=base_uri, seen=seen, depth=depth)
        if isinstance(flat, BooleanSchema) or depth > _MAX_DEPTH:
            return flat
        children = self._inline_children(flat, base_uri=base_uri, seen=seen, depth=depth)
        return replace(flat, **children)

    def _inline_children(
        self, schema: ObjectSchema, *, base_uri: str, seen: frozenset[str], depth: int
    ) -> dict[str, _SubSchemaValue]:
        """Inline every keyword whose value holds sub-schemas.

        Driven by the same field metadata the parser dispatches on, so a keyword
        added to `ObjectSchema` is covered here without touching this method.
        """

        def step(sub: JsonSchema) -> JsonSchema:
            return self._inline(sub, base_uri=base_uri, seen=seen, depth=depth + 1)

        out: dict[str, _SubSchemaValue] = {}
        for f in fields(ObjectSchema):
            kind = f.metadata.get("kind")
            value = getattr(schema, f.name)
            if kind not in _SUB_SCHEMA_KINDS or value is None:
                continue
            if kind == "optional_schema":
                out[f.name] = step(value)
            elif kind == "schema_list":
                out[f.name] = [step(sub) for sub in value]
            else:
                out[f.name] = {name: step(sub) for name, sub in value.items()}
        return out

    def _parts(
        self, schema: ObjectSchema, *, base_uri: str, seen: frozenset[str], depth: int
    ) -> list[ObjectSchema]:
        """Return the flattened `$ref` target and `allOf` branches contributing to `schema`."""
        sources: list[JsonSchema] = []
        if schema.ref is not None:
            target = self._resolve(schema.ref, base_uri=base_uri, seen=seen, schema=schema)
            if target is not None:
                sources.append(target)
                seen |= {schema.ref}
        sources.extend(schema.all_of or ())
        parts: list[ObjectSchema] = []
        for source in sources:
            flat = self._flatten(source, base_uri=base_uri, seen=seen, depth=depth + 1)
            if isinstance(flat, ObjectSchema):
                parts.append(flat)
            elif not flat.value:
                self._warn(
                    "An `allOf` branch is `false`, so no value can satisfy this schema.",
                    code="unsatisfiable-branch",
                    schema=schema,
                )
        return parts

    def _resolve(
        self, ref: str, *, base_uri: str, seen: frozenset[str], schema: ObjectSchema
    ) -> JsonSchema | None:
        if ref in seen:
            self._warn(f"Ignoring recursive $ref {ref!r}.", code="recursive-ref", schema=schema)
            return None
        if self.resolver is None:
            return None
        target = self.resolver.lookup(ref, base_uri=base_uri)
        if target is None:
            self._warn(f"Cannot resolve $ref {ref!r}.", code="unresolved-ref", schema=schema)
        return target

    # ------------------------------------------------------------------
    # Merging
    # ------------------------------------------------------------------

    def _merge(self, base: ObjectSchema, other: ObjectSchema) -> ObjectSchema:
        return replace(
            base,
            type=_intersect_types(base, other),
            properties=self._merge_properties(base, other),
            required=_union_or_none(base.required, other.required),
            extensions={**other.get_extensions(), **base.get_extensions()},
            **_first_set(base, other),
        )

    def _merge_properties(
        self, base: ObjectSchema, other: ObjectSchema
    ) -> Mapping[str, JsonSchema] | None:
        if base.properties is None or other.properties is None:
            return base.properties if other.properties is None else other.properties
        # `setdefault`, not `{**other, **base}`: a property keeps both the value *and* the
        # position of its first definition, so columns come out in declaration order.
        merged = dict(base.properties)
        for name, schema in other.properties.items():
            if name in merged and not _same_schema(merged[name], schema):
                self._warn(
                    f"Property {name!r} is defined by more than one `allOf` branch; "
                    f"keeping the first definition.",
                    code="conflicting-property",
                    schema=base,
                )
            merged.setdefault(name, schema)
        return merged

    def _warn(self, msg: str, *, code: str, schema: ObjectSchema) -> None:
        location = None
        if schema.source_ref:
            location = SourceLocation(
                doc_id=schema.source_ref.source_id, json_pointer=schema.source_ref.json_pointer
            )
        self._warnings.append(TranspilationWarning(msg, code=code, location=location))


# ---------------------------------------------------------------------------
# Keyword-level merge helpers
# ---------------------------------------------------------------------------


def _same_schema(a: JsonSchema, b: JsonSchema) -> bool:
    """Report whether two schemas say the same thing.

    CST nodes carry a `source_ref`, so two branches that spell out an identical schema
    are unequal as values.  Comparing the serialized form ignores provenance.
    """
    serializer = JsonSchemaSerializer()
    return serializer.serialize(a) == serializer.serialize(b)


# Keywords a single branch either sets or leaves alone; the first branch to set one wins.
# No schema that a table can be generated from sets one of these on two `allOf` branches.
_FIRST_SET_KEYWORDS = (
    "title",
    "description",
    "format",
    "pattern",
    "enum",
    "const",
    "minimum",
    "maximum",
    "exclusive_minimum",
    "exclusive_maximum",
    "min_length",
    "max_length",
    "items",
    "property_names",
    "additional_properties",
    "unevaluated_properties",
    "pattern_properties",
    "read_only",
    "write_only",
)


def _first_set(base: ObjectSchema, other: ObjectSchema) -> dict[str, _KeywordValue]:
    """Return the keywords `base` leaves unset and `other` supplies."""
    out: dict[str, _KeywordValue] = {}
    for name in _FIRST_SET_KEYWORDS:
        value = getattr(base, name)
        # Identity, not equality: `False` is the unset state for the boolean keywords,
        # but `0 == False`, and `0` is a real bound for `minimum` and friends.
        if value is None or value is False:
            out[name] = getattr(other, name)
    return out


def _intersect_types(base: ObjectSchema, other: ObjectSchema) -> SchemaType | None:
    """Intersect the declared types, treating an absent `type` as unconstrained."""
    base_types, other_types = base.get_types(), other.get_types()
    if not base_types or not other_types:
        return _as_schema_type(base_types or other_types)
    return _as_schema_type(base_types & other_types)


def _as_schema_type(types: frozenset[JsonSchemaType]) -> SchemaType | None:
    if not types:
        return None
    if len(types) == 1:
        return next(iter(types))
    return types


def _union_or_none(a: frozenset[str] | None, b: frozenset[str] | None) -> frozenset[str] | None:
    if a is None or b is None:
        return a if b is None else b
    return a | b
