"""Generator: FastAPI from OpenAPI.

#### Mapping rules

- `components/schemas` entries are converted to Pydantic v2 `BaseModel` classes via `PydanticTransformer`,
  so `x-pydantic-*` extension keywords (including `x-pydantic-enum`) are honored there too.
  Inline schemas elsewhere
  (route parameters, request/response bodies not `$ref`-ing a component)
  go through this module's own, simpler mapping instead,
  which still emits `Literal[…]` for `enum` regardless of `x-pydantic-enum`.
- Each path × HTTP-method pair becomes an `async def` route function decorated with `@app.<method>("<path>")`.
- Path parameters are annotated with `Annotated[T, Path()]`.
- Query parameters use `Annotated[T, Query()]`; optional ones add `= None`.
- Header and cookie parameters use `Annotated[T, Header()]` / `Annotated[T, Cookie()]` respectively.
- Request bodies whose schema is a `$ref` to a component become a `body` parameter typed as that Pydantic model.
  Inline schemas fall back to `dict[str, Any]`.
- The primary 2xx response schema, when determinable, is set as `response_model=` in the decorator and as the function return annotation.
- Schemas that cannot be mapped emit a `TranspilationWarning` and fall back to `Any`.
"""

import re
from collections.abc import Set
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from schema_to.ast.python import (
    ClassDef,
    ClassStyle,
    Decorator,
    EnumDef,
    FromImport,
    FunctionDef,
    PyDeclaration,
    PythonDocString,
    PythonModule,
    PythonTypeAnnotation,
    SimpleImport,
    TypeAliasDef,
    VarDef,
)
from schema_to.ast.python import Parameter as PyParameter
from schema_to.core import SourceRef
from schema_to.cst.json_schema import BooleanSchema, JsonSchema, JsonSchemaType, ObjectSchema
from schema_to.cst.openapi import (
    HttpMethod,
    MediaTypeObject,
    OpenApiDocument,
    ParameterLocation,
    PathItem,
    concrete,
    concrete_list,
    concrete_map,
)
from schema_to.cst.openapi import Parameter as OasParameter
from schema_to.errors import TranspilationWarning
from schema_to.generate._python_utils import (
    ANY,
    NONE,
    PRIMITIVE_MAP,
    STR,
    nullable_of,
    safe_python_class_name,
    safe_python_field_name,
)
from schema_to.generate.fastapi.endpoint_body import (
    EndpointBody,
    EndpointBodyBackend,
    NullBodyBackend,
    RouteParam,
    endpoint_context,
)
from schema_to.generate.fastapi.security import build_security_module, route_security_params
from schema_to.generate.pydantic.pydantic import PydanticTransformer
from schema_to.pipeline import Transformer
from schema_to.result import Err, Ok, Result
from schema_to.transpile.extract import OpenApiComponentExtractor

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from schema_to.ast.python import PyImport
    from schema_to.cst.openapi import Operation, SecurityRequirement

__all__ = ["FastApiTransformer"]


# ---------------------------------------------------------------------------
# Type annotation helpers
# ---------------------------------------------------------------------------


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
        return ANY
    if isinstance(schema, BooleanSchema):
        return ANY
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
        return nullable_of(base) if has_null else base
    return nullable_of(ANY) if has_null else ANY


def _map_object_schema(schema: ObjectSchema) -> PythonTypeAnnotation:
    t = schema.type
    if t is None:
        return ANY
    if isinstance(t, Set):
        non_null = t - {JsonSchemaType.NULL}
        has_null = JsonSchemaType.NULL in t
        if not non_null:
            return NONE
        base = _map_single_type(next(iter(non_null)), schema) if len(non_null) == 1 else ANY
        return nullable_of(base) if has_null else base
    return _map_single_type(t, schema)


def _map_single_type(t: JsonSchemaType, schema: ObjectSchema) -> PythonTypeAnnotation:
    if t == JsonSchemaType.ARRAY:
        item_ann = _schema_to_annotation(schema.items) if schema.items is not None else ANY
        return PythonTypeAnnotation("list", args=[item_ann])
    if t == JsonSchemaType.OBJECT:
        return PythonTypeAnnotation("dict", args=[STR, ANY])
    return PRIMITIVE_MAP.get(t, ANY)


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


def _scan_enum_decl(decl: EnumDef, needed: dict[str, set[str]]) -> None:
    if decl.base_module:
        needed.setdefault(decl.base_module, set()).add(decl.base)
    if any(m.value == "auto()" for m in decl.members):
        needed.setdefault("enum", set()).add("auto")


def _build_imports(
    declarations: list[PyDeclaration], extra: Sequence[PyImport] = ()
) -> Sequence[PyImport]:
    needed: dict[str, set[str]] = {"fastapi": {"FastAPI"}}
    for decl in declarations:
        if isinstance(decl, ClassDef):
            _scan_class_decl(decl, needed)
        elif isinstance(decl, FunctionDef):
            _scan_function_decl(decl, needed)
        elif isinstance(decl, TypeAliasDef):
            _scan_annotation(decl.annotation, needed)
        elif isinstance(decl, EnumDef):
            _scan_enum_decl(decl, needed)
    simple: list[SimpleImport] = []
    for imp in extra:
        if isinstance(imp, FromImport):
            for name, _alias in imp.names:
                needed.setdefault(imp.module, set()).add(name)
        elif imp not in simple:
            simple.append(imp)
    from_imports: list[PyImport] = [
        FromImport(module=mod, names=[(n, None) for n in sorted(needed[mod])])
        for mod in sorted(needed)
        if needed[mod]
    ]
    return [*sorted(simple, key=lambda s: s.module), *from_imports]


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FastApiTransformer(Transformer[OpenApiDocument, PythonModule]):
    """Generates a FastAPI app from an OpenAPI doc.

    Attributes:
        body_backend: Strategy that fills each route body.
            Defaults to
            [endpoint_body.NullBodyBackend][],
            which leaves the reifier's `...` stub.
        roots: If given,
            only `components/schemas` entries named here become their own Pydantic model;
            the rest are still available for `$ref` resolution.
            `None` emits every entry.
            Routes are unaffected.
    """

    body_backend: EndpointBodyBackend = field(default_factory=NullBodyBackend)
    roots: Set[str] | None = None

    def apply(self, input: OpenApiDocument) -> Result[PythonModule]:
        ctx = _GenCtx(doc=input, body_backend=self.body_backend, roots=self.roots)
        return ctx.build().with_warnings(ctx.warnings)


# ---------------------------------------------------------------------------
# Generation context (internal)
# ---------------------------------------------------------------------------


@dataclass
class _GenCtx:
    """Per-document generation state."""

    doc: OpenApiDocument
    body_backend: EndpointBodyBackend
    roots: Set[str] | None = None
    warnings: list[TranspilationWarning] = field(default_factory=list)
    extra_imports: list[PyImport] = field(default_factory=list)

    def build(self) -> Result[PythonModule]:
        model_decls = self._generate_models()
        app_var = self._make_app_var()
        security = build_security_module(concrete_map(self.doc.components.security_schemes))
        self.extra_imports.extend(security.imports)
        self.warnings.extend(security.warnings)
        route_fns = self._generate_routes()

        declarations: list[PyDeclaration] = [
            *model_decls,
            app_var,
            *security.declarations,
            *route_fns,
        ]
        imports = _build_imports(declarations, self.extra_imports)
        return Ok(
            PythonModule(
                # A FastAPI application is entered through one module, and `main` is
                # what every deployment recipe for one expects to import.
                name="main",
                imports=imports,
                declarations=declarations,
                source_ids=(self.doc.source_id,),
                module_doc=f'FastAPI application for "{self.doc.info.title}".',
            )
        )

    # -- Pydantic models from components/schemas --------------------------------

    def _generate_models(self) -> Sequence[PyDeclaration]:
        decls: list[PyDeclaration] = []
        for doc in OpenApiComponentExtractor(roots=self.roots).documents(self.doc):
            result = PydanticTransformer().apply(doc)
            self.warnings.extend(result.warnings)
            if isinstance(result, Err):
                for err in result.errors:
                    self._warn(
                        f"Could not generate model for {doc.display_name!r}: {err.message}",
                        code="model-error",
                        location=err.location,
                    )
                continue
            decls.extend(result.value.declarations)
        return decls

    # -- App instance -----------------------------------------------------------

    def _make_app_var(self) -> VarDef:
        info = self.doc.info
        kwargs = [f'title="{_esc(info.title)}"', f'version="{_esc(info.version)}"']
        if info.description:
            kwargs.append(f'description="{_esc(info.description)}"')
        return VarDef(name="app", value=f"FastAPI({', '.join(kwargs)})")

    # -- Routes -----------------------------------------------------------------

    def _generate_routes(self) -> Sequence[FunctionDef]:
        return [
            self._make_route_fn(path, path_item, method, operation)
            for path, path_item in self.doc.paths.items()
            for method, operation in _iter_operations(path_item)
        ]

    def _make_route_fn(
        self, path: str, path_item: PathItem, method: HttpMethod, op: Operation
    ) -> FunctionDef:
        fn_name = _op_fn_name(method, path, op.operation_id)
        merged = _merged_parameters(path_item, op)
        params = self._build_params(merged, op)
        success_code, return_ann = self._success_response(op)
        decorator = self._make_decorator(method, path, success_code, return_ann)
        doc = self._op_doc(op)
        body = self._render_body(path, path_item, method, op, merged)
        sec_params = self._security_params(op)
        return FunctionDef(
            name=fn_name,
            parameters=[*params, *body.parameters, *sec_params],
            return_annotation=return_ann,
            doc=doc,
            decorators=[decorator],
            is_async=True,
            body=tuple(body.lines),
        )

    def _security_params(self, op: Operation) -> Sequence[PyParameter]:
        """Build `Security`/`Depends` parameters for the operation's requirements."""
        params, imports, warnings = route_security_params(
            self._effective_security(op),
            concrete_map(self.doc.components.security_schemes),
            op.source_ref,
        )
        self.extra_imports.extend(imports)
        self.warnings.extend(warnings)
        return params

    def _render_body(
        self,
        path: str,
        path_item: PathItem,
        method: HttpMethod,
        op: Operation,
        merged: Sequence[OasParameter],
    ) -> EndpointBody:
        """Delegate the route body to the configured `EndpointBodyBackend`."""
        ctx = endpoint_context(
            method=method,
            path=path,
            op=op,
            path_item=path_item,
            params=self._route_params(merged, op),
            security=self._effective_security(op),
            resource_schema=self._resource_schema(op),
        )
        body = self.body_backend.render(ctx)
        self.extra_imports.extend(body.imports)
        self.warnings.extend(body.warnings)
        return body

    def _route_params(self, merged: Sequence[OasParameter], op: Operation) -> Sequence[RouteParam]:
        """Resolve the route's parameters for the body template's context."""
        out = [
            RouteParam(name=p.name, py_name=safe_python_field_name(p.name), location=p.in_)
            for p in merged
        ]
        if self._body_param(op) is not None:
            out.append(RouteParam(name="body", py_name="body"))
        return out

    def _effective_security(self, op: Operation) -> Sequence[SecurityRequirement]:
        """Operation-level security, falling back to the document default."""
        return op.security if op.security is not None else self.doc.security

    def _resource_schema(self, op: Operation) -> ObjectSchema | None:
        """Best-effort resolution of the resource object schema for an operation."""
        schema: JsonSchema | None = None
        request_body = concrete(op.request_body) if op.request_body is not None else None
        if request_body is not None:
            schema = _json_schema_from_content(request_body.content)
        if schema is None:
            for code, resp in concrete_map(op.responses).items():
                if code.startswith("2"):
                    schema = _json_schema_from_content(resp.content)
                    break
        return self._lookup_object_schema(schema)

    def _lookup_object_schema(self, schema: JsonSchema | None) -> ObjectSchema | None:
        if schema is None or isinstance(schema, BooleanSchema):
            return None
        ref = schema.ref
        if ref is None and schema.items is not None and not isinstance(schema.items, BooleanSchema):
            ref = schema.items.ref
        if ref is None:
            return schema if isinstance(schema, ObjectSchema) else None
        name = ref.rstrip("/").rsplit("/", 1)[-1]
        target = self.doc.components.schemas.get(name)
        return target if isinstance(target, ObjectSchema) else None

    def _op_doc(self, op: Operation) -> PythonDocString | None:
        if not (op.summary or op.description):
            return None
        return PythonDocString(
            summary=op.summary or op.description or "",
            description=op.description if op.summary else None,
        )

    def _build_params(self, merged: Sequence[OasParameter], op: Operation) -> Sequence[PyParameter]:
        params = [self._oas_param_to_py(p) for p in merged]
        body_param = self._body_param(op)
        if body_param is not None:
            params.append(body_param)
        return _order_params([p for p in params if p is not None])

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
        nullable = nullable_of(base_ann) if not base_ann.nullable else base_ann
        schema_default = _schema_default(p.schema)
        default = schema_default if schema_default is not None else "None"
        return PyParameter(
            name=py_name, annotation=_annotated(nullable, "Query()"), default=default
        )

    def _body_param(self, op: Operation) -> PyParameter | None:
        request_body = concrete(op.request_body) if op.request_body is not None else None
        if request_body is None:
            return None
        schema = _json_schema_from_content(request_body.content)
        if schema is None:
            return None
        return PyParameter(name="body", annotation=_schema_to_annotation(schema))

    def _success_response(self, op: Operation) -> tuple[int | None, PythonTypeAnnotation | None]:
        for code_str, response in concrete_map(op.responses).items():
            if not (code_str.startswith("2") and code_str.isdigit()):
                continue
            code = int(code_str)
            if code == 204:
                return code, NONE
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
        if response_ann is not None and response_ann not in {ANY, NONE}:
            args.append(f"response_model={_annotation_str(response_ann)}")
        return Decorator(name=f"app.{method}({', '.join(args)})")

    def _warn(self, message: str, *, code: str, location: SourceRef | None = None) -> None:
        self.warnings.append(TranspilationWarning(message, code=code, location=location))


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _annotated(base: PythonTypeAnnotation, fastapi_expr: str) -> PythonTypeAnnotation:
    """Wrap *base* in `Annotated[base, fastapi_expr]`."""
    return PythonTypeAnnotation(
        "Annotated",
        module="typing",
        args=[base, PythonTypeAnnotation(fastapi_expr, module="fastapi")],
    )


def _opt_default(p: OasParameter) -> str | None:
    return "None" if not p.required else None


def _order_params(params: list[PyParameter]) -> Sequence[PyParameter]:
    """Make a positional parameter list valid Python.

    Drops duplicate names, keeping the first.
    Orders parameters without a default before those with one.
    FastAPI matches parameters by name, so reordering is safe.
    """
    seen: set[str] = set()
    unique: list[PyParameter] = []
    for p in params:
        if p.name in seen:
            continue
        seen.add(p.name)
        unique.append(p)
    return [p for p in unique if p.default is None] + [p for p in unique if p.default is not None]


def _merged_parameters(path_item: PathItem, op: Operation) -> Sequence[OasParameter]:
    """Merge path-item parameters with operation parameters.

    Per the OpenAPI spec, parameters declared on a `PathItem` apply to all of its operations;
    an operation parameter overrides a path-item one with the same `name` and `in` location.
    """
    by_key: dict[tuple[str, ParameterLocation], OasParameter] = {
        (p.name, p.in_): p for p in concrete_list(path_item.parameters)
    }
    for p in concrete_list(op.parameters):
        by_key[p.name, p.in_] = p
    return list(by_key.values())


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
    for media_type in ("application/json", "application/merge-patch+json", "application/*", "*/*"):
        mt = content.get(media_type)
        if mt is not None:
            return mt.schema
    return None


def _schema_default(schema: JsonSchema | None) -> str | None:
    if schema is None or isinstance(schema, BooleanSchema):
        return None
    if schema.default is not None:
        # TODO: `MutableSequence` and `MutableSequence` don't define `repr`.
        return repr(schema.default.value)
    return None


def _esc(s: str) -> str:
    """Escape double quotes and backslashes for embedding in a string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')
