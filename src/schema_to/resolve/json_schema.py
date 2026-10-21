"""JSON Schema 2020-12 $ref / $dynamicRef resolver.

Resolution is two-phase:

1. **Registration** (`register`):
   index a `JsonSchemaDocument` into both the `referencing` library registry
   (for URI math / anchor lookup)
   and our own CST pointer/anchor index
   (for generator lookups that return typed CST nodes).

2. **Validation** (`apply`):
   walk the document's schema tree and ensure every `$ref` / `$dynamicRef` string is resolvable,
   accumulating `ResolutionError`s rather than stopping at the first failure.
   The document is returned unchanged on success.

The `lookup` / `lookup_anchor` methods are intended for use by generators
after `apply` has confirmed the document is valid.
"""

import urllib.parse
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override

from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from schema_to.cst.json_schema import (
    BooleanSchema,
    JsonSchema,
    JsonSchemaDocument,
    JsonSchemaMapDocument,
    ObjectSchema,
)
from schema_to.errors import ResolutionError, TranspilationError
from schema_to.io.uri import Uri
from schema_to.pipeline import RefResolver
from schema_to.resolve._resolver import Resolver
from schema_to.result import Err, Ok, Result
from schema_to.serialize.json_schema import JsonSchemaSerializer

if TYPE_CHECKING:
    from collections.abc import Iterator, Set

__all__ = ["JsonSchemaMapRefResolver", "JsonSchemaRefResolver"]


def _escape(name: str) -> str:
    """Escape a name for use as a single JSON Pointer segment (RFC 6901)."""
    return name.replace("~", "~0").replace("/", "~1")


_SERIALIZER = JsonSchemaSerializer()


# ---------------------------------------------------------------------------
# Sub-schema iterator
# ---------------------------------------------------------------------------


# ruff:ignore[complex-structure, too-many-branches]  # Mostly shared structure
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
    if schema.then_ is not None:
        yield _single("then", schema.then_)
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
        _registry: The `referencing` library registry used for URI math and anchor lookups.
        _cst_by_pointer: Maps `(source_id, json_pointer)` → CST node.
        _cst_by_anchor: Maps `(source_id, anchor_name)` → CST node.
        _id_to_source: Maps absolute `$id` URI → `source_id`.
        _docs: Maps `source_id` → `JsonSchemaDocument`.
        _map_docs: Maps `source_id` → `JsonSchemaMapDocument`.
    """

    _registry: Registry = field(default_factory=Registry)
    _cst_by_pointer: dict[tuple[str, str], JsonSchema] = field(default_factory=dict)
    _cst_by_anchor: dict[tuple[str, str], JsonSchema] = field(default_factory=dict)
    _id_to_source: dict[str, str] = field(default_factory=dict)
    _docs: dict[str, JsonSchemaDocument] = field(default_factory=dict)
    _map_docs: dict[str, JsonSchemaMapDocument] = field(default_factory=dict)

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

    def register_map(self, cst: JsonSchemaMapDocument) -> None:
        """Add a map of named schemas to the registry.

        Each entry is indexed at its own pointer (`/name`),
        which is where a `$ref` of the form `./that-file.yaml#/name` looks for it.
        """
        if cst.source_id in self._map_docs:
            return
        self._map_docs[cst.source_id] = cst
        for name, schema in cst.schemas.items():
            self._index_cst(schema, source_id=cst.source_id, pointer=f"/{_escape(name)}")
        raw = {name: _SERIALIZER.serialize(schema) for name, schema in cst.schemas.items()}
        resource = Resource.from_contents(raw, default_specification=DRAFT202012)
        self._registry = self._registry.with_resource(cst.source_id, resource)

    def apply(self, input: JsonSchemaDocument) -> Result[JsonSchemaDocument]:
        """Validate all `$ref` / `$dynamicRef` in *input*.

        Returns `Ok(input)` unchanged if every reference resolves,
        or `Err` with one `ResolutionError` per unresolvable reference.
        Auto-registers the document if it has not been registered yet.
        """
        if input.source_id not in self._docs:
            self.register(input)
        ref_resolver = self._resolver_for(input.source_id)
        errors: list[TranspilationError] = []
        self._check_refs(input.root, ref_resolver=ref_resolver, errors=errors)
        if errors:
            return Err(tuple(errors))
        return Ok(input)

    def lookup(self, ref: str, *, base_uri: str) -> JsonSchema | None:
        """Resolve a `$ref` string to its CST node.

        Returns `None` when the ref cannot be resolved
        (i.e. the document was never registered, or the pointer / anchor does not exist).
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

    def registered_source_ids(self) -> Set[str]:
        """Return the set of source IDs currently in the registry."""
        return frozenset(self._docs) | frozenset(self._map_docs)

    def apply_map(self, input: JsonSchemaMapDocument) -> Result[JsonSchemaMapDocument]:
        """Validate every `$ref` / `$dynamicRef` in each named schema of `input`.

        Auto-registers the document if it has not been registered yet.
        Registering the other documents it references first is the caller's job;
        a reference into an unregistered file cannot resolve.
        """
        if input.source_id not in self._map_docs:
            self.register_map(input)
        ref_resolver = self._resolver_for(input.source_id)
        errors: list[TranspilationError] = []
        for schema in input.schemas.values():
            self._check_refs(schema, ref_resolver=ref_resolver, errors=errors)
        if errors:
            return Err(tuple(errors))
        return Ok(input)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolver_for(self, source_id: str) -> Resolver:
        """Return a resolver rooted at `source_id`.

        The fragment of a carved-out document's ID is dropped,
        as RFC 3986 drops a base URI's fragment:
        `#/other` in `file:///catalog.yaml#/thing` means `file:///catalog.yaml#/other`.
        `referencing` would instead look for `/other` inside the document registered as `source_id`,
        which is only the carved-out piece.
        """
        return Resolver(self._registry.resolver(base_uri=Uri.parse(source_id).document))

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
        self, schema: JsonSchema, *, ref_resolver: Resolver, errors: list[TranspilationError]
    ) -> None:
        if isinstance(schema, BooleanSchema):
            return

        loc = schema.source_ref

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
            except Unresolvable:  # ruff:ignore[try-except-pass]  # Not a schema error.
                # `$id` may reference an unregistered canonical URI.
                # The current resolver stays valid for nested schemas;
                # any real ref failures are already caught by the $ref/$dynamicRef checks above.
                pass

        for _, sub_schema in _iter_sub_schemas(schema, schema.source_ref.json_pointer):
            self._check_refs(sub_schema, ref_resolver=current_resolver, errors=errors)

    def _split_ref(self, ref: str, base_uri: str) -> tuple[str, str]:
        """Return `(doc_uri, fragment)` by resolving *ref* against *base_uri*.

        `urllib.parse.urljoin` does not correctly resolve fragment-only references (`"#/foo"`)
        against non-HTTP base URIs such as `"test://doc"`;
        it returns the fragment as-is with an empty document component.
        We detect that case and substitute the base document URI.
        """
        resolved = urllib.parse.urljoin(base_uri, ref)
        if "#" in resolved:
            doc_uri, fragment = resolved.split("#", 1)
        else:
            doc_uri, fragment = resolved, ""
        # Pure fragment reference: doc_uri came out empty.
        if not doc_uri:
            doc_uri = Uri.parse(base_uri).document
        return doc_uri, fragment

    def _find_source_id(self, doc_uri: str) -> str | None:
        if doc_uri in self._docs or doc_uri in self._map_docs:
            return doc_uri
        return self._id_to_source.get(doc_uri)


@dataclass(frozen=True, slots=True)
class JsonSchemaMapRefResolver(RefResolver[JsonSchemaMapDocument]):
    """The schema-map face of a `JsonSchemaRefResolver`.

    A `JsonSchemaRefResolver` indexes both kinds of document into one registry,
    which is what lets a reference cross between them;
    this exposes its map half as an ordinary `RefResolver`,
    so a set of map documents registers and validates through,
    using the same two-pass composition as any other:

    ```python
    Each(maps.registering()).then(Each(maps))
    ```
    """

    inner: JsonSchemaRefResolver

    @override
    def register(self, cst: JsonSchemaMapDocument) -> None:
        self.inner.register_map(cst)

    @override
    def apply(self, input: JsonSchemaMapDocument) -> Result[JsonSchemaMapDocument]:
        return self.inner.apply_map(input)
