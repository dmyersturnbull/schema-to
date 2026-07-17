"""General REST conventions for mapping OpenAPI paths/operations to intent.

These helpers are deliberately persistence-agnostic and carry no awareness of
any particular query convention (no notion of `where`/`select`/etc. lives here —
that belongs to templates and their runtime library).  They classify a path and
method into a REST operation and derive a resource name from a path, and are
exposed to endpoint-body templates as Jinja globals.
"""


from enum import StrEnum, auto
from typing import TYPE_CHECKING, NamedTuple

from schema_to.cst.openapi import HttpMethod

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["RestOperation", "infer_operation", "is_item_path", "resource_name"]


class RestOperation(StrEnum):
    """The REST operation a path/method pair conventionally implements.

    Attributes:
        LIST: `GET` on a collection.
        GET: `GET` on a single item.
        PUT: `PUT` on a single item (replace).
        PATCH: `PATCH` (RFC 7396 merge).
        DELETE: `DELETE`.
    """

    LIST = auto()
    GET = auto()
    PUT = auto()
    PATCH = auto()
    DELETE = auto()


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


# POST and unlisted methods fall back to a collection write (`PATCH`).
_OPERATION_BY_SHAPE: Mapping[_Shape, RestOperation] = {
    _Shape(HttpMethod.GET, is_item=True): RestOperation.GET,
    _Shape(HttpMethod.GET, is_item=False): RestOperation.LIST,
    _Shape(HttpMethod.PUT, is_item=True): RestOperation.PUT,
    _Shape(HttpMethod.PUT, is_item=False): RestOperation.PUT,
    _Shape(HttpMethod.PATCH, is_item=True): RestOperation.PATCH,
    _Shape(HttpMethod.PATCH, is_item=False): RestOperation.PATCH,
    _Shape(HttpMethod.DELETE, is_item=True): RestOperation.DELETE,
    _Shape(HttpMethod.DELETE, is_item=False): RestOperation.DELETE,
}


def infer_operation(method: HttpMethod, path: str) -> RestOperation:
    """Classify a path/method pair into a `RestOperation` by REST convention."""
    shape = _Shape(method, is_item=is_item_path(path))
    return _OPERATION_BY_SHAPE.get(shape, RestOperation.PATCH)
