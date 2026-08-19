"""Shared primitives for all target-language AST modules."""

from abc import ABC
from enum import StrEnum, auto

__all__ = ["AstNode", "DocString", "Visibility"]


class Visibility(StrEnum):
    """Visibility modifier applicable across multiple target languages.

    Not all targets support every level;
    generators emit the closest equivalent or omit the modifier when the concept does not apply.
    """

    PUBLIC = auto()
    PROTECTED = auto()
    PRIVATE = auto()
    INTERNAL = auto()


# ruff:ignore[abstract-base-class-without-abstract-method]  # Sealed marker; abstract identity is enforced by the type system
class AstNode(ABC):
    """Sealed marker base for every target-language AST node.

    Concrete nodes are immutable
    `@dataclass(frozen=True, slots=True)`
    subclasses organised into language-specific modules.
    Each language module defines its own root node (e.g. `PythonModule`, `SqlScript`),
    which acts as the entry point for reification.
    """


class DocString(AstNode, ABC):
    """Abstract documentation comment attached to a declaration.

    The concrete subclass lives in the target-language module,
    allowing them to carry language-specific metadata
    (e.g. JSDoc tags, Google-style sections).
    """

    @property
    def text(self) -> str:
        """The raw documentation text, which may contain Markdown."""
        raise NotImplementedError
