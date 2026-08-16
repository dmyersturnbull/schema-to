"""Concrete Syntax Tree for [OpenAPI 3.1](https://spec.openapis.org/oas/v3.1.0).

OpenAPI 3.1 is compliant with JSON Schema 2020-12.
Every `schema` field in this module is typed as [JsonSchema][].

The hierarchy follows the object model of the
[OAS 3.1 spec](https://spec.openapis.org/oas/v3.1.0#schema).

Each node's field annotations are the whole description of its wire format:
`parse._plan` compiles them into the plan that the parser and the serializer
both run on.  A field's JSON key is its name with one trailing underscore
dropped, lower-camel-cased (`terms_of_service` is `termsOfService`), and a field
is required exactly when it declares no default.  Annotations must therefore
resolve at runtime, which is why the imports below are not deferred.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum, auto

from schema_to.core import JsonValue
from schema_to.cst.base import SYNTHETIC, CstNode, SourceRef
from schema_to.cst.json_schema import JsonSchema

__all__ = [
    "ApiKeyLocation",
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
    """[Contact Object](https://spec.openapis.org/oas/v3.1.0#contact-object).

    Attributes:
        name: The identifying name of the contact person/organisation.
        url: URL pointing to contact information.
        email: Email address of the contact person/organisation.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    name: str | None = None
    url: str | None = None
    email: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class License(CstNode):
    """[License Object](https://spec.openapis.org/oas/v3.1.0#license-object).

    Attributes:
        name: The license name used for the API (required by the spec).
        identifier: An [SPDX](https://spdx.org/licenses/) identifier, e.g. `"MIT"`.
        url: URL to the license text.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    name: str
    identifier: str | None = None
    url: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class Info(CstNode):
    """[Info Object](https://spec.openapis.org/oas/v3.1.0#info-object).

    Attributes:
        title: The title of the API (required).
        version: The version of the OpenAPI document (required).
        summary: Short summary of the API.
        description: Longer description; CommonMark is allowed.
        terms_of_service: URL to the Terms of Service.
        contact: Contact information for the API.
        license_: License information for the API.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    title: str
    version: str
    summary: str | None = None
    description: str | None = None
    terms_of_service: str | None = None
    contact: Contact | None = None
    license_: License | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class ServerVariable(CstNode):
    """[Server Variable Object](https://spec.openapis.org/oas/v3.1.0#server-variable-object).

    Attributes:
        default: The default value to use if no value is provided (required).
        enum: An enumeration of allowable string values.
        description: Optional description; CommonMark allowed.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    default: str
    enum: Sequence[str] | None = None
    description: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class Server(CstNode):
    """[Server Object](https://spec.openapis.org/oas/v3.1.0#server-object).

    Attributes:
        url: URL of the target host, possibly with template variables.
        description: Optional description; CommonMark allowed.
        variables: Map from variable name to `ServerVariable`.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    url: str
    description: str | None = None
    variables: Mapping[str, ServerVariable] = field(default_factory=dict)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class ExternalDocumentation(CstNode):
    """[External Documentation Object](https://spec.openapis.org/oas/v3.1.0#external-documentation-object).

    Attributes:
        url: URL for the target documentation (required).
        description: Short description; CommonMark allowed.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    url: str
    description: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class Tag(CstNode):
    """[Tag Object](https://spec.openapis.org/oas/v3.1.0#tag-object).

    Attributes:
        name: Name of the tag (required).
        description: Short description; CommonMark allowed.
        external_docs: Additional external documentation.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    name: str
    description: str | None = None
    external_docs: ExternalDocumentation | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class Reference(CstNode):
    """[Reference Object](https://spec.openapis.org/oas/v3.1.0#reference-object).

    OpenAPI allows a `$ref` wherever a Parameter, Response, Header, Request Body,
    Link, Example, Security Scheme, or Path Item is expected, so those positions
    are typed `Reference | …`.  The reference alternative is declared first so it
    is recognised by its `$ref` before the more permissive object shape is tried.

    Like `$ref` inside a schema, the target is *not* resolved here: parsing keeps
    the URI as written and a later stage inlines it.

    Attributes:
        ref: The URI reference to the target object.
        summary: Overrides the target's `summary` (OAS 3.1 addition).
        description: Overrides the target's `description` (OAS 3.1 addition).
        source_ref: Origin in the source document.
    """

    ref: str = field(metadata={"key": "$ref"})
    summary: str | None = None
    description: str | None = None
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


def concrete[N: CstNode](value: Reference | N) -> N | None:
    """Return `value`, or `None` if it is a `Reference` no stage has inlined yet."""
    return None if isinstance(value, Reference) else value


def concrete_list[N: CstNode](values: Iterable[Reference | N]) -> list[N]:
    """Drop the entries of `values` that are still unresolved references."""
    return [value for value in values if not isinstance(value, Reference)]


def concrete_map[N: CstNode](values: Mapping[str, Reference | N]) -> dict[str, N]:
    """Drop the entries of `values` that are still unresolved references."""
    return {name: value for name, value in values.items() if not isinstance(value, Reference)}


@dataclass(frozen=True, slots=True)
class Example(CstNode):
    """[Example Object](https://spec.openapis.org/oas/v3.1.0#example-object).

    Attributes:
        summary: Short description of the example.
        description: Long description; CommonMark allowed.
        value: The embedded example value, mutually exclusive with `external_value`.
        external_value: URI of a literal example, mutually exclusive with `value`.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    summary: str | None = None
    description: str | None = None
    value: JsonValue | None = None
    external_value: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


# ---------------------------------------------------------------------------
# Parameter, Header, Encoding, and MediaType
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Header(CstNode):
    """[Header Object](https://spec.openapis.org/oas/v3.1.0#header-object).

    Attributes:
        schema: JSON Schema for the header value.
        content: Per-media-type serialization, mutually exclusive with `schema`.
        description: CommonMark description.
        required: Defaults to `False`.
        deprecated: Marks the header as deprecated.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    schema: JsonSchema | None = None
    content: Mapping[str, MediaTypeObject] = field(default_factory=dict)
    description: str | None = None
    required: bool = False
    deprecated: bool = False
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class Encoding(CstNode):
    """[Encoding Object](https://spec.openapis.org/oas/v3.1.0#encoding-object).

    Attributes:
        content_type: Content-Type for encoding a specific property.
        headers: Additional headers, excluding `Content-Type`.
        style: Serialisation style.
        explode: Whether arrays/objects generate separate parameters.
        allow_reserved: Allow reserved characters without percent-encoding.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    content_type: str | None = None
    headers: Mapping[str, Reference | Header] = field(default_factory=dict)
    style: str | None = None
    explode: bool = False
    allow_reserved: bool = False
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class MediaTypeObject(CstNode):
    """[Media Type Object](https://spec.openapis.org/oas/v3.1.0#media-type-object).

    Attributes:
        schema: JSON Schema describing the media type.
        example: Example value (mutually exclusive with `examples`).
        examples: Named example objects (mutually exclusive with `example`).
        encoding: Per-property encoding hints for `multipart` and `form` bodies.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    schema: JsonSchema | None = None
    example: JsonValue | None = None
    examples: Mapping[str, Reference | Example] = field(default_factory=dict)
    encoding: Mapping[str, Encoding] = field(default_factory=dict)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class Parameter(CstNode):
    """[Parameter Object](https://spec.openapis.org/oas/v3.1.0#parameter-object).

    Attributes:
        name: Parameter name (required).
        in_: Location of the parameter (required).
        schema: JSON Schema for the parameter value.
        content: Per-media-type serialization, mutually exclusive with `schema`.
        description: CommonMark description.
        required: Must be `True` for path parameters.
        deprecated: Marks the parameter as deprecated.
        allow_empty_value: Allows empty-string values (query only).
        style: Serialisation style.
        explode: Whether arrays/objects generate separate parameters.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

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
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class RequestBody(CstNode):
    """[Request Body Object](https://spec.openapis.org/oas/v3.1.0#request-body-object).

    Attributes:
        content: Map from media-type string to `MediaTypeObject` (required).
        description: CommonMark description.
        required: Whether the body is mandatory. Defaults to `False`.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    content: Mapping[str, MediaTypeObject]
    description: str | None = None
    required: bool = False
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class Response(CstNode):
    """[Response Object](https://spec.openapis.org/oas/v3.1.0#response-object).

    Attributes:
        description: Short description of the response (required).
        headers: Map of header name to `Header`.
        content: Map of media-type string to `MediaTypeObject`.
        links: Map of link name to `Link`.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    description: str
    headers: Mapping[str, Reference | Header] = field(default_factory=dict)
    content: Mapping[str, MediaTypeObject] = field(default_factory=dict)
    links: Mapping[str, Reference | Link] = field(default_factory=dict)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class Link(CstNode):
    """[Link Object](https://spec.openapis.org/oas/v3.1.0#link-object).

    Attributes:
        operation_ref: Relative or absolute URI reference to an OAS operation.
        operation_id: The `operationId` of an existing operation.
        parameters: Map from parameter name to its value expression.
        request_body: Value expression for the request body.
        description: CommonMark description.
        server: Target server for this link.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    operation_ref: str | None = None
    operation_id: str | None = None
    parameters: Mapping[str, JsonValue] = field(default_factory=dict)
    request_body: JsonValue | None = None
    description: str | None = None
    server: Server | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


# ---------------------------------------------------------------------------
# Operations and paths
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Operation(CstNode):
    """[Operation Object](https://spec.openapis.org/oas/v3.1.0#operation-object).

    Attributes:
        responses: Map from HTTP status code (or `"default"`) to `Response` (required).
        tags: List of tag names for grouping.
        summary: Short summary.
        description: CommonMark description.
        external_docs: Additional external documentation.
        operation_id: Unique string identifier for the operation.
        parameters: List of parameters applicable to this operation.
        request_body: The request body, if applicable.
        deprecated: Marks the operation as deprecated.
        security: Overrides the top-level security requirements.
        servers: Alternative servers for this operation.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    responses: Mapping[str, Reference | Response] = field(default_factory=dict)
    tags: Sequence[str] = field(default_factory=list)
    summary: str | None = None
    description: str | None = None
    external_docs: ExternalDocumentation | None = None
    operation_id: str | None = None
    parameters: Sequence[Reference | Parameter] = field(default_factory=list)
    request_body: Reference | RequestBody | None = None
    deprecated: bool = False
    security: Sequence[SecurityRequirement] | None = None
    servers: Sequence[Server] = field(default_factory=list)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


type SecurityRequirement = Mapping[str, Sequence[str]]


@dataclass(frozen=True, slots=True)
class PathItem(CstNode):
    """[Path Item Object](https://spec.openapis.org/oas/v3.1.0#path-item-object).

    Each HTTP method is a separate optional field mirroring the spec.

    Attributes:
        summary: Optional summary applied to all operations in this path.
        description: CommonMark description.
        get/put/post/delete/options/head/patch/trace: Per-method operations.
        parameters: Parameters shared across all operations in this path.
        servers: Alternative servers for all operations in this path.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

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
    parameters: Sequence[Reference | Parameter] = field(default_factory=list)
    servers: Sequence[Server] = field(default_factory=list)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


# ---------------------------------------------------------------------------
# Security schemes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OAuthFlow(CstNode):
    """A single [OAuth Flow Object](https://spec.openapis.org/oas/v3.1.0#oauth-flow-object).

    Attributes:
        scopes: Map from scope name to short description (required).
        authorization_url: URL for the `authorization_code` and `implicit` flows.
        token_url: URL for `password`, `clientCredentials`, and `authorizationCode`.
        refresh_url: URL for obtaining refresh tokens.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    scopes: Mapping[str, str]
    authorization_url: str | None = None
    token_url: str | None = None
    refresh_url: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


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
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class SecurityScheme(CstNode):
    """[Security Scheme Object](https://spec.openapis.org/oas/v3.1.0#security-scheme-object).

    Attributes:
        type_: Security scheme type (required).
        description: CommonMark description.
        name: API key name (`apiKey` type only).
        in_: Location of the API key (`apiKey` type only).
        scheme: HTTP authentication scheme (`http` type only), e.g. `"bearer"`.
        bearer_format: Format hint for `Bearer` tokens.
        flows: OAuth flow definitions (`oauth2` type only).
        open_id_connect_url: OpenID Connect Discovery URL.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    type_: SecuritySchemeType
    description: str | None = None
    name: str | None = None
    in_: ApiKeyLocation | None = None
    scheme: str | None = None
    bearer_format: str | None = None
    flows: OAuthFlows | None = None
    open_id_connect_url: str | None = None
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


# ---------------------------------------------------------------------------
# Components and document root
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Components(CstNode):
    """[Components Object](https://spec.openapis.org/oas/v3.1.0#components-object).

    A registry of reusable objects referenced via `$ref` elsewhere in the document.

    Attributes:
        schemas: Reusable JSON Schema definitions.
        responses: Reusable response objects.
        parameters: Reusable parameter objects.
        request_bodies: Reusable request body objects.
        headers: Reusable header objects.
        security_schemes: Reusable security scheme definitions.
        links: Reusable link objects.
        path_items: Reusable path item objects (OAS 3.1 addition).
        examples: Reusable example objects.
        extensions: `x-*` extension fields.
        source_ref: Origin in the source document.
    """

    schemas: Mapping[str, JsonSchema] = field(default_factory=dict)
    responses: Mapping[str, Reference | Response] = field(default_factory=dict)
    parameters: Mapping[str, Reference | Parameter] = field(default_factory=dict)
    examples: Mapping[str, Reference | Example] = field(default_factory=dict)
    request_bodies: Mapping[str, Reference | RequestBody] = field(default_factory=dict)
    headers: Mapping[str, Reference | Header] = field(default_factory=dict)
    security_schemes: Mapping[str, Reference | SecurityScheme] = field(default_factory=dict)
    links: Mapping[str, Reference | Link] = field(default_factory=dict)
    path_items: Mapping[str, Reference | PathItem] = field(default_factory=dict)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)


@dataclass(frozen=True, slots=True)
class OpenApiDocument(CstNode):
    """The root of a parsed OpenAPI 3.1 document.

    Attributes:
        openapi: The OpenAPI Specification version string (required), e.g. `"3.1.0"`.
        info: Metadata about the API (required).
        json_schema_dialect: Default `$schema` for schemas that declare none.
        paths: Map from path template to `PathItem`.
        components: Container for reusable objects.
        servers: List of server objects; defaults to `[{url: "/"}]` if absent.
        security: Default security requirements for all operations.
        tags: List of tag objects for grouping operations.
        external_docs: Additional external documentation.
        webhooks: Map of webhook name to `PathItem` (OAS 3.1 addition).
        extensions: `x-*` extension fields.
        source_id: Matches `RawDoc.source_id`.
        display_name: Short name for the document, carried over from the `RawDoc`.
            It is what a re-emitted file is named after.
        source_ref: Points to the document root (`""`).
    """

    openapi: str
    info: Info
    json_schema_dialect: str | None = None
    paths: Mapping[str, PathItem] = field(default_factory=dict)
    components: Components = field(default_factory=Components)
    servers: Sequence[Server] = field(default_factory=list)
    security: Sequence[SecurityRequirement] = field(default_factory=list)
    tags: Sequence[Tag] = field(default_factory=list)
    external_docs: ExternalDocumentation | None = None
    webhooks: Mapping[str, Reference | PathItem] = field(default_factory=dict)
    extensions: Mapping[str, JsonValue] = field(default_factory=dict, metadata=SYNTHETIC)
    source_id: str | None = field(default=None, metadata=SYNTHETIC)
    display_name: str | None = field(default=None, metadata=SYNTHETIC)
    source_ref: SourceRef | None = field(default=None, metadata=SYNTHETIC)
