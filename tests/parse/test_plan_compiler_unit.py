"""Deriving a node plan from a CST dataclass's annotations.

The golden snapshot is the safety net for that derivation:
a change to the rules, or to a CST field, shows up as a diff in a checked-in table.
"""

import json
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from schema_to.core import JsonObject, JsonValue
from schema_to.cst.json_schema import ObjectSchema
from schema_to.cst.openapi import (
    Components,
    Contact,
    Encoding,
    Example,
    ExternalDocumentation,
    Header,
    Info,
    License,
    Link,
    MediaTypeObject,
    OAuthFlow,
    OAuthFlows,
    OpenApiDocument,
    Operation,
    Parameter,
    PathItem,
    Reference,
    RequestBody,
    Response,
    SecurityScheme,
    Server,
    ServerVariable,
    Tag,
)
from schema_to.parse._plan import (
    EnumSpec,
    FieldPlan,
    IntSpec,
    ListSpec,
    MapSpec,
    NodeSpec,
    OneOfSpec,
    SchemaSpec,
    SetSpec,
    json_key,
    plan_for,
)

_GOLDEN = Path(__file__).parent / "plans.golden.json"

# Every node built from a plan. The document envelopes are excluded: a JSON
# Schema document *is* its root schema rather than an object of keywords.
_PLANNED = [
    ObjectSchema,
    OpenApiDocument,
    Components,
    Contact,
    Encoding,
    Example,
    ExternalDocumentation,
    Header,
    Info,
    License,
    Link,
    MediaTypeObject,
    OAuthFlow,
    OAuthFlows,
    Operation,
    Parameter,
    PathItem,
    Reference,
    RequestBody,
    Response,
    SecurityScheme,
    Server,
    ServerVariable,
    Tag,
]


def _spec_json(spec: object) -> JsonValue:
    rendered: JsonValue
    match spec:
        case ListSpec(item=item):
            rendered = {"kind": "list", "item": _spec_json(item)}
        case SetSpec(item=item):
            rendered = {"kind": "set", "item": _spec_json(item)}
        case MapSpec(value=value):
            rendered = {"kind": "map", "value": _spec_json(value)}
        case OneOfSpec(options=options):
            rendered = {"kind": "one-of", "options": [_spec_json(o) for o in options]}
        case NodeSpec(node=node):
            rendered = {"kind": "node", "type": node.__name__}
        case EnumSpec(enum=enum):
            rendered = {"kind": "enum", "type": enum.__name__}
        case SchemaSpec():
            rendered = {"kind": "schema"}
        case IntSpec(minimum=minimum) if minimum is not None:
            rendered = {"kind": "int", "minimum": minimum}
        case _:
            rendered = {"kind": type(spec).__name__.removesuffix("Spec").lower()}
    return rendered


def _field_json(entry: FieldPlan) -> JsonValue:
    rendered: JsonObject = {"property": entry.key, "field": entry.name}
    if entry.required:
        rendered["required"] = True
    if entry.nullable:
        rendered["nullable"] = True
    if entry.since is not None:
        rendered["since"] = entry.since.text
    if entry.until is not None:
        rendered["until"] = entry.until.text
    rendered["spec"] = _spec_json(entry.spec)
    return rendered


def _render_plans() -> str:
    nodes: list[JsonValue] = []
    for node in _PLANNED:
        plan = plan_for(node)
        nodes.append(
            {
                "node": node.__name__,
                "extensions": plan.has_extensions,
                "sourceRef": plan.has_source_ref,
                "fields": [_field_json(entry) for entry in plan.entries],
            }
        )
    return json.dumps(nodes, indent=2) + "\n"


def test_plans_match_golden_snapshot() -> None:
    rendered = _render_plans()
    if not _GOLDEN.exists():  # pragma: no cover — only on first run
        _GOLDEN.write_text(rendered, encoding="utf-8")
    assert rendered == _GOLDEN.read_text(encoding="utf-8"), (
        "Compiled plans changed. Review the diff; if it is intended, delete "
        f"{_GOLDEN.name} and re-run to regenerate it."
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("in_", "in"),
        ("type_", "type"),
        ("license_", "license"),
        ("terms_of_service", "termsOfService"),
        ("open_id_connect_url", "openIdConnectUrl"),
        ("path_items", "pathItems"),
        ("url", "url"),
    ],
)
def test_json_key_derivation(name: str, expected: str) -> None:
    assert json_key(name) == expected


def test_every_planned_node_is_a_frozen_dataclass() -> None:
    for node in _PLANNED:
        assert is_dataclass(node), node
        assert fields(node), node


def test_requiredness_matches_the_absence_of_a_default() -> None:
    required = {e.key for e in plan_for(Info).entries if e.required}
    assert required == {"title", "version"}
    # OAS 3.1 made `responses` optional, so the CST gives it a default.
    assert not any(e.required for e in plan_for(Operation).entries)
