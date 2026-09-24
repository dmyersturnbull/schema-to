"""Writing temporary document trees on disk, for tests that walk a real directory."""

from collections.abc import Mapping
from pathlib import Path


def write(root: Path, relative_path: str, text: str) -> Path:
    """Write `text` to `relative_path` under `root`, creating parent directories."""
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def write_all(root: Path, files: Mapping[str, str]) -> Path:
    """Write every `relative path → text` entry under `root` and return `root`."""
    for relative_path, text in files.items():
        write(root, relative_path, text)
    return root
