"""Target AST for TypeScript output.

Nodes represent TypeScript declarations emitted by the transpiler.  Reification
produces a `.ts` source file formatted to match Biome's default settings.

The AST covers the subset of TypeScript needed to express schemas: `interface`,
`type`, `enum`, and optionally function signatures for FastAPI-style endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from schema_to.ast.base import AstNode, DocString

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "EnumDecl",
    "EnumMember",
    "FunctionDecl",
    "ImportDecl",
    "InterfaceDecl",
    "JSDocComment",
    "PropertySignature",
    "TypeAliasDecl",
    "TypeScriptModule",
    "TypeScriptTypeAnnotation",
    "UtilityType",
]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class UtilityType(StrEnum):
    """TypeScript built-in utility types applied to a base type.

    Attributes:
        PARTIAL: `Partial<T>` — all properties become optional.
        REQUIRED: `Required<T>` — all properties become required.
        READONLY: `Readonly<T>` — all properties become `readonly`.
        PICK: `Pick<T, K>` — select a subset of properties.
        OMIT: `Omit<T, K>` — exclude a subset of properties.
    """

    PARTIAL = "Partial"
    REQUIRED = "Required"
    READONLY = "Readonly"
    PICK = "Pick"
    OMIT = "Omit"


# ---------------------------------------------------------------------------
# Type annotations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypeScriptTypeAnnotation(AstNode):
    """A TypeScript type expression as a structured tree.

    Attributes:
        name: The base type name, e.g. `"string"`, `"number"`, `"User"`.
        args: Generic type arguments.
        nullable: Appends `| null` to the type.
        optional: Marks the annotation as `T | undefined` (distinct from `null`).
        is_array: Wraps the type as `T[]`.
        from_module: Module path for named imports.
    """

    name: str
    args: Sequence[TypeScriptTypeAnnotation] = field(default_factory=list)
    nullable: bool = False
    optional: bool = False
    is_array: bool = False
    from_module: str | None = None


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JSDocComment(DocString):
    """A JSDoc comment block attached to a TypeScript declaration.

    Attributes:
        summary: One-line summary.
        description: Extended description (CommonMark).
        params: Mapping from parameter name to description.
        returns: Return value description.
        deprecated: Emits `@deprecated` with optional message.
        see: List of `@see` references.
        tags: Arbitrary extra JSDoc tags as `(tag_name, value)` pairs.
    """

    summary: str
    description: str | None = None
    params: Sequence[tuple[str, str]] = field(default_factory=list)
    returns: str | None = None
    deprecated: str | None = None
    see: Sequence[str] = field(default_factory=list)
    tags: Sequence[tuple[str, str]] = field(default_factory=list)

    @property
    def text(self) -> str: ...


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImportDecl(AstNode):
    """An ES module import statement.

    Attributes:
        module: The module specifier string, e.g. `"./types"`.
        names: Named imports as `(name, alias_or_None)` pairs.
        default_import: Name of the default import, if any.
        type_only: Emits `import type { … }`.
    """

    module: str
    names: Sequence[tuple[str, str | None]] = field(default_factory=list)
    default_import: str | None = None
    type_only: bool = True


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PropertySignature(AstNode):
    """A property in an `InterfaceDecl` or object literal type.

    Attributes:
        name: Property name (quoted automatically if not a valid identifier).
        annotation: TypeScript type annotation.
        optional: Emits `?:` instead of `:`.
        readonly: Prepends the `readonly` modifier.
        doc: JSDoc comment for this property.
    """

    name: str
    annotation: TypeScriptTypeAnnotation
    optional: bool = False
    readonly: bool = False
    doc: JSDocComment | None = None


@dataclass(frozen=True, slots=True)
class InterfaceDecl(AstNode):
    """A TypeScript `interface` declaration.

    Attributes:
        name: Interface name.
        properties: Property signatures in declaration order.
        extends: Names of interfaces this one extends.
        doc: JSDoc comment.
        exported: Whether to emit `export`.
    """

    name: str
    properties: Sequence[PropertySignature] = field(default_factory=list)
    extends: Sequence[str] = field(default_factory=list)
    doc: JSDocComment | None = None
    exported: bool = True


@dataclass(frozen=True, slots=True)
class TypeAliasDecl(AstNode):
    """A `type Name = …` declaration.

    Attributes:
        name: Alias name.
        annotation: The right-hand side type expression.
        doc: JSDoc comment.
        exported: Whether to emit `export`.
    """

    name: str
    annotation: TypeScriptTypeAnnotation
    doc: JSDocComment | None = None
    exported: bool = True


@dataclass(frozen=True, slots=True)
class EnumMember(AstNode):
    """A single member of a TypeScript `enum`.

    Attributes:
        name: The identifier for this member.
        value: Optional initialiser literal, e.g. `'"active"'` or `'1'`.
        doc: JSDoc comment for this member.
    """

    name: str
    value: str | None = None
    doc: JSDocComment | None = None


@dataclass(frozen=True, slots=True)
class EnumDecl(AstNode):
    """A TypeScript `enum` declaration.

    Attributes:
        name: Enum name.
        members: Members in declaration order.
        is_const: Whether to emit `const enum`.
        doc: JSDoc comment.
        exported: Whether to emit `export`.
    """

    name: str
    members: Sequence[EnumMember] = field(default_factory=list)
    is_const: bool = True
    doc: JSDocComment | None = None
    exported: bool = True


@dataclass(frozen=True, slots=True)
class FunctionDecl(AstNode):
    """A TypeScript function declaration (typically for endpoint signatures).

    Attributes:
        name: Function name.
        params: `(name, type)` pairs for each parameter.
        return_type: Return type annotation.
        doc: JSDoc comment.
        is_async: Whether to emit `async function`.
        exported: Whether to emit `export`.
    """

    name: str
    params: Sequence[tuple[str, TypeScriptTypeAnnotation]] = field(default_factory=list)
    return_type: TypeScriptTypeAnnotation | None = None
    doc: JSDocComment | None = None
    is_async: bool = False
    exported: bool = True


# ---------------------------------------------------------------------------
# Module root
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypeScriptModule(AstNode):
    """The root node of a TypeScript output file.

    Attributes:
        imports: Import declarations, emitted before any declarations.
        declarations: Top-level declarations in emission order.
        source_ids: Source `RawDocument` identifiers that produced this module.
        module_doc: File-level JSDoc comment (optional).
    """

    imports: Sequence[ImportDecl] = field(default_factory=list)
    declarations: Sequence[InterfaceDecl | TypeAliasDecl | EnumDecl | FunctionDecl] = field(
        default_factory=list
    )
    source_ids: tuple[str, ...] = ()
    module_doc: str | None = None
