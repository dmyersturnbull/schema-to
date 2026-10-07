"""Generic endpoint-body backend driven by OpenAPI extensions.

This backend keeps schema-to free of any persistence layer.
Each operation chooses its route body through `x-` extensions.
The backend renders it with a neutral context,
returning the statements plus the imports and extra signature parameters the operation declares.

- `x-fastapi-template`: the *name* of a Jinja template registered on the CLI with
  `--template <name>=<path>` (the recommended mechanism).
- `x-fastapi-body`: an inline Jinja template (string), as an alternative.
- `x-fastapi-imports`: a list of import statements the body needs, e.g.
  `["from fastapi import Depends", "from query_dsl import build_get_query"]`.
- `x-fastapi-params`: a list of extra signature parameters, each a mapping with
  `name` and optional `annotation`, `default`, and `kind`.

The template context is documented in `examples/postgres/README.md`:
the operation (`method`, `path`, `operation_id`, `operation`),
its resolved `params` (plus `param(name)` and `params_by_name`),
the merged `ext` mapping,
the resource's `json_properties`,
and the REST helpers from `schema_to.generate.rest`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from typing import TYPE_CHECKING, cast

from jinja2 import Environment, StrictUndefined, TemplateError, select_autoescape

from schema_to.ast.python import FromImport, PythonTypeAnnotation, SimpleImport
from schema_to.ast.python import Parameter as PyParameter
from schema_to.errors import TranspilationWarning
from schema_to.generate.fastapi.endpoint_body import EndpointBody, EndpointBodyBackend
from schema_to.generate.fastapi.resource import json_properties
from schema_to.generate.fastapi.rest import (
    RestOperation,
    infer_operation,
    is_item_path,
    resource_name,
)

if TYPE_CHECKING:
    from schema_to.ast.python import PyImport
    from schema_to.core import JsonValue
    from schema_to.generate.fastapi.endpoint_body import EndpointContext

__all__ = ["BODY_KEY", "IMPORTS_KEY", "PARAMS_KEY", "TEMPLATE_KEY", "TemplateBodyBackend"]

TEMPLATE_KEY = "x-fastapi-template"
BODY_KEY = "x-fastapi-body"
IMPORTS_KEY = "x-fastapi-imports"
PARAMS_KEY = "x-fastapi-params"


@cache
def _environment() -> Environment:
    # Templates render Python source, not markup, so autoescaping must stay off
    # for these string templates (escaping would corrupt the code, e.g. turning
    # a quote into `&#39;`). StrictUndefined turns a typo into a clear error.
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
        keep_trailing_newline=False,
    )
    env.filters["repr"] = repr
    cast("dict[str, object]", env.globals).update(_TEMPLATE_GLOBALS)
    return env


# REST helpers exposed to every endpoint-body template.
_TEMPLATE_GLOBALS: Mapping[str, object] = {
    "is_item_path": is_item_path,
    "resource_name": resource_name,
    "infer_operation": infer_operation,
    "RestOperation": RestOperation,
}


@dataclass(frozen=True, slots=True)
class TemplateBodyBackend(EndpointBodyBackend):
    """Renders route bodies from named templates or the `x-fastapi-*` extensions.

    Attributes:
        named_templates: Jinja template sources registered by name (from the
            CLI's `--template <name>=<path>`), referenced by `x-fastapi-template`.
    """

    named_templates: Mapping[str, str] = field(default_factory=dict)

    def render(self, ctx: EndpointContext) -> EndpointBody:
        source = self._source(ctx)
        if source is None:
            return EndpointBody()
        rendered = self._render(source, ctx)
        if rendered is None:
            return EndpointBody(warnings=(self._render_warning(ctx),))
        return EndpointBody(
            lines=tuple(rendered.rstrip("\n").split("\n")),
            parameters=_parse_params(ctx.extensions.get(PARAMS_KEY)),
            imports=_parse_imports(ctx.extensions.get(IMPORTS_KEY)),
        )

    def _source(self, ctx: EndpointContext) -> str | None:
        name = ctx.extensions.get(TEMPLATE_KEY)
        if isinstance(name, str):
            return self.named_templates.get(name)
        body = ctx.extensions.get(BODY_KEY)
        return body if isinstance(body, str) else None

    def _render(self, source: str, ctx: EndpointContext) -> str | None:
        try:
            return _environment().from_string(source).render(_variables(ctx))
        except TemplateError:
            return None

    def _render_warning(self, ctx: EndpointContext) -> TranspilationWarning:
        return TranspilationWarning(
            f"Could not render the body template for {ctx.method.value.upper()} {ctx.path}.",
            code="template-body-render",
            location=ctx.location,
        )


def _variables(ctx: EndpointContext) -> Mapping[str, object]:
    by_name = {p.name: p.py_name for p in ctx.params}
    return {
        "method": ctx.method.value,
        "path": ctx.path,
        "operation_id": ctx.operation_id,
        "operation": infer_operation(ctx.method, ctx.path),
        "params": ctx.params,
        "params_by_name": by_name,
        "param": lambda name: by_name.get(name, "None"),
        "ext": ctx.extensions,
        "json_properties": json_properties(ctx.resource_schema),
    }


def _parse_imports(value: JsonValue | None) -> tuple[PyImport, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(_parse_import(line) for line in value if isinstance(line, str))


def _parse_import(line: str) -> PyImport:
    text = line.strip()
    if text.startswith("from "):
        module, _, names = text[len("from ") :].partition(" import ")
        return FromImport(module=module.strip(), names=[_split_alias(n) for n in names.split(",")])
    module, alias = _split_alias(text.removeprefix("import "))
    return SimpleImport(module=module, alias=alias)


def _split_alias(name: str) -> tuple[str, str | None]:
    base, _, alias = name.strip().partition(" as ")
    return base.strip(), (alias.strip() or None)


def _parse_params(value: JsonValue | None) -> tuple[PyParameter, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        _parse_param(cast("Mapping[str, JsonValue]", item))
        for item in value
        if isinstance(item, Mapping)
    )


def _parse_param(spec: Mapping[str, JsonValue]) -> PyParameter:
    name = spec.get("name")
    annotation = spec.get("annotation")
    default = spec.get("default")
    kind = spec.get("kind")
    return PyParameter(
        name=str(name),
        annotation=PythonTypeAnnotation(annotation) if isinstance(annotation, str) else None,
        default=default if isinstance(default, str) else None,
        kind=kind if isinstance(kind, str) else "keyword_only",
    )
