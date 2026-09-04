"""`SpecVersion` comparison, and the keys each spec version admits.

A key introduced in 3.2 is rejected in a 3.1 document and accepted in a 3.2 one;
serializing into an older version drops it again.
"""

from dataclasses import replace

import pytest
from tests.support.stages import minimal_openapi, openapi_result

from schema_to.parse._plan import SpecVersion
from schema_to.result import Err, Ok
from schema_to.serialize.openapi import OpenApiSerializer

# ---------------------------------------------------------------------------
# Version gating
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "parts"), [("3.1.0", (3, 1, 0)), ("3.2", (3, 2)), ("3.2.0-rc1", (3, 2, 0))]
)
def test_spec_version_parsing(text: str, parts: tuple[int, ...]) -> None:
    version = SpecVersion.parse(text)
    assert version is not None
    assert version.parts == parts


def _version(text: str) -> SpecVersion:
    parsed = SpecVersion.parse(text)
    assert parsed is not None
    return parsed


def test_spec_version_ignores_trailing_zeroes_when_comparing() -> None:
    v31, v32 = _version("3.1.0"), _version("3.2")
    assert v32.at_least(v31)
    assert not v31.at_least(v32)
    assert v32.at_least(_version("3.2.0"))


def test_a_three_two_key_is_rejected_in_a_three_one_document() -> None:
    result = openapi_result(minimal_openapi(**{"$self": "https://example.com/api"}))
    assert isinstance(result, Err)
    assert any(
        "$self was introduced in OpenAPI 3.2" in e.message and "declares 3.1.0" in e.message
        for e in result.errors
    ), [e.message for e in result.errors]


def test_the_same_key_is_accepted_in_a_three_two_document() -> None:
    document = {
        "openapi": "3.2.0",
        "info": {"title": "T", "version": "1"},
        "$self": "https://example.com/api",
        "servers": [{"url": "/", "name": "default"}],
    }
    result = openapi_result(document)
    assert isinstance(result, Ok), [e.message for e in getattr(result, "errors", ())]
    assert result.value.self_ == "https://example.com/api"
    assert result.value.servers[0].name == "default"
    assert OpenApiSerializer().serialize(result.value) == document


def test_gating_reaches_nested_nodes() -> None:
    result = openapi_result(
        minimal_openapi(
            paths={
                "/x": {"get": {"responses": {"200": {"description": "ok", "summary": "too new"}}}}
            }
        )
    )
    assert isinstance(result, Err)
    assert any("summary was introduced in OpenAPI 3.2" in e.message for e in result.errors)


def test_three_two_path_item_operations_parse() -> None:
    result = openapi_result(
        {
            "openapi": "3.2.0",
            "info": {"title": "T", "version": "1"},
            "paths": {
                "/x": {
                    "query": {"operationId": "queryX"},
                    "additionalOperations": {"PURGE": {"operationId": "purgeX"}},
                }
            },
        }
    )
    assert isinstance(result, Ok), [e.message for e in getattr(result, "errors", ())]
    path_item = result.value.paths["/x"]
    assert path_item.query is not None
    assert path_item.query.operation_id == "queryX"
    assert path_item.additional_operations["PURGE"].operation_id == "purgeX"


def test_serializing_into_an_older_version_drops_the_gated_key() -> None:
    """A 3.2 field on a CST relabelled 3.1 emits nothing, so the output re-parses."""
    parsed = openapi_result(
        {
            "openapi": "3.2.0",
            "info": {"title": "T", "version": "1"},
            "$self": "https://example.com/api",
        }
    )
    assert isinstance(parsed, Ok), parsed
    relabelled = replace(parsed.value, openapi="3.1.0")
    emitted = OpenApiSerializer().serialize(relabelled)
    assert "$self" not in emitted


def test_an_unreadable_version_gates_nothing() -> None:
    """A document whose version cannot be read has worse problems to report."""
    result = openapi_result({"info": {"title": "T", "version": "1"}, "$self": "x"})
    assert isinstance(result, Err)
    messages = [e.message for e in result.errors]
    assert any("openapi is required" in m for m in messages)
    assert not any("introduced in OpenAPI" in m for m in messages)
