"""Pluggable backends that fill FastAPI route bodies.

The FastAPI generator produces route *signatures* (`generate/fastapi.py`); the
*bodies* are delegated to an `EndpointBodyBackend`, mirroring the way
`FastApiTransformer` already embeds `PydanticTransformer` for models.  This keeps
the FastAPI generator agnostic of any particular persistence layer: swap the
backend to target psycopg, SQLite, an in-memory store, etc.

A backend receives an `EndpointContext` (the REST operation kind plus the table,
schema, primary key, parameter roles, and resource schema resolved from the
OpenAPI document) and returns an `EndpointBody` (rendered statement lines, the
imports those lines need, and any warnings).

This module also owns the mapping from an OpenAPI path/operation to a
`(kind, table, schema, primary key)` tuple, using `x-pg-*` extensions with a
fallback that infers them from the path shape and HTTP method.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import TYPE_CHECKING

from schema_to.cst.openapi import HttpMethod, ParameterLocation
from schema_to.generate._names import safe_sql_identifier

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from schema_to.ast.python import PyImport
    from schema_to.core import JsonValue
    from schema_to.cst.json_schema import ObjectSchema
    from schema_to.cst.openapi import Operation, PathItem, SecurityRequirement
    from schema_to.errors import TranspilationWarning

__all__ = [
    "DEFAULT_PK_COLUMN",
    "EndpointBody",
    "EndpointBodyBackend",
    "EndpointContext",
    "EndpointKind",
    "NullBodyBackend",
    "ParamRole",
    "RouteParam",
    "endpoint_context",
]

DEFAULT_PK_COLUMN = "id"
DEFAULT_SCHEMA = "public"


class EndpointKind(StrEnum):
    """The REST operation a route implements, used to pick a body template.

    Attributes:
        LIST: `GET` on a collection — list rows with select/where/sort/paging.
        GET: `GET` on a single item — fetch one row by primary key.
        REPLACE: `PUT` on a single item — replace a row by primary key.
        MERGE_PATCH_ITEM: `PATCH` on a single item — RFC 7396 merge by key.
        MERGE_PATCH_COLLECTION: `PATCH` on a collection — RFC 7396 merge.
        DELETE: `DELETE` on a single item — remove a row by primary key.
    """

    LIST = auto()
    GET = auto()
    REPLACE = auto()
    MERGE_PATCH_ITEM = auto()
    MERGE_PATCH_COLLECTION = auto()
    DELETE = auto()


class ParamRole(StrEnum):
    """The semantic role a route parameter plays in query construction.

    `OTHER` covers parameters with no special meaning to a backend (e.g. a
    header), which are still passed through to the route signature.
    """

    SELECT = auto()
    WHERE = auto()
    SORT = auto()
    LIMIT = auto()
    OFFSET = auto()
    ID = auto()
    BODY = auto()
    OTHER = auto()


# OpenAPI parameter names recognised as list-operation query roles.
_ROLE_BY_NAME: Mapping[str, ParamRole] = {
    "select": ParamRole.SELECT,
    "where": ParamRole.WHERE,
    "sort": ParamRole.SORT,
    "limit": ParamRole.LIMIT,
    "offset": ParamRole.OFFSET,
}


@dataclass(frozen=True, slots=True)
class RouteParam:
    """A resolved route parameter, linking the OpenAPI name to its Python name.

    Attributes:
        role: The semantic role used by backends to build queries.
        name: The original OpenAPI parameter name (or `"body"` for the body).
        py_name: The sanitised Python identifier used in the route signature.
        location: The OpenAPI parameter location; `None` for the request body.
    """

    role: ParamRole
    name: str
    py_name: str
    location: ParameterLocation | None = None


@dataclass(frozen=True, slots=True)
class EndpointContext:
    """Everything a backend needs to render one route body.

    Attributes:
        kind: The REST operation kind.
        table: PostgreSQL table name (already a safe identifier).
        schema: PostgreSQL schema name.
        pk_column: Primary-key column name.
        params: Resolved route parameters, in signature order.
        security: Effective security requirements for the operation.
        resource_schema: The resolved resource object schema, when known; used
            to decide which columns hold JSON.
    """

    kind: EndpointKind
    table: str
    pk_column: str = DEFAULT_PK_COLUMN
    schema: str = DEFAULT_SCHEMA
    params: Sequence[RouteParam] = field(default_factory=tuple)
    security: Sequence[SecurityRequirement] = field(default_factory=tuple)
    resource_schema: ObjectSchema | None = None

    def param(self, role: ParamRole) -> RouteParam | None:
        """Return the first parameter with the given role, or `None`."""
        return next((p for p in self.params if p.role is role), None)


@dataclass(frozen=True, slots=True)
class EndpointBody:
    """The result of rendering a route body.

    Attributes:
        lines: Body statement lines, each without leading indentation.
        imports: Imports the body statements require.
        warnings: Non-fatal diagnostics raised while rendering.
    """

    lines: Sequence[str] = field(default_factory=tuple)
    imports: Sequence[PyImport] = field(default_factory=tuple)
    warnings: Sequence[TranspilationWarning] = field(default_factory=tuple)


class EndpointBodyBackend(ABC):
    """Strategy that turns an `EndpointContext` into a route body."""

    @abstractmethod
    def render(self, ctx: EndpointContext) -> EndpointBody:
        """Render the body for one route."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class NullBodyBackend(EndpointBodyBackend):
    """Default backend that emits no body, leaving the reifier's `...` stub.

    This preserves the dependency-free behavior of the plain `fastapi` target.
    """

    def render(self, ctx: EndpointContext) -> EndpointBody:  # noqa: ARG002
        return EndpointBody()


# ---------------------------------------------------------------------------
# Mapping: OpenAPI path/operation → EndpointContext metadata
# ---------------------------------------------------------------------------


def _ext(op: Operation, path_item: PathItem, key: str) -> JsonValue | None:
    """Look up an `x-` extension on the operation, falling back to the path item."""
    if key in op.extensions:
        return op.extensions[key]
    return path_item.extensions.get(key)


def _ext_str(op: Operation, path_item: PathItem, key: str) -> str | None:
    value = _ext(op, path_item, key)
    return value if isinstance(value, str) else None


def _is_item_path(path: str) -> bool:
    """Return `True` if *path* ends in a templated segment such as `/{id}`."""
    last = path.rstrip("/").rsplit("/", 1)[-1]
    return last.startswith("{") and last.endswith("}")


def _infer_table(path: str) -> str:
    """Derive a table name from the last non-templated path segment."""
    for segment in reversed([s for s in path.split("/") if s]):
        if not (segment.startswith("{") and segment.endswith("}")):
            return safe_sql_identifier(segment)
    return safe_sql_identifier(path or "table")


# (method, is_item_path) → endpoint kind. POST and unlisted methods fall back
# to a collection merge-style write.
_KIND_BY_SHAPE: Mapping[tuple[HttpMethod, bool], EndpointKind] = {
    (HttpMethod.GET, True): EndpointKind.GET,
    (HttpMethod.GET, False): EndpointKind.LIST,
    (HttpMethod.PUT, True): EndpointKind.REPLACE,
    (HttpMethod.PUT, False): EndpointKind.REPLACE,
    (HttpMethod.DELETE, True): EndpointKind.DELETE,
    (HttpMethod.DELETE, False): EndpointKind.DELETE,
    (HttpMethod.PATCH, True): EndpointKind.MERGE_PATCH_ITEM,
    (HttpMethod.PATCH, False): EndpointKind.MERGE_PATCH_COLLECTION,
}


def _infer_kind(method: HttpMethod, path: str) -> EndpointKind:
    return _KIND_BY_SHAPE.get((method, _is_item_path(path)), EndpointKind.MERGE_PATCH_COLLECTION)


_KIND_BY_NAME: Mapping[str, EndpointKind] = {k.value: k for k in EndpointKind}


def resolve_kind(method: HttpMethod, path: str, op: Operation, path_item: PathItem) -> EndpointKind:
    """Resolve the endpoint kind: `x-pg-operation` override, else inference."""
    override = _ext_str(op, path_item, "x-pg-operation")
    if override is not None and override in _KIND_BY_NAME:
        return _KIND_BY_NAME[override]
    return _infer_kind(method, path)


def resolve_table(path: str, op: Operation, path_item: PathItem) -> str:
    """Resolve the table name: `x-pg-table` override, else path inference."""
    override = _ext_str(op, path_item, "x-pg-table")
    return safe_sql_identifier(override) if override else _infer_table(path)


def role_for_param(name: str, location: ParameterLocation) -> ParamRole:
    """Classify an OpenAPI parameter by name/location into a `ParamRole`."""
    if location is ParameterLocation.PATH:
        return ParamRole.ID
    return _ROLE_BY_NAME.get(name.lower(), ParamRole.OTHER)


def endpoint_context(
    *,
    method: HttpMethod,
    path: str,
    op: Operation,
    path_item: PathItem,
    params: Sequence[RouteParam],
    security: Sequence[SecurityRequirement],
    resource_schema: ObjectSchema | None,
) -> EndpointContext:
    """Assemble an `EndpointContext` from a resolved path/operation."""
    return EndpointContext(
        kind=resolve_kind(method, path, op, path_item),
        table=resolve_table(path, op, path_item),
        pk_column=_ext_str(op, path_item, "x-pg-id") or DEFAULT_PK_COLUMN,
        schema=_ext_str(op, path_item, "x-pg-schema") or DEFAULT_SCHEMA,
        params=tuple(params),
        security=tuple(security),
        resource_schema=resource_schema,
    )
