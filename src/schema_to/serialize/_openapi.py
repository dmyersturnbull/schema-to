"""Serialize OpenAPI 3.1 CST nodes back to JSON-compatible values."""

from __future__ import annotations

from schema_to.cst._base import JsonValue
from schema_to.cst._openapi import (
    Components,
    Contact,
    ExternalDocumentation,
    Header,
    Info,
    License,
    MediaTypeObject,
    OpenApiDocument,
    Operation,
    Parameter,
    PathItem,
    RequestBody,
    Response,
    Server,
    ServerVariable,
    Tag,
)
from schema_to.serialize._json_schema import JsonSchemaSerializer, _set

__all__ = ["OpenApiSerializer"]


class OpenApiSerializer:
    """Convert an `OpenApiDocument` CST node to a JSON-serializable dict."""

    def __init__(self) -> None:
        self._js = JsonSchemaSerializer()

    def serialize(self, doc: OpenApiDocument) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {
            "openapi": doc.openapi,
            "info": self._info(doc.info),
        }
        if doc.paths:
            out["paths"] = {p: self._path_item(pi) for p, pi in doc.paths.items()}
        comp = self._components(doc.components)
        if comp:
            out["components"] = comp
        if doc.servers:
            out["servers"] = [self._server(s) for s in doc.servers]
        if doc.security:
            out["security"] = [dict(req) for req in doc.security]
        if doc.tags:
            out["tags"] = [self._tag(t) for t in doc.tags]
        if doc.external_docs is not None:
            out["externalDocs"] = self._external_docs(doc.external_docs)
        if doc.webhooks:
            out["webhooks"] = {n: self._path_item(pi) for n, pi in doc.webhooks.items()}
        out.update(doc.extensions)
        return out

    def _info(self, info: Info) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {"title": info.title, "version": info.version}
        _set(out, "summary", info.summary)
        _set(out, "description", info.description)
        _set(out, "termsOfService", info.terms_of_service)
        if info.contact is not None:
            out["contact"] = self._contact(info.contact)
        if info.license_ is not None:
            out["license"] = self._license(info.license_)
        out.update(info.extensions)
        return out

    def _contact(self, c: Contact) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {}
        _set(out, "name", c.name)
        _set(out, "url", c.url)
        _set(out, "email", c.email)
        out.update(c.extensions)
        return out

    def _license(self, lic: License) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {"name": lic.name}
        _set(out, "identifier", lic.identifier)
        _set(out, "url", lic.url)
        out.update(lic.extensions)
        return out

    def _server(self, s: Server) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {"url": s.url}
        _set(out, "description", s.description)
        if s.variables:
            out["variables"] = {k: self._server_variable(v) for k, v in s.variables.items()}
        out.update(s.extensions)
        return out

    def _server_variable(self, v: ServerVariable) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {"default": v.default}
        if v.enum is not None:
            out["enum"] = list(v.enum)
        _set(out, "description", v.description)
        out.update(v.extensions)
        return out

    def _tag(self, t: Tag) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {"name": t.name}
        _set(out, "description", t.description)
        if t.external_docs is not None:
            out["externalDocs"] = self._external_docs(t.external_docs)
        out.update(t.extensions)
        return out

    def _external_docs(self, e: ExternalDocumentation) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {"url": e.url}
        _set(out, "description", e.description)
        out.update(e.extensions)
        return out

    def _path_item(self, pi: PathItem) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {}
        _set(out, "summary", pi.summary)
        _set(out, "description", pi.description)
        for method, op in pi.operations.items():
            out[method.value] = self._operation(op)
        if pi.parameters:
            out["parameters"] = [self._parameter(p) for p in pi.parameters]
        if pi.servers:
            out["servers"] = [self._server(s) for s in pi.servers]
        out.update(pi.extensions)
        return out

    def _operation(self, op: Operation) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {
            "responses": {k: self._response(v) for k, v in op.responses.items()},
        }
        if op.tags:
            out["tags"] = list(op.tags)
        _set(out, "summary", op.summary)
        _set(out, "description", op.description)
        if op.external_docs is not None:
            out["externalDocs"] = self._external_docs(op.external_docs)
        _set(out, "operationId", op.operation_id)
        if op.parameters:
            out["parameters"] = [self._parameter(p) for p in op.parameters]
        if op.request_body is not None:
            out["requestBody"] = self._request_body(op.request_body)
        if op.deprecated:
            out["deprecated"] = True
        if op.security is not None:
            out["security"] = [dict(req) for req in op.security]
        if op.servers:
            out["servers"] = [self._server(s) for s in op.servers]
        out.update(op.extensions)
        return out

    def _parameter(self, p: Parameter) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {"name": p.name, "in": p.in_.value}
        if p.schema is not None:
            out["schema"] = self._js.serialize(p.schema)
        _set(out, "description", p.description)
        if p.required:
            out["required"] = True
        if p.deprecated:
            out["deprecated"] = True
        if p.allow_empty_value:
            out["allowEmptyValue"] = True
        _set(out, "style", p.style)
        if p.explode is not None:
            out["explode"] = p.explode
        out.update(p.extensions)
        return out

    def _request_body(self, rb: RequestBody) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {
            "content": {k: self._media_type_obj(v) for k, v in rb.content.items()},
        }
        _set(out, "description", rb.description)
        if rb.required:
            out["required"] = True
        out.update(rb.extensions)
        return out

    def _response(self, r: Response) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {"description": r.description}
        if r.headers:
            out["headers"] = {k: self._header(v) for k, v in r.headers.items()}
        if r.content:
            out["content"] = {k: self._media_type_obj(v) for k, v in r.content.items()}
        out.update(r.extensions)
        return out

    def _header(self, h: Header) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {}
        if h.schema is not None:
            out["schema"] = self._js.serialize(h.schema)
        _set(out, "description", h.description)
        if h.required:
            out["required"] = True
        if h.deprecated:
            out["deprecated"] = True
        out.update(h.extensions)
        return out

    def _media_type_obj(self, mt: MediaTypeObject) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {}
        if mt.schema is not None:
            out["schema"] = self._js.serialize(mt.schema)
        if mt.example is not None:
            out["example"] = mt.example
        if mt.examples:
            out["examples"] = dict(mt.examples)
        out.update(mt.extensions)
        return out

    def _components(self, comp: Components) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {}
        if comp.schemas:
            out["schemas"] = {k: self._js.serialize(v) for k, v in comp.schemas.items()}
        if comp.responses:
            out["responses"] = {k: self._response(v) for k, v in comp.responses.items()}
        if comp.parameters:
            out["parameters"] = {k: self._parameter(v) for k, v in comp.parameters.items()}
        if comp.request_bodies:
            out["requestBodies"] = {k: self._request_body(v) for k, v in comp.request_bodies.items()}
        if comp.headers:
            out["headers"] = {k: self._header(v) for k, v in comp.headers.items()}
        out.update(comp.extensions)
        return out
