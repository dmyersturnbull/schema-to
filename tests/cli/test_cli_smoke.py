"""CLI smoke tests: invoke the real `schema-to` binary and verify output files."""

import json
import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from schema_to.transpile.std_router import SupportedTarget

_PG_EXAMPLE = Path(__file__).resolve().parent.parent.parent / "examples" / "postgres"


def _run(*args: str, cwd: Path | None = None) -> CompletedProcess[str]:
    # ruff:ignore[subprocess-without-shell-equals-true]  # Test helper: executable and module are both constants.
    return subprocess.run(
        [sys.executable, "-m", "schema_to", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


def _check_retcode(result: CompletedProcess[str], code: int = 0) -> None:
    assert result.returncode == code, (
        f"CLI exited with code {code}:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def _check_files(
    out_dir: Path, expected: str | tuple[str, ...] | set[str | tuple[str, ...]]
) -> set[Path]:
    """Checks that exactly the expected files were created, ignoring special pytest-generated files.

    Returns:
        The actual paths
    """
    if not isinstance(expected, set):
        expected = {expected}
    actual = {p for p in out_dir.iterdir() if p.name not in {"out", "err"}}
    exp = {Path(out_dir, *p) if isinstance(p, tuple) else out_dir / p for p in expected}
    assert {str(p.relative_to(out_dir)) for p in actual} == {
        str(p.relative_to(out_dir)) for p in exp
    }
    for p in actual:
        assert p.is_file(follow_symlinks=False), (
            f"File {p} is not a regular file (stat: {p.lstat()})"
        )
    return actual


def test_cli_help() -> None:
    """The CLI exits 0 and prints usage information for --help."""
    result = _run("--help")
    _check_retcode(result)
    out, err = result.stdout, result.stderr
    assert not err, f"Should not have warning or error output with --help. STDERR: {err}"
    assert "--roots" in out
    assert "--yaml" in out
    assert "--json" in out
    for t in SupportedTarget:
        assert t.value in result.stdout


def test_cli_pass_thru_json_schema(tmp_path: Path) -> None:
    """Pass-thru on a JSON Schema file creates a normalised `.schema.json` output."""
    schema = {"type": "object", "title": "User", "properties": {"name": {"type": "string"}}}
    input_file = tmp_path / "user.schema.json"
    input_file.write_text(json.dumps(schema))

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = _run(str(input_file), "--output", str(output_dir))
    _check_retcode(result)
    _check_files(output_dir, "user.schema.json")
    content = json.loads((output_dir / "user.schema.json").read_text())
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
    _check_retcode(result)
    _check_files(output_dir, "item.schema.yaml")
    assert b"type:" in (output_dir / "item.schema.yaml").read_bytes()


def test_cli_unsupported_target_exits_nonzero(tmp_path: Path) -> None:
    """Requesting an unsupported target format exits with a non-zero status."""
    schema = {"type": "object"}
    input_file = tmp_path / "schema.json"
    input_file.write_text(json.dumps(schema))
    result = _run(str(input_file), "--to", "typescript")
    _check_retcode(result, 2)
    assert "Invalid value for '-t' / '--to':" in result.stderr


@pytest.mark.parametrize("flag", ["--help"])
def test_cli_no_input_shows_help(flag: str) -> None:
    """Invoking with --help always succeeds."""
    result = _run(flag)
    _check_retcode(result)


def test_cli_fastapi_named_templates(tmp_path: Path) -> None:
    """`--template name=path` fills route bodies from the named templates."""
    template_dir = _PG_EXAMPLE / "templates"
    found = list(template_dir.glob("*.py.jinja"))
    template_args = [
        arg
        for path in found
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
    _check_retcode(result)
    _check_files(tmp_path, "main.py")
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
    _check_retcode(result)

    # The module is named after the document it was generated from.
    _check_files(output_dir, "root.py")
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
    _check_retcode(result, 2)
    assert "Invalid value for '--template'" in result.stderr


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
    _check_retcode(result)

    _check_files(output_dir, {"User.schema.json", "Group.schema.json"})
    user = json.loads((output_dir / "User.schema.json").read_text())
    assert user["properties"]["id"]["type"] == "string"


_REL_BASE = {"timestamp": {"type": "string", "format": "date-time"}}
_REL_THING = {
    "Thing": {
        "type": "object",
        "properties": {
            "at": {"$ref": "../base/time.yaml#/timestamp"},
            "other": {"$ref": "#/Other"},
        },
    },
    "Other": {"type": "object", "properties": {"n": {"type": "integer"}}},
}


def _write_ref_tree(root: Path) -> None:
    (root / "in" / "base").mkdir(parents=True)
    (root / "in" / "sub").mkdir()
    (root / "out").mkdir()
    (root / "in" / "base" / "time.yaml").write_text(json.dumps(_REL_BASE))
    (root / "in" / "sub" / "thing.yaml").write_text(json.dumps(_REL_THING))


@pytest.mark.parametrize("directory", ["in", "./in", "../{name}/in"])
def test_cli_schema_map_recursive_relative_dir_resolves_refs(
    tmp_path: Path, directory: str
) -> None:
    """Cross-file `$ref`s resolve when the input directory is given as a relative path."""
    _write_ref_tree(tmp_path)
    result = _run(
        directory.format(name=tmp_path.name),
        "--schema-map",
        "-r",
        "--to",
        "pydantic",
        "--output",
        "out",
        cwd=tmp_path,
    )
    _check_retcode(result)
    assert "error" not in result.stderr
    assert {p.name for p in (tmp_path / "out").iterdir()} == {
        "timestamp.py",
        "thing.py",
        "other.py",
    }


def test_cli_relative_file_path(tmp_path: Path) -> None:
    """A single input file given as a relative path is read and transpiled."""
    (tmp_path / "user.schema.json").write_text(json.dumps({"type": "object", "title": "User"}))
    (tmp_path / "out").mkdir()
    result = _run("user.schema.json", "--output", "out", cwd=tmp_path)
    _check_retcode(result)
    assert (tmp_path / "out" / "user.schema.json").is_file()


def test_cli_relative_file_path_with_parent_segment(tmp_path: Path) -> None:
    (tmp_path / "schemas").mkdir()
    (tmp_path / "work").mkdir()
    (tmp_path / "schemas" / "user.schema.json").write_text(json.dumps({"type": "object"}))
    result = _run("../schemas/user.schema.json", "--output", "out", cwd=tmp_path / "work")
    _check_retcode(result)
    assert (tmp_path / "work" / "out" / "user.schema.json").is_file()


def test_cli_relative_dir_without_schema_map(tmp_path: Path) -> None:
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "a.schema.json").write_text(json.dumps({"type": "object"}))
    result = _run("in", "-r", "--output", "out", cwd=tmp_path)
    _check_retcode(result)
    assert (tmp_path / "out" / "a.schema.json").is_file()
