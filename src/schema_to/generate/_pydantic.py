"""Generator: JSON Schema 2020-12 CST → Pydantic v2 Python AST.

Mapping rules
-------------
* An ``object``-typed schema (root or ``$defs`` entry) becomes a
  ``pydantic.BaseModel`` subclass (``ClassStyle.PYDANTIC``).
* Non-object named schemas become PEP 695 ``type`` aliases.
* Properties that appear in ``required`` get a plain annotation; all others
  get ``T | None = None``.
* ``$ref: "#/$defs/Name"`` becomes a forward reference to the generated class.
* ``anyOf`` / ``oneOf`` with exactly one non-null branch collapses to ``T | None``.
* ``enum`` / ``const`` map to ``Literal[…]``.
* Unsupported constructs emit ``TranspilationWarning`` and fall back to ``Any``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from schema_to._errors import (
    GenerationError,
    SourceLocation,
    TranspilationError,
    TranspilationWarning,
)
from schema_to._names import safe_python_class_name, safe_python_field_name
from schema_to._pipeline import Generator
from schema_to._result import Err, Ok, Result
from schema_to.ast._python import (
    ClassDef,
    ClassStyle,
    FieldDef,
    FromImport,
    PythonDocString,
    PythonModule,
    PythonTypeAnnotation,
    TypeAliasDef,
)
from schema_to.cst._json_schema import (
    BooleanSchema,
    JsonSchema,
    JsonSchemaDocument,
    JsonSchemaType,
    ObjectSchema,
)
from schema_to.resolve._json_schema import JsonSchemaRefResolver

__all__ = ["PydanticGenerator"]

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


def _ref_to_class_name(ref: str) -> str:
    """Extract a class name from a ``$ref`` like ``"#/$defs/MyModel"``."""
    fragment = ref.split("#", 1)[-1] if "#" in ref else ref
    part = fragment.rstrip("/").rsplit("/", 1)[-1]
    return safe_python_class_name(part) if part else "Unknown"


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


@dataclass
class PydanticGenerator(Generator[JsonSchemaDocument, PythonModule]):
    """Generates a ``PythonModule`` with Pydantic v2 ``BaseModel`` classes.

    Attributes:
        resolver: Optional resolver for cross-document ``$ref`` lookup.
        _warnings: Accumulated warnings from the most recent ``apply`` call.
    """

    resolver: JsonSchemaRefResolver | None = None
    _warnings: list[TranspilationWarning] = field(default_factory=list, repr=False)

    @property
    def warnings(self) -> Sequence[TranspilationWarning]:
        return list(self._warnings)

    def apply(self, input: JsonSchemaDocument) -> Result[PythonModule]:
        self._warnings = []
        ctx = _GenCtx(source_id=input.source_id, resolver=self.resolver, warnings=self._warnings)

        declarations: list[TypeAliasDef | ClassDef] = []
        errors: list[TranspilationError] = []

        # --- Named definitions ($defs) ---
        if isinstance(input.root, ObjectSchema) and input.root.defs:
            for def_name, def_schema in input.root.defs.items():
                result = ctx.schema_to_declaration(def_schema, name=def_name)
                if result is not None:
                    declarations.append(result)

        # --- Root schema ---
        root_name = _root_class_name(input)
        root_decl = ctx.schema_to_declaration(input.root, name=root_name)
        if root_decl is not None:
            declarations.append(root_decl)
        elif not declarations:
            errors.append(
                GenerationError(
                    "Root schema is a boolean schema; cannot generate a Pydantic model.",
                    location=None,
                )
            )

        if errors:
            return Err(tuple(errors))

        imports = _build_imports(declarations, ctx)
        return Ok(
            PythonModule(imports=imports, declarations=declarations, source_ids=(input.source_id,))
        )


def _root_class_name(doc: JsonSchemaDocument) -> str:
    if isinstance(doc.root, ObjectSchema) and doc.root.title:
        return safe_python_class_name(doc.root.title)
    return safe_python_class_name(doc.display_name or doc.source_id.rstrip("/").rsplit("/", 1)[-1])


# ---------------------------------------------------------------------------
# Generation context (internal)
# ---------------------------------------------------------------------------


@dataclass
class _GenCtx:
    """Per-document generation state threaded through the CST walk.

    Holds the source document identifier, an optional ref resolver for
    cross-document ``$ref`` lookup, and the mutable warnings list that is
    shared with the owning ``PydanticGenerator``.
    """

    source_id: str
    resolver: JsonSchemaRefResolver | None
    warnings: list[TranspilationWarning]

    def schema_to_declaration(
        self, schema: JsonSchema, name: str
    ) -> TypeAliasDef | ClassDef | None:
        """Convert a top-level schema to a declaration node, or None for booleans."""
        if isinstance(schema, BooleanSchema):
            return None
        if self._is_object_schema(schema):
            return self._make_class(schema, name)
        ann = self.schema_to_annotation(schema, required=True)
        doc = None
        if schema.title or schema.description:
            doc = PythonDocString(
                summary=schema.title or schema.description or "",
                description=schema.description if schema.title else None,
            )
        return TypeAliasDef(name=safe_python_class_name(name), annotation=ann, doc=doc)

    def _is_object_schema(self, schema: ObjectSchema) -> bool:
        if schema.type == JsonSchemaType.OBJECT:
            return True
        if isinstance(schema.type, frozenset) and JsonSchemaType.OBJECT in schema.type:
            return True
        # Schemas with properties but no explicit type are treated as objects.
        return schema.type is None and schema.properties is not None

    def _make_class(self, schema: ObjectSchema, name: str) -> ClassDef:
        class_name = safe_python_class_name(name)
        required_set = set(schema.required or frozenset())
        fields: list[FieldDef] = []

        for prop_name, prop_schema in (schema.properties or {}).items():
            is_required = prop_name in required_set
            ann = self.schema_to_annotation(prop_schema, required=is_required)
            py_name = safe_python_field_name(prop_name)

            alias_kwargs = ""
            if py_name != prop_name:
                alias_kwargs = f'alias="{prop_name}"'

            default: str | None = None
            if not is_required:
                default = "None"
            elif isinstance(prop_schema, ObjectSchema) and prop_schema.default is not None:
                default = repr(prop_schema.default.value)

            doc: str | None = None
            if isinstance(prop_schema, ObjectSchema):
                doc = prop_schema.description or prop_schema.title

            field_kw: list[str] = []
            if alias_kwargs:
                field_kw.append(alias_kwargs)
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

            if field_kw:
                default = (
                    f"Field({', '.join(field_kw)})"
                    if default is None
                    else f"Field({default}, {', '.join(field_kw)})"
                )

            fields.append(FieldDef(name=py_name, annotation=ann, default=default, doc=doc))

        doc_node: PythonDocString | None = None
        if schema.title or schema.description:
            doc_node = PythonDocString(
                summary=schema.title or schema.description or "",
                description=schema.description if schema.title else None,
            )

        return ClassDef(name=class_name, style=ClassStyle.PYDANTIC, fields=fields, doc=doc_node)

    def schema_to_annotation(self, schema: JsonSchema, *, required: bool) -> PythonTypeAnnotation:
        """Return the Python type annotation for a field's schema."""
        ann = self._annotation_inner(schema)
        if not required and not ann.nullable and ann != _NONE:
            ann = _nullable(ann)
        return ann

    def _annotation_inner(self, schema: JsonSchema) -> PythonTypeAnnotation:
        if isinstance(schema, BooleanSchema):
            return _ANY if schema.value else PythonTypeAnnotation("Never", module="typing")

        # $ref → forward reference class name
        if schema.ref:
            return PythonTypeAnnotation(_ref_to_class_name(schema.ref))

        # enum → Literal[...]
        if schema.enum is not None:
            return _literal(*schema.enum)

        # const → Literal[value]
        if schema.const is not None:
            return _literal(schema.const.value)

        # anyOf / oneOf: collapse [T, null] → T | None, else Any
        for applicator in (schema.any_of, schema.one_of):
            if applicator is not None:
                result = self._nullable_union(list(applicator))
                if result is not None:
                    return result
                self._warn(
                    f"anyOf/oneOf with {len(applicator)} branches cannot be "
                    "expressed precisely; using Any.",
                    code="anyof-fallback",
                    schema=schema,
                )
                return _ANY

        # allOf: warn + Any (complex merge not supported)
        if schema.all_of is not None:
            if len(schema.all_of) == 1:
                return self._annotation_inner(schema.all_of[0])
            self._warn(
                "allOf with multiple branches uses Any.", code="allof-fallback", schema=schema
            )
            return _ANY

        # Union type array, e.g. type: [string, null]
        if isinstance(schema.type, frozenset):
            return self._type_set_annotation(schema.type, schema)

        # Single primitive type
        if schema.type is not None:
            return self._single_type_annotation(schema.type, schema)

        # No type specified — Any
        return _ANY

    def _single_type_annotation(
        self, t: JsonSchemaType, schema: ObjectSchema
    ) -> PythonTypeAnnotation:
        if t == JsonSchemaType.ARRAY:
            if schema.items is not None:
                item_ann = self._annotation_inner(schema.items)
            elif schema.prefix_items:
                item_ann = _ANY
            else:
                item_ann = _ANY
            return PythonTypeAnnotation("list", args=[item_ann])
        if t == JsonSchemaType.OBJECT:
            return PythonTypeAnnotation("dict", args=[_STR, _ANY])
        return _PRIMITIVE_MAP.get(t, _ANY)

    def _type_set_annotation(
        self, types: frozenset[JsonSchemaType], schema: ObjectSchema
    ) -> PythonTypeAnnotation:
        non_null = types - {JsonSchemaType.NULL}
        has_null = JsonSchemaType.NULL in types
        if not non_null:
            return _NONE
        if len(non_null) == 1:
            base = self._single_type_annotation(next(iter(non_null)), schema)
            return _nullable(base) if has_null else base
        self._warn(
            f"type array {sorted(str(t) for t in types)} maps to Any.",
            code="multi-type-fallback",
            schema=schema,
        )
        return _nullable(_ANY) if has_null else _ANY

    def _nullable_union(self, schemas: list[JsonSchema]) -> PythonTypeAnnotation | None:
        """If exactly one branch is ``null`` and one is non-null, return ``T | None``."""
        null_count = sum(
            1 for s in schemas if isinstance(s, ObjectSchema) and s.type == JsonSchemaType.NULL
        )
        non_null = [
            s
            for s in schemas
            if not (isinstance(s, ObjectSchema) and s.type == JsonSchemaType.NULL)
        ]
        if null_count == 1 and len(non_null) == 1:
            return _nullable(self._annotation_inner(non_null[0]))
        if null_count == 0 and len(schemas) == 1:
            return self._annotation_inner(schemas[0])
        return None

    def _warn(self, msg: str, *, code: str, schema: ObjectSchema) -> None:
        loc: SourceLocation | None = None
        if schema.source_ref:
            loc = SourceLocation(
                source_id=schema.source_ref.source_id, json_pointer=schema.source_ref.json_pointer
            )
        self.warnings.append(TranspilationWarning(msg, code=code, location=loc))


# ---------------------------------------------------------------------------
# Import collection
# ---------------------------------------------------------------------------


def _build_imports(declarations: list[TypeAliasDef | ClassDef], ctx: _GenCtx) -> list[FromImport]:
    """Collect all needed imports from the declaration tree."""
    needed: dict[str, set[str]] = {}  # module -> names

    def _add(module: str, name: str) -> None:
        needed.setdefault(module, set()).add(name)

    def _scan_ann(ann: PythonTypeAnnotation) -> None:
        if ann.module:
            _add(ann.module, ann.name)
        for arg in ann.args:
            _scan_ann(arg)

    def _scan_field(f: FieldDef) -> None:
        _scan_ann(f.annotation)
        if f.default and "Field(" in (f.default or ""):
            _add("pydantic", "Field")

    has_class = False
    for decl in declarations:
        if isinstance(decl, ClassDef):
            has_class = True
            for f in decl.fields:
                _scan_field(f)
        elif isinstance(decl, TypeAliasDef):
            _scan_ann(decl.annotation)

    if has_class:
        _add("pydantic", "BaseModel")

    result: list[FromImport] = []
    for module in sorted(needed):
        names = sorted(needed[module])
        result.append(FromImport(module=module, names=[(n, None) for n in names]))
    return result
