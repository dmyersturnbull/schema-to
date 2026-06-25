"""Tests for endpoint-body mapping helpers and the default backend.

Covers the `x-pg-*` extension / path-inference mapping from an OpenAPI
operation to an `EndpointContext`, and confirms `NullBodyBackend` leaves the
route body empty (so the reifier keeps its `...` stub).
"""

from __future__ import annotations

from schema_to.cst.openapi import HttpMethod, Operation, ParameterLocation, PathItem
from schema_to.generate.endpoint_body import (
    EndpointContext,
    EndpointKind,
    NullBodyBackend,
    ParamRole,
    resolve_kind,
    resolve_table,
    role_for_param,
)


def _op(**kw: object) -> Operation:
    return Operation(responses={}, **kw)  # type: ignore[arg-type]


def test_infer_kind_from_path_and_method() -> None:
    item = PathItem()
    assert resolve_kind(HttpMethod.GET, "/api/things/", _op(), item) is EndpointKind.LIST
    assert resolve_kind(HttpMethod.GET, "/api/things/{id}", _op(), item) is EndpointKind.GET
    assert resolve_kind(HttpMethod.PUT, "/api/things/{id}", _op(), item) is EndpointKind.REPLACE
    assert resolve_kind(HttpMethod.DELETE, "/api/things/{id}", _op(), item) is EndpointKind.DELETE
    assert (
        resolve_kind(HttpMethod.PATCH, "/api/things/{id}", _op(), item)
        is EndpointKind.MERGE_PATCH_ITEM
    )
    assert (
        resolve_kind(HttpMethod.PATCH, "/api/things/", _op(), item)
        is EndpointKind.MERGE_PATCH_COLLECTION
    )


def test_kind_extension_override() -> None:
    op = _op(extensions={"x-pg-operation": "delete"})
    assert resolve_kind(HttpMethod.GET, "/api/things/", op, PathItem()) is EndpointKind.DELETE


def test_table_inference_and_override() -> None:
    assert resolve_table("/api/things/{id}", _op(), PathItem()) == "things"
    op = _op(extensions={"x-pg-table": "Custom Table"})
    assert resolve_table("/api/things/", op, PathItem()) == "custom_table"


def test_table_extension_on_path_item() -> None:
    item = PathItem(extensions={"x-pg-table": "widgets"})
    assert resolve_table("/api/things/", _op(), item) == "widgets"


def test_role_for_param() -> None:
    assert role_for_param("select", ParameterLocation.QUERY) is ParamRole.SELECT
    assert role_for_param("WHERE", ParameterLocation.QUERY) is ParamRole.WHERE
    assert role_for_param("id", ParameterLocation.PATH) is ParamRole.ID
    assert role_for_param("x-api-key", ParameterLocation.HEADER) is ParamRole.OTHER


def test_null_backend_renders_empty_body() -> None:
    body = NullBodyBackend().render(EndpointContext(kind=EndpointKind.LIST, table="things"))
    assert body.lines == ()
    assert body.imports == ()
