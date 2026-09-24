"""Turning a parsed OpenAPI document into a FastAPI module.

One operation becomes one route, one component schema becomes one model,
and a `$ref` in a parameter or response position reaches the route it was written for.
"""

import ast

import pytest
from hypothesis import HealthCheck, given, settings
from tests.strategies.openapi import openapi_doc_st
from tests.support.asserts import ok
from tests.support.docs import openapi_doc
from tests.support.drive import FASTAPI
from tests.support.source import python_module
from tests.support.stages import fastapi_module
from tests.support.types import JsonLike

from schema_to import Ok, OpenApiParser, PythonReifier
from schema_to.ast.python import FunctionDef, PythonModule, VarDef
from schema_to.generate.fastapi.fastapi import FastApiTransformer

_PARSER = OpenApiParser()
_HTTP_METHODS = frozenset(["get", "post", "put", "delete", "patch", "options", "head", "trace"])


def _transpile(data: JsonLike) -> str:
    """Run the full pipeline and return the emitted Python source."""
    return FASTAPI.text(openapi_doc(data))


def _route_count(module: PythonModule) -> int:
    """Count the route functions, which are the ones carrying an `app.<method>` decorator.

    A module may hold undecorated functions that are not routes:
    A document with security schemes also gets a `require_scopes` stub.
    """
    return sum(
        1
        for d in module.declarations
        if isinstance(d, FunctionDef)
        and any(str(dec.name).startswith("app.") for dec in d.decorators)
    )


def _count_operations(doc: dict) -> int:
    return sum(
        1
        for path_item in doc.get("paths", {}).values()
        for key in path_item
        if key in _HTTP_METHODS
    )


# ---------------------------------------------------------------------------
# Property: what must hold for any document
# ---------------------------------------------------------------------------


@pytest.mark.slow
@given(doc=openapi_doc_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_any_openapi_document_generates_a_valid_module(doc: dict) -> None:
    """Every whole-document invariant, checked against one generation per example."""
    module = fastapi_module(doc)
    app_vars = [d for d in module.declarations if isinstance(d, VarDef) and d.name == "app"]
    assert len(app_vars) == 1, "expected exactly one `app` variable"
    assert _route_count(module) == _count_operations(doc), "expected one route per path x method"
    [artifact] = ok(PythonReifier().apply(module))
    source = artifact.content.decode()
    python_module(source)
    assert "from fastapi import" in source


# ---------------------------------------------------------------------------
# Curated petstore document (doubles as usage example)
# ---------------------------------------------------------------------------

_PETSTORE: dict = {
    "openapi": "3.1.0",
    "info": {"title": "Pet Store", "version": "1.0.0"},
    "components": {
        "schemas": {
            "Pet": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "tag": {"type": "string"},
                },
                "required": ["id", "name"],
            },
            "NewPet": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "tag": {"type": "string"}},
                "required": ["name"],
            },
        }
    },
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List all pets",
                "parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer"}}],
                "responses": {
                    "200": {
                        "description": "A list of pets",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/Pet"},
                                }
                            }
                        },
                    }
                },
            },
            "post": {
                "operationId": "createPet",
                "summary": "Create a new pet",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/NewPet"}}
                    },
                },
                "responses": {
                    "201": {
                        "description": "Created",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}
                        },
                    }
                },
            },
        },
        "/pets/{pet_id}": {
            "get": {
                "operationId": "getPet",
                "summary": "Get a pet by ID",
                "parameters": [
                    {
                        "name": "pet_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "A single pet",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}
                        },
                    }
                },
            }
        },
    },
}


def test_integration_petstore() -> None:
    """Full pipeline with a petstore-style document.

    Demonstrates the expected output structure:

    - Pydantic models for component schemas
    - FastAPI app instance
    - Async route functions with typed parameters and response models
    """
    src = _transpile(_PETSTORE)

    # Must be syntactically valid Python.
    ast.parse(src)

    # --- Boilerplate ---
    assert "from fastapi import" in src
    assert "FastAPI" in src
    assert "from pydantic import BaseModel" in src
    assert "Annotated" in src

    # --- App instance ---
    assert 'app = FastAPI(title="Pet Store", version="1.0.0")' in src

    # --- Pydantic models appear before the app instance ---
    assert "class Pet(BaseModel):" in src
    assert "class NewPet(BaseModel):" in src
    pet_pos = src.index("class Pet(BaseModel):")
    app_pos = src.index("app = FastAPI(")
    assert pet_pos < app_pos, "Models must precede the app instance"

    # Required fields have no Optional default.
    assert "id: int" in src
    assert "name: str" in src

    # --- Route functions ---
    assert "async def list_pets(" in src
    assert "async def create_pet(" in src
    assert "async def get_pet(" in src

    # Route decorators carry the correct path.
    assert '@app.get("/pets"' in src
    assert '@app.post("/pets"' in src
    assert '@app.get("/pets/{pet_id}"' in src

    # Response models encoded in decorators.
    assert "response_model=list[Pet]" in src
    assert "response_model=Pet" in src

    # POST /pets has a 201 status code.
    assert "status_code=201" in src

    # --- Parameter annotations ---
    # limit is an optional query param → Annotated[int | None, Query()] = None
    assert "Query()" in src
    assert "limit" in src

    # pet_id is a required path param → Annotated[int, Path()]
    assert "Path()" in src
    assert "pet_id" in src

    # body for POST → typed as the NewPet model
    assert "body: NewPet" in src


def test_roots_keeps_only_named_component_schemas() -> None:
    """`roots` narrows generated component-schema models; routes are unaffected."""
    transformer = FastApiTransformer(roots=frozenset({"Pet"}))
    r1 = _PARSER.apply(openapi_doc(_PETSTORE))
    assert isinstance(r1, Ok)
    result = transformer.apply(r1.value)
    assert isinstance(result, Ok)
    src = PythonReifier().apply(result.value)
    assert isinstance(src, Ok)
    content = src.value[0].content.decode()
    assert "class Pet(BaseModel):" in content
    assert "class NewPet(BaseModel):" not in content
    assert "async def list_pets(" in content


# ---------------------------------------------------------------------------
# Referenced components
# ---------------------------------------------------------------------------


_REF_DOC = {
    "openapi": "3.1.0",
    "info": {"title": "Refs", "version": "1.0.0"},
    "paths": {
        "/things/{thingId}": {
            "get": {
                "operationId": "getThing",
                "parameters": [{"$ref": "#/components/parameters/ThingId"}],
                "responses": {"200": {"$ref": "#/components/responses/Thing"}},
            }
        }
    },
    "components": {
        "parameters": {
            "ThingId": {
                "name": "thingId",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
            }
        },
        "responses": {
            "Thing": {
                "description": "one thing",
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Thing"}}},
            }
        },
        "schemas": {
            "Thing": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            }
        },
    },
}


def test_referenced_parameter_reaches_the_generated_route() -> None:
    """A `$ref`'d parameter used to be dropped, leaving the route without its input."""
    source = _transpile(_REF_DOC)
    ast.parse(source)
    assert "thing_id" in source


def test_referenced_response_reaches_the_generated_route() -> None:
    source = _transpile(_REF_DOC)
    assert "Thing" in source


# ---------------------------------------------------------------------------
# Multi-document references
# ---------------------------------------------------------------------------

_MULTI_MAIN = {
    "openapi": "3.1.0",
    "info": {"title": "Multi", "version": "1.0.0"},
    "paths": {
        "/things/{thingId}": {
            "get": {
                "operationId": "getThing",
                "parameters": [{"$ref": "shared.yaml#/components/parameters/ThingId"}],
                "responses": {"200": {"$ref": "shared.yaml#/components/responses/Thing"}},
            }
        }
    },
}

_MULTI_SHARED = {
    "openapi": "3.1.0",
    "info": {"title": "Shared", "version": "1.0.0"},
    "components": {
        "parameters": {
            "ThingId": {
                "name": "thingId",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
            }
        },
        "responses": {
            "Thing": {
                "description": "one thing",
                "content": {"application/json": {"schema": {"type": "object"}}},
            }
        },
    },
}


def test_a_reference_into_a_sibling_document_resolves_through_the_pipeline() -> None:
    """A `$ref` into another document in the same batch must resolve, not error.

    The FastAPI pipeline resolves each document independently unless every document is registered before any of them is resolved;
    this exercises the two-pass registration that makes cross-document `$ref`s work.
    """
    main = openapi_doc(_MULTI_MAIN, "main.yaml")
    shared = openapi_doc(_MULTI_SHARED, "shared.yaml")
    result = FASTAPI.run(main, shared)
    assert isinstance(result, Ok), (
        f"Transpile failed: {[getattr(e, 'message', str(e)) for e in result.errors]}"
    )
    sources = [artifact.content.decode() for artifact in result.value]
    main_source = next(src for src in sources if "async def get_thing(" in src)
    ast.parse(main_source)
    assert "thing_id" in main_source
