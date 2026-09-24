"""The JSON-shaped type that test data is written as."""

from collections.abc import Mapping, Sequence

# TODO: Remove once we introduce a covariant Json in core.
type JsonLike = Mapping[str, JsonLike] | Sequence[JsonLike] | str | float | bool | None
"""Any value a test may hand to a document builder to be serialized as JSON.

Covariant in its members, unlike `schema_to.core.JsonValue`,
so a plain `dict[str, str]` literal is accepted without a cast.
Test data is only ever read, never mutated, so nothing is lost by that.
"""
