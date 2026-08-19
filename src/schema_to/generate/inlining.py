"""Resolution of `allOf` composition and `$ref` indirection into a single schema.

Targets that map one schema to one flat structure — a SQL table, a dataclass —
cannot act on `allOf` directly:
the keywords they read (`properties`, `required`) live on the branches, not on the
schema that composes them.

Three terms, used strictly in this sense throughout the module:

- **Merging**
  combines exactly two schemas into one, keyword by keyword.
  It is the non-recursive primitive the other two are built from.
- **Flattening**
  resolves one schema's own composition:
  It merges in each `allOf`  branch and the `$ref` target, recursively, and clears both keywords.
  Sub-schemas are left as written, so a `$ref` may remain deeper in the tree.
- **Inlining**
  flattens a schema and every sub-schema, so nothing anywhere in the result is a `$ref`.
  Needed only when the result is handed to something that
  cannot follow a reference, such as `pg_jsonschema`.

Merging follows JSON Schema semantics where a target can express them
and falls back to a documented choice where it cannot:

- `properties` are unioned;
  a name defined by more than one branch keeps its first definition and raises a warning,
  since a column has exactly one type.
- `required` is unioned, matching `allOf` exactly.
- `type` is intersected across the branches that declare it, matching `allOf` exactly.
- A singular keyword (`description`, `propertyNames`, …)
  is taken from the first schema that sets one.
  Two `allOf` branches disagreeing on a **constraint** warns,
  because only one of the two assertions survives into the output.
  Disagreeing on a `title` or `description` does not,
  and neither does a keyword written beside a `$ref`,
  since overriding the target is what that idiom is for.
- A resolved `$ref` target brings its own document with it,
  so a reference written  inside it resolves against **that** file,
  rather than against the one pointing at it.
- Extensions merge with the outer schema winning,
  so a `$ref`ed schema cannot override an `x-pg-*` keyword written at the point of use.
"""

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from schema_to.cst.json_schema import (
    DOC_KEYWORDS,
    SINGULAR_KEYWORDS,
    BooleanSchema,
    JsonSchema,
    ObjectSchema,
)
from schema_to.errors import SourceLocation, TranspilationWarning
from schema_to.parse._plan import ListSpec, MapSpec, SchemaSpec, sub_schema_fields
from schema_to.serialize.json_schema import JsonSchemaSerializer

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence, Set

    from schema_to.core import JsonValue
    from schema_to.cst.json_schema import ConstValue, JsonSchemaType, SchemaType
    from schema_to.resolve.json_schema import JsonSchemaRefResolver

__all__ = ["FlatteningResult", "SchemaFlattener"]

# Guards against a `$ref` cycle that `_seen` cannot catch, e.g. one built from `$dynamicRef`.
_MAX_DEPTH = 32

# What `_inline_children` puts back on a schema, matching the three shapes a
# sub-schema-bearing keyword can take.
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
class FlatteningResult:
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

    def flatten(self, schema: JsonSchema, *, base_uri: str) -> FlatteningResult:
        """Merge `schema`'s `allOf` branches and `$ref` target into one schema.

        Only this schema's own composition is resolved; sub-schemas are left as written.
        Use `inline` when the result must stand alone.
        """
        self._warnings.clear()
        merged = self._flatten(schema, base_uri=base_uri, seen=frozenset(), depth=0)
        return FlatteningResult(schema=merged, warnings=tuple(self._warnings))

    def inline(self, schema: JsonSchema, *, base_uri: str) -> FlatteningResult:
        """Flatten `schema` and every sub-schema, leaving no `$ref` anywhere in the result.

        Needed wherever a schema is handed to something that cannot follow a reference.
        `pg_jsonschema`, for instance, validates against a literal embedded in the DDL,
        and it has no way to fetch `./other-file.yaml#/thing`.
        """
        self._warnings.clear()
        merged = self._inline(schema, base_uri=base_uri, seen=frozenset(), depth=0)
        return FlatteningResult(schema=merged, warnings=tuple(self._warnings))

    # ------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------

    def _flatten(
        self, schema: JsonSchema, *, base_uri: str, seen: Set[str], depth: int
    ) -> JsonSchema:
        if isinstance(schema, BooleanSchema) or depth > _MAX_DEPTH:
            return schema
        own = replace(schema, ref=None, all_of=None)
        for part, from_ref in self._parts(schema, base_uri=base_uri, seen=seen, depth=depth):
            own = self._merge(own, part, from_ref=from_ref)
        return own

    def _inline(
        self, schema: JsonSchema, *, base_uri: str, seen: Set[str], depth: int
    ) -> JsonSchema:
        flat = self._flatten(schema, base_uri=base_uri, seen=seen, depth=depth)
        if isinstance(flat, BooleanSchema) or depth > _MAX_DEPTH:
            return flat
        children = self._inline_children(flat, base_uri=base_uri, seen=seen, depth=depth)
        return replace(flat, **children)

    def _inline_children(
        self, schema: ObjectSchema, *, base_uri: str, seen: Set[str], depth: int
    ) -> dict[str, _SubSchemaValue]:
        """Inline every keyword whose value holds sub-schemas.

        Driven by the same plans the parser and serializer run on,
        so a keyword added to `ObjectSchema` is covered here without touching this method.
        """

        def step(sub: JsonSchema) -> JsonSchema:
            return self._inline(sub, base_uri=_base_of(sub, base_uri), seen=seen, depth=depth + 1)

        out: dict[str, _SubSchemaValue] = {}
        for entry in sub_schema_fields(ObjectSchema):
            value = getattr(schema, entry.name)
            match entry.spec:
                case _ if value is None:
                    continue
                case SchemaSpec():
                    out[entry.name] = step(value)
                case ListSpec():
                    out[entry.name] = [step(sub) for sub in value]
                case MapSpec():
                    out[entry.name] = {name: step(sub) for name, sub in value.items()}
                case _:  # pragma: no cover
                    msg = f"{entry.spec} should not hold a subschema"
                    raise AssertionError(msg)
        return out

    def _parts(
        self, schema: ObjectSchema, *, base_uri: str, seen: Set[str], depth: int
    ) -> list[tuple[ObjectSchema, bool]]:
        """Return the flattened `$ref` target and `allOf` branches contributing to `schema`.

        Each is paired with whether it came from the `$ref`,
        which decides how a keyword set on both it and `schema` is treated.
        """
        sources: list[tuple[JsonSchema, bool]] = []
        if schema.ref is not None:
            target = self._resolve(schema.ref, base_uri=base_uri, seen=seen, schema=schema)
            if target is not None:
                sources.append((target, True))
                seen |= {schema.ref}
        sources.extend((branch, False) for branch in schema.all_of or ())
        parts: list[tuple[ObjectSchema, bool]] = []
        for source, from_ref in sources:
            # A resolved target brings its own document with it: a `$ref` written inside
            # it is relative to *that* file, not to the one that pointed at it.
            flat = self._flatten(
                source, base_uri=_base_of(source, base_uri), seen=seen, depth=depth + 1
            )
            if isinstance(flat, ObjectSchema):
                parts.append((flat, from_ref))
            elif not flat.value:
                self._warn(
                    "An `allOf` branch is `false`, so no value can satisfy this schema.",
                    code="unsatisfiable-branch",
                    schema=schema,
                )
        return parts

    def _resolve(
        self, ref: str, *, base_uri: str, seen: Set[str], schema: ObjectSchema
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

    def _merge(self, base: ObjectSchema, other: ObjectSchema, *, from_ref: bool) -> ObjectSchema:
        return replace(
            base,
            type=_intersect_types(base, other),
            properties=self._merge_properties(base, other),
            required=_union_or_none(base.required, other.required),
            extensions={**other.get_extensions(), **base.get_extensions()},
            **self._merge_singular(base, other, from_ref=from_ref),
        )

    def _merge_singular(
        self, base: ObjectSchema, other: ObjectSchema, *, from_ref: bool
    ) -> dict[str, _KeywordValue]:
        """Take each singular keyword from the first schema that sets one.

        `allOf` means both assertions hold.
        However, one must be chosen for a flat schema.

        A warning is issued if, for a keyword <var>k</var>:

        - <var>k</var> is neither `title` nor `description`;
        - There exist 2 branches providing different values for <var>k</var>;
        - Neither value is the default (unspecified); and
        - Neither value is provided as a sibling of a `$ref`
          (E.g. `{"$ref": "#/foo", "minimum": 1}`).
        """
        out: dict[str, _KeywordValue] = {}
        for name in SINGULAR_KEYWORDS:
            mine, theirs = getattr(base, name), getattr(other, name)
            # TODO: How does this if condition work? Don't we still need to warn for some cases?
            # Identity, not equality: `False` is the unset state for the boolean keywords,
            # but `0 == False`, and `0` is a real bound for `minimum` and friends.
            if mine is None or mine is False:
                out[name] = theirs
            elif self._is_conflict(name, mine, theirs, from_ref=from_ref):
                self._warn(
                    f"Keyword {name!r} is set to conflicting values by more than one "
                    f"`allOf` branch; keeping the first.",
                    code="conflicting-keyword",
                    schema=base,
                )
        return out

    def _is_conflict(
        self, name: str, mine: _KeywordValue, theirs: _KeywordValue, *, from_ref: bool
    ) -> bool:
        """Report whether losing `theirs` to `mine` costs anything important."""
        if from_ref or name in DOC_KEYWORDS:
            return False
        return theirs is not None and theirs is not False and mine != theirs

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


def _base_of(schema: JsonSchema, fallback: str) -> str:
    """Return the document a schema was parsed from, for resolving its relative refs."""
    if schema.source_ref is not None:
        return schema.source_ref.source_id
    return fallback


def _same_schema(a: JsonSchema, b: JsonSchema) -> bool:
    """Report whether two schemas say the same thing.

    CST nodes carry a `source_ref`,
    so two branches that spell out an identical schema are unequal as values.
    Comparing the serialized form ignores provenance.
    """
    serializer = JsonSchemaSerializer()
    return serializer.serialize(a) == serializer.serialize(b)


def _intersect_types(base: ObjectSchema, other: ObjectSchema) -> SchemaType | None:
    """Intersect the declared types, treating an absent `type` as unconstrained."""
    base_types, other_types = base.get_types(), other.get_types()
    if not base_types or not other_types:
        return _as_schema_type(base_types or other_types)
    return _as_schema_type(base_types & other_types)


def _as_schema_type(types: Set[JsonSchemaType]) -> SchemaType | None:
    if not types:
        return None
    if len(types) == 1:
        return next(iter(types))
    return types


def _union_or_none(a: Set[str] | None, b: Set[str] | None) -> Set[str] | None:
    if a is None or b is None:
        return a if b is None else b
    return a | b
