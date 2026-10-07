"""Concrete Syntax Tree for OpenAPI 3.1 and 3.2.

Covers
[OAS 3.1](https://spec.openapis.org/oas/v3.1.0)
and
[OAS 3.2](https://spec.openapis.org/oas/v3.2.0).

OpenAPI 3.1 is compliant with JSON Schema 2020-12,
so every `schema` field is a [JsonSchema][].

One set of classes covers both versions.
A field the two versions disagree on carries:

- `since` — the first version defining it
- `until` — the last one still defining it

A document declaring a version outside that range may not use the key.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum, auto

from schema_to.core import JsonValue
from schema_to.cst.base import SYNTHETIC, CstNode, SourceRef
from schema_to.cst.json_schema import JsonSchema

__all__ = [
    "ApiKeyLocation",
    "Callback",
    "Components",
    "Contact",
    "Encoding",
    "Example",
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
    "Reference",
    "RequestBody",
    "Response",
    "SecurityRequirement",
    "SecurityScheme",
    "SecuritySchemeType",
    "Server",
    "ServerVariable",
    "Tag",
    "concrete",
    "concrete_list",
    "concrete_map",
]


# ---------------------------------------------------------------------------
# Primitive enumerations
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Supporting objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Contact(CstNode):
    """[Contact Object](https://spec.openapis.org/oas/v3.1.0#contact-object)."""

    name: str | None = None
    url: str | None = None
    email: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class License(CstNode):
    """[License Object](https://spec.openapis.org/oas/v3.1.0#license-object)."""

    name: str
    identifier: str | None = None
    url: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


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
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class ServerVariable(CstNode):
    """[Server Variable Object](https://spec.openapis.org/oas/v3.1.0#server-variable-object)."""

    default: str
    enum: Sequence[str] | None = None
    description: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class Server(CstNode):
    """[Server Object](https://spec.openapis.org/oas/v3.1.0#server-object)."""

    url: str
    name: str | None = field(default=None, metadata={"since": "3.2"})
    description: str | None = None
    variables: Mapping[str, ServerVariable] = field(default_factory=dict)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class ExternalDocumentation(CstNode):
    """[External Documentation Object](https://spec.openapis.org/oas/v3.1.0#external-documentation-object)."""

    url: str
    description: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class Tag(CstNode):
    """[Tag Object](https://spec.openapis.org/oas/v3.1.0#tag-object)."""

    name: str
    description: str | None = None
    external_docs: ExternalDocumentation | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class Reference(CstNode):
    """[Reference Object](https://spec.openapis.org/oas/v3.1.0#reference-object).

    OpenAPI allows a `$ref` wherever a
    Parameter, Response, Header, Request Body, Link, Example, Security Scheme, or Path Item
    is expected, so those positions are typed `Reference | …`.
    The reference alternative is declared first,
    so it is recognised by its `$ref` before the more permissive object shape is tried.

    Like `$ref` inside a schema, the target is **not** resolved here:
    Parsing keeps the URI as written, and `resolve.openapi.OpenApiRefResolver` inlines it.
    """

    ref: str = field(metadata={"key": "$ref"})
    summary: str | None = None
    description: str | None = None
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


def concrete[N: CstNode](value: Reference | N) -> N | None:
    """Return `value`, or `None` if it is a `Reference` no stage has inlined yet."""
    return None if isinstance(value, Reference) else value


def concrete_list[N: CstNode](values: Iterable[Reference | N]) -> Sequence[N]:
    """Drop the entries of `values` that are still unresolved references."""
    return [value for value in values if not isinstance(value, Reference)]


def concrete_map[N: CstNode](values: Mapping[str, Reference | N]) -> Mapping[str, N]:
    """Drop the entries of `values` that are still unresolved references."""
    return {name: value for name, value in values.items() if not isinstance(value, Reference)}


@dataclass(frozen=True, slots=True)
class Example(CstNode):
    """[Example Object](https://spec.openapis.org/oas/v3.1.0#example-object)."""

    summary: str | None = None
    description: str | None = None
    value: JsonValue | None = None
    external_value: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


# ---------------------------------------------------------------------------
# Parameter, Header, Encoding, and MediaType
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Header(CstNode):
    """[Header Object](https://spec.openapis.org/oas/v3.1.0#header-object)."""

    schema: JsonSchema | None = None
    content: Mapping[str, MediaTypeObject] = field(default_factory=dict)
    description: str | None = None
    required: bool = False
    deprecated: bool = False
    style: str | None = None
    explode: bool | None = None
    example: JsonValue | None = None
    examples: Mapping[str, Reference | Example] = field(default_factory=dict)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class Encoding(CstNode):
    """[Encoding Object](https://spec.openapis.org/oas/v3.1.0#encoding-object)."""

    content_type: str | None = None
    headers: Mapping[str, Reference | Header] = field(default_factory=dict)
    style: str | None = None
    explode: bool = False
    allow_reserved: bool = False
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class MediaTypeObject(CstNode):
    """[Media Type Object](https://spec.openapis.org/oas/v3.1.0#media-type-object)."""

    schema: JsonSchema | None = None
    item_schema: JsonSchema | None = field(default=None, metadata={"since": "3.2"})
    example: JsonValue | None = None
    examples: Mapping[str, Reference | Example] = field(default_factory=dict)
    encoding: Mapping[str, Encoding] = field(default_factory=dict)
    prefix_encoding: Sequence[Encoding] = field(default_factory=list, metadata={"since": "3.2"})
    item_encoding: Encoding | None = field(default=None, metadata={"since": "3.2"})
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


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
    allow_reserved: bool = False
    example: JsonValue | None = None
    examples: Mapping[str, Reference | Example] = field(default_factory=dict)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class RequestBody(CstNode):
    """[Request Body Object](https://spec.openapis.org/oas/v3.1.0#request-body-object)."""

    content: Mapping[str, MediaTypeObject]
    description: str | None = None
    required: bool = False
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class Response(CstNode):
    """[Response Object](https://spec.openapis.org/oas/v3.1.0#response-object)."""

    description: str
    summary: str | None = field(default=None, metadata={"since": "3.2"})
    headers: Mapping[str, Reference | Header] = field(default_factory=dict)
    content: Mapping[str, MediaTypeObject] = field(default_factory=dict)
    links: Mapping[str, Reference | Link] = field(default_factory=dict)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class Link(CstNode):
    """[Link Object](https://spec.openapis.org/oas/v3.1.0#link-object)."""

    operation_ref: str | None = None
    operation_id: str | None = None
    parameters: Mapping[str, JsonValue] = field(default_factory=dict)
    request_body: JsonValue | None = None
    description: str | None = None
    server: Server | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


# ---------------------------------------------------------------------------
# Operations and paths
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Operation(CstNode):
    """[Operation Object](https://spec.openapis.org/oas/v3.1.0#operation-object)."""

    responses: Mapping[str, Reference | Response] = field(default_factory=dict)
    tags: Sequence[str] = field(default_factory=list)
    summary: str | None = None
    description: str | None = None
    external_docs: ExternalDocumentation | None = None
    operation_id: str | None = None
    parameters: Sequence[Reference | Parameter] = field(default_factory=list)
    request_body: Reference | RequestBody | None = None
    callbacks: Mapping[str, Reference | Callback] = field(default_factory=dict)
    deprecated: bool = False
    security: Sequence[SecurityRequirement] | None = None
    servers: Sequence[Server] = field(default_factory=list)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


type SecurityRequirement = Mapping[str, Sequence[str]]

# A [Callback Object](https://spec.openapis.org/oas/v3.1.0#callback-object): a map from a
# runtime expression to the Path Item Object describing the request made to it.  It defines
# no fixed fields of its own, so it is a bare map rather than a CST node.
type Callback = Mapping[str, PathItem]


@dataclass(frozen=True, slots=True)
class PathItem(CstNode):
    """[Path Item Object](https://spec.openapis.org/oas/v3.1.0#path-item-object).

    `$ref` is a field here rather than a `Reference` standing in for the whole object:
    It sits alongside the other fields,
    and the specification leaves the result undefined when both are given.
    """

    ref: str | None = field(default=None, metadata={"key": "$ref"})
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
    query: Operation | None = field(default=None, metadata={"since": "3.2"})
    additional_operations: Mapping[str, Operation] = field(
        default_factory=dict, metadata={"since": "3.2"}
    )
    parameters: Sequence[Reference | Parameter] = field(default_factory=list)
    servers: Sequence[Server] = field(default_factory=list)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


# ---------------------------------------------------------------------------
# Security schemes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OAuthFlow(CstNode):
    """A single [OAuth Flow Object](https://spec.openapis.org/oas/v3.1.0#oauth-flow-object)."""

    scopes: Mapping[str, str]
    authorization_url: str | None = None
    token_url: str | None = None
    refresh_url: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class OAuthFlows(CstNode):
    """[OAuth Flows Object](https://spec.openapis.org/oas/v3.1.0#oauth-flows-object)."""

    implicit: OAuthFlow | None = None
    password: OAuthFlow | None = None
    client_credentials: OAuthFlow | None = None
    authorization_code: OAuthFlow | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


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
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)


# ---------------------------------------------------------------------------
# Components and document root
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Components(CstNode):
    """[Components Object](https://spec.openapis.org/oas/v3.1.0#components-object)."""

    schemas: Mapping[str, JsonSchema] = field(default_factory=dict)
    responses: Mapping[str, Reference | Response] = field(default_factory=dict)
    parameters: Mapping[str, Reference | Parameter] = field(default_factory=dict)
    examples: Mapping[str, Reference | Example] = field(default_factory=dict)
    request_bodies: Mapping[str, Reference | RequestBody] = field(default_factory=dict)
    headers: Mapping[str, Reference | Header] = field(default_factory=dict)
    security_schemes: Mapping[str, Reference | SecurityScheme] = field(default_factory=dict)
    links: Mapping[str, Reference | Link] = field(default_factory=dict)
    callbacks: Mapping[str, Reference | Callback] = field(default_factory=dict)
    path_items: Mapping[str, Reference | PathItem] = field(default_factory=dict)
    media_types: Mapping[str, Reference | MediaTypeObject] = field(
        default_factory=dict, metadata={"since": "3.2"}
    )
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    # `None` only for the empty `Components` of a document that has none:
    # that was never written, so there is nowhere in the file for it to point.
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class OpenApiDocument(CstNode):
    """The root of a parsed OpenAPI 3.1 document.

    Special attributes:
      - source_id: Matches `RawDoc.uri`.
      - display_name: Short name for the document, carried over from the `RawDoc`.
        It is what a re-emitted file is named after.
      - source_ref: Points to the document root (`""`).
    """

    openapi: str
    info: Info
    self_: str | None = field(default=None, metadata={"key": "$self", "since": "3.2"})
    json_schema_dialect: str | None = None
    paths: Mapping[str, PathItem] = field(default_factory=dict)
    components: Components = field(default_factory=Components)
    servers: Sequence[Server] = field(default_factory=list)
    security: Sequence[SecurityRequirement] = field(default_factory=list)
    tags: Sequence[Tag] = field(default_factory=list)
    external_docs: ExternalDocumentation | None = None
    webhooks: Mapping[str, Reference | PathItem] = field(default_factory=dict)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_id: str = field(kw_only=True, metadata=SYNTHETIC)
    display_name: str = field(kw_only=True, metadata=SYNTHETIC)
    source_ref: SourceRef = field(kw_only=True, metadata=SYNTHETIC)
