"""Generator: Pydantic classes from JSON Schema.

#### Mapping rules

- An `object`-typed schema (root or `$defs` entry) becomes a
  `pydantic.BaseModel` subclass (`ClassStyle.PYDANTIC`).
- Non-object named schemas become PEP 695 `type` aliases.
- Properties that appear in `required` get a plain annotation;
  all others get `T | None = None`.
- `$ref: "#/$defs/Name"` becomes a forward reference to the generated class.
- A declaration composed with `allOf` is flattened first,
  so the model carries every branch's fields.
  Only the declaration's own composition is resolved:
  A bare `$ref` stays an alias,
  and a property referencing another schema stays a reference to its class,
  since inlining either would replace a named model with a copy.
- `anyOf` / `oneOf` with exactly one non-null branch collapses to `T | None`.
- `enum` / `const` map to `Literal[…]`, unless `x-pydantic-enum` requests a real `Enum` class.
- Unsupported constructs emit `TranspilationWarning` and fall back to `Any`.

#### Extension keywords

`x-pydantic-frozen`, `x-pydantic-skip`, `x-pydantic-class`, and `x-pydantic-enum`
adjust generation beyond what JSON Schema itself expresses. See
[generate.pydantic._pydantic_keywords][] for the keyword vocabulary.
"""

import re
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, assert_never

from schema_to.ast.python import (
    ClassDef,
    ClassStyle,
    EnumDef,
    EnumMemberDef,
    FieldDef,
    FromImport,
    PyDeclaration,
    PythonDocString,
    PythonModule,
    PythonTypeAnnotation,
    TypeAliasDef,
)
from schema_to.core import JsonArray, JsonPrimitive, JsonValue, is_json_primitive_sequence
from schema_to.cst.json_schema import (
    BooleanSchema,
    JsonSchema,
    JsonSchemaDocument,
    JsonSchemaType,
    ObjectSchema,
    is_object_schema,
)
from schema_to.errors import GenerationError, SourceLocation, TranspilationWarning
from schema_to.generate._python_utils import (
    ANY,
    NONE,
    PRIMITIVE_MAP,
    STR,
    literal_of,
    nullable_of,
    safe_python_class_name,
    safe_python_field_name,
    split_class_name,
    to_snake,
)
from schema_to.generate.inlining import SchemaFlattener
from schema_to.generate.pydantic._pydantic_keywords import (
    EnumKeyword,
    read_class,
    read_enum,
    read_frozen,
    read_skip,
)
from schema_to.pipeline import Transformer
from schema_to.result import Err, Ok, Result

if TYPE_CHECKING:
    from schema_to.resolve.json_schema import JsonSchemaRefResolver

__all__ = ["PydanticTransformer"]

type _Variant = Literal["read", "write"] | None
"""Which half of a readOnly/writeOnly split a class or annotation is for; `None` outside a split."""


# ---------------------------------------------------------------------------
# `x-pydantic-enum` helpers
# ---------------------------------------------------------------------------

_NON_IDENT = re.compile(r"\W")
SUPPORTED_ENUM_BASE = Literal["Enum", "StrEnum", "IntEnum"]


def _classify_enum_base(values: Sequence[JsonValue]) -> SUPPORTED_ENUM_BASE:
    """Pick `StrEnum`/`IntEnum`/`Enum` from the enum's value types.

    JSON `true`/`false` are Python `bool`, itself an `int` subclass, so they are
    excluded from the integer check to avoid misclassifying a boolean enum as `IntEnum`.
    """
    if values and all(isinstance(v, str) for v in values):
        return "StrEnum"
    if values and all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        return "IntEnum"
    return "Enum"


def _enum_member_name(value: JsonPrimitive) -> str:
    """Derive a unique `UPPER_SNAKE_CASE` member identifier for *value*."""
    match value:
        case bool(v):
            name = "TRUE" if v else "FALSE"
        case str(v):
            name = _NON_IDENT.sub("_", to_snake(v).upper())
            name = re.sub(r"_+", "_", name).strip("_") or "EMPTY"
            if name[0].isdigit():
                name = f"V_{name}"
        case int(v):
            name = f"NEG_{-v}" if v < 0 else f"VALUE_{v}"
        case float(v):
            digits = str(v).replace(".", "_").replace("-", "")
            name = f"NEG_{digits}" if value < 0 else f"VALUE_{digits}"
        case None:
            name = "NONE"
        case _:
            assert_never(value)
    return name


def _build_enum_def(
    name: str, values: Sequence[JsonPrimitive], enum_kw: EnumKeyword, doc: PythonDocString | None
) -> EnumDef:
    """Build an `EnumDef` for *values*, or `None` if a value can't become a member."""
    base = enum_kw.base or _classify_enum_base(values)
    base_module = "enum" if base in SUPPORTED_ENUM_BASE else None
    is_int_auto = base == "IntEnum" and list(values) == list(range(1, len(values) + 1))
    members: list[EnumMemberDef] = []
    for v in values:
        member_name = _enum_member_name(v)
        if is_int_auto or (base == "StrEnum" and isinstance(v, str) and v == member_name.lower()):
            expr = "auto()"
        else:
            expr = repr(v)
        members.append(EnumMemberDef(name=member_name, value=expr))
    return EnumDef(
        name=safe_python_class_name(name),
        base=base,
        base_module=base_module,
        members=members,
        doc=doc,
    )


def _has_split_properties(schema: JsonSchema) -> bool:
    """Return True if *schema* has any `readOnly` or `writeOnly` property."""
    if not isinstance(schema, ObjectSchema) or not schema.properties:
        return False
    return any(
        isinstance(p, ObjectSchema) and (p.read_only or p.write_only)
        for p in schema.properties.values()
    )


def _compute_split_names(input: JsonSchemaDocument, overrides: Mapping[str, str]) -> Set[str]:
    """Return the canonical class names of schemas that need a Read/Write split."""
    names: set[str] = set()
    if isinstance(input.root, ObjectSchema) and input.root.defs:
        for def_name, def_schema in input.root.defs.items():
            if _has_split_properties(def_schema):
                names.add(safe_python_class_name(overrides.get(def_name, def_name)))
    if _has_split_properties(input.root):
        names.add(_root_class_name(input))
    return frozenset(names)


def _compute_name_overrides(input: JsonSchemaDocument) -> Mapping[str, str]:
    """Return the `x-pydantic-class` override for each `$defs` entry that sets one."""
    overrides: dict[str, str] = {}
    if isinstance(input.root, ObjectSchema) and input.root.defs:
        for def_name, def_schema in input.root.defs.items():
            if not isinstance(def_schema, ObjectSchema):
                continue
            override = read_class(def_schema.get_extensions(), where=f"schema {def_name!r}")
            if override:
                overrides[def_name] = override
    return overrides


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PydanticTransformer(Transformer[JsonSchemaDocument, PythonModule]):
    """Generates a `PythonModule` with Pydantic v2 `BaseModel` classes.

    Attributes:
        resolver: Optional resolver for cross-document `$ref` lookup.
        roots: If given, only `$defs` entries named here become their own declaration;
            the rest are still available for `$ref` resolution.
            `None` emits every entry.
    """

    resolver: JsonSchemaRefResolver | None = None
    roots: Set[str] | None = None

    def apply(self, input: JsonSchemaDocument) -> Result[PythonModule]:
        warnings: list[TranspilationWarning] = []
        try:
            name_overrides = _compute_name_overrides(input)
            ctx = _GenCtx(
                source_id=input.source_id,
                resolver=self.resolver,
                warnings=warnings,
                base_uri=input.get_base_uri(),
                split_names=_compute_split_names(input, name_overrides),
                name_overrides=name_overrides,
            )
            declarations = ctx.build_declarations(input, roots=self.roots)
        except GenerationError as exc:
            return Err((exc,), warnings=tuple(warnings))

        if not declarations:
            error = GenerationError(
                "Root schema is a boolean schema; cannot generate a Pydantic model."
            )
            return Err((error,), warnings=tuple(warnings))

        # Enum classes synthesized from inline (property-level) `x-pydantic-enum` schemas
        # must precede any declaration referencing them, since generated code doesn't use
        # `from __future__ import annotations` or string annotations.
        declarations = [*ctx.enum_decls, *declarations]
        imports = _build_imports(declarations)
        return Ok(
            PythonModule(
                name=_module_name(input),
                imports=imports,
                declarations=declarations,
                source_ids=(input.source_id,),
            ),
            warnings=tuple(warnings),
        )


def _module_name(doc: JsonSchemaDocument) -> str:
    """Name the module after the document, then the source ID's last segment.

    Unlike the root class, the module is not named after `title`: a title describes
    the schema, whereas the file the models land in is the document they came from,
    and two documents titled alike would otherwise write one file.
    """
    if doc.display_name:
        return safe_python_field_name(doc.display_name)
    return safe_python_field_name(doc.source_id.rstrip("/").rsplit("/", 1)[-1])


def _root_class_name(doc: JsonSchemaDocument) -> str:
    """Name the root model.

    Prefers `x-pydantic-class`, then `title`, then `display_name`,
    then the source ID's last segment.
    """
    if isinstance(doc.root, ObjectSchema):
        override = read_class(doc.root.get_extensions(), where="the root schema")
        if override:
            return safe_python_class_name(override)
        if doc.root.title:
            return safe_python_class_name(doc.root.title)
    if doc.display_name:
        return safe_python_class_name(doc.display_name)
    return safe_python_class_name(doc.source_id.rstrip("/").rsplit("/", 1)[-1])


# ---------------------------------------------------------------------------
# Generation context (internal)
# ---------------------------------------------------------------------------


@dataclass
class _GenCtx:
    """Per-document generation state threaded through the CST walk.

    Holds the source document identifier, an optional ref resolver for
    cross-document `$ref` lookup, and the mutable warnings list that is
    shared with the owning `PydanticGenerator`.
    """

    source_id: str
    resolver: JsonSchemaRefResolver | None
    warnings: list[TranspilationWarning]
    base_uri: str = ""
    split_names: Set[str] = field(default_factory=frozenset)
    name_overrides: Mapping[str, str] = field(default_factory=dict)
    enum_decls: list[EnumDef] = field(default_factory=list)
    enum_name_cache: dict[int, str] = field(default_factory=dict)

    def build_declarations(
        self, input: JsonSchemaDocument, *, roots: Set[str] | None
    ) -> list[PyDeclaration]:
        """Convert every `$defs` entry (subject to *roots*) and the root schema."""
        declarations: list[PyDeclaration] = []
        if isinstance(input.root, ObjectSchema) and input.root.defs:
            for def_name, def_schema in input.root.defs.items():
                if roots is not None and def_name not in roots:
                    continue
                effective_name = self.name_overrides.get(def_name, def_name)
                declarations.extend(self.schema_to_declarations(def_schema, name=effective_name))
        root_name = _root_class_name(input)
        declarations.extend(self.schema_to_declarations(input.root, name=root_name))
        return declarations

    def schema_to_declarations(self, schema: JsonSchema, name: str) -> list[PyDeclaration]:
        """Convert a top-level schema to one or two declaration nodes.

        Returns two `ClassDef`s (Read/Write) when *schema* has any
        `readOnly`/`writeOnly` property, one otherwise; an empty list for
        boolean schemas.
        """
        if isinstance(schema, BooleanSchema):
            return []
        schema = self._composed(schema)
        if is_object_schema(schema):
            if safe_python_class_name(name) in self.split_names:
                return [
                    self._make_class(schema, name, variant="read"),
                    self._make_class(schema, name, variant="write"),
                ]
            return [self._make_class(schema, name, variant=None)]
        doc = None
        if schema.title or schema.description:
            doc = PythonDocString(
                summary=schema.title or schema.description or "",
                description=schema.description if schema.title else None,
            )
        if schema.enum is not None:
            enum_decl = self._top_level_enum(schema, schema.enum, name=name, doc=doc)
            if enum_decl is not None:
                return [enum_decl]
        ann = self.schema_to_annotation(schema, required=True)
        return [TypeAliasDef(name=safe_python_class_name(name), annotation=ann, doc=doc)]

    def _top_level_enum(
        self, schema: ObjectSchema, values: JsonArray, *, name: str, doc: PythonDocString | None
    ) -> EnumDef | None:
        """Build the `EnumDef` for a `$defs` entry or root schema, if `x-pydantic-enum` asks for one.

        *values* is *schema*'s already-known `enum` list, passed in rather than read again
        here so the type checker can see it is not `None` without an `assert`.

        `x-pydantic-enum`'s own `name` is ignored here: the name is already resolved
        (via `x-pydantic-class`, title, etc.) before this runs, and letting the enum
        keyword rename it too would silently diverge from what `$ref`s targeting this
        schema resolve to, since `_ref_to_class_name` has no visibility into it.
        """
        enum_kw = read_enum(schema.get_extensions(), where=f"schema {name!r}")
        if enum_kw is None:
            return None
        if is_json_primitive_sequence(values):
            return _build_enum_def(name, values, enum_kw, doc)
        self._warn(
            "enum contains list/dict values, which cannot become Enum members; using Literal.",
            code="enum-value-unsupported",
            schema=schema,
        )
        return None

    def _composed(self, schema: ObjectSchema) -> ObjectSchema:
        """Merge an `allOf` composition so the model gets every branch's fields.

        Only composition is resolved, and only here.  A declaration that is a bare
        `$ref` stays an alias to the class its target generates, and a *property*
        that references another schema still becomes a reference to that class —
        inlining either would replace a named model with a copy of its contents.
        """
        if not schema.all_of:
            return schema
        result = SchemaFlattener(resolver=self.resolver).flatten(
            schema, base_uri=self.base_uri or self.source_id
        )
        self.warnings.extend(result.warnings)
        return result.schema if isinstance(result.schema, ObjectSchema) else schema

    def _make_class(self, schema: ObjectSchema, name: str, *, variant: _Variant) -> ClassDef:
        class_name = (
            split_class_name(name, variant) if variant is not None else safe_python_class_name(name)
        )
        canonical_name = safe_python_class_name(name)
        required_set = set(schema.required or frozenset())
        fields = [
            self._build_field_def(
                prop_name,
                prop_schema,
                is_required=(prop_name in required_set),
                variant=variant,
                canonical_class_name=canonical_name,
            )
            for prop_name, prop_schema in (schema.properties or {}).items()
            if self._field_included(prop_name, prop_schema, variant=variant)
        ]
        doc_node: PythonDocString | None = None
        if schema.title or schema.description:
            doc_node = PythonDocString(
                summary=schema.title or schema.description or "",
                description=schema.description if schema.title else None,
            )
        frozen = read_frozen(schema.get_extensions(), where=f"schema {name!r}")
        style = ClassStyle.PYDANTIC_FROZEN if frozen else ClassStyle.PYDANTIC
        return ClassDef(name=class_name, style=style, fields=fields, doc=doc_node)

    def _field_included(
        self, prop_name: str, prop_schema: JsonSchema, *, variant: _Variant
    ) -> bool:
        if not isinstance(prop_schema, ObjectSchema):
            return True
        if read_skip(prop_schema.get_extensions(), where=f"property {prop_name!r}"):
            return False
        if variant is None:
            return True
        if variant == "read":
            return not prop_schema.write_only
        return not prop_schema.read_only

    def _build_field_def(
        self,
        prop_name: str,
        prop_schema: JsonSchema,
        *,
        is_required: bool,
        canonical_class_name: str,
        variant: _Variant = None,
    ) -> FieldDef:
        """Build the field declaration for one property.

        *canonical_class_name* is the un-suffixed name of the class *prop_schema* belongs
        to (i.e. before any Read/Write split), used as the prefix for a class name derived
        from `x-pydantic-enum: true`. Passing the same canonical name for both the Read and
        Write variant is what lets them share one enum class instead of each emitting a copy.
        """
        name_hint = f"{canonical_class_name}{safe_python_class_name(prop_name)}"
        ann = self.schema_to_annotation(
            prop_schema, required=is_required, variant=variant, name_hint=name_hint
        )
        py_name = safe_python_field_name(prop_name)
        alias = f'alias="{prop_name}"' if py_name != prop_name else ""
        default_ = self._build_field_default(prop_schema, is_required=is_required)
        doc: str | None = None
        if isinstance(prop_schema, ObjectSchema):
            doc = prop_schema.description or prop_schema.title
        field_kw = self._build_field_kwargs(prop_schema, alias=alias)
        if field_kw:
            default_ = (
                f"Field({', '.join(field_kw)})"
                if default_ is None
                else f"Field({default_}, {', '.join(field_kw)})"
            )
        return FieldDef(name=py_name, annotation=ann, default=default_, doc=doc)

    def _build_field_default(self, prop_schema: JsonSchema, *, is_required: bool) -> str | None:
        if not is_required:
            return "None"
        if isinstance(prop_schema, ObjectSchema) and prop_schema.default is not None:
            # TODO: `MutableSequence` and `MutableSequence` don't define `repr`.
            return repr(prop_schema.default.value)
        return None

    def _build_field_kwargs(self, prop_schema: JsonSchema, *, alias: str) -> list[str]:
        field_kw: list[str] = []
        if alias:
            field_kw.append(alias)
        if isinstance(prop_schema, ObjectSchema):
            if prop_schema.min_length is not None:
                field_kw.append(f"min_length={prop_schema.min_length}")
            if prop_schema.max_length is not None:
                field_kw.append(f"max_length={prop_schema.max_length}")
            if prop_schema.minimum is not None:
                field_kw.append(f"ge={prop_schema.minimum}")
            if prop_schema.maximum is not None:
                field_kw.append(f"le={prop_schema.maximum}")
            if prop_schema.pattern is not None:
                field_kw.append(f"pattern={prop_schema.pattern!r}")
        return field_kw

    def schema_to_annotation(
        self,
        schema: JsonSchema,
        *,
        required: bool,
        variant: _Variant = None,
        name_hint: str | None = None,
    ) -> PythonTypeAnnotation:
        """Return the Python type annotation for a field's schema."""
        ann = self._annotation_inner(schema, variant=variant, name_hint=name_hint)
        if not required and not ann.nullable and ann != NONE:
            ann = nullable_of(ann)
        return ann

    def _ref_to_class_name(self, ref: str, *, variant: _Variant) -> str:
        """Extract a class name from a `$ref` like `"#/$defs/MyModel"`.

        If the referenced schema is itself split into Read/Write variants, the
        *current* variant is propagated; a ref from a non-split context
        defaults to the Read variant, since JSON Schema gives no other signal.
        """
        fragment = ref.split("#", 1)[-1] if "#" in ref else ref
        part = fragment.rstrip("/").rsplit("/", 1)[-1]
        if not part:
            return "Unknown"
        name = self.name_overrides.get(part, part)
        base = safe_python_class_name(name)
        if base in self.split_names:
            return split_class_name(name, variant if variant is not None else "read")
        return base

    def _annotation_inner(
        self, schema: JsonSchema, *, variant: _Variant = None, name_hint: str | None = None
    ) -> PythonTypeAnnotation:
        if isinstance(schema, BooleanSchema):
            return ANY if schema.value else PythonTypeAnnotation("Never", module="typing")
        if schema.ref:
            return PythonTypeAnnotation(self._ref_to_class_name(schema.ref, variant=variant))
        if schema.enum is not None:
            return self._inline_enum_annotation(schema, schema.enum, name_hint=name_hint)
        if schema.const is not None:
            return literal_of(schema.const.value)
        ann = self._annotation_from_applicators(schema, variant=variant, name_hint=name_hint)
        if ann is not None:
            return ann
        return self._annotation_from_type(schema, variant=variant, name_hint=name_hint)

    def _inline_enum_annotation(
        self, schema: ObjectSchema, values: Sequence[JsonValue], *, name_hint: str | None
    ) -> PythonTypeAnnotation:
        """Build (or reuse) the `EnumDef` for an inline (property-level) `enum` schema.

        Falls back to `Literal[…]` when `x-pydantic-enum` isn't set, or when it is but the
        values can't become `Enum` members (a `list`/`dict` value; see `_build_enum_def`).

        Reuse is keyed by the schema node's identity: a readOnly/writeOnly split visits the
        same property schema twice (once per Read/Write variant class), and both visits carry
        the same *canonical* `name_hint`, so the second visit reuses the first's class name
        instead of emitting a duplicate declaration.
        """
        where = f"schema for {name_hint!r}" if name_hint else "an inline enum"
        enum_kw = read_enum(schema.get_extensions(), where=where)
        if enum_kw is None:
            return literal_of(*values)
        cached = self.enum_name_cache.get(id(schema))
        if cached is not None:
            return PythonTypeAnnotation(cached)
        if is_json_primitive_sequence(values):
            enum_def = _build_enum_def(
                enum_kw.name or name_hint or "Enum", values, enum_kw, doc=None
            )
        else:
            self._warn(
                "enum has values that are composite types; using Literal.",
                code="enum-value-unsupported",
                schema=schema,
            )
            return literal_of(*values)
        self.enum_name_cache[id(schema)] = enum_def.name
        self.enum_decls.append(enum_def)
        return PythonTypeAnnotation(enum_def.name)

    def _annotation_from_applicators(
        self, schema: ObjectSchema, *, variant: _Variant, name_hint: str | None
    ) -> PythonTypeAnnotation | None:
        for applicator in (schema.any_of, schema.one_of):
            if applicator is not None:
                result = self._nullable_union(
                    list(applicator), variant=variant, name_hint=name_hint
                )
                if result is not None:
                    return result
                self._warn(
                    f"anyOf/oneOf with {len(applicator)} branches cannot be expressed precisely; using Any.",
                    code="anyof-fallback",
                    schema=schema,
                )
                return ANY
        if schema.all_of is not None:
            if len(schema.all_of) == 1:
                return self._annotation_inner(
                    schema.all_of[0], variant=variant, name_hint=name_hint
                )
            self._warn(
                "allOf with multiple branches uses Any.", code="allof-fallback", schema=schema
            )
            return ANY
        return None

    def _annotation_from_type(
        self, schema: ObjectSchema, *, variant: _Variant, name_hint: str | None
    ) -> PythonTypeAnnotation:
        if isinstance(schema.type, Set):
            return self._type_set_annotation(
                schema.type, schema, variant=variant, name_hint=name_hint
            )
        if schema.type is not None:
            return self._single_type_annotation(
                schema.type, schema, variant=variant, name_hint=name_hint
            )
        return ANY

    def _single_type_annotation(
        self, t: JsonSchemaType, schema: ObjectSchema, *, variant: _Variant, name_hint: str | None
    ) -> PythonTypeAnnotation:
        if t == JsonSchemaType.ARRAY:
            if schema.items is not None:
                item_ann = self._annotation_inner(
                    schema.items, variant=variant, name_hint=name_hint
                )
            elif schema.prefix_items:
                item_ann = ANY
            else:
                item_ann = ANY
            return PythonTypeAnnotation("list", args=[item_ann])
        if t == JsonSchemaType.OBJECT:
            return PythonTypeAnnotation("dict", args=[STR, ANY])
        # TODO: This can return `None`.
        return PRIMITIVE_MAP.get(t, ANY)

    def _type_set_annotation(
        self,
        types: Set[JsonSchemaType],
        schema: ObjectSchema,
        *,
        variant: _Variant,
        name_hint: str | None,
    ) -> PythonTypeAnnotation:
        non_null = types - {JsonSchemaType.NULL}
        has_null = JsonSchemaType.NULL in types
        if not non_null:
            return NONE
        if len(non_null) == 1:
            base = self._single_type_annotation(
                next(iter(non_null)), schema, variant=variant, name_hint=name_hint
            )
            return nullable_of(base) if has_null else base
        self._warn(
            f"type array {sorted(str(t) for t in types)} maps to Any.",
            code="multi-type-fallback",
            schema=schema,
        )
        return nullable_of(ANY) if has_null else ANY

    def _nullable_union(
        self, schemas: list[JsonSchema], *, variant: _Variant, name_hint: str | None
    ) -> PythonTypeAnnotation | None:
        """If exactly one branch is `null` and one is non-null, return `T | None`."""
        null_count = sum(
            1 for s in schemas if isinstance(s, ObjectSchema) and s.type == JsonSchemaType.NULL
        )
        non_null = [
            s
            for s in schemas
            if not (isinstance(s, ObjectSchema) and s.type == JsonSchemaType.NULL)
        ]
        if null_count == 1 and len(non_null) == 1:
            return nullable_of(
                self._annotation_inner(non_null[0], variant=variant, name_hint=name_hint)
            )
        if null_count == 0 and len(schemas) == 1:
            return self._annotation_inner(schemas[0], variant=variant, name_hint=name_hint)
        return None

    def _warn(self, msg: str, *, code: str, schema: ObjectSchema) -> None:
        loc: SourceLocation | None = None
        if schema.source_ref:
            loc = SourceLocation(
                doc_id=schema.source_ref.source_id, json_pointer=schema.source_ref.json_pointer
            )
        self.warnings.append(TranspilationWarning(msg, code=code, location=loc))


# ---------------------------------------------------------------------------
# Import collection
# ---------------------------------------------------------------------------


def _scan_annotation(ann: PythonTypeAnnotation, needed: dict[str, set[str]]) -> None:
    if ann.module:
        needed.setdefault(ann.module, set()).add(ann.name)
    for arg in ann.args:
        _scan_annotation(arg, needed)


def _scan_enum_imports(decl: EnumDef, needed: dict[str, set[str]]) -> None:
    if decl.base_module:
        needed.setdefault(decl.base_module, set()).add(decl.base)
    if any(m.value == "auto()" for m in decl.members):
        needed.setdefault("enum", set()).add("auto")


def _scan_class_imports(decl: ClassDef, needed: dict[str, set[str]]) -> None:
    if decl.style == ClassStyle.PYDANTIC_FROZEN:
        needed.setdefault("pydantic", set()).add("ConfigDict")
    for f in decl.fields:
        _scan_annotation(f.annotation, needed)
        if f.default and "Field(" in f.default:
            needed.setdefault("pydantic", set()).add("Field")


def _build_imports(declarations: list[PyDeclaration]) -> list[FromImport]:
    """Collect all needed imports from the declaration tree."""
    needed: dict[str, set[str]] = {}
    has_class = False
    for decl in declarations:
        if isinstance(decl, EnumDef):
            _scan_enum_imports(decl, needed)
        elif isinstance(decl, ClassDef):
            has_class = True
            _scan_class_imports(decl, needed)
        elif isinstance(decl, TypeAliasDef):
            _scan_annotation(decl.annotation, needed)
    if has_class:
        needed.setdefault("pydantic", set()).add("BaseModel")
    return [
        FromImport(module=module, names=[(n, None) for n in sorted(needed[module])])
        for module in sorted(needed)
    ]
