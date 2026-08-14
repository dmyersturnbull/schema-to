"""Building the transpiler for a target, for tests that exercise a whole target.

The router is the only thing that knows how a target is assembled, so a test that
wants one asks it, exactly as the CLI does.
"""

from collections.abc import Mapping, Set

from schema_to.io.media_type import MediaType, MediaTypes
from schema_to.io.source import JsonSchemaRawDoc, RawDoc
from schema_to.pipeline import Transpiler
from schema_to.transpile.factory import TranspilerRouter


def transpiler_for(
    name: str,
    *,
    selects: type[RawDoc] = JsonSchemaRawDoc,
    output_media_type: MediaType = MediaTypes.json,
    templates: Mapping[str, str] | None = None,
    roots: Set[str] | None = None,
    schema_map: bool = False,
) -> Transpiler:
    """Return the transpiler routed for `name` that consumes `selects` documents."""
    routed = TranspilerRouter().route(
        name, output_media_type, templates=templates, roots=roots, schema_map=schema_map
    )
    [chosen] = [t for t in routed if t.selects is selects]
    return chosen
