"""Collection-time wiring shared by the whole suite.

Applies the layer marker named by each module's filename,
and rejects a test module whose name does not carry one.
See `tests` for what the layers mean.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path

import pytest


class TestModuleLayer(StrEnum):
    UNIT = auto()
    INTEGRATION = auto()
    SMOKE = auto()
    E2E = auto()


@dataclass(frozen=True, slots=True)
class TestModuleMetadata:
    subject: str
    layer: TestModuleLayer

    def __str__(self) -> str:
        return f"{self.layer}::{self.subject}"


_TEST_MODULE_RE = re.compile(
    rf"^test_(?P<subject>(?:[^_.]++_?)*)_(?P<layer>{'|'.join(f'(?:{m.value})' for m in TestModuleLayer)})\.py$"
)


def metadata_of(path: Path) -> TestModuleMetadata | None:
    if m := _TEST_MODULE_RE.fullmatch(path.name):
        return TestModuleMetadata(m.group("subject"), TestModuleLayer(m.group("layer")))
    return None


def pytest_collection_modifyitems(items: Sequence[pytest.Item]) -> None:
    """Mark every collected item with its module's layer, failing on a module that names none."""
    metadata = {item: metadata_of(item.path) for item in items}
    if invalid := sorted({i.path.name for i, layer in metadata.items() if layer is None}):
        msg = f"Test module(s) do not match {_TEST_MODULE_RE.pattern}: {', '.join(invalid)}"
        raise pytest.UsageError(msg)
    for item, meta in metadata.items():
        if meta is not None:
            item.add_marker(meta.layer.value)


if __name__ == "__main__":
    # This is a meta-test.
    valid: dict[str, TestModuleMetadata] = {}
    invalid: set[str] = set()
    for f in Path(__file__).parent.rglob("**/*.py"):
        if m := metadata_of(f):
            valid[f.name] = m
        else:
            invalid.add(f.name)
    c1 = max(len(s) for s in valid.keys() | invalid)
    c2 = max(len(m.layer) for m in valid.values())
    c3 = max(len(m.subject) for m in valid.values())
    print(f"| {'filename'.ljust(c1)} | {'layer'.ljust(c2)} | {'subject'.ljust(c3)} |")  # ruff: ignore[print]
    print(f"| {'-' * c1} | {'-' * c2} | {'-' * c3} |")  # ruff: ignore[print]
    for name, m in valid.items():
        print(f"| {name.ljust(c1)} | {m.layer.ljust(c2)} | {m.subject.ljust(c3)} |")  # ruff: ignore[print]
    for name in invalid:
        print(f"| {name.ljust(c1)} | {' ' * c2} | {' ' * c3} |")  # ruff: ignore[print]
