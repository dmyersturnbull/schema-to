"""Test suite for `schema_to`.

Test modules are named `test_{subject}_{layer}.py`,
where _subject_ is the behavior and/or component being tested,
and _layer_ is the type of test.

Layers:

    unit: Tests a single module in isolation.
        Each independent class is tested in isolation.
        No routing, no filesystem, no subprocess.
    integration: Tests a single feature/aspect, using multiple modules.
        typically parse → resolve → generate → reify.
    smoke: Tests that something runs without breaking.
        A key example is the CLI.
    e2e: Tests that a full transpilation pipeline works.
        These check raw bytes in finished artifact.

[tests.conftest][] reads the layer off the filename and applies the matching marker,
so `pytest -m unit` works without hand-marking,
and a test module whose name carries no layer fails collection.

Tests that take a noticeably long time carry the `slow` marker,
including Hypothesis tests.

Two packages hold shared code and are not collected:

- [tests.support][] — raw-document builders, target drivers, assertions, and temporary-tree helpers.
- [tests.strategies][] — Hypothesis strategies for JSON Schema and OpenAPI documents.

Prefer a Hypothesis-driven test over one with hand-written input
wherever both would cover the same behavior at the same layer.
"""
