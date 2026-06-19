"""Generator: OpenAPI 3.1 CST → FastAPI application Python AST.

Mapping rules
-------------
* ``components/schemas`` entries are converted to Pydantic v2 ``BaseModel``
  classes via `PydanticTransformer`.
* Each path × HTTP-method pair becomes an ``async def`` route function
  decorated with ``@app.<method>("<path>")``.
* Path parameters are annotated with ``Annotated[T, Path()]``.
* Query parameters use ``Annotated[T, Query()]``; optional ones add ``= None``.
* Header and cookie parameters use ``Annotated[T, Header()]`` /
  ``Annotated[T, Cookie()]`` respectively.
* Request bodies whose schema is a ``$ref`` to a component become a ``body``
  parameter typed as that Pydantic model.  Inline schemas fall back to
  ``dict[str, Any]``.
* The primary 2xx response schema, when determinable, is set as
  ``response_model=`` in the decorator and as the function return annotation.
* Schemas that cannot be mapped emit a `TranspilationWarning` and fall back
  to ``Any``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from schema_to.ast.python import (
    ClassDef,
    ClassStyle,
    Decorator,
    FromImport,
    FunctionDef,
    ModuleVarDef,
    PythonDocString,
    PythonModule,
    PythonTypeAnnotation,
    TypeAliasDef,
)
from schema_to.ast.python import Parameter as PyParameter
from schema_to.cst.json_schema import (
    BooleanSchema,
    JsonSchema,
    JsonSchemaDocument,
    JsonSchemaType,
    ObjectSchema,
)
from schema_to.cst.openapi import (
    HttpMethod,
    MediaTypeObject,
    OpenApiDocument,
    ParameterLocation,
    PathItem,
)
from schema_to.cst.openapi import Parameter as OasParameter
from schema_to.errors import SourceLocation, TranspilationWarning
from schema_to.generate._names import safe_python_class_name, safe_python_field_name
from schema_to.generate.pydantic import PydanticTransformer
from schema_to.pipeline import Transformer
from schema_to.result import Err, Ok, Result

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from schema_to.cst.openapi import Operation

__all__ = ["FastApiTransformer"]


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


def _ref_to_class_name(ref: str) -> str:
    fragment = ref.split("#", 1)[-1] if "#" in ref else ref
    part = fragment.rstrip("/").rsplit("/", 1)[-1]
    return safe_python_class_name(part) if part else "Unknown"


def _annotation_str(ann: PythonTypeAnnotation) -> str:
    """Render an annotation to its string form (mirrors PythonReifier._emit_annotation)."""
    base = ann.name
    if ann.args:
        args_str = ", ".join(_annotation_str(a) for a in ann.args)
        base = f"{base}[{args_str}]"
    if ann.nullable:
        base = f"{base} | None"
    return base


# ---------------------------------------------------------------------------
# JsonSchema → PythonTypeAnnotation (for route signatures)
# ---------------------------------------------------------------------------


def _schema_to_annotation(schema: JsonSchema | None) -> PythonTypeAnnotation:
    """Map a JSON Schema to a Python type annotation for a route signature."""
    if schema is None:
        return _ANY
    if isinstance(schema, BooleanSchema):
        return _ANY
    if schema.ref:
        return PythonTypeAnnotation(_ref_to_class_name(schema.ref))
    if schema.enum is not None:
        args = [PythonTypeAnnotation(repr(v)) for v in schema.enum]
        return PythonTypeAnnotation("Literal", args=args, module="typing")
    branches = schema.any_of or schema.one_of
    if branches is not None:
        return _union_annotation(list(branches))
    return _map_object_schema(schema)


def _union_annotation(branches: list[JsonSchema]) -> PythonTypeAnnotation:
    non_null = [
        b for b in branches if not (isinstance(b, ObjectSchema) and b.type == JsonSchemaType.NULL)
    ]
    has_null = len(non_null) < len(branches)
    if len(non_null) == 1:
        base = _schema_to_annotation(non_null[0])
        return _nullable(base) if has_null else base
    return _nullable(_ANY) if has_null else _ANY


def _map_object_schema(schema: ObjectSchema) -> PythonTypeAnnotation:
    t = schema.type
    if t is None:
        return _ANY
    if isinstance(t, frozenset):
        non_null = t - {JsonSchemaType.NULL}
        has_null = JsonSchemaType.NULL in t
        if not non_null:
            return _NONE
        base = _map_single_type(next(iter(non_null)), schema) if len(non_null) == 1 else _ANY
        return _nullable(base) if has_null else base
    return _map_single_type(t, schema)


def _map_single_type(t: JsonSchemaType, schema: ObjectSchema) -> PythonTypeAnnotation:
    if t == JsonSchemaType.ARRAY:
        item_ann = _schema_to_annotation(schema.items) if schema.items is not None else _ANY
        return PythonTypeAnnotation("list", args=[item_ann])
    if t == JsonSchemaType.OBJECT:
        return PythonTypeAnnotation("dict", args=[_STR, _ANY])
    return _PRIMITIVE_MAP.get(t, _ANY)


# ---------------------------------------------------------------------------
# Import collection
# ---------------------------------------------------------------------------


def _scan_annotation(ann: PythonTypeAnnotation, needed: dict[str, set[str]]) -> None:
    if ann.module:
        # Strip parentheses from callable expressions like "Query()" → "Query"
        name = ann.name.split("(")[0]
        needed.setdefault(ann.module, set()).add(name)
    for arg in ann.args:
        _scan_annotation(arg, needed)


def _scan_class_decl(decl: ClassDef, needed: dict[str, set[str]]) -> None:
    if decl.style in {ClassStyle.PYDANTIC, ClassStyle.PYDANTIC_FROZEN}:
        needed.setdefault("pydantic", set()).add("BaseModel")
    for f in decl.fields:
        _scan_annotation(f.annotation, needed)
        if f.default and "Field(" in f.default:
            needed.setdefault("pydantic", set()).add("Field")


def _scan_function_decl(decl: FunctionDef, needed: dict[str, set[str]]) -> None:
    for p in decl.parameters:
        if p.annotation:
            _scan_annotation(p.annotation, needed)
    if decl.return_annotation:
        _scan_annotation(decl.return_annotation, needed)


def _build_imports(
    declarations: list[TypeAliasDef | ClassDef | FunctionDef | ModuleVarDef],
) -> list[FromImport]:
    needed: dict[str, set[str]] = {"fastapi": {"FastAPI"}}
    for decl in declarations:
        if isinstance(decl, ClassDef):
            _scan_class_decl(decl, needed)
        elif isinstance(decl, FunctionDef):
            _scan_function_decl(decl, needed)
        elif isinstance(decl, TypeAliasDef):
            _scan_annotation(decl.annotation, needed)
    return [
        FromImport(module=mod, names=[(n, None) for n in sorted(needed[mod])])
        for mod in sorted(needed)
        if needed[mod]
    ]


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


@dataclass
class FastApiTransformer(Transformer[OpenApiDocument, PythonModule]):
    """Generates a FastAPI application `PythonModule` from an `OpenApiDocument` CST.

    Attributes:
        _warnings: Accumulated non-fatal diagnostics from the most recent `apply` call.
    """

    _warnings: list[TranspilationWarning] = field(default_factory=list, repr=False)

    @property
    def warnings(self) -> Sequence[TranspilationWarning]:
        return list(self._warnings)

    def apply(self, input: OpenApiDocument) -> Result[PythonModule]:
        self._warnings.clear()
        ctx = _GenCtx(doc=input, warnings=self._warnings)
        return ctx.build()


# ---------------------------------------------------------------------------
# Generation context (internal)
# ---------------------------------------------------------------------------


@dataclass
class _GenCtx:
    """Per-document generation state."""

    doc: OpenApiDocument
    warnings: list[TranspilationWarning]

    def build(self) -> Result[PythonModule]:
        model_decls = self._generate_models()
        app_var = self._make_app_var()
        route_fns = self._generate_routes()

        declarations: list[TypeAliasDef | ClassDef | FunctionDef | ModuleVarDef] = [
            *model_decls,
            app_var,
            *route_fns,
        ]
        imports = _build_imports(declarations)
        return Ok(
            PythonModule(
                imports=imports,
                declarations=declarations,
                source_ids=(self.doc.source_id or "",),
                module_doc=f'FastAPI application for "{self.doc.info.title}".',
            )
        )

    # -- Pydantic models from components/schemas --------------------------------

    def _generate_models(self) -> list[TypeAliasDef | ClassDef | FunctionDef | ModuleVarDef]:
        decls: list[TypeAliasDef | ClassDef | FunctionDef | ModuleVarDef] = []
        for name, schema in self.doc.components.schemas.items():
            doc = JsonSchemaDocument(root=schema, source_id=name, display_name=name)
            transformer = PydanticTransformer()
            result = transformer.apply(doc)
            self.warnings.extend(transformer.warnings)
            if isinstance(result, Err):
                for err in result.errors:
                    self._warn(
                        f"Could not generate model for {name!r}: {err.message}",
                        code="model-error",
                        location=err.location,
                    )
                continue
            decls.extend(result.value.declarations)
        return decls

    # -- App instance -----------------------------------------------------------

    def _make_app_var(self) -> ModuleVarDef:
        info = self.doc.info
        kwargs = [f'title="{_esc(info.title)}"', f'version="{_esc(info.version)}"']
        if info.description:
            kwargs.append(f'description="{_esc(info.description)}"')
        return ModuleVarDef(name="app", value=f"FastAPI({', '.join(kwargs)})")

    # -- Routes -----------------------------------------------------------------

    def _generate_routes(self) -> list[FunctionDef]:
        return [
            self._make_route_fn(path, method, operation)
            for path, path_item in self.doc.paths.items()
            for method, operation in _iter_operations(path_item)
        ]

    def _make_route_fn(self, path: str, method: HttpMethod, op: Operation) -> FunctionDef:
        fn_name = _op_fn_name(method, path, op.operation_id)
        params = self._build_params(op)
        success_code, return_ann = self._success_response(op)
        decorator = self._make_decorator(method, path, success_code, return_ann)
        doc = self._op_doc(op)
        return FunctionDef(
            name=fn_name,
            parameters=params,
            return_annotation=return_ann,
            doc=doc,
            decorators=[decorator],
            is_async=True,
        )

    def _op_doc(self, op: Operation) -> PythonDocString | None:
        if not (op.summary or op.description):
            return None
        return PythonDocString(
            summary=op.summary or op.description or "",
            description=op.description if op.summary else None,
        )

    def _build_params(self, op: Operation) -> list[PyParameter]:
        params = [self._oas_param_to_py(p) for p in op.parameters]
        body_param = self._body_param(op)
        if body_param is not None:
            params.append(body_param)
        return [p for p in params if p is not None]

    def _oas_param_to_py(self, p: OasParameter) -> PyParameter | None:
        py_name = safe_python_field_name(p.name)
        base_ann = _schema_to_annotation(p.schema)
        match p.in_:
            case ParameterLocation.PATH:
                ann = _annotated(base_ann, "Path()")
                return PyParameter(name=py_name, annotation=ann)
            case ParameterLocation.QUERY:
                return self._query_param(py_name, base_ann, p)
            case ParameterLocation.HEADER:
                ann = _annotated(base_ann, "Header()")
                return PyParameter(name=py_name, annotation=ann, default=_opt_default(p))
            case ParameterLocation.COOKIE:
                ann = _annotated(base_ann, "Cookie()")
                return PyParameter(name=py_name, annotation=ann, default=_opt_default(p))

    def _query_param(
        self, py_name: str, base_ann: PythonTypeAnnotation, p: OasParameter
    ) -> PyParameter:
        if p.required:
            return PyParameter(name=py_name, annotation=_annotated(base_ann, "Query()"))
        nullable = _nullable(base_ann) if not base_ann.nullable else base_ann
        schema_default = _schema_default(p.schema)
        default = schema_default if schema_default is not None else "None"
        return PyParameter(
            name=py_name, annotation=_annotated(nullable, "Query()"), default=default
        )

    def _body_param(self, op: Operation) -> PyParameter | None:
        if op.request_body is None:
            return None
        schema = _json_schema_from_content(op.request_body.content)
        if schema is None:
            return None
        return PyParameter(name="body", annotation=_schema_to_annotation(schema))

    def _success_response(self, op: Operation) -> tuple[int | None, PythonTypeAnnotation | None]:
        for code_str, response in op.responses.items():
            if not (code_str.startswith("2") and code_str.isdigit()):
                continue
            code = int(code_str)
            if code == 204:
                return code, _NONE
            schema = _json_schema_from_content(response.content)
            return code, _schema_to_annotation(schema) if schema is not None else None
        return None, None

    def _make_decorator(
        self,
        method: HttpMethod,
        path: str,
        status_code: int | None,
        response_ann: PythonTypeAnnotation | None,
    ) -> Decorator:
        args = [f'"{path}"']
        if status_code is not None and status_code != 200:
            args.append(f"status_code={status_code}")
        if response_ann is not None and response_ann not in {_ANY, _NONE}:
            args.append(f"response_model={_annotation_str(response_ann)}")
        return Decorator(name=f"app.{method}({', '.join(args)})")

    def _warn(self, message: str, *, code: str, location: SourceLocation | None = None) -> None:
        self.warnings.append(TranspilationWarning(message, code=code, location=location))


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _annotated(base: PythonTypeAnnotation, fastapi_expr: str) -> PythonTypeAnnotation:
    """Wrap *base* in ``Annotated[base, fastapi_expr]``."""
    return PythonTypeAnnotation(
        "Annotated",
        module="typing",
        args=[base, PythonTypeAnnotation(fastapi_expr, module="fastapi")],
    )


def _opt_default(p: OasParameter) -> str | None:
    return "None" if not p.required else None


def _iter_operations(path_item: PathItem) -> Iterator[tuple[HttpMethod, Operation]]:
    for method in HttpMethod:
        op = getattr(path_item, method.value)
        if op is not None:
            yield method, op


def _op_fn_name(method: HttpMethod, path: str, operation_id: str | None) -> str:
    if operation_id:
        return safe_python_field_name(operation_id)
    sanitized = re.sub(r"[{}]", "", path)
    parts = [method.value] + [p for p in sanitized.split("/") if p]
    return safe_python_field_name("_".join(parts))


def _json_schema_from_content(content: Mapping[str, MediaTypeObject]) -> JsonSchema | None:
    for media_type in ("application/json", "application/*", "*/*"):
        mt = content.get(media_type)
        if mt is not None:
            return mt.schema
    return None


def _schema_default(schema: JsonSchema | None) -> str | None:
    if schema is None or isinstance(schema, BooleanSchema):
        return None
    if schema.default is not None:
        return repr(schema.default.value)
    return None


def _esc(s: str) -> str:
    """Escape double quotes and backslashes for embedding in a string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')
