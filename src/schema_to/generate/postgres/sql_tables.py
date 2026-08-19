"""Generator: PostgreSQL DDLs from schema-map documents.

Generates one a set of schema-map documents → one PostgreSQL DDL script.
Where `generate.sql` maps one document to one table,
this maps a whole tree of schema files to the set of tables they describe.

Only schemas carrying `x-pg-table` become tables.
See [generate._pg_keywords][] for the keyword vocabulary.

Tables are emitted in dependency order:
A table is declared after every table its foreign keys reference.
If there is a foreign key cycle, the foreign keys in it are made `DEFERRABLE INITIALLY DEFERRED`.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override

from schema_to.ast.sql import (
    ColumnConstraint,
    ColumnDef,
    CreateIndexStmt,
    CreateTableStmt,
    DataType,
    PgDataType,
    SqlScript,
    TableConstraint,
)
from schema_to.cst.json_schema import JsonSchemaMapDocument, ObjectSchema, is_object_schema
from schema_to.errors import GenerationError, SourceLocation, TranspilationWarning
from schema_to.generate.inlining import SchemaFlattener
from schema_to.generate.postgres._pg_keywords import (
    TABLE,
    ExtraColumn,
    ForeignKeyRef,
    IndexRequest,
    PropertyKeywords,
    TableKeywords,
    read_property_keywords,
    read_table_keywords,
)
from schema_to.generate.postgres._sql_utils import safe_sql_identifier
from schema_to.generate.postgres.sql import ColumnBuilder
from schema_to.pipeline import Transformer
from schema_to.result import Err, Ok, Result

if TYPE_CHECKING:
    from collections.abc import Mapping, Set

    from schema_to.core import JsonValue
    from schema_to.cst.json_schema import JsonSchema
    from schema_to.resolve.json_schema import JsonSchemaRefResolver

__all__ = ["PostgresTableSetTransformer", "TableSpec"]


@dataclass(frozen=True, slots=True)
class TableSpec:
    """One schema selected to become a table, with its keywords already read."""

    table_name: str
    schema_name: str
    source_id: str
    schema: ObjectSchema
    keywords: TableKeywords

    @property
    def where(self) -> str:
        """Human-readable identification for error messages."""
        return f"schema {self.schema_name!r}"

    @property
    def primary_key(self) -> tuple[str, ...]:
        """The key columns: the declared ones, else `id` when the schema has one."""
        if self.keywords.primary_key:
            return self.keywords.primary_key
        if "id" in (self.schema.properties or {}):
            return ("id",)
        return ()


@dataclass(frozen=True, slots=True)
class PostgresTableSetTransformer(Transformer[JsonSchemaMapDocument, SqlScript]):
    """Generates an `SqlScript` schema-map documents containing one or more `x-pg-table` schemas.

    Each schema is flattened against the file it was written in,
    rather than against the document holding it.
    This keeps a merged set's references working:
    `#/other` in a file means that file's `other`, wherever the schema ends up.

    Attributes:
        resolver: Resolves `$ref` across the document set.  Register every document
            with it before generating, or references between files will not resolve.
        validate_json: Emit `pg_jsonschema` `CHECK` constraints for JSON columns.
        roots: If given, only schemas named here are considered for a table, even if
            marked `x-pg-table`; unnamed ones are still available for `$ref`
            resolution. `None` considers every schema, as before.
    """

    resolver: JsonSchemaRefResolver | None = None
    validate_json: bool = False
    roots: Set[str] | None = None

    @override
    def apply(self, input: JsonSchemaMapDocument) -> Result[SqlScript]:
        ctx = _GenCtx(resolver=self.resolver, validate_json=self.validate_json, roots=self.roots)
        try:
            script = ctx.build(input)
        except GenerationError as exc:
            return Err((exc,), warnings=tuple(ctx.warnings))
        return Ok(script, warnings=tuple(ctx.warnings))


@dataclass
class _GenCtx:
    """Per-document generation state for `PostgresTableSetTransformer`."""

    resolver: JsonSchemaRefResolver | None
    validate_json: bool
    roots: Set[str] | None
    warnings: list[TranspilationWarning] = field(default_factory=list)

    def build(self, input: JsonSchemaMapDocument) -> SqlScript:
        specs = self._collect(input)
        _reject_duplicate_names(specs)
        self._check_reference_targets(specs)
        self._warn_keyless(specs)
        ordered, cycles = _in_dependency_order(specs)
        self._warn_cycles(cycles, specs)
        tables = [self._build_table(spec, cycles) for spec in ordered]
        indexes = [stmt for spec in ordered for stmt in self._build_indexes(spec)]
        preamble = "CREATE EXTENSION IF NOT EXISTS pg_jsonschema;" if self.validate_json else None
        return SqlScript(
            statements=(*tables, *indexes),
            source_ids=tuple(dict.fromkeys(spec.source_id for spec in ordered)),
            preamble=preamble,
        )

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _collect(self, doc: JsonSchemaMapDocument) -> list[TableSpec]:
        """Return a spec for every schema marked with `x-pg-table`, in document order."""
        specs: list[TableSpec] = []
        for name, schema in doc.schemas.items():
            if self.roots is not None and name not in self.roots:
                continue
            spec = self._as_spec(name, schema, source_id=_origin_of(schema, doc))
            if spec is not None:
                specs.append(spec)
        return specs

    def _as_spec(self, name: str, schema: JsonSchema, *, source_id: str) -> TableSpec | None:
        # Test for the keyword before flattening. Most schemas in a tree are not tables,
        # and flattening every one of them would be wasted work. The cost is that
        # `x-pg-table` must be written on the schema itself, not on an `allOf` branch —
        # which is where you would write it anyway.
        if not isinstance(schema, ObjectSchema) or TABLE not in schema.get_extensions():
            return None
        flat = self._flatten(schema, base_uri=source_id)
        if not is_object_schema(flat):
            msg = (
                f"Schema {name!r} is marked with `x-pg-table` but is not an object schema, "
                f"so it has no columns."
            )
            raise GenerationError(msg)
        keywords = read_table_keywords(flat.get_extensions(), where=f"schema {name!r}")
        table_name = keywords.table or name
        return TableSpec(
            table_name=table_name,
            schema_name=name,
            source_id=source_id,
            schema=flat,
            keywords=keywords,
        )

    def _flatten(self, schema: JsonSchema, *, base_uri: str) -> JsonSchema:
        result = SchemaFlattener(resolver=self.resolver).flatten(schema, base_uri=base_uri)
        self.warnings.extend(result.warnings)
        return result.schema

    def _check_reference_targets(self, specs: Sequence[TableSpec]) -> None:
        """Warn about foreign keys pointing at tables no schema in this set declares.

        A warning, not an error: the target may be a table managed outside this
        schema set, which is legitimate but worth surfacing, since a typo looks the same.
        """
        declared = {spec.table_name for spec in specs}
        for spec in specs:
            for target in _referenced_tables(spec):
                if target not in declared:
                    self.warnings.append(
                        TranspilationWarning(
                            f"Table {spec.table_name!r} references table {target!r}, "
                            f"which no schema in this set declares.",
                            code="unknown-fk-target",
                            location=SourceLocation(spec.source_id, ""),
                        )
                    )

    def _warn_keyless(self, specs: Sequence[TableSpec]) -> None:
        """Warn about a table with neither an `id` property nor a declared key."""
        for spec in specs:
            if not spec.primary_key:
                self.warnings.append(
                    TranspilationWarning(
                        f"Table {spec.table_name!r} has no `id` property and no "
                        f"`x-pg-primary-key`, so it is generated without a primary key.",
                        code="no-primary-key",
                        location=SourceLocation(spec.source_id, ""),
                    )
                )

    def _warn_cycles(self, cycles: Set[str], specs: Sequence[TableSpec]) -> None:
        """Note that a foreign-key cycle forced its keys to be deferred."""
        by_name = {spec.table_name: spec for spec in specs}
        for name in sorted(cycles):
            self.warnings.append(
                TranspilationWarning(
                    f"Table {name!r} takes part in a foreign-key cycle, so it cannot be "
                    f"declared after everything it references; its keys within the cycle "
                    f"are DEFERRABLE INITIALLY DEFERRED and are checked at commit.",
                    code="reference-cycle",
                    location=SourceLocation(by_name[name].source_id, ""),
                )
            )

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------

    def _build_table(self, spec: TableSpec, cycles: Set[str]) -> CreateTableStmt:
        required = spec.schema.get_required()
        builder = ColumnBuilder(resolver=self.resolver, validate_json=self.validate_json)
        columns: list[ColumnDef] = []
        for prop_name, prop_schema in (spec.schema.properties or {}).items():
            column = self._build_column(
                spec, prop_name, prop_schema, builder=builder, required=required, cycles=cycles
            )
            if column is not None:
                columns.append(column)
        self.warnings.extend(builder.warnings)
        if spec.keywords.overflow_column:
            columns.append(_overflow_column(spec.keywords.overflow_column))
        columns.extend(_extra_column(extra) for extra in spec.keywords.extra_columns)
        return CreateTableStmt(
            table_name=spec.table_name,
            columns=tuple(columns),
            table_constraints=_table_constraints(spec),
            doc=spec.schema.description or spec.schema.title,
            source_ids=(spec.source_id,),
        )

    def _build_column(
        self,
        spec: TableSpec,
        prop_name: str,
        prop_schema: JsonSchema,
        *,
        builder: ColumnBuilder,
        required: Set[str],
        cycles: Set[str],
    ) -> ColumnDef | None:
        flat = self._flatten(prop_schema, base_uri=spec.source_id)
        where = f"property {prop_name!r} of schema {spec.schema_name!r}"
        keywords = read_property_keywords(_extensions_of(flat), where=where)
        if keywords.skip:
            return None
        col_name = keywords.column or safe_sql_identifier(prop_name)
        refs = keywords.refs
        column = builder.build(
            col_name, flat, required=prop_name in required, sql_type=keywords.sql_type
        )
        pk = spec.primary_key
        # A cycle cannot be ordered away, but it can be deferred: checking at commit
        # lets both directions be satisfied by one transaction.
        deferred = refs is not None and spec.table_name in cycles and refs.table in cycles
        return _with_keywords(
            column,
            keywords,
            refs=refs,
            single_pk=len(pk) == 1 and col_name == pk[0],
            deferred=deferred,
        )

    def _build_indexes(self, spec: TableSpec) -> list[CreateIndexStmt]:
        """Return the index statements for a table, from both keyword forms."""
        requests: list[IndexRequest] = []
        for prop_name, prop_schema in (spec.schema.properties or {}).items():
            where = f"property {prop_name!r} of schema {spec.schema_name!r}"
            keywords = read_property_keywords(_extensions_of(prop_schema), where=where)
            if keywords.index is not None and not keywords.skip:
                column = keywords.column or safe_sql_identifier(prop_name)
                requests.append(_with_columns(keywords.index, (column,)))
        requests.extend(spec.keywords.indexes)
        return [_index_stmt(spec.table_name, request) for request in requests]


# ---------------------------------------------------------------------------
# Column and constraint assembly
# ---------------------------------------------------------------------------


def _with_keywords(
    column: ColumnDef,
    keywords: PropertyKeywords,
    *,
    refs: ForeignKeyRef | None,
    single_pk: bool,
    deferred: bool,
) -> ColumnDef:
    """Apply the key, uniqueness, and foreign-key keywords to a built column."""
    reference = refs
    constraint = ColumnConstraint(
        # A primary key is NOT NULL by definition; saying both is noise.
        not_null=column.constraint.not_null and not single_pk,
        unique=keywords.unique,
        primary_key=single_pk,
        check_expr=column.constraint.check_expr,
        references_table=reference.table if reference else None,
        references_column=reference.column if reference else None,
        on_delete=reference.on_delete if reference else ColumnConstraint().on_delete,
        on_update=reference.on_update if reference else ColumnConstraint().on_update,
        deferrable=deferred,
    )
    return ColumnDef(
        name=column.name, data_type=column.data_type, constraint=constraint, doc=column.doc
    )


def _overflow_column(name: str) -> ColumnDef:
    return ColumnDef(
        name=name,
        data_type=DataType.jsonb(),
        constraint=ColumnConstraint(not_null=True, default_expr="'{}'::jsonb"),
        doc="Keys present on the resource that the schema does not define.",
    )


def _extra_column(extra: ExtraColumn) -> ColumnDef:
    """Build a column the database owns, which no property in the schema describes."""
    return ColumnDef(
        name=extra.name,
        data_type=DataType(base=PgDataType.CUSTOM, custom=extra.sql_type),
        constraint=ColumnConstraint(not_null=extra.not_null, default_expr=extra.default),
    )


def _table_constraints(spec: TableSpec) -> tuple[TableConstraint, ...]:
    if len(spec.primary_key) < 2:
        # A single-column key is inlined on the column itself, which reads better.
        return ()
    return (
        TableConstraint(constraint_name=f"{spec.table_name}_pkey", primary_key=spec.primary_key),
    )


def _index_stmt(table_name: str, request: IndexRequest) -> CreateIndexStmt:
    return CreateIndexStmt(
        table_name=table_name,
        columns=request.columns,
        index_name=request.name or f"{table_name}_{'_'.join(request.columns)}_idx",
        method=request.method,
        unique=request.unique,
        where_expr=request.where,
    )


def _with_columns(request: IndexRequest, columns: tuple[str, ...]) -> IndexRequest:
    return IndexRequest(
        columns=request.columns or columns,
        name=request.name,
        method=request.method,
        unique=request.unique,
        where=request.where,
    )


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def _origin_of(schema: JsonSchema, doc: JsonSchemaMapDocument) -> str:
    """Return the file a schema was written in, which its references resolve against."""
    if schema.source_ref is not None:
        return schema.source_ref.source_id
    return doc.source_id


def _reject_duplicate_names(specs: Sequence[TableSpec]) -> None:
    seen: dict[str, TableSpec] = {}
    for spec in specs:
        clash = seen.get(spec.table_name)
        if clash is not None:
            msg = (
                f"Two schemas both declare table {spec.table_name!r}: "
                f"{clash.schema_name!r} and {spec.schema_name!r}."
            )
            raise GenerationError(msg)
        seen[spec.table_name] = spec


def _in_dependency_order(specs: Sequence[TableSpec]) -> tuple[list[TableSpec], set[str]]:
    """Sort so that a table follows every table it references.

    Ties keep the input order, which keeps output stable across runs.

    Returns the ordered tables and the names of every table taking part in a
    reference cycle, which by definition cannot all follow their dependencies.
    """
    by_name = {spec.table_name: spec for spec in specs}
    ordered: list[TableSpec] = []
    placed: set[str] = set()
    visiting: list[str] = []
    cycles: set[str] = set()

    def visit(spec: TableSpec) -> None:
        if spec.table_name in placed:
            return
        if spec.table_name in visiting:
            # Everything still open back to the repeat is part of the same cycle.
            cycles.update(visiting[visiting.index(spec.table_name) :])
            return
        visiting.append(spec.table_name)
        for target in _referenced_tables(spec):
            dependency = by_name.get(target)
            if dependency is not None:
                visit(dependency)
        visiting.pop()
        placed.add(spec.table_name)
        ordered.append(spec)

    for spec in specs:
        visit(spec)
    return ordered, cycles


def _referenced_tables(spec: TableSpec) -> list[str]:
    """Return the tables this table's foreign keys point at."""
    targets: list[str] = []
    for prop_name, prop_schema in (spec.schema.properties or {}).items():
        where = f"property {prop_name!r} of schema {spec.schema_name!r}"
        keywords = read_property_keywords(_extensions_of(prop_schema), where=where)
        if keywords.skip or keywords.refs is None:
            continue
        if keywords.refs.table != spec.table_name:
            targets.append(keywords.refs.table)
    return targets


def _extensions_of(schema: JsonSchema) -> Mapping[str, JsonValue]:
    return schema.get_extensions() if isinstance(schema, ObjectSchema) else {}
