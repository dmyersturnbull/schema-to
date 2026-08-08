"""Generator: a set of schema-map documents → one PostgreSQL DDL script.

Where `generate.sql` maps one document to one table, this maps a whole tree of
schema files to the set of tables they describe — the unit a migration actually is.

Only schemas carrying `x-pg-table` become tables, so a tree may hold as many
request bodies, patch documents, and shared primitives as it likes without any of
them turning into a table.  See `generate._pg_keywords` for the keyword vocabulary.

Tables are emitted in dependency order: a table is declared after every table its
foreign keys reference.  A reference cycle has no such order — the script warns and
falls back to input order, leaving one forward reference for the author to break.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from schema_to.ast.sql import (
    ColumnConstraint,
    ColumnDef,
    CreateIndexStmt,
    CreateTableStmt,
    DataType,
    SqlScript,
    TableConstraint,
)
from schema_to.cst.json_schema import JsonSchemaMapDocument, ObjectSchema, is_object_schema
from schema_to.errors import GenerationError, SourceLocation, TranspilationWarning
from schema_to.generate._compose import SchemaFlattener
from schema_to.generate._names import safe_sql_identifier
from schema_to.generate._pg_keywords import (
    TABLE,
    IndexRequest,
    PropertyKeywords,
    TableKeywords,
    read_property_keywords,
    read_table_keywords,
)
from schema_to.generate.sql import ColumnBuilder
from schema_to.result import Err, Ok, Result

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

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


@dataclass
class PostgresTableSetTransformer:
    """Generates one `SqlScript` from every `x-pg-table` schema across several documents.

    Attributes:
        resolver: Resolves `$ref` across the document set.  Register every document
            with it before generating, or references between files will not resolve.
        validate_json: Emit `pg_jsonschema` `CHECK` constraints for JSON columns.
    """

    resolver: JsonSchemaRefResolver | None = None
    validate_json: bool = False
    _warnings: list[TranspilationWarning] = field(default_factory=list, repr=False)

    @property
    def warnings(self) -> Sequence[TranspilationWarning]:
        return list(self._warnings)

    def apply(self, input: Sequence[JsonSchemaMapDocument]) -> Result[SqlScript]:
        self._warnings.clear()
        try:
            return Ok(self._apply(input))
        except GenerationError as exc:
            return Err((exc,))

    def _apply(self, input: Sequence[JsonSchemaMapDocument]) -> SqlScript:
        specs = self._collect(input)
        _reject_duplicate_names(specs)
        self._check_reference_targets(specs)
        ordered, cycles = _in_dependency_order(specs)
        self._warn_cycles(cycles, specs)
        tables = [self._build_table(spec) for spec in ordered]
        indexes = [stmt for spec in ordered for stmt in self._build_indexes(spec)]
        preamble = "CREATE EXTENSION IF NOT EXISTS pg_jsonschema;" if self.validate_json else None
        return SqlScript(
            statements=(*tables, *indexes),
            source_ids=tuple(doc.source_id for doc in input),
            preamble=preamble,
        )

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _collect(self, docs: Iterable[JsonSchemaMapDocument]) -> list[TableSpec]:
        """Return a spec for every schema marked with `x-pg-table`, in document order."""
        specs: list[TableSpec] = []
        for doc in docs:
            for name, schema in doc.schemas.items():
                spec = self._as_spec(name, schema, source_id=doc.source_id)
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
        self._warnings.extend(result.warnings)
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
                    self._warnings.append(
                        TranspilationWarning(
                            f"Table {spec.table_name!r} references table {target!r}, "
                            f"which no schema in this set declares.",
                            code="unknown-fk-target",
                            location=SourceLocation(spec.source_id, ""),
                        )
                    )

    def _warn_cycles(self, cycles: Sequence[str], specs: Sequence[TableSpec]) -> None:
        """Warn that a foreign-key cycle left a forward reference in the output."""
        by_name = {spec.table_name: spec for spec in specs}
        for name in cycles:
            self._warnings.append(
                TranspilationWarning(
                    f"Table {name!r} takes part in a foreign-key cycle, so it cannot be "
                    f"declared after everything it references; break the cycle by hand.",
                    code="reference-cycle",
                    location=SourceLocation(by_name[name].source_id, ""),
                )
            )

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------

    def _build_table(self, spec: TableSpec) -> CreateTableStmt:
        required = spec.schema.get_required()
        builder = ColumnBuilder(resolver=self.resolver, validate_json=self.validate_json)
        columns: list[ColumnDef] = []
        for prop_name, prop_schema in (spec.schema.properties or {}).items():
            column = self._build_column(spec, prop_name, prop_schema, builder, required)
            if column is not None:
                columns.append(column)
        self._warnings.extend(builder.warnings)
        if spec.keywords.extras_column:
            columns.append(_extras_column(spec.keywords.extras_column))
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
        builder: ColumnBuilder,
        required: frozenset[str],
    ) -> ColumnDef | None:
        flat = self._flatten(prop_schema, base_uri=spec.source_id)
        where = f"property {prop_name!r} of schema {spec.schema_name!r}"
        keywords = read_property_keywords(_extensions_of(flat), where=where)
        if keywords.skip:
            return None
        column = builder.build(
            keywords.column or safe_sql_identifier(prop_name),
            flat,
            required=prop_name in required,
            force_json=keywords.force_json,
            sql_type=keywords.sql_type,
        )
        return _with_keywords(column, keywords, single_pk=_is_single_pk(spec, keywords))

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


def _with_keywords(column: ColumnDef, keywords: PropertyKeywords, *, single_pk: bool) -> ColumnDef:
    """Apply the key, uniqueness, and foreign-key keywords to a built column."""
    reference = keywords.references
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
    )
    return ColumnDef(
        name=column.name, data_type=column.data_type, constraint=constraint, doc=column.doc
    )


def _is_single_pk(spec: TableSpec, keywords: PropertyKeywords) -> bool:
    """Report whether this property is the table's whole primary key.

    A property marked `x-pg-primary-key` is inlined as `PRIMARY KEY` only when the
    schema does not declare a composite key, which becomes a table constraint instead.
    """
    return keywords.primary_key and not spec.keywords.primary_key


def _extras_column(name: str) -> ColumnDef:
    return ColumnDef(
        name=name,
        data_type=DataType.jsonb(),
        constraint=ColumnConstraint(not_null=True, default_expr="'{}'::jsonb"),
        doc="Keys present on the resource that the schema does not define.",
    )


def _table_constraints(spec: TableSpec) -> tuple[TableConstraint, ...]:
    if not spec.keywords.primary_key:
        return ()
    return (
        TableConstraint(
            constraint_name=f"{spec.table_name}_pkey", primary_key=spec.keywords.primary_key
        ),
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


def _in_dependency_order(specs: Sequence[TableSpec]) -> tuple[list[TableSpec], list[str]]:
    """Sort so that a table follows every table it references.

    Ties keep the input order, which keeps output stable across runs.

    Returns the ordered tables and the names of any that take part in a
    reference cycle, which by definition cannot all follow their dependencies.
    """
    by_name = {spec.table_name: spec for spec in specs}
    ordered: list[TableSpec] = []
    placed: set[str] = set()
    visiting: list[str] = []
    cycles: list[str] = []

    def visit(spec: TableSpec) -> None:
        if spec.table_name in placed:
            return
        if spec.table_name in visiting:
            cycles.append(spec.table_name)
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
    targets: list[str] = []
    for prop_name, prop_schema in (spec.schema.properties or {}).items():
        where = f"property {prop_name!r} of schema {spec.schema_name!r}"
        keywords = read_property_keywords(_extensions_of(prop_schema), where=where)
        if keywords.references is not None and keywords.references.table != spec.table_name:
            targets.append(keywords.references.table)
    return targets


def _extensions_of(schema: JsonSchema) -> Mapping[str, JsonValue]:
    return schema.get_extensions() if isinstance(schema, ObjectSchema) else {}
