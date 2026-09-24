"""Reading things back out of generated source, for tests that assert on shape rather than text."""

import ast
import re


def python_module(source: str) -> ast.Module:
    """Return `source` parsed as Python, failing with the source itself if it does not parse."""
    try:
        return ast.parse(source)
    except SyntaxError as e:
        msg = f"Generated source is not valid Python ({e}):\n{source}"
        raise AssertionError(msg) from e


def read_write_slices(source: str, name: str) -> tuple[str, str]:
    """Return the bodies of the `<name>Read` and `<name>Write` classes declared in `source`.

    A body runs to the next top-level `class`, so a field assertion can name the variant it means.
    """
    return _class_body(source, f"{name}Read"), _class_body(source, f"{name}Write")


def _class_body(source: str, name: str) -> str:
    match = re.search(
        rf"^class {re.escape(name)}\b.*?(?=^class |\Z)", source, re.DOTALL | re.MULTILINE
    )
    assert match is not None, f"No class {name} in:\n{source}"
    return match.group()
