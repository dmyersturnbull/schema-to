"""End-to-end test of the generic `x-fastapi-body` mechanism.

Transpiles the shipped PostgreSQL example
(`examples/postgres/things.openapi.yaml`)
with the plain `fastapi` target.
Asserts that the generated module fills its route bodies from the inline Jinja templates,
wires up the declared imports and the injected connection parameter, and parses as valid Python.
"""


import ast
from pathlib import Path

import pytest

from schema_to import MediaTypes, Ok, OpenApiRawDoc
from schema_to.transpile.factory import TranspilerRouter

_EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "examples" / "postgres"
_EXAMPLE = _EXAMPLE_DIR / "things.openapi.yaml"


def _named_templates() -> dict[str, str]:
    return {
        path.name.removesuffix(".py.jinja"): path.read_text(encoding="utf-8")
        for path in (_EXAMPLE_DIR / "templates").glob("*.py.jinja")
    }


def _generate(target: str) -> str:
    doc = OpenApiRawDoc(
        doc_id="t://api",
        content=_EXAMPLE.read_bytes(),
        media_type=MediaTypes.yaml,
        display_name="api",
    )
    [transpiler] = TranspilerRouter().route(
        target, output_media_type=MediaTypes.json, templates=_named_templates()
    )
    result = transpiler.transpile(doc)
    assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
    assert len(result.value) == 1
    return result.value[0].content.decode("utf-8")


@pytest.fixture(scope="module")
def main() -> str:
    return _generate("fastapi")


def test_generated_source_parses(main: str) -> None:
    try:
        ast.parse(main)
    except SyntaxError as exc:  # pragma: no cover - failure path
        pytest.fail(f"main.py is not valid Python: {exc}")


def test_list_body_is_filled(main: str) -> None:
    assert "build_list_query(" in main
    assert "table='things'" in main
    assert "json_columns=('meta',)" in main
    assert "await cur.execute(query, params)" in main
    assert "..." not in main  # no stub bodies remain


def test_connection_is_injected(main: str) -> None:
    assert "conn: AsyncConnection = Depends(get_db)" in main
    assert "from query_dsl import" in main
    assert "build_list_query" in main
    assert "from _db import get_db" in main


def test_item_route_uses_path_param(main: str) -> None:
    assert "async def get_thing(id: Annotated[int, Path()]" in main
    assert "pk_value=id" in main


def test_delete_uses_404_path(main: str) -> None:
    assert "build_delete_query(" in main
    assert "raise HTTPException(status_code=404)" in main


def test_no_x_extensions_leak_into_output(main: str) -> None:
    assert "x-fastapi-body" not in main
