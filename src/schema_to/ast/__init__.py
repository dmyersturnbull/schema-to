"""Target-language Abstract Syntax Trees.

Three independent sub-modules, one per supported output language:

- `_python` — Python dataclasses and Pydantic models.
- `_typescript` — TypeScript interfaces, type aliases, and enums.
- `_sql` — PostgreSQL DDL statements.

All AST nodes are immutable `@dataclass(frozen=True, slots=True)` subclasses of `AstNode`.
"""

from schema_to.ast._base import AstNode, DocString, Visibility
from schema_to.ast._python import (
    ClassDef,
    ClassStyle,
    Decorator,
    FieldDef,
    FromImport,
    FunctionDef,
    PythonDocString,
    PythonModule,
    PythonTypeAnnotation,
    SimpleImport,
    TypeAliasDef,
)
from schema_to.ast._sql import (
    ColumnConstraint,
    ColumnDef,
    CommentOnStmt,
    CreateIndexStmt,
    CreateTableStmt,
    DataType,
    ForeignKeyAction,
    IndexMethod,
    PgDataType,
    SqlScript,
    TableConstraint,
)
from schema_to.ast._typescript import (
    EnumDecl,
    EnumMember,
    FunctionDecl,
    ImportDecl,
    InterfaceDecl,
    JSDocComment,
    PropertySignature,
    TypeAliasDecl,
    TypeScriptModule,
    TypeScriptTypeAnnotation,
    UtilityType,
)

__all__ = [
    # Base
    "AstNode",
    # Python
    "ClassDef",
    "ClassStyle",
    # SQL
    "ColumnConstraint",
    "ColumnDef",
    "CommentOnStmt",
    "CreateIndexStmt",
    "CreateTableStmt",
    "DataType",
    "Decorator",
    "DocString",
    # TypeScript
    "EnumDecl",
    "EnumMember",
    "FieldDef",
    "ForeignKeyAction",
    "FromImport",
    "FunctionDecl",
    "FunctionDef",
    "ImportDecl",
    "IndexMethod",
    "InterfaceDecl",
    "JSDocComment",
    "PgDataType",
    "PropertySignature",
    "PythonDocString",
    "PythonModule",
    "PythonTypeAnnotation",
    "SimpleImport",
    "SqlScript",
    "TableConstraint",
    "TypeAliasDecl",
    "TypeAliasDef",
    "TypeScriptModule",
    "TypeScriptTypeAnnotation",
    "UtilityType",
    "Visibility",
]
