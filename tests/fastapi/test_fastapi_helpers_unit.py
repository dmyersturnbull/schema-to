"""Pure helpers of the FastAPI generator: escaping, `$ref` naming, and annotation rendering.

These take and return plain values, with no document and no pipeline behind them.
"""

import pytest

from schema_to.ast.python import PythonTypeAnnotation
from schema_to.cst.openapi import HttpMethod
from schema_to.generate.fastapi.fastapi import (
    _annotation_str,
    _esc,
    _op_fn_name,
    _ref_to_class_name,
    nullable_of,
)

# ---------------------------------------------------------------------------
# Unit tests: string escaping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hello world", "hello world"),
        ('say "hi"', 'say \\"hi\\"'),
        ("C:\\path", "C:\\\\path"),
        ('\\"', '\\\\\\"'),
    ],
)
def test_esc_escapes_quotes_and_backslashes(text: str, expected: str) -> None:
    assert _esc(text) == expected


# ---------------------------------------------------------------------------
# Unit tests: $ref → class name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ref", "expected"),
    [("#/components/schemas/User", "User"), ("#/$defs/Item", "Item"), ("MyModel", "MyModel")],
)
def test_ref_to_class_name_takes_the_last_segment(ref: str, expected: str) -> None:
    assert _ref_to_class_name(ref) == expected


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
    result = nullable_of(PythonTypeAnnotation("str"))
    assert result.nullable is True
    assert result.name == "str"


def test_nullable_preserves_args() -> None:
    inner = PythonTypeAnnotation("str")
    ann = PythonTypeAnnotation("list", args=[inner])
    result = nullable_of(ann)
    assert result.nullable is True
    assert list(result.args) == [inner]


def test_nullable_preserves_module() -> None:
    ann = PythonTypeAnnotation("Any", module="typing")
    result = nullable_of(ann)
    assert result.module == "typing"
    assert result.nullable is True


def test_nullable_already_nullable_stays_nullable() -> None:
    ann = PythonTypeAnnotation("str", nullable=True)
    assert nullable_of(ann).nullable is True


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


@pytest.mark.parametrize("name", ["str", "int", "float", "MyModel"])
def test_annotation_str_appends_none_only_when_nullable(name: str) -> None:
    """The `| None` suffix tracks the flag, whatever the annotation names."""
    assert _annotation_str(PythonTypeAnnotation(name, nullable=True)).endswith(" | None")
    assert not _annotation_str(PythonTypeAnnotation(name, nullable=False)).endswith(" | None")
