"""CLI smoke tests: invoke the real `schema-to` binary and verify output files."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PG_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "postgres"


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    # ruff:ignore[subprocess-without-shell-equals-true]  # Test helper: executable and module are both constants.
    return subprocess.run(
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


def test_cli_fastapi_named_templates(tmp_path: Path) -> None:
    """`--template name=path` fills route bodies from the named templates."""
    template_dir = _PG_EXAMPLE / "templates"
    template_args = [
        arg
        for path in sorted(template_dir.glob("*.py.jinja"))
        for arg in ("--template", f"{path.name.removesuffix('.py.jinja')}={path}")
    ]
    result = _run(
        str(_PG_EXAMPLE / "things.openapi.yaml"),
        "--to",
        "fastapi",
        "--output",
        str(tmp_path),
        *template_args,
    )
    assert result.returncode == 0, f"CLI failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

    main = (tmp_path / "main.py").read_text()
    assert "build_list_query(" in main
    assert "x-fastapi" not in main


def test_cli_roots_restricts_generated_defs(tmp_path: Path) -> None:
    """`--roots` keeps only the named `$defs` entry; the root model is unaffected."""
    schema = {
        "type": "object",
        "title": "Root",
        "$defs": {
            "Kept": {"type": "object", "properties": {"a": {"type": "string"}}},
            "Dropped": {"type": "object", "properties": {"b": {"type": "string"}}},
        },
    }
    input_file = tmp_path / "root.schema.json"
    input_file.write_text(json.dumps(schema))

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = _run(
        str(input_file), "--to", "pydantic", "--output", str(output_dir), "--roots", "Kept"
    )
    assert result.returncode == 0, f"CLI failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

    # The module is named after the document it was generated from.
    content = (output_dir / "root.py").read_text()
    assert "class Kept(BaseModel):" in content
    assert "class Dropped(BaseModel):" not in content
    assert "class Root(BaseModel):" in content


def test_cli_unknown_template_spec_exits_nonzero(tmp_path: Path) -> None:
    """A malformed --template spec exits with a non-zero status."""
    schema = {"openapi": "3.1.0", "info": {"title": "x", "version": "1"}, "paths": {}}
    input_file = tmp_path / "api.json"
    input_file.write_text(json.dumps(schema))

    result = _run(str(input_file), "--to", "fastapi", "--template", "noequals")
    assert result.returncode != 0
    assert "NAME=PATH" in result.stderr


def test_cli_json_schema_extracts_openapi_components(tmp_path: Path) -> None:
    """`--to json-schema` writes each `components/schemas` entry as its own file."""
    openapi = {
        "openapi": "3.1.0",
        "info": {"title": "Test", "version": "1.0"},
        "components": {
            "schemas": {
                "User": {"type": "object", "properties": {"id": {"type": "string"}}},
                "Group": {"type": "object"},
            }
        },
    }
    input_file = tmp_path / "api.openapi.json"
    input_file.write_text(json.dumps(openapi))

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = _run(str(input_file), "--to", "json-schema", "--output", str(output_dir))
    assert result.returncode == 0, f"CLI failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

    written = {path.name for path in output_dir.iterdir()}
    assert written == {"User.schema.json", "Group.schema.json"}
    user = json.loads((output_dir / "User.schema.json").read_text())
    assert user["properties"]["id"]["type"] == "string"
