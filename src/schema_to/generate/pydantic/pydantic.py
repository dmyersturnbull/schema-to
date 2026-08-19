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
- `enum` / `const` map to `Literal[…]`.
- Unsupported constructs emit `TranspilationWarning` and fall back to `Any`.
"""

from collections.abc import Set
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from schema_to.ast.python import (
    ClassDef,
    ClassStyle,
    FieldDef,
    FromImport,
    PythonDocString,
    PythonModule,
    PythonTypeAnnotation,
    TypeAliasDef,
)
from schema_to.cst.json_schema import (
    BooleanSchema,
    JsonSchema,
    JsonSchemaDocument,
    JsonSchemaType,
    ObjectSchema,
    is_object_schema,
)
from schema_to.errors import (
    GenerationError,
    SourceLocation,
    TranspilationError,
    TranspilationWarning,
)
from schema_to.generate._python_utils import (
    safe_python_class_name,
    safe_python_field_name,
    split_class_name,
)
from schema_to.generate.inlining import SchemaFlattener
from schema_to.pipeline import Transformer
from schema_to.result import Err, Ok, Result

if TYPE_CHECKING:
    from schema_to.resolve.json_schema import JsonSchemaRefResolver

__all__ = ["PydanticTransformer"]

# ---------------------------------------------------------------------------
# Type annotation helpers
# ---------------------------------------------------------------------------

_ANY = PythonTypeAnnotation("Any", module="typing")
_NONE = PythonTypeAnnotation("None")
_STR = PythonTypeAnnotation("str")
_INT = PythonTypeAnnotation("int")
_FLOAT = PythonTypeAnnotation("float")
_BOOL = PythonTypeAnnotation("bool")

_PRIMITIVE_MAP: dict[JsonSchemaType, PythonTypeAnnotation] = {
    JsonSchemaType.STRING: _STR,
    JsonSchemaType.INTEGER: _INT,
    JsonSchemaType.NUMBER: _FLOAT,
    JsonSchemaType.BOOLEAN: _BOOL,
    JsonSchemaType.NULL: _NONE,
}


def _nullable(ann: PythonTypeAnnotation) -> PythonTypeAnnotation:
    return PythonTypeAnnotation(ann.name, args=ann.args, module=ann.module, nullable=True)


def _literal(*values: object) -> PythonTypeAnnotation:
    args = [PythonTypeAnnotation(repr(v)) for v in values]
    return PythonTypeAnnotation("Literal", args=args, module="typing")


def _has_split_properties(schema: JsonSchema) -> bool:
    """Return True if *schema* has any `readOnly` or `writeOnly` property."""
    if not isinstance(schema, ObjectSchema) or not schema.properties:
        return False
    return any(
        isinstance(p, ObjectSchema) and (p.read_only or p.write_only)
        for p in schema.properties.values()
    )


def _compute_split_names(input: JsonSchemaDocument) -> Set[str]:
    """Return the canonical class names of schemas that need a Read/Write split."""
    names: set[str] = set()
    if isinstance(input.root, ObjectSchema) and input.root.defs:
        for def_name, def_schema in input.root.defs.items():
            if _has_split_properties(def_schema):
                names.add(safe_python_class_name(def_name))
    if _has_split_properties(input.root):
        names.add(_root_class_name(input))
    return frozenset(names)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PydanticTransformer(Transformer[JsonSchemaDocument, PythonModule]):
    """Generates a `PythonModule` with Pydantic v2 `BaseModel` classes.

    Attributes:
        resolver: Optional resolver for cross-document `$ref` lookup.
        roots: If given, only `$defs` entries named here become their own declaration;
            the rest are still available for `$ref` resolution. `None` emits every entry,
            as before.
    """

    resolver: JsonSchemaRefResolver | None = None
    roots: Set[str] | None = None

    def apply(self, input: JsonSchemaDocument) -> Result[PythonModule]:
        warnings: list[TranspilationWarning] = []
        ctx = _GenCtx(
            source_id=input.source_id,
            resolver=self.resolver,
            warnings=warnings,
            base_uri=input.get_base_uri(),
            split_names=_compute_split_names(input),
        )

        declarations: list[TypeAliasDef | ClassDef] = []
        errors: list[TranspilationError] = []

        # --- Named definitions ($defs) ---
        if isinstance(input.root, ObjectSchema) and input.root.defs:
            for def_name, def_schema in input.root.defs.items():
                if self.roots is not None and def_name not in self.roots:
                    continue
                declarations.extend(ctx.schema_to_declarations(def_schema, name=def_name))

        # --- Root schema ---
        root_name = _root_class_name(input)
        root_decls = ctx.schema_to_declarations(input.root, name=root_name)
        declarations.extend(root_decls)
        if not root_decls and not declarations:
            errors.append(
                GenerationError(
                    "Root schema is a boolean schema; cannot generate a Pydantic model.",
                    location=None,
                )
            )

        if errors:
            return Err(tuple(errors), warnings=tuple(warnings))

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
    """Name the root model after `title`, then `display_name`, then the source ID's last segment."""
    if isinstance(doc.root, ObjectSchema) and doc.root.title:
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

    def schema_to_declarations(
        self, schema: JsonSchema, name: str
    ) -> list[TypeAliasDef | ClassDef]:
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
        ann = self.schema_to_annotation(schema, required=True)
        doc = None
        if schema.title or schema.description:
            doc = PythonDocString(
                summary=schema.title or schema.description or "",
                description=schema.description if schema.title else None,
            )
        return [TypeAliasDef(name=safe_python_class_name(name), annotation=ann, doc=doc)]

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

    def _make_class(
        self, schema: ObjectSchema, name: str, *, variant: Literal["read", "write"] | None
    ) -> ClassDef:
        class_name = (
            split_class_name(name, variant) if variant is not None else safe_python_class_name(name)
        )
        required_set = set(schema.required or frozenset())
        fields = [
            self._build_field_def(
                prop_name, prop_schema, is_required=(prop_name in required_set), variant=variant
            )
            for prop_name, prop_schema in (schema.properties or {}).items()
            if self._field_included(prop_schema, variant=variant)
        ]
        doc_node: PythonDocString | None = None
        if schema.title or schema.description:
            doc_node = PythonDocString(
                summary=schema.title or schema.description or "",
                description=schema.description if schema.title else None,
            )
        return ClassDef(name=class_name, style=ClassStyle.PYDANTIC, fields=fields, doc=doc_node)

    def _field_included(
        self, prop_schema: JsonSchema, *, variant: Literal["read", "write"] | None
    ) -> bool:
        if variant is None or not isinstance(prop_schema, ObjectSchema):
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
        variant: Literal["read", "write"] | None = None,
    ) -> FieldDef:
        ann = self.schema_to_annotation(prop_schema, required=is_required, variant=variant)
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
        self, schema: JsonSchema, *, required: bool, variant: Literal["read", "write"] | None = None
    ) -> PythonTypeAnnotation:
        """Return the Python type annotation for a field's schema."""
        ann = self._annotation_inner(schema, variant=variant)
        if not required and not ann.nullable and ann != _NONE:
            ann = _nullable(ann)
        return ann

    def _ref_to_class_name(self, ref: str, *, variant: Literal["read", "write"] | None) -> str:
        """Extract a class name from a `$ref` like `"#/$defs/MyModel"`.

        If the referenced schema is itself split into Read/Write variants, the
        *current* variant is propagated; a ref from a non-split context
        defaults to the Read variant, since JSON Schema gives no other signal.
        """
        fragment = ref.split("#", 1)[-1] if "#" in ref else ref
        part = fragment.rstrip("/").rsplit("/", 1)[-1]
        base = safe_python_class_name(part) if part else "Unknown"
        if base in self.split_names:
            return split_class_name(part, variant if variant is not None else "read")
        return base

    def _annotation_inner(
        self, schema: JsonSchema, *, variant: Literal["read", "write"] | None = None
    ) -> PythonTypeAnnotation:
        if isinstance(schema, BooleanSchema):
            return _ANY if schema.value else PythonTypeAnnotation("Never", module="typing")
        if schema.ref:
            return PythonTypeAnnotation(self._ref_to_class_name(schema.ref, variant=variant))
        if schema.enum is not None:
            return _literal(*schema.enum)
        if schema.const is not None:
            return _literal(schema.const.value)
        ann = self._annotation_from_applicators(schema, variant=variant)
        if ann is not None:
            return ann
        return self._annotation_from_type(schema, variant=variant)

    def _annotation_from_applicators(
        self, schema: ObjectSchema, *, variant: Literal["read", "write"] | None
    ) -> PythonTypeAnnotation | None:
        for applicator in (schema.any_of, schema.one_of):
            if applicator is not None:
                result = self._nullable_union(list(applicator), variant=variant)
                if result is not None:
                    return result
                self._warn(
                    f"anyOf/oneOf with {len(applicator)} branches cannot be expressed precisely; using Any.",
                    code="anyof-fallback",
                    schema=schema,
                )
                return _ANY
        if schema.all_of is not None:
            if len(schema.all_of) == 1:
                return self._annotation_inner(schema.all_of[0], variant=variant)
            self._warn(
                "allOf with multiple branches uses Any.", code="allof-fallback", schema=schema
            )
            return _ANY
        return None

    def _annotation_from_type(
        self, schema: ObjectSchema, *, variant: Literal["read", "write"] | None
    ) -> PythonTypeAnnotation:
        if isinstance(schema.type, Set):
            return self._type_set_annotation(schema.type, schema, variant=variant)
        if schema.type is not None:
            return self._single_type_annotation(schema.type, schema, variant=variant)
        return _ANY

    def _single_type_annotation(
        self, t: JsonSchemaType, schema: ObjectSchema, *, variant: Literal["read", "write"] | None
    ) -> PythonTypeAnnotation:
        if t == JsonSchemaType.ARRAY:
            if schema.items is not None:
                item_ann = self._annotation_inner(schema.items, variant=variant)
            elif schema.prefix_items:
                item_ann = _ANY
            else:
                item_ann = _ANY
            return PythonTypeAnnotation("list", args=[item_ann])
        if t == JsonSchemaType.OBJECT:
            return PythonTypeAnnotation("dict", args=[_STR, _ANY])
        return _PRIMITIVE_MAP.get(t, _ANY)

    def _type_set_annotation(
        self,
        types: Set[JsonSchemaType],
        schema: ObjectSchema,
        *,
        variant: Literal["read", "write"] | None,
    ) -> PythonTypeAnnotation:
        non_null = types - {JsonSchemaType.NULL}
        has_null = JsonSchemaType.NULL in types
        if not non_null:
            return _NONE
        if len(non_null) == 1:
            base = self._single_type_annotation(next(iter(non_null)), schema, variant=variant)
            return _nullable(base) if has_null else base
        self._warn(
            f"type array {sorted(str(t) for t in types)} maps to Any.",
            code="multi-type-fallback",
            schema=schema,
        )
        return _nullable(_ANY) if has_null else _ANY

    def _nullable_union(
        self, schemas: list[JsonSchema], *, variant: Literal["read", "write"] | None
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
            return _nullable(self._annotation_inner(non_null[0], variant=variant))
        if null_count == 0 and len(schemas) == 1:
            return self._annotation_inner(schemas[0], variant=variant)
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


def _build_imports(declarations: list[TypeAliasDef | ClassDef]) -> list[FromImport]:
    """Collect all needed imports from the declaration tree."""
    needed: dict[str, set[str]] = {}
    has_class = False
    for decl in declarations:
        if isinstance(decl, ClassDef):
            has_class = True
            for f in decl.fields:
                _scan_annotation(f.annotation, needed)
                if f.default and "Field(" in f.default:
                    needed.setdefault("pydantic", set()).add("Field")
        elif isinstance(decl, TypeAliasDef):
            _scan_annotation(decl.annotation, needed)
    if has_class:
        needed.setdefault("pydantic", set()).add("BaseModel")
    return [
        FromImport(module=module, names=[(n, None) for n in sorted(needed[module])])
        for module in sorted(needed)
    ]
