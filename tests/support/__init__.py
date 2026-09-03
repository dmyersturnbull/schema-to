"""Shared helpers for the test suite.

Nothing here is collected as a test.
Each module holds one kind of helper:

- `types` — the JSON-shaped type that test data is written as.
- `docs` — builders for the `RawDoc`s a pipeline test starts from.
- `asserts` — unwrapping a `Result` and reporting usefully when it is not the expected variant.
- `stages` — running individual pipeline stages, for integration tests.
- `drive` — running a whole routed target, for end-to-end tests.
- `trees` — writing temporary document trees on disk.
"""
