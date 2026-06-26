"""Tests for REST mapping helpers, the neutral context, and body backends.

Covers the persistence-agnostic `schema_to.generate.rest` helpers, the
`endpoint_context` assembly (extension merging), and both shipped backends:
`NullBodyBackend` (empty) and `TemplateBodyBackend` (renders `x-fastapi-*`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from schema_to.cst.openapi import HttpMethod, Operation, ParameterLocation, PathItem
from schema_to.generate.endpoint_body import (
    EndpointContext,
    NullBodyBackend,
    RouteParam,
    endpoint_context,
)
from schema_to.generate.rest import (
    ParamRole,
    RestOperation,
    infer_operation,
    is_item_path,
    resource_name,
    role_for_param,
)
from schema_to.generate.template_body import TemplateBodyBackend

if TYPE_CHECKING:
    from collections.abc import Mapping

    from schema_to.core import JsonValue


def _op(extensions: Mapping[str, JsonValue] | None = None) -> Operation:
    return Operation(responses={}, extensions=extensions or {})


def test_infer_operation_from_path_and_method() -> None:
    assert infer_operation(HttpMethod.GET, "/api/things/") is RestOperation.LIST
    assert infer_operation(HttpMethod.GET, "/api/things/{id}") is RestOperation.GET
    assert infer_operation(HttpMethod.PUT, "/api/things/{id}") is RestOperation.REPLACE
    assert infer_operation(HttpMethod.DELETE, "/api/things/{id}") is RestOperation.DELETE
    assert infer_operation(HttpMethod.PATCH, "/api/things/{id}") is RestOperation.MERGE_PATCH_ITEM
    assert (
        infer_operation(HttpMethod.PATCH, "/api/things/") is RestOperation.MERGE_PATCH_COLLECTION
    )


def test_is_item_path_and_resource_name() -> None:
    assert is_item_path("/api/things/{id}")
    assert not is_item_path("/api/things/")
    assert resource_name("/api/things/{id}") == "things"
    assert resource_name("/") == "resource"


def test_role_for_param() -> None:
    assert role_for_param("select", ParameterLocation.QUERY) is ParamRole.SELECT
    assert role_for_param("WHERE", ParameterLocation.QUERY) is ParamRole.WHERE
    assert role_for_param("id", ParameterLocation.PATH) is ParamRole.ID
    assert role_for_param("x-api-key", ParameterLocation.HEADER) is ParamRole.OTHER


def test_endpoint_context_merges_extensions() -> None:
    ctx = endpoint_context(
        method=HttpMethod.GET,
        path="/api/things/",
        op=_op({"x-pg-table": "op_table"}),
        path_item=PathItem(extensions={"x-pg-table": "item_table", "x-pg-schema": "s"}),
        params=(),
        security=(),
        resource_schema=None,
    )
    assert ctx.extensions["x-pg-table"] == "op_table"  # operation overrides path item
    assert ctx.extensions["x-pg-schema"] == "s"  # inherited from path item


def test_null_backend_renders_empty_body() -> None:
    body = NullBodyBackend().render(
        EndpointContext(method=HttpMethod.GET, path="/api/things/")
    )
    assert body.lines == ()
    assert body.imports == ()


def test_template_backend_renders_body_imports_and_params() -> None:
    ctx = EndpointContext(
        method=HttpMethod.GET,
        path="/api/things/{id}",
        params=(RouteParam(ParamRole.ID, "id", "id", ParameterLocation.PATH),),
        extensions={
            "x-pg-table": "things",
            "x-fastapi-body": "row = get({{ ext['x-pg-table'] | py }}, {{ arg('id') }})\nreturn row",
            "x-fastapi-imports": ["from db import get"],
            "x-fastapi-params": [{"name": "conn", "annotation": "AsyncConnection"}],
        },
    )
    body = TemplateBodyBackend().render(ctx)
    assert body.lines == ("row = get('things', id)", "return row")
    assert body.parameters[0].name == "conn"
    assert body.parameters[0].annotation is not None
    assert body.imports[0].module == "db"


def test_template_backend_without_extension_is_empty() -> None:
    ctx = EndpointContext(method=HttpMethod.GET, path="/api/things/")
    assert TemplateBodyBackend().render(ctx).lines == ()


def test_template_backend_reports_bad_template() -> None:
    ctx = EndpointContext(
        method=HttpMethod.GET,
        path="/api/things/",
        extensions={"x-fastapi-body": "{{ missing_var }}"},
    )
    body = TemplateBodyBackend().render(ctx)
    assert body.lines == ()
    assert body.warnings
    assert body.warnings[0].code == "template-body-render"
