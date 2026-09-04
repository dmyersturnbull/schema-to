"""Serializing a `SqlScript` AST to DDL text.

The generator decides what the tables are; this decides how they read.
These build the AST by hand, so a clause reachable only from an unusual
combination of AST fields is still pinned.

Identifiers appear bare here because `quote_sql_identifier` quotes only what
PostgreSQL would otherwise reject; the quoting rule itself is covered by
`tests/postgres/test_sql_tables_refs_integration.py`.
"""

import pytest
from tests.support.asserts import ok

from schema_to.ast.sql import (
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
from schema_to.reify.sql import SqlReifier

type _Statement = CreateTableStmt | CreateIndexStmt | CommentOnStmt


def _emit(*statements: _Statement, preamble: str = "") -> str:
    [artifact] = ok(
        SqlReifier("schema.sql").apply(SqlScript(statements=list(statements), preamble=preamble))
    )
    return artifact.content.decode()


def _typed(name: str, data_type: DataType, **constraint: object) -> ColumnDef:
    return ColumnDef(name=name, data_type=data_type, constraint=ColumnConstraint(**constraint))  # ty: ignore[invalid-argument-type]


def _column(name: str = "id", **constraint: object) -> ColumnDef:
    return _typed(name, DataType(base=PgDataType.TEXT), **constraint)


def _table(*columns: ColumnDef, **kwargs: object) -> CreateTableStmt:
    return CreateTableStmt(table_name="thing", columns=list(columns), **kwargs)  # ty: ignore[invalid-argument-type]


def test_the_artifact_is_named_as_asked() -> None:
    [artifact] = ok(SqlReifier("migrations/001.sql").apply(SqlScript(statements=[])))
    assert artifact.artifact_id == "migrations/001.sql"


def test_the_source_documents_are_carried_onto_the_artifact() -> None:
    """A written file has to be traceable back to the documents it came from."""
    script = SqlScript(statements=[], source_ids=("file:///a.yaml", "file:///b.yaml"))
    [artifact] = ok(SqlReifier("schema.sql").apply(script))
    assert artifact.source_ids == ("file:///a.yaml", "file:///b.yaml")


def test_a_preamble_is_emitted_before_the_statements() -> None:
    sql = _emit(_table(_column()), preamble="CREATE EXTENSION IF NOT EXISTS pg_jsonschema;")
    assert sql.startswith("CREATE EXTENSION IF NOT EXISTS pg_jsonschema;")


def test_a_table_with_no_columns_says_so() -> None:
    """PostgreSQL rejects an empty parenthesis list, and a comment reads better than a crash."""
    assert "-- (no columns)" in _emit(_table())


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


def test_a_custom_type_is_emitted_verbatim() -> None:
    column = _typed("pos", DataType(base=PgDataType.CUSTOM, custom="geometry(Point, 4326)"))
    assert "pos geometry(Point, 4326)" in _emit(_table(column))


def test_an_array_type_is_the_element_type_with_brackets() -> None:
    array = DataType(
        base=PgDataType.TEXT, is_array=True, element_type=DataType(base=PgDataType.TEXT)
    )
    assert "tags text[]" in _emit(_table(_typed("tags", array)))


def test_a_precision_and_scale_are_both_emitted() -> None:
    column = _typed("amount", DataType(base=PgDataType.NUMERIC, precision=10, scale=2))
    assert "amount numeric(10, 2)" in _emit(_table(column))


def test_a_precision_alone_is_emitted_alone() -> None:
    column = _typed("code", DataType(base=PgDataType.VARCHAR, precision=8))
    assert "code varchar(8)" in _emit(_table(column))


# ---------------------------------------------------------------------------
# Column constraints
# ---------------------------------------------------------------------------


def test_a_default_expression_is_emitted_as_written() -> None:
    assert "DEFAULT now()" in _emit(_table(_column(default_expr="now()")))


def test_a_primary_key_column_is_not_also_marked_unique() -> None:
    """A primary key already implies uniqueness, so saying both would be noise."""
    sql = _emit(_table(_column(primary_key=True, unique=True)))
    assert "PRIMARY KEY" in sql
    assert "UNIQUE" not in sql


def test_a_named_check_carries_its_constraint_name() -> None:
    sql = _emit(_table(_column(check_expr="id <> ''", constraint_name="id_not_blank")))
    assert "CONSTRAINT id_not_blank CHECK (id <> '')" in sql


def test_an_unnamed_check_is_emitted_without_a_name() -> None:
    sql = _emit(_table(_column(check_expr="id <> ''")))
    assert "CHECK (id <> '')" in sql
    assert "CONSTRAINT" not in sql


def test_a_foreign_key_names_the_column_when_it_has_one() -> None:
    sql = _emit(_table(_column(references_table="author", references_column="id")))
    assert "REFERENCES author(id)" in sql


def test_a_foreign_key_without_a_column_references_the_table_alone() -> None:
    assert "REFERENCES author" in _emit(_table(_column(references_table="author")))


def test_referential_actions_are_emitted_in_upper_case() -> None:
    column = _column(
        references_table="author",
        on_delete=ForeignKeyAction.CASCADE,
        on_update=ForeignKeyAction.SET_NULL,
    )
    sql = _emit(_table(column))
    assert "ON DELETE CASCADE" in sql
    assert "ON UPDATE SET NULL" in sql


def test_the_default_referential_action_is_left_unsaid() -> None:
    """`NO ACTION` is the default, so spelling it out would only add noise."""
    sql = _emit(_table(_column(references_table="author")))
    assert "ON DELETE" not in sql
    assert "ON UPDATE" not in sql


def test_a_deferrable_key_says_when_it_is_checked() -> None:
    sql = _emit(_table(_column(references_table="author", deferrable=True)))
    assert "DEFERRABLE INITIALLY DEFERRED" in sql


# ---------------------------------------------------------------------------
# Table constraints
# ---------------------------------------------------------------------------


def test_a_composite_primary_key_becomes_a_table_constraint() -> None:
    constraints = [TableConstraint(primary_key=["a", "b"])]
    assert "PRIMARY KEY (a, b)" in _emit(_table(_column("a"), table_constraints=constraints))


def test_a_composite_unique_constraint_names_its_columns() -> None:
    constraints = [TableConstraint(unique=["a"])]
    assert "UNIQUE (a)" in _emit(_table(_column("a"), table_constraints=constraints))


def test_a_table_level_check_is_emitted() -> None:
    constraints = [TableConstraint(check_expr="a > 0")]
    assert "CHECK (a > 0)" in _emit(_table(_column("a"), table_constraints=constraints))


def test_a_composite_foreign_key_names_both_sides() -> None:
    constraint = TableConstraint(
        foreign_key_columns=["a", "b"],
        references_table="other",
        references_columns=["x", "y"],
        on_delete=ForeignKeyAction.CASCADE,
        on_update=ForeignKeyAction.RESTRICT,
    )
    sql = _emit(_table(_column("a"), table_constraints=[constraint]))
    assert "FOREIGN KEY (a, b) REFERENCES other (x, y)" in sql
    assert "ON DELETE CASCADE" in sql
    assert "ON UPDATE RESTRICT" in sql


def test_a_foreign_key_without_target_columns_omits_them() -> None:
    constraint = TableConstraint(foreign_key_columns=["a"], references_table="other")
    sql = _emit(_table(_column("a"), table_constraints=[constraint]))
    assert "FOREIGN KEY (a) REFERENCES other" in sql


def test_a_constraint_that_says_nothing_is_left_out() -> None:
    """An empty `TableConstraint` would otherwise emit a stray comma and a blank line."""
    sql = _emit(_table(_column("a"), table_constraints=[TableConstraint()]))
    assert "," not in sql


def test_a_json_schema_check_escapes_quotes_in_the_embedded_schema() -> None:
    table = _table(_column("data"), jsonschema_constraint='{"const": "it\'s"}')
    assert "jsonb_matches_schema('{\"const\": \"it''s\"}', data)" in _emit(table)


# ---------------------------------------------------------------------------
# Indexes and comments
# ---------------------------------------------------------------------------


def test_an_index_names_its_table_method_and_columns() -> None:
    index = CreateIndexStmt(table_name="thing", columns=["a", "b"], index_name="thing_ab_idx")
    assert "CREATE INDEX IF NOT EXISTS thing_ab_idx ON thing USING BTREE (a, b);" in _emit(index)


def test_an_unnamed_index_omits_if_not_exists() -> None:
    """PostgreSQL rejects `IF NOT EXISTS` without a name — there is nothing to test for."""
    sql = _emit(CreateIndexStmt(table_name="thing", columns=["a"]))
    assert "IF NOT EXISTS" not in sql
    assert "CREATE INDEX ON thing USING BTREE (a);" in sql


def test_an_index_may_be_asked_for_without_if_not_exists() -> None:
    index = CreateIndexStmt(table_name="thing", columns=["a"], index_name="i", if_not_exists=False)
    assert "IF NOT EXISTS" not in _emit(index)


@pytest.mark.parametrize("method", list(IndexMethod))
def test_every_index_method_is_emitted_in_upper_case(method: IndexMethod) -> None:
    index = CreateIndexStmt(table_name="thing", columns=["a"], index_name="i", method=method)
    assert f"USING {method.value.upper()}" in _emit(index)


def test_a_unique_partial_index_carries_both_clauses() -> None:
    index = CreateIndexStmt(
        table_name="thing", columns=["a"], index_name="i", unique=True, where_expr="a IS NOT NULL"
    )
    sql = _emit(index)
    assert "CREATE UNIQUE INDEX" in sql
    assert "WHERE a IS NOT NULL" in sql


def test_a_comment_names_what_it_is_on() -> None:
    comment = CommentOnStmt(object_type="TABLE", object_name="thing", comment="A thing.")
    assert "COMMENT ON TABLE thing IS 'A thing.';" in _emit(comment)


def test_a_comment_escapes_a_quote_in_its_text() -> None:
    comment = CommentOnStmt(object_type="TABLE", object_name="thing", comment="it's")
    assert "IS 'it''s';" in _emit(comment)
