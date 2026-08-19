"""Tests for JsonSchemaRefResolver.

Covers:

- Property invariants: schemas with no refs always resolve;
  schemas with valid internal $defs/$ref always resolve.
- Smoke tests: simple pointer lookup, anchor lookup, cross-document resolution.
- Failure tests: unresolvable $ref, cross-document ref to unregistered doc.
- Edge cases: circular (self-recursive) schemas, multiple bad refs accumulate.
"""

import orjson
from hypothesis import HealthCheck, given, settings
from tests._strategies import json_schema_st, json_schema_with_defs_st

from schema_to.cst.json_schema import JsonSchemaDocument, JsonSchemaType, ObjectSchema
from schema_to.errors import ResolutionError
from schema_to.io.media_type import MediaTypes
from schema_to.io.source import JsonSchemaRawDoc
from schema_to.parse.json_schema import JsonSchemaParser
from schema_to.pipeline import Err, Ok
from schema_to.resolve.json_schema import JsonSchemaRefResolver

_PARSER = JsonSchemaParser()


def _doc(data: object, source_id: str = "test://doc") -> JsonSchemaRawDoc:
    return JsonSchemaRawDoc(
        doc_id=source_id, content=orjson.dumps(data), media_type=MediaTypes.json
    )


def _parse(data: object, source_id: str = "test://doc") -> JsonSchemaDocument:
    r = _PARSER.apply(_doc(data, source_id))
    assert isinstance(r, Ok), f"Parse failed: {r}"
    return r.value


# ---------------------------------------------------------------------------
# Property: schemas without $ref always resolve
# ---------------------------------------------------------------------------


@given(schema=json_schema_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_no_refs_always_resolve(schema: object) -> None:
    """Any schema that contains no $ref / $dynamicRef passes the resolver."""

    # Strip $ref / $dynamicRef from the generated schema so we guarantee none.
    def _strip_refs(obj: object) -> object:
        if isinstance(obj, dict):
            return {k: _strip_refs(v) for k, v in obj.items() if k not in {"$ref", "$dynamicRef"}}
        if isinstance(obj, list):
            return [_strip_refs(v) for v in obj]
        return obj

    stripped = _strip_refs(schema)
    cst = _parse(stripped)
    resolver = JsonSchemaRefResolver()
    result = resolver.apply(cst)
    assert isinstance(result, Ok), (
        f"Resolver failed on ref-free schema: {[e.message for e in result.errors]}"
    )


# ---------------------------------------------------------------------------
# Property: schemas with valid internal $defs/$ref always resolve
# ---------------------------------------------------------------------------


@given(schema=json_schema_with_defs_st())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_valid_internal_refs_resolve(schema: dict) -> None:
    """Schemas where all $ref point to existing $defs entries must resolve OK."""
    cst = _parse(schema)
    resolver = JsonSchemaRefResolver()
    result = resolver.apply(cst)
    assert isinstance(result, Ok), (
        f"Resolver failed on schema with valid $defs refs: "
        f"{[e.message for e in result.errors]}\nSchema: {schema}"
    )


# ---------------------------------------------------------------------------
# Property: apply is idempotent — calling it twice returns Ok both times
# ---------------------------------------------------------------------------


@given(schema=json_schema_with_defs_st())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_apply_idempotent(schema: dict) -> None:
    """Calling apply twice on the same document returns Ok both times."""
    cst = _parse(schema)
    resolver = JsonSchemaRefResolver()
    r1 = resolver.apply(cst)
    r2 = resolver.apply(cst)
    assert type(r1) is type(r2)
    assert isinstance(r1, Ok)


# ---------------------------------------------------------------------------
# Smoke: pointer lookup
# ---------------------------------------------------------------------------


def test_lookup_pointer_to_def() -> None:
    """lookup() returns the correct CST node for a #/$defs/ pointer."""
    schema = {
        "type": "object",
        "$defs": {"Email": {"type": "string", "format": "email"}},
        "properties": {"address": {"$ref": "#/$defs/Email"}},
    }
    cst = _parse(schema)
    resolver = JsonSchemaRefResolver()
    result = resolver.apply(cst)
    assert isinstance(result, Ok)

    node = resolver.lookup("#/$defs/Email", base_uri="test://doc")
    assert node is not None

    assert isinstance(node, ObjectSchema)

    assert node.type == JsonSchemaType.STRING
    assert node.format == "email"


def test_lookup_root_pointer() -> None:
    """lookup('#') returns the root schema."""
    schema = {"type": "object"}
    cst = _parse(schema)
    resolver = JsonSchemaRefResolver()
    resolver.apply(cst)
    node = resolver.lookup("#", base_uri="test://doc")
    assert node is not None


def test_lookup_nonexistent_returns_none() -> None:
    """lookup() returns None for a pointer that does not exist."""
    cst = _parse({"type": "object"})
    resolver = JsonSchemaRefResolver()
    resolver.apply(cst)
    node = resolver.lookup("#/$defs/Missing", base_uri="test://doc")
    assert node is None


# ---------------------------------------------------------------------------
# Smoke: anchor resolution
# ---------------------------------------------------------------------------


def test_anchor_resolution() -> None:
    """$ref to an $anchor resolves correctly."""
    schema = {
        "type": "object",
        "$defs": {"Name": {"$anchor": "nameAnchor", "type": "string"}},
        "properties": {"name": {"$ref": "#nameAnchor"}},
    }
    cst = _parse(schema)
    resolver = JsonSchemaRefResolver()
    result = resolver.apply(cst)
    assert isinstance(result, Ok), f"Anchor resolution failed: {[e.message for e in result.errors]}"

    node = resolver.lookup_anchor("nameAnchor", source_id="test://doc")
    assert node is not None


def test_dynamic_anchor_resolution() -> None:
    """$dynamicRef to a $dynamicAnchor resolves correctly."""
    schema = {
        "type": "object",
        "$defs": {"Item": {"$dynamicAnchor": "items", "type": "string"}},
        "properties": {"x": {"$dynamicRef": "#items"}},
    }
    cst = _parse(schema)
    resolver = JsonSchemaRefResolver()
    result = resolver.apply(cst)
    assert isinstance(result, Ok), f"Dynamic anchor failed: {[e.message for e in result.errors]}"


# ---------------------------------------------------------------------------
# Smoke: cross-document resolution
# ---------------------------------------------------------------------------


def test_cross_document_ref_success() -> None:
    """A $ref to a separately-registered document resolves OK."""
    address_schema = {"type": "object", "properties": {"street": {"type": "string"}}}
    address_cst = _parse(address_schema, source_id="test://address")

    root_schema = {"type": "object", "properties": {"home": {"$ref": "test://address"}}}
    root_cst = _parse(root_schema, source_id="test://root")

    resolver = JsonSchemaRefResolver()
    resolver.register(address_cst)
    result = resolver.apply(root_cst)
    assert isinstance(result, Ok), f"Cross-doc ref failed: {[e.message for e in result.errors]}"


def test_cross_document_ref_missing() -> None:
    """A $ref to an unregistered document produces a ResolutionError."""
    schema = {"type": "object", "properties": {"x": {"$ref": "test://nonexistent"}}}
    cst = _parse(schema)
    resolver = JsonSchemaRefResolver()
    result = resolver.apply(cst)
    assert isinstance(result, Err)
    assert any(isinstance(e, ResolutionError) for e in result.errors)


# ---------------------------------------------------------------------------
# Failure: unresolvable internal $ref
# ---------------------------------------------------------------------------


def test_missing_def_ref_fails() -> None:
    """$ref pointing to an absent $defs entry produces ResolutionError."""
    schema = {"type": "object", "properties": {"x": {"$ref": "#/$defs/DoesNotExist"}}}
    cst = _parse(schema)
    resolver = JsonSchemaRefResolver()
    result = resolver.apply(cst)
    assert isinstance(result, Err)
    assert len(result.errors) == 1
    err = result.errors[0]
    assert isinstance(err, ResolutionError)
    assert "DoesNotExist" in err.message or "$ref" in err.message


def test_missing_anchor_ref_fails() -> None:
    """$ref to a non-existent anchor produces ResolutionError."""
    schema = {"properties": {"x": {"$ref": "#noSuchAnchor"}}}
    cst = _parse(schema)
    resolver = JsonSchemaRefResolver()
    result = resolver.apply(cst)
    assert isinstance(result, Err)
    assert all(isinstance(e, ResolutionError) for e in result.errors)
    assert any("noSuchAnchor" in e.message or "$ref" in e.message for e in result.errors)


def test_multiple_bad_refs_all_reported() -> None:
    """All unresolvable $ref values are reported, not just the first."""
    schema = {
        "type": "object",
        "properties": {"a": {"$ref": "#/$defs/Missing1"}, "b": {"$ref": "#/$defs/Missing2"}},
    }
    cst = _parse(schema)
    resolver = JsonSchemaRefResolver()
    result = resolver.apply(cst)
    assert isinstance(result, Err)
    assert all(isinstance(e, ResolutionError) for e in result.errors)
    assert len(result.errors) >= 2
    messages = " ".join(e.message for e in result.errors)
    assert "Missing1" in messages or "$ref" in messages
    assert "Missing2" in messages or "$ref" in messages


# ---------------------------------------------------------------------------
# Edge: self-recursive schema
# ---------------------------------------------------------------------------


def test_self_recursive_schema_validates() -> None:
    """A schema where a $defs entry references itself resolves without infinite recursion."""
    schema = {
        "type": "object",
        "$defs": {
            "Node": {
                "type": "object",
                "properties": {
                    "value": {"type": "integer"},
                    "children": {"type": "array", "items": {"$ref": "#/$defs/Node"}},
                },
            }
        },
        "properties": {"root": {"$ref": "#/$defs/Node"}},
    }
    cst = _parse(schema)
    resolver = JsonSchemaRefResolver()
    result = resolver.apply(cst)
    assert isinstance(result, Ok), (
        f"Self-recursive schema failed: {[e.message for e in result.errors]}"
    )


def test_mutual_recursion_validates() -> None:
    """Two $defs that reference each other both resolve without error."""
    schema = {
        "type": "object",
        "$defs": {
            "A": {"type": "object", "properties": {"b": {"$ref": "#/$defs/B"}}},
            "B": {"type": "object", "properties": {"a": {"$ref": "#/$defs/A"}}},
        },
    }
    cst = _parse(schema)
    resolver = JsonSchemaRefResolver()
    result = resolver.apply(cst)
    assert isinstance(result, Ok)


# ---------------------------------------------------------------------------
# Edge: register does not double-index
# ---------------------------------------------------------------------------


def test_register_idempotent() -> None:
    """Calling register() twice for the same source_id does not raise."""
    cst = _parse({"type": "string"})
    resolver = JsonSchemaRefResolver()
    resolver.register(cst)
    resolver.register(cst)
    assert "test://doc" in resolver.registered_source_ids()


# ---------------------------------------------------------------------------
# Edge: $id within schema changes lookup base URI
# ---------------------------------------------------------------------------


def test_schema_with_id_registers_alias() -> None:
    """A schema with a root $id is also reachable by that URI."""
    schema = {"$id": "https://example.com/thing.json", "type": "object"}
    cst = _parse(schema, source_id="test://thing")
    resolver = JsonSchemaRefResolver()
    result = resolver.apply(cst)
    assert isinstance(result, Ok)
    # The $id URI should be usable as a lookup base.
    node = resolver.lookup("#", base_uri="https://example.com/thing.json")
    assert node is not None
