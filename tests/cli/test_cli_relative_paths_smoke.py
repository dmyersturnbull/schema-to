"""CLI smoke tests run from several working directories, naming inputs and outputs by relative path."""

import re
import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from tests.support.trees import write_all

_TREE = {
    "schemas/base/time.yaml": "timestamp:\n  type: string\n",
    "schemas/main/catalog.yaml": (
        "thing:\n"
        "  type: object\n"
        "  properties:\n"
        "    id:\n"
        "      type: string\n"
        "    t:\n"
        "      $ref: '../base/time.yaml#/timestamp'\n"
        "    o:\n"
        "      $ref: '#/other'\n"
        "other:\n"
        "  type: string\n"
    ),
}


def _run(*args: str, cwd: Path) -> CompletedProcess[str]:
    # ruff:ignore[subprocess-without-shell-equals-true]  # Test helper: executable and module are both constants.
    return subprocess.run(
        [sys.executable, "-m", "schema_to", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


@pytest.mark.parametrize(
    ("cwd", "input_dir", "output_dir"),
    [
        (".", "schemas", "out"),
        ("schemas/main", "..", "../../out"),
        ("elsewhere/deeper", "../../schemas", "../../out"),
    ],
)
def test_a_schema_map_tree_transpiles_from_any_cwd(
    tmp_path: Path, cwd: str, input_dir: str, output_dir: str
) -> None:
    write_all(tmp_path, _TREE)
    (tmp_path / cwd).mkdir(parents=True, exist_ok=True)
    result = _run(
        "--schema-map", "-r", input_dir, "-t", "pydantic", "-o", output_dir, cwd=tmp_path / cwd
    )
    assert result.returncode == 0, result.stderr
    assert "Wrote 3 artifact(s) from 2 document(s)." in result.stdout
    assert {p.name for p in (tmp_path / "out").iterdir()} == {
        "thing.py",
        "timestamp.py",
        "other.py",
    }


def test_errors_name_the_file_relative_to_the_cwd_with_line_and_column(tmp_path: Path) -> None:
    write_all(
        tmp_path,
        {**_TREE, "schemas/main/catalog.yaml": "thing:\n  $ref: '../base/time.yaml#/nope'\n"},
    )
    (tmp_path / "elsewhere").mkdir()
    result = _run(
        "--schema-map", "-r", "../schemas", "-t", "pydantic", "-o", "out", cwd=tmp_path / "elsewhere"
    )
    assert result.returncode == 1
    # Not a terminal, so no colors.
    assert "\x1b[" not in result.stderr
    assert re.search(
        r"^\.\./schemas/main/catalog\.yaml:1:1: error: Cannot resolve \$ref '\.\./base/time\.yaml#/nope'",
        result.stderr,
        flags=re.MULTILINE,
    ), result.stderr
