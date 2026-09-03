"""Strategies for OpenAPI 3.1 documents."""

from hypothesis import strategies as st
from tests.strategies._primitives import identifier, media_type_str, nonempty_text, safe_text
from tests.strategies.json_schema import json_schema_st

from schema_to.core import JsonObject

_PARAM_LOCATIONS = ["query", "header", "path", "cookie"]

# OpenAPI 3.1 allows exact codes (100-599), wildcard patterns (1xx-5xx),
# and "default".
_STATUS_CODES = (
    [str(c) for c in range(100, 600, 100)]
    + ["200", "201", "400", "404", "500"]
    + [f"{d}xx" for d in range(1, 6)]
    + ["default"]
)


@st.composite
def _response_st(draw: st.DrawFn) -> JsonObject:
    d: JsonObject = {"description": draw(safe_text)}
    if draw(st.booleans()):
        media_types = draw(st.lists(media_type_str, min_size=1, max_size=2, unique=True))
        d["content"] = {
            mt: (
                {"schema": draw(json_schema_st())}
                if draw(st.booleans()) and "/" in mt and mt.split("/")[0] in {"application", "text"}
                else {}
            )
            for mt in media_types
        }
    return d


@st.composite
def _parameter_st(draw: st.DrawFn) -> JsonObject:
    return {"name": draw(identifier), "in": draw(st.sampled_from(_PARAM_LOCATIONS))}


@st.composite
def _operation_st(draw: st.DrawFn) -> JsonObject:
    status = draw(st.sampled_from(_STATUS_CODES))
    d: JsonObject = {"responses": {status: draw(_response_st())}}
    if draw(st.booleans()):
        d["summary"] = draw(safe_text)
    if draw(st.booleans()):
        d["description"] = draw(safe_text)
    if draw(st.booleans()):
        d["operationId"] = draw(identifier)
    if draw(st.booleans()):
        d["deprecated"] = draw(st.booleans())
    if draw(st.booleans()):
        d["tags"] = draw(st.lists(identifier, min_size=1, max_size=3, unique=True))
    if draw(st.booleans()):
        d["parameters"] = [draw(_parameter_st())]
    return d


@st.composite
def _path_item_st(draw: st.DrawFn) -> JsonObject:
    method = draw(st.sampled_from(["get", "post", "put", "delete", "patch"]))
    d: JsonObject = {method: draw(_operation_st())}
    if draw(st.booleans()):
        d["summary"] = draw(safe_text)
    if draw(st.booleans()):
        d["description"] = draw(safe_text)
    if draw(st.booleans()):
        d["parameters"] = [draw(_parameter_st())]
    return d


@st.composite
def openapi_doc_st(draw: st.DrawFn) -> JsonObject:
    """Generate a minimal but valid OpenAPI 3.1 document dict."""
    d: JsonObject = {
        "openapi": "3.1.0",
        "info": {"title": draw(nonempty_text), "version": draw(nonempty_text)},
    }

    # Optional paths (empty paths: {} is valid)
    if draw(st.booleans()):
        path_names = draw(
            st.lists(st.builds(lambda s: f"/{s}", identifier), min_size=0, max_size=3, unique=True)
        )
        d["paths"] = {path: draw(_path_item_st()) for path in path_names}

    # Optional components/schemas
    if draw(st.booleans()):
        schema_names = draw(st.lists(identifier, min_size=1, max_size=4, unique=True))
        d["components"] = {"schemas": {name: draw(json_schema_st()) for name in schema_names}}

    # Optional servers
    if draw(st.booleans()):
        d["servers"] = [{"url": "https://api.example.com"}]

    return d
