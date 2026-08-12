"""Tests for the Python reifier, focused on the `FunctionDef.body` feature.

A `FunctionDef` with no `body` emits an `...` stub (existing behavior);
a `FunctionDef` with `body` lines emits those lines, indented, after the optional docstring.
"""

import ast

from schema_to.ast.python import FunctionDef, PythonDocString, PythonModule
from schema_to.reify.python import PythonReifier
from schema_to.result import Ok


def _emit(fn: FunctionDef) -> str:
    module = PythonModule(declarations=[fn])
    result = PythonReifier(artifact_id="m.py").apply(module)
    assert isinstance(result, Ok)
    return result.value[0].content.decode("utf-8")


def test_empty_body_emits_stub() -> None:
    src = _emit(FunctionDef(name="f"))
    assert "def f():" in src
    assert src.strip().endswith("...")
    ast.parse(src)


def test_body_lines_are_indented_and_emitted() -> None:
    fn = FunctionDef(name="f", is_async=True, body=["x = 1", "return x"])
    src = _emit(fn)
    assert "async def f():" in src
    assert "    x = 1" in src
    assert "    return x" in src
    assert "..." not in src
    ast.parse(src)


def test_body_follows_docstring() -> None:
    fn = FunctionDef(name="f", doc=PythonDocString(summary="Do it."), body=["return 1"])
    src = _emit(fn)
    lines = src.splitlines()
    doc_idx = next(i for i, ln in enumerate(lines) if '"""Do it."""' in ln)
    body_idx = next(i for i, ln in enumerate(lines) if "return 1" in ln)
    assert doc_idx < body_idx
    ast.parse(src)


def test_blank_body_line_emits_no_trailing_whitespace() -> None:
    fn = FunctionDef(name="f", body=["x = 1", "", "return x"])
    src = _emit(fn)
    assert "\n\n" in src  # the blank line is preserved with no indentation
    assert " \n" not in src  # no trailing-whitespace line
    ast.parse(src)
