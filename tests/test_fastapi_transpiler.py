"""Tests for the OpenAPI 3.1 → FastAPI generator pipeline.

Covers:
- Unit: pure helper functions (_esc, _ref_to_class_name, _annotation_str, _nullable, _op_fn_name).
- Property: any parsed OpenAPI document always produces syntactically valid Python.
- Property: generated module always contains an ``app`` variable and one route per operation.
- Integration: curated petstore-style document — models, routes, parameters, imports.
"""

import ast

import orjson
import pytest
from hypothesis import HealthCheck, given, settings
from tests.strategies import openapi_doc_st

from schema_to import MediaTypes, Ok, OpenApiParser, OpenApiRawDoc
from schema_to.ast.python import FunctionDef, PythonModule, PythonTypeAnnotation, VarDef
from schema_to.cst.openapi import HttpMethod
from schema_to.generate.fastapi import (
    FastApiTransformer,
    _annotation_str,
    _esc,
    _nullable,
    _op_fn_name,
    _ref_to_class_name,
)
from schema_to.transpile.fastapi import OpenApiToFastApiTranspiler

_PARSER = OpenApiParser()
_HTTP_METHODS = frozenset(["get", "post", "put", "delete", "patch", "options", "head", "trace"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _doc(data: object, source_id: str = "test://api") -> OpenApiRawDoc:
    return OpenApiRawDoc(
        doc_id=source_id,
        content=orjson.dumps(data),
        media_type=MediaTypes.json,
        display_name="test",
    )


def _generate(data: object) -> PythonModule:
    """Parse → generate; assert Ok and return the PythonModule."""
    r1 = _PARSER.apply(_doc(data))
    assert isinstance(r1, Ok)
    transformer = FastApiTransformer()
    result = transformer.apply(r1.value)
    assert isinstance(result, Ok)
    return result.value


def _transpile(data: object) -> str:
    """Run the full pipeline and return the emitted Python source."""
    transpiler = OpenApiToFastApiTranspiler()
    result = transpiler.transpile(_doc(data))
    assert isinstance(result, Ok), (
        f"Transpile failed: {[getattr(e, 'message', str(e)) for e in result.errors]}"
    )
    return result.value[0].content.decode("utf-8")


def _count_operations(doc: dict) -> int:
    return sum(
        1
        for path_item in doc.get("paths", {}).values()
        for key in path_item
        if key in _HTTP_METHODS
    )


# ---------------------------------------------------------------------------
# Unit tests: string escaping
# ---------------------------------------------------------------------------


def test_esc_plain_string() -> None:
    assert _esc("hello world") == "hello world"


def test_esc_double_quotes() -> None:
    assert _esc('say "hi"') == 'say \\"hi\\"'


def test_esc_backslash() -> None:
    assert _esc("C:\\path") == "C:\\\\path"


def test_esc_both_double_quote_and_backslash() -> None:
    assert _esc('\\"') == '\\\\\\"'


# ---------------------------------------------------------------------------
# Unit tests: $ref → class name
# ---------------------------------------------------------------------------


def test_ref_to_class_name_components_schemas() -> None:
    assert _ref_to_class_name("#/components/schemas/User") == "User"


def test_ref_to_class_name_defs_path() -> None:
    assert _ref_to_class_name("#/$defs/Item") == "Item"


def test_ref_to_class_name_bare_name() -> None:
    assert _ref_to_class_name("MyModel") == "MyModel"


def test_ref_to_class_name_with_hyphen_produces_identifier() -> None:
    result = _ref_to_class_name("#/components/schemas/pet-tag")
    assert result.isidentifier()
    assert result[0].isupper()


# ---------------------------------------------------------------------------
# Unit tests: annotation string rendering
# ---------------------------------------------------------------------------


def test_annotation_str_builtin() -> None:
    assert _annotation_str(PythonTypeAnnotation("str")) == "str"


def test_annotation_str_generic_list() -> None:
    ann = PythonTypeAnnotation("list", args=[PythonTypeAnnotation("str")])
    assert _annotation_str(ann) == "list[str]"


def test_annotation_str_nullable() -> None:
    assert _annotation_str(PythonTypeAnnotation("int", nullable=True)) == "int | None"


def test_annotation_str_nested_generic() -> None:
    inner = PythonTypeAnnotation("str")
    outer = PythonTypeAnnotation("list", args=[inner], nullable=True)
    assert _annotation_str(outer) == "list[str] | None"


def test_annotation_str_dict_two_args() -> None:
    ann = PythonTypeAnnotation(
        "dict", args=[PythonTypeAnnotation("str"), PythonTypeAnnotation("Any", module="typing")]
    )
    assert _annotation_str(ann) == "dict[str, Any]"


# ---------------------------------------------------------------------------
# Unit tests: nullable wrapping
# ---------------------------------------------------------------------------


def test_nullable_sets_flag() -> None:
    result = _nullable(PythonTypeAnnotation("str"))
    assert result.nullable is True
    assert result.name == "str"


def test_nullable_preserves_args() -> None:
    inner = PythonTypeAnnotation("str")
    ann = PythonTypeAnnotation("list", args=[inner])
    result = _nullable(ann)
    assert result.nullable is True
    assert list(result.args) == [inner]


def test_nullable_preserves_module() -> None:
    ann = PythonTypeAnnotation("Any", module="typing")
    result = _nullable(ann)
    assert result.module == "typing"
    assert result.nullable is True


def test_nullable_already_nullable_stays_nullable() -> None:
    ann = PythonTypeAnnotation("str", nullable=True)
    assert _nullable(ann).nullable is True


# ---------------------------------------------------------------------------
# Unit tests: operation function naming
# ---------------------------------------------------------------------------


def test_op_fn_name_uses_operation_id() -> None:
    assert _op_fn_name(HttpMethod.GET, "/pets", "listPets") == "list_pets"


def test_op_fn_name_derives_from_method_and_path() -> None:
    assert _op_fn_name(HttpMethod.POST, "/users", None) == "post_users"


def test_op_fn_name_strips_path_param_braces() -> None:
    assert _op_fn_name(HttpMethod.GET, "/pets/{pet_id}", None) == "get_pets_pet_id"


def test_op_fn_name_is_valid_identifier() -> None:
    for path in ["/a/b/c", "/{x}/{y}", "/foo-bar"]:
        for method in (HttpMethod.GET, HttpMethod.DELETE):
            name = _op_fn_name(method, path, None)
            assert name.isidentifier(), f"{name!r} is not a valid identifier"


# ---------------------------------------------------------------------------
# Unit tests: nullable flag reflected in annotation string
# ---------------------------------------------------------------------------


def test_annotation_str_nullable_suffix_present_when_true() -> None:
    for name in ("str", "int", "float", "MyModel"):
        ann = PythonTypeAnnotation(name, nullable=True)
        assert _annotation_str(ann).endswith(" | None"), f"Expected suffix for {ann}"


def test_annotation_str_nullable_suffix_absent_when_false() -> None:
    for name in ("str", "int", "float", "MyModel"):
        ann = PythonTypeAnnotation(name, nullable=False)
        assert not _annotation_str(ann).endswith(" | None"), f"Unexpected suffix for {ann}"


# ---------------------------------------------------------------------------
# Property: any OpenAPI document generates valid Python
# ---------------------------------------------------------------------------


@given(doc=openapi_doc_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_any_openapi_doc_generates_valid_python(doc: dict) -> None:
    """Any parsed OpenAPI 3.1 document must produce syntactically valid Python."""
    src = _transpile(doc)
    try:
        ast.parse(src)
    except SyntaxError as exc:
        pytest.fail(f"Generated invalid Python:\n{src}\nError: {exc}")


@given(doc=openapi_doc_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_transformer_always_returns_ok(doc: dict) -> None:
    """FastApiTransformer.apply always succeeds (warnings are non-fatal)."""
    r1 = _PARSER.apply(_doc(doc))
    assert isinstance(r1, Ok)
    transformer = FastApiTransformer()
    result = transformer.apply(r1.value)
    assert isinstance(result, Ok)


@given(doc=openapi_doc_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_app_var_always_present(doc: dict) -> None:
    """The module always contains exactly one VarDef named 'app'."""
    module = _generate(doc)
    app_vars = [d for d in module.declarations if isinstance(d, VarDef) and d.name == "app"]
    assert len(app_vars) == 1


@given(doc=openapi_doc_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_route_count_matches_operations(doc: dict) -> None:
    """One FunctionDef is generated per path × method operation."""
    module = _generate(doc)
    fn_count = sum(1 for d in module.declarations if isinstance(d, FunctionDef))
    assert fn_count == _count_operations(doc)


@given(doc=openapi_doc_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_fastapi_import_always_present(doc: dict) -> None:
    """Generated source always imports from fastapi (at minimum FastAPI for app)."""
    src = _transpile(doc)
    assert "from fastapi import" in src


# ---------------------------------------------------------------------------
# Integration: curated petstore document (doubles as usage example)
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
    * Pydantic models for component schemas
    * FastAPI app instance
    * Async route functions with typed parameters and response models
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
