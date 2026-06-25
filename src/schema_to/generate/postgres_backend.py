"""PostgreSQL endpoint-body backend.

Fills FastAPI route bodies with psycopg-based code, rendered from Jinja2
templates (one per `EndpointKind`).  The bodies delegate runtime query building
to a shipped support module, `pg_runtime.py`, emitted once per document via
`support_artifacts`.

psycopg is *not* a dependency of schema-to — it is only required by the
generated application at runtime; this backend merely emits its imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from schema_to.ast.python import FromImport, PythonTypeAnnotation
from schema_to.ast.python import Parameter as PyParameter
from schema_to.errors import TranspilationWarning
from schema_to.generate.endpoint_body import (
    EndpointBody,
    EndpointBodyBackend,
    EndpointContext,
    EndpointKind,
    ParamRole,
)
from schema_to.generate.pg_query import json_columns
from schema_to.io.sink import PythonArtifact

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["RUNTIME_MODULE", "PostgresBodyBackend"]

# Name of the emitted runtime support module (also the import path used by the
# generated routes).
RUNTIME_MODULE = "pg_runtime"

_CONN_PARAM = PyParameter(
    name="conn",
    annotation=PythonTypeAnnotation("AsyncConnection", module="psycopg"),
    default="Depends(get_db)",
    kind="keyword_only",
)

# Extra `pg_runtime` names imported by each endpoint kind, beyond `get_db`.
_RUNTIME_IMPORTS: dict[EndpointKind, tuple[str, ...]] = {
    EndpointKind.LIST: ("build_list_query", "dict_row"),
    EndpointKind.GET: ("build_get_query", "dict_row"),
    EndpointKind.DELETE: ("build_delete_query",),
    EndpointKind.REPLACE: ("build_replace_query", "dict_row", "to_dict"),
    EndpointKind.MERGE_PATCH_ITEM: ("build_merge_patch_query", "dict_row", "to_dict"),
    EndpointKind.MERGE_PATCH_COLLECTION: (),
}

# Endpoint kinds whose body raises `HTTPException` for a missing row.
_NEEDS_HTTP_EXCEPTION = frozenset(
    {EndpointKind.GET, EndpointKind.DELETE, EndpointKind.MERGE_PATCH_ITEM}
)
_ITEM_KINDS = frozenset(
    {EndpointKind.GET, EndpointKind.DELETE, EndpointKind.REPLACE, EndpointKind.MERGE_PATCH_ITEM}
)
_BODY_KINDS = frozenset({EndpointKind.REPLACE, EndpointKind.MERGE_PATCH_ITEM})


@cache
def _environment() -> Environment:
    # Templates render Python source, not markup; `select_autoescape` leaves the
    # non-HTML `.jinja` templates unescaped (escaping would corrupt the code).
    return Environment(
        loader=PackageLoader("schema_to.generate", "templates/postgres"),
        undefined=StrictUndefined,
        keep_trailing_newline=False,
        autoescape=select_autoescape(),
    )


@dataclass(frozen=True, slots=True)
class PostgresBodyBackend(EndpointBodyBackend):
    """Renders psycopg-backed route bodies and the `pg_runtime` support module."""

    def render(self, ctx: EndpointContext) -> EndpointBody:
        warnings = list(self._validate(ctx))
        lines = self._render_lines(ctx)
        return EndpointBody(
            lines=lines,
            parameters=(_CONN_PARAM,),
            imports=self._imports(ctx.kind),
            warnings=warnings,
        )

    def support_artifacts(self) -> Sequence[PythonArtifact]:
        source = _environment().get_template("pg_runtime.py.jinja").render()
        return (
            PythonArtifact(artifact_id=f"{RUNTIME_MODULE}.py", content=source.encode("utf-8")),
        )

    # -- internals ----------------------------------------------------------

    def _render_lines(self, ctx: EndpointContext) -> tuple[str, ...]:
        template = _environment().get_template(f"{ctx.kind.value}.py.jinja")
        rendered = template.render(**self._variables(ctx))
        return tuple(rendered.rstrip("\n").split("\n"))

    def _variables(self, ctx: EndpointContext) -> dict[str, str]:
        cols = tuple(sorted(json_columns(ctx.resource_schema)))
        return {
            "schema": repr(ctx.schema),
            "table": repr(ctx.table),
            "pk": repr(ctx.pk_column),
            "id": self._param_ref(ctx, ParamRole.ID),
            "body": self._param_ref(ctx, ParamRole.BODY),
            "select": self._param_ref(ctx, ParamRole.SELECT),
            "where": self._param_ref(ctx, ParamRole.WHERE),
            "sort": self._param_ref(ctx, ParamRole.SORT),
            "limit": self._param_ref(ctx, ParamRole.LIMIT),
            "offset": self._param_ref(ctx, ParamRole.OFFSET),
            "json_columns": repr(cols),
        }

    def _param_ref(self, ctx: EndpointContext, role: ParamRole) -> str:
        param = ctx.param(role)
        return param.py_name if param is not None else "None"

    def _validate(self, ctx: EndpointContext) -> Sequence[TranspilationWarning]:
        warnings: list[TranspilationWarning] = []
        if ctx.kind is EndpointKind.MERGE_PATCH_COLLECTION:
            warnings.append(
                TranspilationWarning(
                    f"Collection merge-patch on {ctx.table!r} is emitted as a stub.",
                    code="pg-unsupported-operation",
                )
            )
        if ctx.kind in _ITEM_KINDS and ctx.param(ParamRole.ID) is None:
            warnings.append(
                TranspilationWarning(
                    f"No path parameter for {ctx.kind.value} on {ctx.table!r}; "
                    "the generated body will reference an undefined primary key.",
                    code="pg-missing-id",
                )
            )
        if ctx.kind in _BODY_KINDS and ctx.param(ParamRole.BODY) is None:
            warnings.append(
                TranspilationWarning(
                    f"No request body for {ctx.kind.value} on {ctx.table!r}; "
                    "the generated body will reference an undefined payload.",
                    code="pg-missing-body",
                )
            )
        return warnings

    def _imports(self, kind: EndpointKind) -> tuple[FromImport, ...]:
        fastapi_names = ["Depends"]
        if kind in _NEEDS_HTTP_EXCEPTION:
            fastapi_names.append("HTTPException")
        runtime_names = ["get_db", *_RUNTIME_IMPORTS[kind]]
        return (
            FromImport(module="fastapi", names=[(n, None) for n in sorted(fastapi_names)]),
            FromImport(module=RUNTIME_MODULE, names=[(n, None) for n in sorted(runtime_names)]),
        )
