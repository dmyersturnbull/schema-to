"""Collecting the JSON keys a strategy actually emits, and the keys the CST declares.

`tests/parse/test_strategy_coverage_unit.py` compares the two,
so a keyword added to the CST but not to a strategy fails rather than going unnoticed.
"""

import inspect
from collections.abc import Iterator, Mapping, Sequence, Set
from dataclasses import fields, is_dataclass
from types import ModuleType

from tests.support.types import JsonLike

from schema_to.cst.base import SYNTHETIC
from schema_to.parse._plan import json_key

_NEVER_WRITTEN = frozenset({"extensions", "source_ref", "source_id", "display_name"})
"""Fields the parser fills in itself rather than reading from the document."""

_NOT_DOCUMENT_NODES = frozenset({"Reference", "SourceRef"})
"""Nodes no document writes: provenance, and the overrides a resolver reads."""


def keys_in(value: JsonLike) -> Set[str]:
    """Return every object key appearing anywhere in `value`, with `x-*` keys folded together."""
    return frozenset(_walk(value))


def _walk(value: JsonLike) -> Iterator[str]:
    if isinstance(value, Mapping):
        for key, sub in value.items():
            yield "x-*" if key.startswith("x-") else key
            yield from _walk(sub)
    elif isinstance(value, Sequence) and not isinstance(value, str):
        for item in value:
            yield from _walk(item)


def declared_keys(module: ModuleType, *, version: str = "3.1") -> Mapping[str, Set[str]]:
    """Return the JSON keys each CST node in `module` reads, keyed by node name.

    Fields introduced after `version`,
    and fields the parser synthesizes rather than reading,
    are left out;
    no document carries them.
    """
    found: dict[str, Set[str]] = {}
    for name, cls in vars(module).items():
        if not (inspect.isclass(cls) and is_dataclass(cls)) or name in _NOT_DOCUMENT_NODES:
            continue
        keys = {
            str(f.metadata.get("key") or json_key(f.name))
            for f in fields(cls)
            if f.name not in _NEVER_WRITTEN
            and not all(f.metadata.get(k) == v for k, v in SYNTHETIC.items())
            and str(f.metadata.get("since", version)) <= version
        }
        if keys:
            found[name] = frozenset(keys)
    return found
