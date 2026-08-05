"""Parser/serializer round-trip tests.

Verifies that parse → serialize → re-parse → re-serialize is idempotent,
for both JSON Schema and OpenAPI documents.
These tests exercise the parsers and serializers directly without going through a `Transpiler`.
"""


import orjson
from hypothesis import HealthCheck, given, settings
from tests.strategies import json_schema_st, openapi_doc_st

from schema_to import (
    JsonSchemaParser,
    JsonSchemaRawDoc,
    JsonSchemaSerializer,
    MediaTypes,
    Ok,
    OpenApiParser,
    OpenApiRawDoc,
    OpenApiSerializer,
)

_JS_PARSER = JsonSchemaParser()
_JS_SERIALIZER = JsonSchemaSerializer()
_OA_PARSER = OpenApiParser()
_OA_SERIALIZER = OpenApiSerializer()


def _make_js_doc(data: object, source_id: str = "test://doc") -> JsonSchemaRawDoc:
    return JsonSchemaRawDoc(
        doc_id=source_id,
        content=orjson.dumps(data),
        media_type=MediaTypes.json,
        display_name="test",
    )


def _make_oa_doc(data: object, source_id: str = "test://doc") -> OpenApiRawDoc:
    return OpenApiRawDoc(
        doc_id=source_id,
        content=orjson.dumps(data),
        media_type=MediaTypes.json,
        display_name="test",
    )


def _stable_json(obj: object) -> bytes:
    return orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)


# ---------------------------------------------------------------------------
# JSON Schema round-trip
# ---------------------------------------------------------------------------


@given(schema=json_schema_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_json_schema_round_trip(schema: object) -> None:
    """Parse → serialize → re-parse → re-serialize must be idempotent."""
    doc = _make_js_doc(schema)

    r1 = _JS_PARSER.apply(doc)
    assert isinstance(r1, Ok), f"First parse failed: {[e.message for e in r1.errors]}"
    serialized1 = _JS_SERIALIZER.serialize_document(r1.value)

    r2 = _JS_PARSER.apply(_make_js_doc(serialized1))
    assert isinstance(r2, Ok), f"Second parse failed: {[e.message for e in r2.errors]}"
    serialized2 = _JS_SERIALIZER.serialize_document(r2.value)

    assert _stable_json(serialized1) == _stable_json(serialized2), (
        f"Round-trip not idempotent.\n"
        f"  after 1st serialize: {serialized1}\n"
        f"  after 2nd serialize: {serialized2}"
    )


# ---------------------------------------------------------------------------
# OpenAPI round-trip
# ---------------------------------------------------------------------------


@given(openapi=openapi_doc_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_openapi_round_trip(openapi: dict) -> None:
    """Parse → serialize → re-parse → re-serialize must be idempotent."""
    doc = _make_oa_doc(openapi)

    r1 = _OA_PARSER.apply(doc)
    assert isinstance(r1, Ok), f"First parse failed: {[e.message for e in r1.errors]}"
    serialized1 = _OA_SERIALIZER.serialize(r1.value)

    r2 = _OA_PARSER.apply(_make_oa_doc(serialized1))
    assert isinstance(r2, Ok), f"Second parse failed: {[e.message for e in r2.errors]}"
    serialized2 = _OA_SERIALIZER.serialize(r2.value)

    assert _stable_json(serialized1) == _stable_json(serialized2), (
        f"Round-trip not idempotent.\n"
        f"  after 1st serialize: {serialized1!r:.500}\n"
        f"  after 2nd serialize: {serialized2!r:.500}"
    )
