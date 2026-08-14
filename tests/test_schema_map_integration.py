"""Integration: a directory tree of named-schema files resolving refs across files.

Separate from `test_schema_map.py`, which exercises the parser, resolver, and
directory source in isolation.  This walks a real tree on disk end to end.
"""

from pathlib import Path

from schema_to.cst.json_schema import JsonSchemaType, ObjectSchema
from schema_to.generate.inlining import SchemaFlattener
from schema_to.io.file import SchemaMapDirectorySource
from schema_to.parse.json_schema import JsonSchemaMapParser
from schema_to.resolve.json_schema import JsonSchemaRefResolver
from schema_to.result import Ok

_PARSER = JsonSchemaMapParser()


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_directory_tree_resolves_relative_refs_and_flattens(tmp_path: Path) -> None:
    """The Goldberry layout: a `base/` file of primitives, a realm file composing them."""
    _write(
        tmp_path,
        "base/time.yaml",
        "timestamp:\n  type: string\n  pattern: '^2'\n  description: A timestamp.\n",
    )
    _write(
        tmp_path,
        "main/catalog.yaml",
        "thing-content:\n"
        "  type: object\n"
        "  properties:\n"
        "    name:\n"
        "      type: string\n"
        "thing-data:\n"
        "  type: object\n"
        "  allOf:\n"
        "    - type: object\n"
        "      required: [id]\n"
        "      properties:\n"
        "        id:\n"
        "          type: string\n"
        "        insert-time:\n"
        "          $ref: '../base/time.yaml#/timestamp'\n"
        "    - $ref: '#/thing-content'\n",
    )

    resolver = JsonSchemaRefResolver()
    docs = []
    for raw in SchemaMapDirectorySource(tmp_path).documents():
        result = _PARSER.apply(raw)
        assert isinstance(result, Ok), [getattr(e, "message", str(e)) for e in result.errors]
        docs.append(result.value)
        resolver.register_map(result.value)
    for doc in docs:
        assert isinstance(resolver.apply_map(doc), Ok)

    catalog = next(d for d in docs if d.source_id.endswith("catalog.yaml"))
    flat = SchemaFlattener(resolver=resolver).flatten(
        catalog.schemas["thing-data"], base_uri=catalog.source_id
    )
    assert flat.warnings == ()
    assert isinstance(flat.schema, ObjectSchema)
    assert list(flat.schema.properties or {}) == ["id", "insert-time", "name"]
    assert flat.schema.get_required() == frozenset({"id"})

    # The cross-file ref resolved to a concrete string type, not an opaque $ref.
    insert_time = (flat.schema.properties or {})["insert-time"]
    resolved = SchemaFlattener(resolver=resolver).flatten(insert_time, base_uri=catalog.source_id)
    assert isinstance(resolved.schema, ObjectSchema)
    assert resolved.schema.get_types() == frozenset({JsonSchemaType.STRING})
    assert resolved.schema.pattern == "^2"
