"""Target AST for Python output.

Nodes in this module represent Python declarations emitted by the transpiler.
Reification produces a syntactically-valid `.py` source file that can be
formatted by `ruff format` without modification.

Supported output styles include bare `@dataclass`, `@dataclass(frozen=True, slots=True)`,
and [Pydantic v2](https://docs.pydantic.dev/latest/) `BaseModel` subclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import TYPE_CHECKING

from schema_to.ast._base import AstNode, DocString

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "ClassDef",
    "ClassStyle",
    "Decorator",
    "FieldDef",
    "FromImport",
    "FunctionDef",
    "Parameter",
    "PythonDocString",
    "PythonModule",
    "PythonTypeAnnotation",
    "SimpleImport",
    "TypeAliasDef",
]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ClassStyle(StrEnum):
    """Code-generation style for a Python class node.

    Attributes:
        PLAIN: A plain class with no decorator.
        DATACLASS: `@dataclass` — mutable by default.
        FROZEN_DATACLASS: `@dataclass(frozen=True, slots=True)` — immutable.
        PYDANTIC: `pydantic.BaseModel` subclass.
        PYDANTIC_FROZEN: `pydantic.BaseModel` with `model_config = ConfigDict(frozen=True, slots=True)`.
    """

    PLAIN = auto()
    DATACLASS = auto()
    FROZEN_DATACLASS = auto()
    PYDANTIC = auto()
    PYDANTIC_FROZEN = auto()


# ---------------------------------------------------------------------------
# Type annotations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PythonTypeAnnotation(AstNode):
    """A Python type annotation as a structured expression.

    Rather than storing raw strings, annotations are kept as trees so that
    the reifier can apply import resolution and formatting.

    Attributes:
        name: The base type name, e.g. `"str"`, `"int"`, `"MyModel"`.
        args: Type arguments for generic types, e.g. `[str]` for `list[str]`.
        module: The module where `name` is defined, used to build imports.
            `None` for builtins.
        nullable: Wraps the annotation in `... | None`.
    """

    name: str
    args: Sequence[PythonTypeAnnotation] = field(default_factory=list)
    module: str | None = None
    nullable: bool = False


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PythonDocString(DocString):
    """A Google-style Python docstring.

    Attributes:
        summary: One-line summary sentence.
        description: Extended description (CommonMark).
        attributes: Mapping from attribute name to its description.
        raises: Mapping from exception type name to description.
        returns: Description of the return value.
    """

    summary: str
    description: str | None = None
    attributes: Sequence[tuple[str, str]] = field(default_factory=list)
    raises: Sequence[tuple[str, str]] = field(default_factory=list)
    returns: str | None = None

    @property
    def text(self) -> str: ...


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SimpleImport(AstNode):
    """An `import <module>` statement.

    Attributes:
        module: The dotted module path, e.g. `"collections.abc"`.
        alias: Optional `as` alias.
    """

    module: str
    alias: str | None = None


@dataclass(frozen=True, slots=True)
class FromImport(AstNode):
    """A `from <module> import <name> [as <alias>]` statement.

    Attributes:
        module: The dotted module path.
        names: Sequence of `(name, alias_or_None)` pairs.
    """

    module: str
    names: Sequence[tuple[str, str | None]]


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Decorator(AstNode):
    """A Python decorator applied to a class or function.

    Attributes:
        name: The decorator expression as a string, e.g. `"dataclass"`,
            `"dataclass(frozen=True, slots=True)"`, or `"app.get('/users')"`.
        module: Module providing the decorator; `None` for builtins.
    """

    name: str
    module: str | None = None


# ---------------------------------------------------------------------------
# Field and parameter declarations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldDef(AstNode):
    """A field declaration inside a `ClassDef`.

    Attributes:
        name: Python identifier for the field.
        annotation: The field's type annotation.
        default: Literal default expression as a string, e.g. `"None"`, `'"active"'`.
        doc: Inline documentation for this field.
        decorators: Decorators on the field (rare; used by some frameworks).
    """

    name: str
    annotation: PythonTypeAnnotation
    default: str | None = None
    doc: str | None = None
    decorators: Sequence[Decorator] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Parameter(AstNode):
    """A parameter in a `FunctionDef` signature.

    Attributes:
        name: Python identifier for the parameter.
        annotation: Type annotation, if any.
        default: Default value as a literal string.
        kind: PEP 570 parameter kind (`"positional_or_keyword"`, `"keyword_only"`, etc.).
    """

    name: str
    annotation: PythonTypeAnnotation | None = None
    default: str | None = None
    kind: str = "positional_or_keyword"


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypeAliasDef(AstNode):
    """A `type Name = ...` declaration (PEP 695).

    Attributes:
        name: The alias name.
        annotation: The right-hand side type expression.
        doc: Documentation string for the alias.
    """

    name: str
    annotation: PythonTypeAnnotation
    doc: PythonDocString | None = None


@dataclass(frozen=True, slots=True)
class FunctionDef(AstNode):
    """A function or method declaration.

    Attributes:
        name: The function name.
        parameters: Ordered list of parameters.
        return_annotation: Return type annotation.
        doc: Google-style docstring.
        decorators: Applied decorators, in declaration order.
        is_async: Whether the function is declared with `async def`.
        is_abstract: Whether to emit `@abstractmethod`.
    """

    name: str
    parameters: Sequence[Parameter] = field(default_factory=list)
    return_annotation: PythonTypeAnnotation | None = None
    doc: PythonDocString | None = None
    decorators: Sequence[Decorator] = field(default_factory=list)
    is_async: bool = False
    is_abstract: bool = False


@dataclass(frozen=True, slots=True)
class ClassDef(AstNode):
    """A Python class declaration.

    Attributes:
        name: The class name.
        style: Code-generation style (dataclass, Pydantic, etc.).
        bases: Explicit base class names (beyond those implied by `style`).
        fields: Field declarations, in declaration order.
        methods: Method declarations.
        nested: Nested class declarations.
        doc: Class-level docstring.
        decorators: Additional decorators beyond those implied by `style`.
    """

    name: str
    style: ClassStyle = ClassStyle.FROZEN_DATACLASS
    bases: Sequence[str] = field(default_factory=list)
    fields: Sequence[FieldDef] = field(default_factory=list)
    methods: Sequence[FunctionDef] = field(default_factory=list)
    nested: Sequence[ClassDef] = field(default_factory=list)
    doc: PythonDocString | None = None
    decorators: Sequence[Decorator] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Module root
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PythonModule(AstNode):
    """The root node of a Python output file.

    Attributes:
        imports: Import statements, emitted before any declarations.
        declarations: Top-level declarations in emission order.
        source_ids: Source `RawDocument` identifiers that produced this module.
        module_doc: Module-level docstring.
    """

    imports: Sequence[SimpleImport | FromImport] = field(default_factory=list)
    declarations: Sequence[TypeAliasDef | ClassDef | FunctionDef] = field(default_factory=list)
    source_ids: tuple[str, ...] = ()
    module_doc: str | None = None
