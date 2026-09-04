"""The Hypothesis strategies' image against what the CST accepts.

A strategy whose image is a proper subset of the supported documents silently stops
covering whatever it leaves out.  These compare the keys each strategy actually emits
against the keys the CST declares, so a keyword added to one and not the other fails
here rather than going unnoticed.

`Reference` is excluded from the comparison: `$ref` appears in the generated documents,
but a Reference Object's own `summary` and `description` overrides are a resolver
concern, covered by `tests/resolve/test_openapi_resolver_unit.py`.
3.2-only fields are excluded too, since the strategies pin the version at 3.1.
"""

import pytest
from hypothesis import HealthCheck, given, settings
from tests.strategies.coverage import declared_keys, keys_in
from tests.strategies.json_schema import json_schema_st
from tests.strategies.openapi import openapi_doc_st
from tests.support.types import JsonLike

import schema_to.cst.json_schema as json_schema_cst
import schema_to.cst.openapi as openapi_cst

_EXAMPLES = 800
_SETTINGS = settings(max_examples=_EXAMPLES, suppress_health_check=list(HealthCheck), deadline=None)


@pytest.mark.slow
def test_json_schema_strategy_emits_every_supported_keyword() -> None:
    """`json_schema_st`'s image is the whole keyword set `ObjectSchema` reads."""
    seen: set[str] = set()

    @given(schema=json_schema_st())
    @_SETTINGS
    def collect(schema: JsonLike) -> None:
        seen.update(keys_in(schema))

    collect()
    [(_, declared)] = [
        (name, keys)
        for name, keys in declared_keys(json_schema_cst).items()
        if name == "ObjectSchema"
    ]
    assert declared <= seen, f"never generated: {sorted(declared - seen)}"


@pytest.mark.slow
def test_openapi_strategy_emits_every_supported_field() -> None:
    """`openapi_doc_st`'s image is every 3.1 fixed field the OpenAPI CST reads."""
    seen: set[str] = set()

    @given(document=openapi_doc_st())
    @_SETTINGS
    def collect(document: JsonLike) -> None:
        seen.update(keys_in(document))

    collect()
    missing = {
        name: sorted(keys - seen)
        for name, keys in declared_keys(openapi_cst).items()
        if keys - seen
    }
    assert not missing, f"never generated: {missing}"
