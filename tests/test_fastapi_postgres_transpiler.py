"""End-to-end tests for the `fastapi+postgres` target.

Asserts that the generated FastAPI module and its `pg_runtime` support module
parse as Python, that route bodies are filled with psycopg-backed code (not
`...` stubs), and that path-item parameters reach item routes.
"""

from __future__ import annotations

import ast

import orjson
import pytest

from schema_to import MediaTypes, Ok, OpenApiRawDoc
from schema_to.transpile.factory import TranspilerRouter

_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Things API", "version": "1.0"},
    "components": {
        "schemas": {
            "Thing": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "meta": {"type": "object"},
                },
                "required": ["id", "name"],
            }
        }
    },
    "paths": {
        "/api/things/": {
            "x-pg-table": "things",
            "get": {
                "operationId": "listThings",
                "parameters": [
                    {"name": "select", "in": "query", "schema": {"type": "string"}},
                    {"name": "where", "in": "query", "schema": {"type": "string"}},
                    {"name": "sort", "in": "query", "schema": {"type": "string"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                    {"name": "offset", "in": "query", "schema": {"type": "integer"}},
                ],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/Thing"},
                                }
                            }
                        },
                    }
                },
            },
        },
        "/api/things/{id}": {
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
            ],
            "get": {
                "operationId": "getThing",
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Thing"}}
                        },
                    }
                },
            },
            "put": {
                "operationId": "putThing",
                "requestBody": {
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/Thing"}}
                    }
                },
                "responses": {"200": {"description": "ok"}},
            },
            "delete": {"operationId": "deleteThing", "responses": {"204": {"description": "gone"}}},
        },
    },
}


def _artifacts() -> dict[str, str]:
    doc = OpenApiRawDoc(
        doc_id="t://api",
        content=orjson.dumps(_SPEC),
        media_type=MediaTypes.json,
        display_name="api",
    )
    [transpiler] = TranspilerRouter().route("fastapi+postgres", output_media_type=MediaTypes.json)
    result = transpiler.transpile(doc)
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    return {art.artifact_id: art.content.decode("utf-8") for art in result.value}


@pytest.fixture(scope="module")
def artifacts() -> dict[str, str]:
    return _artifacts()


def test_emits_main_and_runtime(artifacts: dict[str, str]) -> None:
    assert set(artifacts) == {"main.py", "pg_runtime.py"}


def test_generated_sources_parse(artifacts: dict[str, str]) -> None:
    for name, src in artifacts.items():
        try:
            ast.parse(src)
        except SyntaxError as exc:  # pragma: no cover - failure path
            pytest.fail(f"{name} is not valid Python: {exc}")


def test_list_body_is_filled(artifacts: dict[str, str]) -> None:
    main = artifacts["main.py"]
    assert "build_list_query(" in main
    assert "json_columns=('meta',)" in main
    assert "await cur.execute(query, params)" in main
    assert "..." not in main  # no stub bodies remain


def test_connection_is_injected(artifacts: dict[str, str]) -> None:
    main = artifacts["main.py"]
    assert "conn: AsyncConnection = Depends(get_db)" in main
    assert "from psycopg import AsyncConnection" in main


def test_path_item_param_reaches_item_route(artifacts: dict[str, str]) -> None:
    main = artifacts["main.py"]
    assert "async def get_thing(id: Annotated[int, Path()]" in main
    assert "pk_value=id" in main


def test_delete_returns_204_path(artifacts: dict[str, str]) -> None:
    main = artifacts["main.py"]
    assert "build_delete_query(" in main
    assert "raise HTTPException(status_code=404)" in main


def test_plain_fastapi_target_still_stubs() -> None:
    doc = OpenApiRawDoc(
        doc_id="t://api",
        content=orjson.dumps(_SPEC),
        media_type=MediaTypes.json,
        display_name="api",
    )
    [transpiler] = TranspilerRouter().route("fastapi", output_media_type=MediaTypes.json)
    result = transpiler.transpile(doc)
    assert isinstance(result, Ok)
    assert len(result.value) == 1
    src = result.value[0].content.decode("utf-8")
    assert "build_list_query" not in src
    assert "..." in src  # stub bodies preserved
