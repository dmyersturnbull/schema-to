"""Collection-time wiring shared by the whole suite.

Applies the layer marker named by each module's filename,
and rejects a test module whose name does not carry one.
See `tests` for what the layers mean.
"""

from collections.abc import Sequence
from pathlib import Path

import pytest

LAYERS = frozenset({"unit", "integration", "smoke", "e2e"})
"""Recognized layer names, one of which must end every test module's filename."""


def layer_of(path: Path) -> str | None:
    """Return the layer named by the last `_`-separated part of `path`'s stem, if it names one."""
    layer = path.stem.rsplit("_", maxsplit=1)[-1]
    return layer if layer in LAYERS else None


def pytest_collection_modifyitems(items: Sequence[pytest.Item]) -> None:
    """Mark every collected item with its module's layer, failing on a module that names none."""
    layers = {item: layer_of(item.path) for item in items}
    unlabeled = sorted({i.path.name for i, layer in layers.items() if layer is None})
    if unlabeled:
        listed = ", ".join(unlabeled)
        msg = (
            f"Test modules must end in a layer ({'/'.join(sorted(LAYERS))}): {listed}. "
            f"See the `tests` package docstring."
        )
        raise pytest.UsageError(msg)
    for item, layer in layers.items():
        if layer is not None:
            item.add_marker(layer)
