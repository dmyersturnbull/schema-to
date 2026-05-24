"""Target AST for PostgreSQL DDL output.

Nodes represent SQL statements emitted by the transpiler.  Reification produces
a `.sql` migration script compatible with PostgreSQL 14+ and optionally
[pg_jsonschema](https://github.com/supabase/pg_jsonschema) for inline JSON
validation constraints.

Custom extension keywords supported by the generator:
- `x-is-table` — emit a `CREATE TABLE` rather than a bare type definition.
- `x-is-fk` — emit a `REFERENCES` foreign key constraint.
- `x-is-index` — emit a `CREATE INDEX` on the annotated column.
- `x-pg-type` — override the inferred PostgreSQL type with a literal type name.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from schema_to.ast._base import AstNode

__all__ = [
    "ColumnConstraint",
    "ColumnDef",
    "CommentOnStmt",
    "CreateIndexStmt",
    "CreateTableStmt",
    "DataType",
    "ForeignKeyAction",
    "IndexMethod",
    "PgDataType",
    "SqlScript",
    "TableConstraint",
]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class PgDataType(str, Enum):
    """PostgreSQL built-in data types used by the code generator.

    This list covers the types reachable from JSON Schema primitives plus
    common extensions.  The `CUSTOM` variant allows generators to fall back
    to a literal type string via `DataType.custom`.
    """

    # Numeric
    SMALLINT = "smallint"
    INTEGER = "integer"
    BIGINT = "bigint"
    NUMERIC = "numeric"
    REAL = "real"
    DOUBLE_PRECISION = "double precision"
    # Character
    TEXT = "text"
    VARCHAR = "varchar"
    CHAR = "char"
    # Boolean
    BOOLEAN = "boolean"
    # Date / time
    DATE = "date"
    TIME = "time"
    TIMETZ = "timetz"
    TIMESTAMP = "timestamp"
    TIMESTAMPTZ = "timestamptz"
    INTERVAL = "interval"
    # Binary
    BYTEA = "bytea"
    # UUID
    UUID = "uuid"
    # JSON
    JSON = "json"
    JSONB = "jsonb"
    # Arrays (use DataType.array_of)
    ARRAY = "array"
    # Other
    CUSTOM = "custom"


class ForeignKeyAction(str, Enum):
    """Actions for `ON DELETE` and `ON UPDATE` foreign-key clauses."""

    NO_ACTION = "NO ACTION"
    RESTRICT = "RESTRICT"
    CASCADE = "CASCADE"
    SET_NULL = "SET NULL"
    SET_DEFAULT = "SET DEFAULT"


class IndexMethod(str, Enum):
    """PostgreSQL index access methods."""

    BTREE = "btree"
    HASH = "hash"
    GIN = "gin"
    GIST = "gist"
    SPGIST = "spgist"
    BRIN = "brin"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DataType(AstNode):
    """A PostgreSQL column data type.

    Attributes:
        base: The primitive or built-in type.
        custom: Literal type expression used when `base` is `PgDataType.CUSTOM`.
        precision: First type modifier (e.g. `10` in `numeric(10, 2)`).
        scale: Second type modifier (e.g. `2` in `numeric(10, 2)`).
        is_array: Appends `[]` to the type.
        element_type: Element type when `is_array` is `True`.
    """

    base: PgDataType
    custom: str | None = None
    precision: int | None = None
    scale: int | None = None
    is_array: bool = False
    element_type: DataType | None = None

    @classmethod
    def text(cls) -> DataType:
        return cls(base=PgDataType.TEXT)

    @classmethod
    def integer(cls) -> DataType:
        return cls(base=PgDataType.INTEGER)

    @classmethod
    def bigint(cls) -> DataType:
        return cls(base=PgDataType.BIGINT)

    @classmethod
    def boolean(cls) -> DataType:
        return cls(base=PgDataType.BOOLEAN)

    @classmethod
    def jsonb(cls) -> DataType:
        return cls(base=PgDataType.JSONB)

    @classmethod
    def uuid(cls) -> DataType:
        return cls(base=PgDataType.UUID)

    @classmethod
    def timestamptz(cls) -> DataType:
        return cls(base=PgDataType.TIMESTAMPTZ)

    @classmethod
    def array_of(cls, element: DataType) -> DataType:
        return cls(base=PgDataType.ARRAY, is_array=True, element_type=element)


# ---------------------------------------------------------------------------
# Column constraints
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ColumnConstraint(AstNode):
    """An inline constraint on a single column.

    Attributes:
        not_null: Emits `NOT NULL`.
        unique: Emits `UNIQUE`.
        primary_key: Emits `PRIMARY KEY`.
        default_expr: `DEFAULT <expr>` literal expression.
        check_expr: `CHECK (<expr>)` literal expression.
        references_table: Foreign key target table.
        references_column: Foreign key target column (defaults to `PRIMARY KEY`).
        on_delete: `ON DELETE` action for the foreign key.
        on_update: `ON UPDATE` action for the foreign key.
        constraint_name: Optional `CONSTRAINT <name>` prefix.
    """

    not_null: bool = False
    unique: bool = False
    primary_key: bool = False
    default_expr: str | None = None
    check_expr: str | None = None
    references_table: str | None = None
    references_column: str | None = None
    on_delete: ForeignKeyAction = ForeignKeyAction.NO_ACTION
    on_update: ForeignKeyAction = ForeignKeyAction.NO_ACTION
    constraint_name: str | None = None


@dataclass(frozen=True, slots=True)
class ColumnDef(AstNode):
    """A column definition within a `CREATE TABLE` statement.

    Attributes:
        name: Column name.
        data_type: PostgreSQL data type.
        constraint: Inline column constraint.
        doc: Text for a `COMMENT ON COLUMN` statement attached to this column.
    """

    name: str
    data_type: DataType
    constraint: ColumnConstraint = field(default_factory=ColumnConstraint)
    doc: str | None = None


# ---------------------------------------------------------------------------
# Table-level constraints
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TableConstraint(AstNode):
    """A table-level constraint declared after all column definitions.

    Attributes:
        constraint_name: Optional `CONSTRAINT <name>` label.
        primary_key: Columns forming the primary key.
        unique: Columns forming a `UNIQUE` constraint.
        check_expr: A `CHECK (<expr>)` expression.
        foreign_key_columns: Local columns for a `FOREIGN KEY` constraint.
        references_table: Referenced table for the foreign key.
        references_columns: Referenced columns for the foreign key.
        on_delete: `ON DELETE` action.
        on_update: `ON UPDATE` action.
    """

    constraint_name: str | None = None
    primary_key: Sequence[str] = field(default_factory=list)
    unique: Sequence[str] = field(default_factory=list)
    check_expr: str | None = None
    foreign_key_columns: Sequence[str] = field(default_factory=list)
    references_table: str | None = None
    references_columns: Sequence[str] = field(default_factory=list)
    on_delete: ForeignKeyAction = ForeignKeyAction.NO_ACTION
    on_update: ForeignKeyAction = ForeignKeyAction.NO_ACTION


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CreateTableStmt(AstNode):
    """A `CREATE TABLE` statement.

    Attributes:
        table_name: Fully qualified or unqualified table name.
        columns: Column definitions in declaration order.
        table_constraints: Table-level constraints appended after columns.
        if_not_exists: Emits `IF NOT EXISTS`.
        jsonschema_constraint: When set, emits a `pg_jsonschema` `CHECK` constraint
            validating the table's JSONB column against this JSON Schema string.
        doc: Text for a `COMMENT ON TABLE` statement.
        source_ids: Source `RawDocument` identifiers that produced this statement.
    """

    table_name: str
    columns: Sequence[ColumnDef]
    table_constraints: Sequence[TableConstraint] = field(default_factory=list)
    if_not_exists: bool = True
    jsonschema_constraint: str | None = None
    doc: str | None = None
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CreateIndexStmt(AstNode):
    """A `CREATE INDEX` statement.

    Attributes:
        index_name: Optional explicit index name (auto-generated if absent).
        table_name: Table on which the index is created.
        columns: Indexed columns or expressions.
        method: Index access method.
        unique: Emits `UNIQUE`.
        if_not_exists: Emits `IF NOT EXISTS`.
        where_expr: Partial index `WHERE` predicate expression.
    """

    table_name: str
    columns: Sequence[str]
    index_name: str | None = None
    method: IndexMethod = IndexMethod.BTREE
    unique: bool = False
    if_not_exists: bool = True
    where_expr: str | None = None


@dataclass(frozen=True, slots=True)
class CommentOnStmt(AstNode):
    """A `COMMENT ON <object> IS '…'` statement.

    Attributes:
        object_type: SQL object type, e.g. `"TABLE"`, `"COLUMN"`, `"INDEX"`.
        object_name: Fully qualified object name.
        comment: The comment text (single-quoted in the output).
    """

    object_type: str
    object_name: str
    comment: str


# ---------------------------------------------------------------------------
# Script root
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SqlScript(AstNode):
    """The root node of a SQL migration script.

    Attributes:
        statements: SQL statements in execution order.
        source_ids: Source `RawDocument` identifiers that produced this script.
        preamble: Optional raw SQL prepended before generated statements
            (e.g. `SET search_path = myschema;`).
    """

    statements: Sequence[CreateTableStmt | CreateIndexStmt | CommentOnStmt]
    source_ids: tuple[str, ...] = ()
    preamble: str | None = None
