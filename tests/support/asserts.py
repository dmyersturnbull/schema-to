"""Unwrapping a `Result`, and reporting usefully when it holds the other variant.

`ok` and `failure` replace the `assert isinstance(result, Ok)` line that would otherwise
open every test, and they put the accumulated messages into the failure output,
where an `isinstance` assertion would show only `False`.
"""

import ast
from collections.abc import Sequence

from schema_to.errors import TranspilationError
from schema_to.result import Err, Ok, Result


def message_of(error: TranspilationError) -> str:
    """Return `error`'s message, falling back to its `str` for a bare exception."""
    return getattr(error, "message", str(error))


def ok[T](result: Result[T]) -> T:
    """Return the value of an `Ok`, failing with the accumulated messages if it is an `Err`."""
    assert isinstance(result, Ok), f"Expected Ok, got errors: {failure(result)}"
    return result.value


def failure[T](result: Result[T]) -> Sequence[str]:
    """Return the messages of an `Err`, failing if the result is an `Ok`."""
    assert isinstance(result, Err), f"Expected Err, got Ok: {result.value!r}"
    return [message_of(e) for e in result.errors]


def warning_codes[T](result: Result[T]) -> Sequence[str]:
    """Return the codes of every warning carried by `result`, in the order they were raised."""
    return [w.code for w in result.warnings if w.code]


def python_module(source: str) -> ast.Module:
    """Return `source` parsed as Python, failing with the source itself if it does not parse."""
    try:
        return ast.parse(source)
    except SyntaxError as e:
        pytest_msg = f"Generated source is not valid Python ({e}):\n{source}"
        raise AssertionError(pytest_msg) from e


def top_level_names(source: str) -> Sequence[str]:
    """Return the names bound at the top level of `source`: classes, functions, and assignments."""
    names: list[str] = []
    for node in python_module(source).body:
        match node:
            case ast.ClassDef() | ast.FunctionDef() | ast.AsyncFunctionDef():
                names.append(node.name)
            case ast.Assign(targets=[ast.Name(id=name)]) | ast.AnnAssign(target=ast.Name(id=name)):
                names.append(name)
            case _:
                pass
    return names
