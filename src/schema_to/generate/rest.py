"""General REST conventions for mapping OpenAPI paths/operations to intent.

These helpers are deliberately persistence-agnostic: they classify a path and
method into a REST operation and a parameter into a query role, and derive a
resource name from a path.  Endpoint-body templates use them (they are exposed
as Jinja globals) so a template can branch on the operation or pick out the
``where``/``sort``/id parameters without re-deriving REST conventions.
"""

from __future__ import annotations

from enum import StrEnum, auto
from typing import TYPE_CHECKING, NamedTuple

from schema_to.cst.openapi import HttpMethod, ParameterLocation

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "ParamRole",
    "RestOperation",
    "infer_operation",
    "is_item_path",
    "resource_name",
    "role_for_param",
]


class RestOperation(StrEnum):
    """The REST operation a path/method pair conventionally implements.

    Attributes:
        LIST: `GET` on a collection — list rows with select/where/sort/paging.
        GET: `GET` on a single item — fetch one row by id.
        REPLACE: `PUT` — replace a row.
        MERGE_PATCH_ITEM: `PATCH` on a single item — RFC 7396 merge by id.
        MERGE_PATCH_COLLECTION: `PATCH` on a collection — RFC 7396 merge.
        DELETE: `DELETE` — remove a row.
    """

    LIST = auto()
    GET = auto()
    REPLACE = auto()
    MERGE_PATCH_ITEM = auto()
    MERGE_PATCH_COLLECTION = auto()
    DELETE = auto()


class ParamRole(StrEnum):
    """The semantic role a route parameter plays in query construction.

    The member values match the conventional query-parameter names
    (`select`, `where`, `sort`, `limit`, `offset`), so a parameter can be
    classified by looking its name up in the enum.  `OTHER` covers parameters
    with no special meaning (e.g. a header); `ID` is any path parameter; `BODY`
    is the request body.
    """

    SELECT = auto()
    WHERE = auto()
    SORT = auto()
    LIMIT = auto()
    OFFSET = auto()
    ID = auto()
    BODY = auto()
    OTHER = auto()


# Roles that a *named* query parameter may carry (the rest are positional or
# structural and are assigned by location, not name).
_QUERY_ROLES = frozenset(
    {ParamRole.SELECT, ParamRole.WHERE, ParamRole.SORT, ParamRole.LIMIT, ParamRole.OFFSET}
)


def role_for_param(name: str, location: ParameterLocation) -> ParamRole:
    """Classify an OpenAPI parameter by name/location into a `ParamRole`."""
    if location is ParameterLocation.PATH:
        return ParamRole.ID
    candidate = ParamRole.__members__.get(name.upper())
    return candidate if candidate in _QUERY_ROLES else ParamRole.OTHER


def is_item_path(path: str) -> bool:
    """Return `True` if *path* ends in a templated segment such as `/{id}`."""
    last = path.rstrip("/").rsplit("/", 1)[-1]
    return last.startswith("{") and last.endswith("}")


def resource_name(path: str) -> str:
    """Return the last non-templated path segment, or `"resource"` if none."""
    for segment in reversed([s for s in path.split("/") if s]):
        if not (segment.startswith("{") and segment.endswith("}")):
            return segment
    return "resource"


class _Shape(NamedTuple):
    """A `(method, is_item)` pair keying the REST-operation lookup table."""

    method: HttpMethod
    is_item: bool


# POST and unlisted methods fall back to a collection merge-style write.
_OPERATION_BY_SHAPE: Mapping[_Shape, RestOperation] = {
    _Shape(HttpMethod.GET, is_item=True): RestOperation.GET,
    _Shape(HttpMethod.GET, is_item=False): RestOperation.LIST,
    _Shape(HttpMethod.PUT, is_item=True): RestOperation.REPLACE,
    _Shape(HttpMethod.PUT, is_item=False): RestOperation.REPLACE,
    _Shape(HttpMethod.DELETE, is_item=True): RestOperation.DELETE,
    _Shape(HttpMethod.DELETE, is_item=False): RestOperation.DELETE,
    _Shape(HttpMethod.PATCH, is_item=True): RestOperation.MERGE_PATCH_ITEM,
    _Shape(HttpMethod.PATCH, is_item=False): RestOperation.MERGE_PATCH_COLLECTION,
}


def infer_operation(method: HttpMethod, path: str) -> RestOperation:
    """Classify a path/method pair into a `RestOperation` by REST convention."""
    shape = _Shape(method, is_item=is_item_path(path))
    return _OPERATION_BY_SHAPE.get(shape, RestOperation.MERGE_PATCH_COLLECTION)
