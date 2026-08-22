"""Tests for parser warnings on unrecognized keys.

Covers:

- A misspelled keyword (`descripton`) warns and is otherwise ignored.
- An `x-*` extension key does not warn.
- Warnings surface on `Err` results too, not just `Ok`.
"""

import json
from collections.abc import Mapping

from schema_to.cst.json_schema import JsonSchemaDocument
from schema_to.cst.openapi import OpenApiDocument
from schema_to.io.media_type import MediaTypes
from schema_to.io.source import JsonSchemaRawDoc, OpenApiRawDoc
from schema_to.parse.json_schema import JsonSchemaParser
from schema_to.parse.openapi import OpenApiParser
from schema_to.result import Err, Ok, Result


def _json_schema_doc(
    data: Mapping[str, object], doc_id: str = "test://schema"
) -> Result[JsonSchemaDocument]:
    raw = JsonSchemaRawDoc(
        doc_id=doc_id, content=json.dumps(data).encode(), media_type=MediaTypes.json
    )
    return JsonSchemaParser().apply(raw)


def _openapi_doc(data: Mapping[str, object], doc_id: str = "test://doc") -> Result[OpenApiDocument]:
    raw = OpenApiRawDoc(
        doc_id=doc_id, content=json.dumps(data).encode(), media_type=MediaTypes.json
    )
    return OpenApiParser().apply(raw)


def test_json_schema_warns_on_unrecognized_keyword() -> None:
    result = _json_schema_doc({"type": "string", "descripton": "a typo"})
    assert isinstance(result, Ok)
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.code == "unrecognized-key"
    assert "descripton" in warning.message
    assert warning.location is not None
    assert warning.location.json_pointer == "/descripton"


def test_json_schema_no_warning_for_known_keywords() -> None:
    result = _json_schema_doc({"type": "string", "minLength": 1})
    assert isinstance(result, Ok)
    assert result.warnings == ()


def test_openapi_warns_on_unrecognized_key_in_nested_node() -> None:
    doc = {"openapi": "3.1.0", "info": {"title": "T", "version": "1", "descripton": "a typo"}}
    result = _openapi_doc(doc)
    assert isinstance(result, Ok)
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.code == "unrecognized-key"
    assert warning.location is not None
    assert warning.location.json_pointer == "/info/descripton"


def test_openapi_extension_keys_do_not_warn() -> None:
    doc = {"openapi": "3.1.0", "info": {"title": "T", "version": "1", "x-custom": "fine"}}
    result = _openapi_doc(doc)
    assert isinstance(result, Ok)
    assert result.warnings == ()


def test_warnings_surface_on_err_too() -> None:
    doc = {
        "openapi": "3.1.0",
        "info": {"version": "1", "descripton": "a typo"},  # missing required `title`
    }
    result = _openapi_doc(doc)
    assert isinstance(result, Err)
    assert any(w.code == "unrecognized-key" for w in result.warnings)
