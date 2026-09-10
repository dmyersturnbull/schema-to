"""Tests for REST mapping helpers, the neutral context, and body backends.

Covers
the persistence-agnostic `schema_to.generate.rest` helpers,
the `endpoint_context` assembly (extension merging),
and both shipped backends:
[NullBodyBackend][] (empty) and [TemplateBodyBackend][] (named + inline templates).
"""

from typing import TYPE_CHECKING

from schema_to.cst.openapi import HttpMethod, Operation, ParameterLocation, PathItem
from schema_to.generate.fastapi.endpoint_body import (
    EndpointContext,
    NullBodyBackend,
    RouteParam,
    endpoint_context,
)
from schema_to.generate.fastapi.rest import (
    RestOperation,
    infer_operation,
    is_item_path,
    resource_name,
)
from schema_to.generate.fastapi.template_body import TemplateBodyBackend

if TYPE_CHECKING:
    from collections.abc import Mapping

    from schema_to.core import JsonValue


def _op(extensions: Mapping[str, JsonValue] | None = None) -> Operation:
    return Operation(responses={}, extensions=extensions or {})


def test_infer_operation_from_path_and_method() -> None:
    assert infer_operation(HttpMethod.GET, "/api/things/") is RestOperation.LIST
    assert infer_operation(HttpMethod.GET, "/api/things/{id}") is RestOperation.GET
    assert infer_operation(HttpMethod.PUT, "/api/things/{id}") is RestOperation.PUT
    assert infer_operation(HttpMethod.PATCH, "/api/things/{id}") is RestOperation.PATCH
    assert infer_operation(HttpMethod.DELETE, "/api/things/{id}") is RestOperation.DELETE


def test_is_item_path_and_resource_name() -> None:
    assert is_item_path("/api/things/{id}")
    assert not is_item_path("/api/things/")
    assert resource_name("/api/things/{id}") == "things"
    assert resource_name("/") == "resource"


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
    body = NullBodyBackend().render(EndpointContext(method=HttpMethod.GET, path="/api/things/"))
    assert body.lines == ()
    assert body.imports == ()


def test_template_backend_inline_body() -> None:
    ctx = EndpointContext(
        method=HttpMethod.GET,
        path="/api/things/{id}",
        params=(RouteParam("id", "id", ParameterLocation.PATH),),
        extensions={
            "x-pg-table": "things",
            "x-fastapi-body": "row = get({{ ext['x-pg-table'] | repr }}, {{ param('id') }})\nreturn row",
            "x-fastapi-imports": ["from db import get"],
            "x-fastapi-params": [{"name": "conn", "annotation": "AsyncConnection"}],
        },
    )
    body = TemplateBodyBackend().render(ctx)
    assert body.lines == ("row = get('things', id)", "return row")
    assert body.parameters[0].name == "conn"
    assert body.parameters[0].annotation is not None
    assert body.imports[0].module == "db"


def test_template_backend_named_template() -> None:
    backend = TemplateBodyBackend(named_templates={"fetch": "return get({{ param('id') }})"})
    ctx = EndpointContext(
        method=HttpMethod.GET,
        path="/api/things/{id}",
        params=(RouteParam("id", "id", ParameterLocation.PATH),),
        extensions={"x-fastapi-template": "fetch"},
    )
    assert TemplateBodyBackend.render(backend, ctx).lines == ("return get(id)",)


def test_named_template_takes_precedence_over_inline() -> None:
    backend = TemplateBodyBackend(named_templates={"t": "named"})
    ctx = EndpointContext(
        method=HttpMethod.GET,
        path="/x",
        extensions={"x-fastapi-template": "t", "x-fastapi-body": "inline"},
    )
    assert backend.render(ctx).lines == ("named",)


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
