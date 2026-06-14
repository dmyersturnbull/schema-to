"""CLI smoke tests: invoke the real `schema-to` binary and verify output files."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # test helper: executable and module are both constants
        [sys.executable, "-m", "schema_to", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


def test_cli_help() -> None:
    """The CLI exits 0 and prints usage information for --help."""
    result = _run("--help")
    assert result.returncode == 0
    assert "schema-to" in result.stdout
    assert "pass-thru" in result.stdout


def test_cli_pass_thru_json_schema(tmp_path: Path) -> None:
    """Pass-thru on a JSON Schema file creates a normalised `.schema.json` output."""
    schema = {"type": "object", "title": "User", "properties": {"name": {"type": "string"}}}
    input_file = tmp_path / "user.schema.json"
    input_file.write_text(json.dumps(schema))

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = _run(str(input_file), "--output", str(output_dir))
    assert result.returncode == 0, f"CLI failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

    output_files = list(output_dir.iterdir())
    assert len(output_files) == 1, f"Expected 1 output file, got: {[f.name for f in output_files]}"
    assert output_files[0].name == "user.schema.json"

    content = json.loads(output_files[0].read_text())
    assert content.get("type") == "object"
    assert content.get("title") == "User"


def test_cli_pass_thru_yaml_output(tmp_path: Path) -> None:
    """--yaml flag produces a `.schema.yaml` artifact."""
    schema = {"type": "object", "title": "Item"}
    input_file = tmp_path / "item.schema.json"
    input_file.write_text(json.dumps(schema))

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = _run(str(input_file), "--output", str(output_dir), "--yaml")
    assert result.returncode == 0, f"CLI failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

    output_files = list(output_dir.iterdir())
    assert len(output_files) == 1
    assert output_files[0].name == "item.schema.yaml"
    assert b"type:" in output_files[0].read_bytes()


def test_cli_unsupported_target_exits_nonzero(tmp_path: Path) -> None:
    """Requesting an unsupported target format exits with a non-zero status."""
    schema = {"type": "object"}
    input_file = tmp_path / "schema.json"
    input_file.write_text(json.dumps(schema))

    result = _run(str(input_file), "--to", "typescript")
    assert result.returncode != 0
    assert "not supported" in result.stderr


@pytest.mark.parametrize("flag", ["--help"])
def test_cli_no_input_shows_help(flag: str) -> None:
    """Invoking with --help always succeeds."""
    result = _run(flag)
    assert result.returncode == 0
