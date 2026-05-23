"""Shared primitives for all target-language AST modules.

Each target language has its own independent AST hierarchy (`_python`,
`_typescript`, `_sql`).  This module provides only the common marker base and
cross-cutting enumerations used by more than one target.
"""

from __future__ import annotations

from abc import ABC
from enum import Enum

__all__ = ["AstNode", "DocString", "Visibility"]


class Visibility(str, Enum):
    """Visibility modifier applicable across multiple target languages.

    Not all targets support every level; generators emit the closest equivalent
    or omit the modifier when the concept does not apply.
    """

    PUBLIC = "public"
    PROTECTED = "protected"
    PRIVATE = "private"
    INTERNAL = "internal"


class AstNode(ABC):
    """Sealed marker base for every target-language AST node.

    Concrete nodes are immutable `@dataclass(frozen=True, slots=True)` subclasses organised
    into language-specific modules.  Each language module defines its own root
    node (e.g. `PythonModule`, `TypeScriptModule`, `SqlScript`) that acts as the
    entry point for reification.
    """


class DocString(AstNode, ABC):
    """Abstract documentation comment attached to a declaration.

    The concrete subclass lives in the target-language module so that it can
    carry language-specific metadata (e.g. JSDoc tags, Google-style sections).
    """

    @property
    def text(self) -> str:
        """The raw documentation text, which may contain Markdown."""
