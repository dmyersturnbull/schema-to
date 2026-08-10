"""Pluggable backends that fill FastAPI route bodies.

The FastAPI generator produces route *signatures* (`generate/fastapi.py`);
the *bodies* are delegated to an `EndpointBodyBackend`, mirroring the way
`FastApiTransformer` already embeds `PydanticTransformer` for models.
This keeps the FastAPI generator agnostic of any particular persistence layer.

A backend receives an `EndpointContext` —
the operation's method, path, resolved parameters, security, merged `x-` extensions, and resource schema —
and returns an `EndpointBody`,
which includes rendered statement lines, the imports and extra signature parameters those lines need, and any warnings.
The context carries no persistence-specific fields;
a backend that wants e.g. a table name reads it from the extensions.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from schema_to.ast.python import Parameter as PyParameter
    from schema_to.ast.python import PyImport
    from schema_to.core import JsonValue
    from schema_to.cst.json_schema import ObjectSchema
    from schema_to.cst.openapi import (
        HttpMethod,
        Operation,
        ParameterLocation,
        PathItem,
        SecurityRequirement,
    )
    from schema_to.errors import TranspilationWarning
    from schema_to.io.sink import PythonArtifact

__all__ = [
    "EndpointBody",
    "EndpointBodyBackend",
    "EndpointContext",
    "NullBodyBackend",
    "RouteParam",
    "endpoint_context",
]


@dataclass(frozen=True, slots=True)
class RouteParam:
    """A resolved route parameter, linking the OpenAPI name to its Python name.

    A template selects parameters by name (and, if it cares, by location);
    core attaches no query-specific meaning to them.

    Attributes:
        name: The original OpenAPI parameter name (or `"body"` for the body).
        py_name: The sanitised Python identifier used in the route signature.
        location: The OpenAPI parameter location; `None` for the request body.
    """

    name: str
    py_name: str
    location: ParameterLocation | None = None


@dataclass(frozen=True, slots=True)
class EndpointContext:
    """Everything a backend needs to render one route body.

    Attributes:
        method: The HTTP method.
        path: The OpenAPI path template, e.g. `/things/{id}`.
        operation_id: The operation's `operationId`, if any.
        params: Resolved route parameters, in signature order.
        security: Effective security requirements for the operation.
        extensions: The operation's `x-` extensions merged over the path item's.
        resource_schema: The resolved resource object schema, when known.
    """

    method: HttpMethod
    path: str
    operation_id: str | None = None
    params: Sequence[RouteParam] = field(default_factory=tuple)
    security: Sequence[SecurityRequirement] = field(default_factory=tuple)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    resource_schema: ObjectSchema | None = None

    def param(self, name: str) -> RouteParam | None:
        """Return the parameter with the given OpenAPI name, or `None`."""
        return next((p for p in self.params if p.name == name), None)


@dataclass(frozen=True, slots=True)
class EndpointBody:
    """The result of rendering a route body.

    Attributes:
        lines: Body statement lines, each without leading indentation.
        parameters: Extra route parameters the body needs
          (e.g. an injected database connection);
          appended to the route signature.
        imports: Imports the body statements require.
        warnings: Non-fatal diagnostics raised while rendering.
    """

    lines: Sequence[str] = field(default_factory=tuple)
    parameters: Sequence[PyParameter] = field(default_factory=tuple)
    imports: Sequence[PyImport] = field(default_factory=tuple)
    warnings: Sequence[TranspilationWarning] = field(default_factory=tuple)


class EndpointBodyBackend(ABC):
    """Strategy that turns an `EndpointContext` into a route body."""

    @abstractmethod
    def render(self, ctx: EndpointContext) -> EndpointBody:
        """Render the body for one route."""
        raise NotImplementedError

    def support_artifacts(self) -> Sequence[PythonArtifact]:
        """Extra files the rendered bodies depend on (e.g. a runtime helper).

        Emitted once per transpiled document. Defaults to none.
        """
        return ()


@dataclass(frozen=True, slots=True)
class NullBodyBackend(EndpointBodyBackend):
    """Default backend that emits no body, leaving the reifier's `...` stub.

    This preserves the dependency-free behavior of the plain `fastapi` target
    for operations that declare no body extension.
    """

    def render(self, ctx: EndpointContext) -> EndpointBody:  # ruff:ignore[unused-method-argument]  # Subclasses might use it.
        return EndpointBody()


def _merged_extensions(op: Operation, path_item: PathItem) -> Mapping[str, JsonValue]:
    """Merge an operation's `x-` extensions over its path item's."""
    return {**path_item.extensions, **op.extensions}


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
        method=method,
        path=path,
        operation_id=op.operation_id,
        params=tuple(params),
        security=tuple(security),
        extensions=_merged_extensions(op, path_item),
        resource_schema=resource_schema,
    )
