"""Concrete Syntax Tree for [OpenAPI 3.1](https://spec.openapis.org/oas/v3.1.0).

OpenAPI 3.1 is complaint with JSON Schema 2020-12.
Every `schema` field in this module is typed as [JsonSchema][].

The hierarchy follows the object model of the
[OAS 3.1 spec](https://spec.openapis.org/oas/v3.1.0#schema).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import TYPE_CHECKING

from schema_to.cst.base import CstNode, SourceRef

if TYPE_CHECKING:
    from schema_to.core import JsonValue
    from schema_to.cst.json_schema import JsonSchema

__all__ = [
    "ApiKeyLocation",
    "Components",
    "Contact",
    "Encoding",
    "ExternalDocumentation",
    "Header",
    "HttpMethod",
    "Info",
    "License",
    "Link",
    "MediaTypeObject",
    "OAuthFlow",
    "OAuthFlows",
    "OpenApiDocument",
    "Operation",
    "Parameter",
    "ParameterLocation",
    "PathItem",
    "RequestBody",
    "Response",
    "SecurityRequirement",
    "SecurityScheme",
    "SecuritySchemeType",
    "Server",
    "ServerVariable",
    "Tag",
]


class HttpMethod(StrEnum):
    """HTTP methods as used in OpenAPI path items."""

    GET = auto()
    PUT = auto()
    POST = auto()
    DELETE = auto()
    OPTIONS = auto()
    HEAD = auto()
    PATCH = auto()
    TRACE = auto()


class ParameterLocation(StrEnum):
    """The `in` field of an OpenAPI Parameter Object."""

    QUERY = auto()
    HEADER = auto()
    PATH = auto()
    COOKIE = auto()


class SecuritySchemeType(StrEnum):
    """The `type` field of a Security Scheme Object."""

    API_KEY = "apiKey"
    HTTP = "http"
    MUTUAL_TLS = "mutualTLS"
    OAUTH2 = "oauth2"
    OPEN_ID_CONNECT = "openIdConnect"


class ApiKeyLocation(StrEnum):
    """The `in` field of an `apiKey` Security Scheme."""

    QUERY = auto()
    HEADER = auto()
    COOKIE = auto()


@dataclass(frozen=True, slots=True)
class Contact(CstNode):
    """[Contact Object](https://spec.openapis.org/oas/v3.1.0#contact-object)."""

    name: str | None = None
    url: str | None = None
    email: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class License(CstNode):
    """[License Object](https://spec.openapis.org/oas/v3.1.0#license-object)."""

    name: str
    identifier: str | None = None
    url: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class Info(CstNode):
    """[Info Object](https://spec.openapis.org/oas/v3.1.0#info-object)."""

    title: str
    version: str
    summary: str | None = None
    description: str | None = None
    terms_of_service: str | None = None
    contact: Contact | None = None
    license_: License | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class ServerVariable(CstNode):
    """[Server Variable Object](https://spec.openapis.org/oas/v3.1.0#server-variable-object)."""

    default: str
    enum: Sequence[str] | None = None
    description: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class Server(CstNode):
    """[Server Object](https://spec.openapis.org/oas/v3.1.0#server-object)."""

    url: str
    description: str | None = None
    variables: Mapping[str, ServerVariable] = field(default_factory=dict)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class ExternalDocumentation(CstNode):
    """[External Documentation Object](https://spec.openapis.org/oas/v3.1.0#external-documentation-object)."""

    url: str
    description: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class Tag(CstNode):
    """[Tag Object](https://spec.openapis.org/oas/v3.1.0#tag-object)."""

    name: str
    description: str | None = None
    external_docs: ExternalDocumentation | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class Header(CstNode):
    """[Header Object](https://spec.openapis.org/oas/v3.1.0#header-object)."""

    schema: JsonSchema | None = None
    content: Mapping[str, MediaTypeObject] = field(default_factory=dict)
    description: str | None = None
    required: bool = False
    deprecated: bool = False
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class Encoding(CstNode):
    """[Encoding Object](https://spec.openapis.org/oas/v3.1.0#encoding-object)."""

    content_type: str | None = None
    headers: Mapping[str, Header] = field(default_factory=dict)
    style: str | None = None
    explode: bool = False
    allow_reserved: bool = False
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class MediaTypeObject(CstNode):
    """[Media Type Object](https://spec.openapis.org/oas/v3.1.0#media-type-object)."""

    schema: JsonSchema | None = None
    example: JsonValue | None = None
    examples: Mapping[str, JsonValue] = field(default_factory=dict)
    encoding: Mapping[str, Encoding] = field(default_factory=dict)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class Parameter(CstNode):
    """[Parameter Object](https://spec.openapis.org/oas/v3.1.0#parameter-object)."""

    name: str
    in_: ParameterLocation
    schema: JsonSchema | None = None
    content: Mapping[str, MediaTypeObject] = field(default_factory=dict)
    description: str | None = None
    required: bool = False
    deprecated: bool = False
    allow_empty_value: bool = False
    style: str | None = None
    explode: bool | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class RequestBody(CstNode):
    """[Request Body Object](https://spec.openapis.org/oas/v3.1.0#request-body-object)."""

    content: Mapping[str, MediaTypeObject]
    description: str | None = None
    required: bool = False
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class Response(CstNode):
    """[Response Object](https://spec.openapis.org/oas/v3.1.0#response-object)."""

    description: str
    headers: Mapping[str, Header] = field(default_factory=dict)
    content: Mapping[str, MediaTypeObject] = field(default_factory=dict)
    links: Mapping[str, Link] = field(default_factory=dict)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class Link(CstNode):
    """[Link Object](https://spec.openapis.org/oas/v3.1.0#link-object)."""

    operation_ref: str | None = None
    operation_id: str | None = None
    parameters: Mapping[str, JsonValue] = field(default_factory=dict)
    request_body: JsonValue | None = None
    description: str | None = None
    server: Server | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class Operation(CstNode):
    """[Operation Object](https://spec.openapis.org/oas/v3.1.0#operation-object)."""

    responses: Mapping[str, Response]
    tags: Sequence[str] = field(default_factory=list)
    summary: str | None = None
    description: str | None = None
    external_docs: ExternalDocumentation | None = None
    operation_id: str | None = None
    parameters: Sequence[Parameter] = field(default_factory=list)
    request_body: RequestBody | None = None
    deprecated: bool = False
    security: Sequence[SecurityRequirement] | None = None
    servers: Sequence[Server] = field(default_factory=list)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


type SecurityRequirement = Mapping[str, Sequence[str]]


@dataclass(frozen=True, slots=True)
class PathItem(CstNode):
    """[Path Item Object](https://spec.openapis.org/oas/v3.1.0#path-item-object)."""

    summary: str | None = None
    description: str | None = None
    get: Operation | None = None
    put: Operation | None = None
    post: Operation | None = None
    delete: Operation | None = None
    options: Operation | None = None
    head: Operation | None = None
    patch: Operation | None = None
    trace: Operation | None = None
    parameters: Sequence[Parameter] = field(default_factory=list)
    servers: Sequence[Server] = field(default_factory=list)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class OAuthFlow(CstNode):
    """A single [OAuth Flow Object](https://spec.openapis.org/oas/v3.1.0#oauth-flow-object)."""

    scopes: Mapping[str, str]
    authorization_url: str | None = None
    token_url: str | None = None
    refresh_url: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class OAuthFlows(CstNode):
    """[OAuth Flows Object](https://spec.openapis.org/oas/v3.1.0#oauth-flows-object).

    Attributes:
        implicit: Configuration for the Implicit flow.
        password: Configuration for the Resource Owner Password flow.
        client_credentials: Configuration for the Client Credentials flow.
        authorization_code: Configuration for the Authorization Code flow.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    implicit: OAuthFlow | None = None
    password: OAuthFlow | None = None
    client_credentials: OAuthFlow | None = None
    authorization_code: OAuthFlow | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class SecurityScheme(CstNode):
    """[Security Scheme Object](https://spec.openapis.org/oas/v3.1.0#security-scheme-object)."""

    type_: SecuritySchemeType
    description: str | None = None
    name: str | None = None
    in_: ApiKeyLocation | None = None
    scheme: str | None = None
    bearer_format: str | None = None
    flows: OAuthFlows | None = None
    open_id_connect_url: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class Components(CstNode):
    """[Components Object](https://spec.openapis.org/oas/v3.1.0#components-object).

    A registry of reusable objects referenced via `$ref` elsewhere in the document.
    """

    schemas: Mapping[str, JsonSchema] = field(default_factory=dict)
    responses: Mapping[str, Response] = field(default_factory=dict)
    parameters: Mapping[str, Parameter] = field(default_factory=dict)
    request_bodies: Mapping[str, RequestBody] = field(default_factory=dict)
    headers: Mapping[str, Header] = field(default_factory=dict)
    security_schemes: Mapping[str, SecurityScheme] = field(default_factory=dict)
    links: Mapping[str, Link] = field(default_factory=dict)
    path_items: Mapping[str, PathItem] = field(default_factory=dict)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class OpenApiDocument(CstNode):
    """The root of a parsed OpenAPI 3.1 document."""

    openapi: str
    info: Info
    paths: Mapping[str, PathItem] = field(default_factory=dict)
    components: Components = field(default_factory=Components)
    servers: Sequence[Server] = field(default_factory=list)
    security: Sequence[SecurityRequirement] = field(default_factory=list)
    tags: Sequence[Tag] = field(default_factory=list)
    external_docs: ExternalDocumentation | None = None
    webhooks: Mapping[str, PathItem] = field(default_factory=dict)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict)
    source_id: str | None = None
    source_ref: SourceRef | None = None
