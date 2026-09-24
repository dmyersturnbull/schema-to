"""Tests for FastAPI security generation from OpenAPI security schemes."""

import ast

from tests.support.docs import openapi_doc
from tests.support.drive import FASTAPI

_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Sec", "version": "1"},
    "components": {
        "securitySchemes": {
            "oauth": {
                "type": "oauth2",
                "flows": {
                    "password": {
                        "tokenUrl": "/oauth/token",
                        "scopes": {"things:read": "r", "things:write": "w"},
                    }
                },
            },
            "apiKey": {"type": "apiKey", "in": "header", "name": "X-Key"},
        }
    },
    "security": [{"oauth": ["things:read"]}],
    "paths": {
        "/api/things/{id}": {
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
            ],
            "get": {"operationId": "getThing", "responses": {"200": {"description": "ok"}}},
            "delete": {
                "operationId": "deleteThing",
                "security": [{"oauth": ["things:write"]}, {"apiKey": []}],
                "responses": {"204": {"description": "gone"}},
            },
        }
    },
}


def _src() -> str:
    doc = openapi_doc(_SPEC, "t://api", display_name="api")
    return FASTAPI.text(doc)


def test_schemes_become_module_variables() -> None:
    src = _src()
    assert "oauth_scheme = OAuth2PasswordBearer(tokenUrl='/oauth/token')" in src
    assert "api_key_scheme = APIKeyHeader(name='X-Key')" in src
    assert "from fastapi.security import APIKeyHeader, OAuth2PasswordBearer" in src
    ast.parse(src)


def test_require_scopes_stub_is_emitted() -> None:
    src = _src()
    assert "def require_scopes(scopes: list[str]) -> Callable:" in src
    assert "raise NotImplementedError" in src


def test_operation_security_overrides_document_default() -> None:
    src = _src()
    # delete declares its own requirements (oauth:write OR apiKey)
    assert "Security(oauth_scheme, scopes=['things:write'])" in src
    assert "Security(api_key_scheme, scopes=[])" in src


def test_document_security_applies_when_operation_omits_it() -> None:
    src = _src()
    # get inherits the document-level requirement
    assert "Security(oauth_scheme, scopes=['things:read'])" in src
    assert "Depends(require_scopes(['things:read']))" in src
