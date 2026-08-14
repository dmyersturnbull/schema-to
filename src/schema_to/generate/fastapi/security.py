"""Generate FastAPI security wiring from an OpenAPI document.

Translates `components.securitySchemes` into module-level `fastapi.security` objects,
emits a `require_scopes` dependency-factory stub for role enforcement,
and attaches `Security`/`Depends` parameters to guarded routes.

The actual enforcement is intentionally left as a stub:
`require_scopes` raises `NotImplementedError` so the wiring is structurally complete
(schemes appear in the generated OpenAPI, scopes are recorded per route)
without pretending to validate credentials.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from schema_to.ast.python import (
    FromImport,
    FunctionDef,
    Parameter,
    PythonDocString,
    PythonTypeAnnotation,
    VarDef,
)
from schema_to.cst.openapi import ApiKeyLocation, SecuritySchemeType
from schema_to.errors import TranspilationWarning
from schema_to.generate._python_utils import safe_python_field_name

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from schema_to.ast.python import PyImport
    from schema_to.cst.openapi import OAuthFlows, SecurityRequirement, SecurityScheme

__all__ = ["SecurityModule", "build_security_module", "route_security_params"]

_REQUIRE_SCOPES = "require_scopes"


@dataclass(frozen=True, slots=True)
class SecurityModule:
    """Module-level security declarations and the imports they require."""

    declarations: Sequence[VarDef | FunctionDef] = field(default_factory=tuple)
    imports: Sequence[PyImport] = field(default_factory=tuple)
    warnings: Sequence[TranspilationWarning] = field(default_factory=tuple)


def _scheme_var(name: str) -> str:
    return f"{safe_python_field_name(name)}_scheme"


def _flow_token_url(flows: OAuthFlows | None) -> str:
    if flows is None:
        return "token"
    for flow in (flows.password, flows.client_credentials, flows.authorization_code):
        if flow is not None and flow.token_url:
            return flow.token_url
    return "token"


def _scheme_expr(scheme: SecurityScheme) -> tuple[str, str] | None:
    """Return `(fastapi.security class, constructor expression)` for a scheme."""
    match scheme.type_:
        case SecuritySchemeType.OAUTH2:
            url = _flow_token_url(scheme.flows)
            return "OAuth2PasswordBearer", f"OAuth2PasswordBearer(tokenUrl={url!r})"
        case SecuritySchemeType.OPEN_ID_CONNECT:
            url = scheme.open_id_connect_url or ""
            return "OpenIdConnect", f"OpenIdConnect(openIdConnectUrl={url!r})"
        case SecuritySchemeType.HTTP:
            if (scheme.scheme or "").lower() == "basic":
                return "HTTPBasic", "HTTPBasic()"
            return "HTTPBearer", "HTTPBearer()"
        case SecuritySchemeType.API_KEY:
            return _api_key_expr(scheme)
        case SecuritySchemeType.MUTUAL_TLS:
            return None


def _api_key_expr(scheme: SecurityScheme) -> tuple[str, str]:
    name = scheme.name or "X-API-Key"
    cls = {
        ApiKeyLocation.HEADER: "APIKeyHeader",
        ApiKeyLocation.QUERY: "APIKeyQuery",
        ApiKeyLocation.COOKIE: "APIKeyCookie",
    }.get(scheme.in_ or ApiKeyLocation.HEADER, "APIKeyHeader")
    return cls, f"{cls}(name={name!r})"


def build_security_module(schemes: Mapping[str, SecurityScheme]) -> SecurityModule:
    """Build module-level security scheme variables and the `require_scopes` stub."""
    if not schemes:
        return SecurityModule()
    decls: list[VarDef | FunctionDef] = []
    security_names: set[str] = set()
    warnings: list[TranspilationWarning] = []
    for name, scheme in schemes.items():
        expr = _scheme_expr(scheme)
        if expr is None:
            warnings.append(
                TranspilationWarning(
                    f"Security scheme {name!r} of type {scheme.type_.value!r} has no FastAPI "
                    "equivalent; skipping.",
                    code="security-unsupported",
                )
            )
            continue
        cls, value = expr
        security_names.add(cls)
        decls.append(VarDef(name=_scheme_var(name), value=value))
    decls.append(_require_scopes_stub())
    imports: list[PyImport] = [FromImport(module="collections.abc", names=[("Callable", None)])]
    if security_names:
        imports.append(
            FromImport(module="fastapi.security", names=[(n, None) for n in sorted(security_names)])
        )
    return SecurityModule(
        declarations=tuple(decls), imports=tuple(imports), warnings=tuple(warnings)
    )


def _require_scopes_stub() -> FunctionDef:
    return FunctionDef(
        name=_REQUIRE_SCOPES,
        parameters=[
            Parameter(
                name="scopes",
                annotation=PythonTypeAnnotation("list", args=[PythonTypeAnnotation("str")]),
            )
        ],
        return_annotation=PythonTypeAnnotation("Callable", module="collections.abc"),
        doc=PythonDocString(
            summary="Dependency factory enforcing that the caller holds the given scopes.",
            description="Stub: implement real enforcement (decode the token, check scopes).",
        ),
        decorators=[],
        body=(
            "def dependency() -> None:",
            "    if scopes:",
            '        detail = "Missing required scopes: " + ", ".join(scopes)',
            "        raise NotImplementedError(detail)",
            "",
            "return dependency",
        ),
    )


def route_security_params(
    requirements: Sequence[SecurityRequirement] | None, schemes: Mapping[str, SecurityScheme]
) -> tuple[list[Parameter], list[PyImport], list[TranspilationWarning]]:
    """Build `Security`/`Depends` parameters enforcing a route's requirements."""
    if not requirements:
        return [], [], []
    scopes_by_scheme = _collect_scopes(requirements)
    params: list[Parameter] = []
    warnings: list[TranspilationWarning] = []
    all_scopes: set[str] = set()
    for scheme_name, scopes in scopes_by_scheme.items():
        if scheme_name not in schemes:
            warnings.append(
                TranspilationWarning(
                    f"Security requirement references unknown scheme {scheme_name!r}.",
                    code="security-unknown-scheme",
                )
            )
            continue
        all_scopes.update(scopes)
        params.append(
            Parameter(
                name=f"_{safe_python_field_name(scheme_name)}",
                default=f"Security({_scheme_var(scheme_name)}, scopes={sorted(scopes)!r})",
                kind="keyword_only",
            )
        )
    if not params:
        return [], [], warnings
    params.append(
        Parameter(
            name="_scopes",
            default=f"Depends({_REQUIRE_SCOPES}({sorted(all_scopes)!r}))",
            kind="keyword_only",
        )
    )
    imports: list[PyImport] = [
        FromImport(module="fastapi", names=[("Depends", None), ("Security", None)])
    ]
    return params, imports, warnings


def _collect_scopes(requirements: Sequence[SecurityRequirement]) -> dict[str, set[str]]:
    """Union the scopes requested for each scheme across all requirements."""
    scopes_by_scheme: dict[str, set[str]] = {}
    for requirement in requirements:
        for scheme_name, scopes in requirement.items():
            scopes_by_scheme.setdefault(scheme_name, set()).update(scopes)
    return scopes_by_scheme
