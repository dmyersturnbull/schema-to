"""Reifier: SQL AST → `.sql` bytes.

Emits PostgreSQL-compatible DDL that can be executed directly by `psql`.

Output style:

- `CREATE TABLE IF NOT EXISTS name (` with one column per line.
- Column constraints inline: `NOT NULL`, `CHECK (...)`, `REFERENCES`.
- Table-level constraints after all column lines.
- `COMMENT ON TABLE` and `COMMENT ON COLUMN` immediately after each table.
- `CREATE INDEX` and standalone `COMMENT ON` in statement order.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from schema_to.ast.sql import (
    ColumnConstraint,
    CommentOnStmt,
    CreateIndexStmt,
    CreateTableStmt,
    DataType,
    ForeignKeyAction,
    PgDataType,
    SqlScript,
    TableConstraint,
)
from schema_to.io.sink import SqlArtifact
from schema_to.pipeline import Reifier
from schema_to.result import Ok, Result

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

__all__ = ["SqlReifier"]

_INDENT = "    "


@dataclass(frozen=True, slots=True)
class SqlReifier(Reifier[SqlScript, SqlArtifact]):
    """Serialise a `SqlScript` AST to a single `.sql` `Artifact`.

    Attributes:
        artifact_name: Base file name for the output artifact (e.g. `"schema.sql"`).
    """

    artifact_name: str

    def apply(self, input: SqlScript) -> Result[Sequence[SqlArtifact]]:
        return Ok([self._apply(input)])

    def _apply(self, input: SqlScript) -> SqlArtifact:
        sql = "\n\n".join(self._emit_script(input)) + "\n"
        return SqlArtifact(
            artifact_id=self.artifact_name, content=sql.encode("utf-8"), source_ids=input.source_ids
        )

    # ------------------------------------------------------------------
    # Script
    # ------------------------------------------------------------------

    def _emit_script(self, script: SqlScript) -> Iterator[str]:
        if script.preamble:
            yield script.preamble
        for stmt in script.statements:
            if isinstance(stmt, CreateTableStmt):
                yield from self._emit_table_block(stmt)
            elif isinstance(stmt, CreateIndexStmt):
                yield self._emit_create_index(stmt)
            elif isinstance(stmt, CommentOnStmt):
                yield (
                    f"COMMENT ON {stmt.object_type} {stmt.object_name} IS {_sql_str(stmt.comment)};"
                )

    # ------------------------------------------------------------------
    # Statements
    # ------------------------------------------------------------------

    def _emit_table_block(self, stmt: CreateTableStmt) -> Iterator[str]:
        yield self._emit_create_table(stmt)
        if stmt.doc:
            yield f"COMMENT ON TABLE {stmt.table_name} IS {_sql_str(stmt.doc)};"
        yield from (
            f"COMMENT ON COLUMN {stmt.table_name}.{col.name} IS {_sql_str(col.doc)};"
            for col in stmt.columns
            if col.doc
        )

    def _emit_create_table(self, stmt: CreateTableStmt) -> str:
        exists_clause = "IF NOT EXISTS " if stmt.if_not_exists else ""
        header = f"CREATE TABLE {exists_clause}{stmt.table_name} ("

        parts: list[str] = []
        for col in stmt.columns:
            col_str = f"{_INDENT}{col.name} {_emit_data_type(col.data_type)}"
            constraint_str = _emit_column_constraint(col.constraint)
            if constraint_str:
                col_str += f" {constraint_str}"
            parts.append(col_str)

        for tc in stmt.table_constraints:
            tc_str = _emit_table_constraint(tc)
            if tc_str:
                parts.append(f"{_INDENT}{tc_str}")

        if stmt.jsonschema_constraint:
            escaped = stmt.jsonschema_constraint.replace("'", "''")
            parts.append(f"{_INDENT}CHECK (jsonb_matches_schema('{escaped}', data))")

        if not parts:
            return f"{header}\n{_INDENT}-- (no columns)\n);"

        return f"{header}\n" + ",\n".join(parts) + "\n);"

    def _emit_create_index(self, stmt: CreateIndexStmt) -> str:
        unique_clause = "UNIQUE " if stmt.unique else ""
        # PostgreSQL puts `IF NOT EXISTS` *before* the index name, and rejects it
        # outright for an unnamed index — there would be no name to test.
        name_clause = ""
        if stmt.index_name:
            exists_clause = "IF NOT EXISTS " if stmt.if_not_exists else ""
            name_clause = f"{exists_clause}{stmt.index_name} "
        method_clause = f" USING {stmt.method.value.upper()}"
        cols = ", ".join(stmt.columns)
        where_clause = f" WHERE {stmt.where_expr}" if stmt.where_expr else ""
        return (
            f"CREATE {unique_clause}INDEX {name_clause}"
            f"ON {stmt.table_name}{method_clause} ({cols}){where_clause};"
        )


# ------------------------------------------------------------------
# Rendering helpers (module-level for reuse)
# ------------------------------------------------------------------


def _emit_data_type(dt: DataType) -> str:
    if dt.base == PgDataType.CUSTOM and dt.custom:
        return dt.custom
    if dt.is_array and dt.element_type is not None:
        return _emit_data_type(dt.element_type) + "[]"
    if dt.precision is not None and dt.scale is not None:
        return f"{dt.base.value}({dt.precision}, {dt.scale})"
    if dt.precision is not None:
        return f"{dt.base.value}({dt.precision})"
    return dt.base.value


def _emit_column_constraint(c: ColumnConstraint) -> str:
    parts: list[str] = []
    if c.not_null:
        parts.append("NOT NULL")
    if c.primary_key:
        parts.append("PRIMARY KEY")
    elif c.unique:
        parts.append("UNIQUE")
    if c.default_expr is not None:
        parts.append(f"DEFAULT {c.default_expr}")
    if c.check_expr is not None:
        name_prefix = f"CONSTRAINT {c.constraint_name} " if c.constraint_name else ""
        parts.append(f"{name_prefix}CHECK ({c.check_expr})")
    if c.references_table is not None:
        ref = f"REFERENCES {c.references_table}"
        if c.references_column is not None:
            ref += f"({c.references_column})"
        if c.on_delete != ForeignKeyAction.NO_ACTION:
            ref += f" ON DELETE {c.on_delete.value.upper()}"
        if c.on_update != ForeignKeyAction.NO_ACTION:
            ref += f" ON UPDATE {c.on_update.value.upper()}"
        parts.append(ref)
    return " ".join(parts)


def _emit_table_constraint(tc: TableConstraint) -> str:
    name_prefix = f"CONSTRAINT {tc.constraint_name} " if tc.constraint_name else ""
    if tc.primary_key:
        cols = ", ".join(tc.primary_key)
        return f"{name_prefix}PRIMARY KEY ({cols})"
    if tc.unique:
        cols = ", ".join(tc.unique)
        return f"{name_prefix}UNIQUE ({cols})"
    if tc.check_expr:
        return f"{name_prefix}CHECK ({tc.check_expr})"
    if tc.foreign_key_columns and tc.references_table:
        fk_cols = ", ".join(tc.foreign_key_columns)
        result = f"{name_prefix}FOREIGN KEY ({fk_cols}) REFERENCES {tc.references_table}"
        if tc.references_columns:
            result += f" ({', '.join(tc.references_columns)})"
        if tc.on_delete != ForeignKeyAction.NO_ACTION:
            result += f" ON DELETE {tc.on_delete.value.upper()}"
        if tc.on_update != ForeignKeyAction.NO_ACTION:
            result += f" ON UPDATE {tc.on_update.value.upper()}"
        return result
    return ""


def _sql_str(text: str) -> str:
    """Return *text* as a SQL single-quoted string literal."""
    return "'" + text.replace("'", "''") + "'"
