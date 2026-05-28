"""JSON Schema 2020-12 $ref / $dynamicRef resolver.

Resolution is two-phase:

1. **Registration** (`register`): index a `JsonSchemaDocument` into both the
   `referencing` library registry (for URI math / anchor lookup) and our own
   CST pointer/anchor index (for generator lookups that return typed CST nodes).

2. **Validation** (`apply`): walk the document's schema tree and ensure every
   `$ref` / `$dynamicRef` string is resolvable, accumulating `ResolutionError`s
   rather than stopping at the first failure.  The document is returned unchanged
   on success.

The `lookup` / `lookup_anchor` methods are intended for use by generators after
`apply` has confirmed the document is valid.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import referencing
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from schema_to.cst.json_schema import BooleanSchema, JsonSchema, JsonSchemaDocument, ObjectSchema
from schema_to.errors import ResolutionError, SourceLocation, TranspilationError
from schema_to.pipeline import RefResolver
from schema_to.result import Err, Ok, Result
from schema_to.serialize.json_schema import JsonSchemaSerializer

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["JsonSchemaRefResolver"]

_SERIALIZER = JsonSchemaSerializer()


# ---------------------------------------------------------------------------
# Sub-schema iterator
# ---------------------------------------------------------------------------


def _iter_sub_schemas(schema: ObjectSchema, pointer: str) -> Iterator[tuple[str, JsonSchema]]:
    """Yield `(child_pointer, child_schema)` for every direct sub-schema."""

    def _single(key: str, sub: JsonSchema) -> tuple[str, JsonSchema]:
        return f"{pointer}/{key}", sub

    def _map(key: str, m: dict) -> Iterator[tuple[str, JsonSchema]]:
        for name, sub in m.items():
            yield f"{pointer}/{key}/{name}", sub

    def _list(key: str, lst: list) -> Iterator[tuple[str, JsonSchema]]:
        for i, sub in enumerate(lst):
            yield f"{pointer}/{key}/{i}", sub

    if schema.defs:
        yield from _map("$defs", dict(schema.defs))
    if schema.properties:
        yield from _map("properties", dict(schema.properties))
    if schema.pattern_properties:
        yield from _map("patternProperties", dict(schema.pattern_properties))
    if schema.dependent_schemas:
        yield from _map("dependentSchemas", dict(schema.dependent_schemas))
    if schema.items is not None:
        yield _single("items", schema.items)
    if schema.contains is not None:
        yield _single("contains", schema.contains)
    if schema.additional_properties is not None:
        yield _single("additionalProperties", schema.additional_properties)
    if schema.property_names is not None:
        yield _single("propertyNames", schema.property_names)
    if schema.prefix_items:
        yield from _list("prefixItems", list(schema.prefix_items))
    if schema.all_of:
        yield from _list("allOf", list(schema.all_of))
    if schema.any_of:
        yield from _list("anyOf", list(schema.any_of))
    if schema.one_of:
        yield from _list("oneOf", list(schema.one_of))
    if schema.not_ is not None:
        yield _single("not", schema.not_)
    if schema.if_ is not None:
        yield _single("if", schema.if_)
    if schema.then is not None:
        yield _single("then", schema.then)
    if schema.else_ is not None:
        yield _single("else", schema.else_)
    if schema.unevaluated_items is not None:
        yield _single("unevaluatedItems", schema.unevaluated_items)
    if schema.unevaluated_properties is not None:
        yield _single("unevaluatedProperties", schema.unevaluated_properties)
    if schema.content_schema is not None:
        yield _single("contentSchema", schema.content_schema)


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


@dataclass
class JsonSchemaRefResolver(RefResolver[JsonSchemaDocument]):
    """Validates and resolves `$ref` / `$dynamicRef` in JSON Schema 2020-12 documents.

    Attributes:
        _registry: The `referencing` library registry used for URI math and
            anchor lookups.
        _cst_by_pointer: Maps `(source_id, json_pointer)` → CST node.
        _cst_by_anchor: Maps `(source_id, anchor_name)` → CST node.
        _id_to_source: Maps absolute `$id` URI → `source_id`.
        _docs: Maps `source_id` → `JsonSchemaDocument`.
    """

    _registry: Registry = field(default_factory=Registry)
    _cst_by_pointer: dict[tuple[str, str], JsonSchema] = field(default_factory=dict)
    _cst_by_anchor: dict[tuple[str, str], JsonSchema] = field(default_factory=dict)
    _id_to_source: dict[str, str] = field(default_factory=dict)
    _docs: dict[str, JsonSchemaDocument] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, cst: JsonSchemaDocument) -> None:
        """Add a document to the registry for cross-document ref resolution."""
        if cst.source_id in self._docs:
            return
        self._docs[cst.source_id] = cst
        self._index_cst(cst.root, source_id=cst.source_id, pointer="")

        raw = _SERIALIZER.serialize_document(cst)
        resource = Resource.from_contents(raw, default_specification=DRAFT202012)
        self._registry = self._registry.with_resource(cst.source_id, resource)

        if isinstance(cst.root, ObjectSchema) and cst.root.id:
            abs_id = urllib.parse.urljoin(cst.source_id, cst.root.id)
            if abs_id != cst.source_id:
                self._id_to_source[abs_id] = cst.source_id
                # Also register the $id URI with the referencing library.
                self._registry = self._registry.with_resource(abs_id, resource)

    def apply(self, input: JsonSchemaDocument) -> Result[JsonSchemaDocument]:
        """Validate all `$ref` / `$dynamicRef` in *input*.

        Returns `Ok(input)` unchanged if every reference resolves, or
        `Err` with one `ResolutionError` per unresolvable reference.
        Auto-registers the document if it has not been registered yet.
        """
        if input.source_id not in self._docs:
            self.register(input)

        try:
            ref_resolver = self._registry.resolver(base_uri=input.source_id)
        except Unresolvable as exc:
            return Err((ResolutionError(str(exc), location=SourceLocation(input.source_id, "")),))

        errors: list[TranspilationError] = []
        self._check_refs(
            input.root, ref_resolver=ref_resolver, source_id=input.source_id, errors=errors
        )

        if errors:
            return Err(tuple(errors))
        return Ok(input)

    def lookup(self, ref: str, *, base_uri: str) -> JsonSchema | None:
        """Resolve a `$ref` string to its CST node.

        Returns `None` when the ref cannot be resolved (i.e. the document
        was never registered, or the pointer / anchor does not exist).
        """
        doc_uri, fragment = self._split_ref(ref, base_uri)
        source_id = self._find_source_id(doc_uri)
        if source_id is None:
            return None
        if not fragment or fragment.startswith("/"):
            return self._cst_by_pointer.get((source_id, fragment))
        return self._cst_by_anchor.get((source_id, fragment))

    def lookup_anchor(self, anchor: str, *, source_id: str) -> JsonSchema | None:
        """Return the CST node that declares the given `$anchor` or `$dynamicAnchor`."""
        return self._cst_by_anchor.get((source_id, anchor))

    def registered_source_ids(self) -> frozenset[str]:
        """Return the set of source IDs currently in the registry."""
        return frozenset(self._docs)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _index_cst(self, schema: JsonSchema, source_id: str, pointer: str) -> None:
        self._cst_by_pointer[source_id, pointer] = schema
        if isinstance(schema, BooleanSchema):
            return
        if schema.anchor:
            self._cst_by_anchor[source_id, schema.anchor] = schema
        if schema.dynamic_anchor:
            self._cst_by_anchor[source_id, schema.dynamic_anchor] = schema
        if schema.id:
            abs_id = urllib.parse.urljoin(source_id, schema.id)
            if abs_id != source_id:
                self._id_to_source[abs_id] = source_id
        for sub_pointer, sub_schema in _iter_sub_schemas(schema, pointer):
            self._index_cst(sub_schema, source_id, sub_pointer)

    def _check_refs(
        self,
        schema: JsonSchema,
        *,
        ref_resolver: referencing.Resolver,  # FIXME: There is no `referencing.Resolver`.
        source_id: str,
        errors: list[TranspilationError],
    ) -> None:
        if isinstance(schema, BooleanSchema):
            return

        pointer = schema.source_ref.json_pointer if schema.source_ref else ""
        loc = SourceLocation(source_id, pointer)

        if schema.ref:
            try:
                ref_resolver.lookup(schema.ref)
            except Unresolvable as exc:
                errors.append(
                    ResolutionError(f"Cannot resolve $ref {schema.ref!r}: {exc}", location=loc)
                )

        if schema.dynamic_ref:
            try:
                ref_resolver.lookup(schema.dynamic_ref)
            except Unresolvable as exc:
                errors.append(
                    ResolutionError(
                        f"Cannot resolve $dynamicRef {schema.dynamic_ref!r}: {exc}", location=loc
                    )
                )

        # $id changes the base URI for nested schemas.
        current_resolver = ref_resolver
        if schema.id:
            try:
                resolved = ref_resolver.lookup(schema.id)
                current_resolver = resolved.resolver
            except Unresolvable:
                pass  # FIXME

        for _, sub_schema in _iter_sub_schemas(schema, pointer):
            self._check_refs(
                sub_schema, ref_resolver=current_resolver, source_id=source_id, errors=errors
            )

    def _split_ref(self, ref: str, base_uri: str) -> tuple[str, str]:
        """Return `(doc_uri, fragment)` by resolving *ref* against *base_uri*.

        `urllib.parse.urljoin` does not correctly resolve fragment-only
        references (`"#/foo"`) against non-HTTP base URIs such as
        `"test://doc"` — it returns the fragment as-is with an empty document
        component.  We detect that case and substitute the base document URI.
        """
        resolved = urllib.parse.urljoin(base_uri, ref)
        if "#" in resolved:
            doc_uri, fragment = resolved.split("#", 1)
        else:
            doc_uri, fragment = resolved, ""
        # Pure fragment reference: doc_uri came out empty.
        if not doc_uri:
            doc_uri = base_uri.split("#", 1)[0] if "#" in base_uri else base_uri
        return doc_uri, fragment

    def _find_source_id(self, doc_uri: str) -> str | None:
        if doc_uri in self._docs:
            return doc_uri
        return self._id_to_source.get(doc_uri)
