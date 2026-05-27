"""Serialize OpenAPI 3.1 CST nodes back to JSON-compatible values."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from schema_to.serialize.json_schema import JsonSchemaSerializer

if TYPE_CHECKING:
    from schema_to.core import JsonObject
    from schema_to.cst.openapi import (
        Components,
        Contact,
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
        RequestBody,
        Response,
        SecurityScheme,
        Server,
        ServerVariable,
        Tag,
    )

__all__ = ["OpenApiSerializer"]

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


def _set(out: JsonObject, key: str, value: object) -> None:
    if value is not None:
        out[key] = value  # type: ignore[assignment]


@dataclass(frozen=True)
class OpenApiSerializer:
    """Convert an `OpenApiDocument` CST node to a JSON-serializable `JsonObject`.

    Attributes:
        js: The JSON Schema serializer used for embedded schema fields.
    """

    js: JsonSchemaSerializer = field(default_factory=JsonSchemaSerializer)

    def serialize(self, doc: OpenApiDocument) -> JsonObject:
        out: JsonObject = {"openapi": doc.openapi, "info": self._info(doc.info)}
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

    def _info(self, info: Info) -> JsonObject:
        out: JsonObject = {"title": info.title, "version": info.version}
        _set(out, "summary", info.summary)
        _set(out, "description", info.description)
        _set(out, "termsOfService", info.terms_of_service)
        if info.contact is not None:
            out["contact"] = self._contact(info.contact)
        if info.license_ is not None:
            out["license"] = self._license(info.license_)
        out.update(info.extensions)
        return out

    def _contact(self, c: Contact) -> JsonObject:
        out: JsonObject = {}
        _set(out, "name", c.name)
        _set(out, "url", c.url)
        _set(out, "email", c.email)
        out.update(c.extensions)
        return out

    def _license(self, lic: License) -> JsonObject:
        out: JsonObject = {"name": lic.name}
        _set(out, "identifier", lic.identifier)
        _set(out, "url", lic.url)
        out.update(lic.extensions)
        return out

    def _server(self, s: Server) -> JsonObject:
        out: JsonObject = {"url": s.url}
        _set(out, "description", s.description)
        if s.variables:
            out["variables"] = {k: self._server_variable(v) for k, v in s.variables.items()}
        out.update(s.extensions)
        return out

    def _server_variable(self, v: ServerVariable) -> JsonObject:
        out: JsonObject = {"default": v.default}
        if v.enum is not None:
            out["enum"] = list(v.enum)
        _set(out, "description", v.description)
        out.update(v.extensions)
        return out

    def _tag(self, t: Tag) -> JsonObject:
        out: JsonObject = {"name": t.name}
        _set(out, "description", t.description)
        if t.external_docs is not None:
            out["externalDocs"] = self._external_docs(t.external_docs)
        out.update(t.extensions)
        return out

    def _external_docs(self, e: ExternalDocumentation) -> JsonObject:
        out: JsonObject = {"url": e.url}
        _set(out, "description", e.description)
        out.update(e.extensions)
        return out

    def _path_item(self, pi: PathItem) -> JsonObject:
        out: JsonObject = {}
        _set(out, "summary", pi.summary)
        _set(out, "description", pi.description)
        for method in _HTTP_METHODS:
            op = getattr(pi, method)
            if op is not None:
                out[method] = self._operation(op)
        if pi.parameters:
            out["parameters"] = [self._parameter(p) for p in pi.parameters]
        if pi.servers:
            out["servers"] = [self._server(s) for s in pi.servers]
        out.update(pi.extensions)
        return out

    def _operation(self, op: Operation) -> JsonObject:
        out: JsonObject = {"responses": {k: self._response(v) for k, v in op.responses.items()}}
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

    def _parameter(self, p: Parameter) -> JsonObject:
        out: JsonObject = {"name": p.name, "in": p.in_.value}
        if p.schema is not None:
            out["schema"] = self.js.serialize(p.schema)
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

    def _request_body(self, rb: RequestBody) -> JsonObject:
        out: JsonObject = {"content": {k: self._media_type_obj(v) for k, v in rb.content.items()}}
        _set(out, "description", rb.description)
        if rb.required:
            out["required"] = True
        out.update(rb.extensions)
        return out

    def _response(self, r: Response) -> JsonObject:
        out: JsonObject = {"description": r.description}
        if r.headers:
            out["headers"] = {k: self._header(v) for k, v in r.headers.items()}
        if r.content:
            out["content"] = {k: self._media_type_obj(v) for k, v in r.content.items()}
        if r.links:
            out["links"] = {k: self._link(v) for k, v in r.links.items()}
        out.update(r.extensions)
        return out

    def _header(self, h: Header) -> JsonObject:
        out: JsonObject = {}
        if h.schema is not None:
            out["schema"] = self.js.serialize(h.schema)
        _set(out, "description", h.description)
        if h.required:
            out["required"] = True
        if h.deprecated:
            out["deprecated"] = True
        out.update(h.extensions)
        return out

    def _media_type_obj(self, mt: MediaTypeObject) -> JsonObject:
        out: JsonObject = {}
        if mt.schema is not None:
            out["schema"] = self.js.serialize(mt.schema)
        if mt.example is not None:
            out["example"] = mt.example
        if mt.examples:
            out["examples"] = dict(mt.examples)
        out.update(mt.extensions)
        return out

    def _link(self, lnk: Link) -> JsonObject:
        out: JsonObject = {}
        _set(out, "operationRef", lnk.operation_ref)
        _set(out, "operationId", lnk.operation_id)
        if lnk.parameters:
            out["parameters"] = dict(lnk.parameters)
        if lnk.request_body is not None:
            out["requestBody"] = lnk.request_body
        _set(out, "description", lnk.description)
        if lnk.server is not None:
            out["server"] = self._server(lnk.server)
        out.update(lnk.extensions)
        return out

    def _components(self, comp: Components) -> JsonObject:
        out: JsonObject = {}
        if comp.schemas:
            out["schemas"] = {k: self.js.serialize(v) for k, v in comp.schemas.items()}
        if comp.responses:
            out["responses"] = {k: self._response(v) for k, v in comp.responses.items()}
        if comp.parameters:
            out["parameters"] = {k: self._parameter(v) for k, v in comp.parameters.items()}
        if comp.request_bodies:
            out["requestBodies"] = {
                k: self._request_body(v) for k, v in comp.request_bodies.items()
            }
        if comp.headers:
            out["headers"] = {k: self._header(v) for k, v in comp.headers.items()}
        if comp.security_schemes:
            out["securitySchemes"] = {
                k: self._security_scheme(v) for k, v in comp.security_schemes.items()
            }
        if comp.links:
            out["links"] = {k: self._link(v) for k, v in comp.links.items()}
        out.update(comp.extensions)
        return out

    def _security_scheme(self, ss: SecurityScheme) -> JsonObject:
        out: JsonObject = {"type": ss.type_.value}
        _set(out, "description", ss.description)
        _set(out, "name", ss.name)
        if ss.in_ is not None:
            out["in"] = ss.in_.value
        _set(out, "scheme", ss.scheme)
        _set(out, "bearerFormat", ss.bearer_format)
        if ss.flows is not None:
            out["flows"] = self._oauth_flows(ss.flows)
        _set(out, "openIdConnectUrl", ss.open_id_connect_url)
        out.update(ss.extensions)
        return out

    def _oauth_flows(self, flows: OAuthFlows) -> JsonObject:
        out: JsonObject = {}
        if flows.implicit is not None:
            out["implicit"] = self._oauth_flow(flows.implicit)
        if flows.password is not None:
            out["password"] = self._oauth_flow(flows.password)
        if flows.client_credentials is not None:
            out["clientCredentials"] = self._oauth_flow(flows.client_credentials)
        if flows.authorization_code is not None:
            out["authorizationCode"] = self._oauth_flow(flows.authorization_code)
        out.update(flows.extensions)
        return out

    def _oauth_flow(self, flow: OAuthFlow) -> JsonObject:
        out: JsonObject = {"scopes": dict(flow.scopes)}
        _set(out, "authorizationUrl", flow.authorization_url)
        _set(out, "tokenUrl", flow.token_url)
        _set(out, "refreshUrl", flow.refresh_url)
        out.update(flow.extensions)
        return out
