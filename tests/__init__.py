"""Test suite for `schema_to`.

Tests are organized by **area** and by **layer**.
Packages mirror `src/schema_to/`, so the tests for a module sit next to the tests for its neighbours.
Every test module names its layer as the last part of its filename: `test_<subject>_<layer>.py`.

Layers:
    unit: One module's own API, called directly.
        No routing, no filesystem, no subprocess.
    integration: One feature across a few stages composed by hand,
        typically parse → resolve → generate → reify.
    smoke: The `schema-to` CLI, run as a subprocess.
        Deliberately few and shallow.
    e2e: A whole transpilation, raw bytes to finished artifact,
        through a `Transpiler` built by `TranspilerRouter`.

A module belongs to exactly one layer and never mixes two.
`tests.conftest` reads the layer off the filename and applies the matching marker,
so `pytest -m unit` works without hand-marking,
and a test module whose name carries no layer fails collection.

Tests that take a noticeably long time carry the `slow` marker,
including Hypothesis tests.

Two packages hold shared code and are not collected:

- `tests.support` — raw-document builders, target drivers, assertions, and temporary-tree helpers.
- `tests.strategies` — Hypothesis strategies for JSON Schema and OpenAPI documents.

Prefer a Hypothesis-driven test over one with hand-written input
wherever both would cover the same behavior at the same layer.
"""
