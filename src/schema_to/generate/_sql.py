"""Generator: JSON Schema 2020-12 CST → PostgreSQL DDL AST.

Mapping rules
-------------
* An `object`-typed root schema becomes a `CREATE TABLE` statement.
* Each `$defs` entry that is `object`-typed becomes its own table.
* Required properties get `NOT NULL`; optional properties are nullable.
* Type mapping follows format-then-type priority with `x-pg-type` overrides:
  - `string` + `format: date-time` → `TIMESTAMPTZ`
  - `string` + `format: date` → `DATE`
  - `string` + `format: time` → `TIME`
  - `string` + `format: uuid` → `UUID`
  - `string` + `format: byte` → `BYTEA`
  - `string` + `maxLength` → `VARCHAR(n)`
  - `string` → `TEXT`
  - `integer` → `INTEGER`
  - `number` → `DOUBLE PRECISION`
  - `boolean` → `BOOLEAN`
  - `array` of simple type → `element_type[]`
  - `object` / complex `array` → `JSONB`
* Numeric constraints map to `CHECK` expressions; `pattern` maps to `~`.
* `enum` values produce `CHECK (col IN (...))`.
* `title` / `description` populate `doc` for `COMMENT ON` emission.
* `x-pg-type` overrides the inferred type with a literal type string.
* Unsupported constructs emit `TranspilationWarning` and fall back to `JSONB`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from schema_to._errors import GenerationError, SourceLocation, TranspilationWarning
from schema_to._names import safe_sql_identifier
from schema_to._pipeline import Generator
from schema_to._result import Err, Ok, Result
from schema_to.ast._sql import (
    ColumnConstraint,
    ColumnDef,
    CreateTableStmt,
    DataType,
    PgDataType,
    SqlScript,
)
from schema_to.cst._base import JsonValue
from schema_to.cst._json_schema import (
    BooleanSchema,
    JsonSchema,
    JsonSchemaDocument,
    JsonSchemaType,
    ObjectSchema,
)
from schema_to.resolve._json_schema import JsonSchemaRefResolver

__all__ = ["PostgresGenerator"]

# ---------------------------------------------------------------------------
# Type dispatch table for simple (non-string, non-array) types
# ---------------------------------------------------------------------------

_SIMPLE_TYPE_MAP: dict[JsonSchemaType, DataType] = {
    JsonSchemaType.INTEGER: DataType.integer(),
    JsonSchemaType.NUMBER: DataType(base=PgDataType.DOUBLE_PRECISION),
    JsonSchemaType.BOOLEAN: DataType.boolean(),
    JsonSchemaType.OBJECT: DataType.jsonb(),
}

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _ref_to_table_name(ref: str) -> str:
    """Extract a table name from a `$ref` like `"#/$defs/MyModel"`."""
    fragment = ref.split("#", 1)[-1] if "#" in ref else ref
    part = fragment.rstrip("/").rsplit("/", 1)[-1]
    return safe_sql_identifier(part) if part else "unknown"


def _sql_literal(v: JsonValue) -> str:
    """Format a JSON value as a SQL literal for use in CHECK expressions.

    Handles `null`, booleans, integers, floats, and strings.  Composite
    values (lists, dicts) fall back to a quoted string representation.
    """
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else str(v)
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return "'" + str(v).replace("'", "''") + "'"


def _num_literal(v: float) -> str:
    """Format a numeric value, dropping the decimal point when it is an integer."""
    return str(int(v)) if v == int(v) else str(v)


def _is_object_schema(schema: ObjectSchema) -> bool:
    """Return `True` if the schema should map to a `CREATE TABLE` statement."""
    if schema.type == JsonSchemaType.OBJECT:
        return True
    if isinstance(schema.type, frozenset) and JsonSchemaType.OBJECT in schema.type:
        return True
    return schema.type is None and schema.properties is not None


def _unwrap_nullable(schema: ObjectSchema) -> tuple[bool, JsonSchema]:
    """Peel off `anyOf` / `oneOf` `[T, null]` or type-array `[T, null]`.

    Returns `(is_extra_nullable, effective_schema)`.  When the schema already
    expresses nullability through one of these patterns, `is_extra_nullable`
    is `True` and `effective_schema` is the single non-null branch.  Otherwise
    both values reflect the original schema unchanged.
    """
    for applicator in (schema.any_of, schema.one_of):
        if applicator is not None:
            non_null = [
                s
                for s in applicator
                if not (isinstance(s, ObjectSchema) and s.type == JsonSchemaType.NULL)
            ]
            if len(applicator) > len(non_null) and len(non_null) == 1:
                return True, non_null[0]
    if isinstance(schema.type, frozenset) and JsonSchemaType.NULL in schema.type:
        return True, schema
    return False, schema


def _join_checks(exprs: list[str]) -> str | None:
    """Combine check expressions into a single AND-joined string, or `None`."""
    if not exprs:
        return None
    return " AND ".join(f"({e})" for e in exprs)


def _string_type(schema: ObjectSchema) -> DataType:
    """Map a `type: string` schema (with format / maxLength) to a `DataType`."""
    fmt = schema.format or ""
    if fmt in {"date-time", "datetime"}:
        return DataType(base=PgDataType.TIMESTAMPTZ)
    if fmt == "date":
        return DataType(base=PgDataType.DATE)
    if fmt == "time":
        return DataType(base=PgDataType.TIME)
    if fmt == "uuid":
        return DataType.uuid()
    if fmt == "byte":
        return DataType(base=PgDataType.BYTEA)
    if schema.max_length is not None:
        return DataType(base=PgDataType.VARCHAR, precision=schema.max_length)
    return DataType.text()


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


@dataclass
class PostgresGenerator(Generator[JsonSchemaDocument, SqlScript]):
    """Generates a `SqlScript` with PostgreSQL DDL from a JSON Schema 2020-12 document.

    Object-typed root and `$defs` entries each become `CREATE TABLE` statements.
    Column types follow format-then-type mapping with `x-pg-type` extension overrides.

    Attributes:
        resolver: Optional resolver for cross-document `$ref` lookup.
    """

    resolver: JsonSchemaRefResolver | None = None
    _warnings: list[TranspilationWarning] = field(default_factory=list, repr=False)

    @property
    def warnings(self) -> Sequence[TranspilationWarning]:
        return list(self._warnings)

    def apply(self, input: JsonSchemaDocument) -> Result[SqlScript]:
        self._warnings = []
        try:
            return Ok(self._apply(input))
        except GenerationError as exc:
            return Err((exc,))

    def _apply(self, input: JsonSchemaDocument) -> SqlScript:
        if isinstance(input.root, BooleanSchema):
            raise GenerationError(
                "Root schema is a boolean schema; cannot generate PostgreSQL DDL."
            )
        root = input.root
        if not _is_object_schema(root):
            raise GenerationError(
                f"Root schema type {root.type!r} is not 'object'; "
                "cannot generate a CREATE TABLE statement."
            )

        statements: list[CreateTableStmt] = []

        # $defs: each object-typed entry becomes its own table.
        if root.defs:
            for def_name, def_schema in root.defs.items():
                if isinstance(def_schema, ObjectSchema) and _is_object_schema(def_schema):
                    table_name = safe_sql_identifier(def_schema.title or def_name)
                    statements.append(
                        self._schema_to_table(def_schema, table_name, input.source_id)
                    )

        # Root schema → its own table.
        root_table = self._root_table_name(input)
        statements.append(self._schema_to_table(root, root_table, input.source_id))

        return SqlScript(statements=tuple(statements), source_ids=(input.source_id,))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _root_table_name(self, doc: JsonSchemaDocument) -> str:
        if isinstance(doc.root, ObjectSchema) and doc.root.title:
            return safe_sql_identifier(doc.root.title)
        name = doc.display_name or doc.source_id.rstrip("/").rsplit("/", 1)[-1]
        return safe_sql_identifier(name)

    def _schema_to_table(
        self, schema: ObjectSchema, table_name: str, source_id: str
    ) -> CreateTableStmt:
        required_set = set(schema.required or frozenset())
        columns = [
            self._prop_to_column(prop_name, prop_schema, required=prop_name in required_set)
            for prop_name, prop_schema in (schema.properties or {}).items()
        ]
        return CreateTableStmt(
            table_name=table_name,
            columns=tuple(columns),
            if_not_exists=True,
            doc=schema.description or schema.title,
            source_ids=(source_id,),
        )

    def _prop_to_column(
        self,
        prop_name: str,
        schema: JsonSchema,
        *,
        required: bool,
    ) -> ColumnDef:
        col_name = safe_sql_identifier(prop_name)

        if isinstance(schema, BooleanSchema):
            return ColumnDef(
                name=col_name,
                data_type=DataType.jsonb(),
                constraint=ColumnConstraint(not_null=required),
            )

        extra_nullable, eff_schema = _unwrap_nullable(schema)
        nullable = not required or extra_nullable

        data_type = self._schema_to_data_type(eff_schema, col_name)
        check_exprs = (
            self._check_exprs(eff_schema, col_name, data_type)
            if isinstance(eff_schema, ObjectSchema)
            else []
        )

        doc = schema.description or schema.title
        return ColumnDef(
            name=col_name,
            data_type=data_type,
            constraint=ColumnConstraint(
                not_null=not nullable,
                check_expr=_join_checks(check_exprs),
            ),
            doc=doc,
        )

    def _schema_to_data_type(self, schema: JsonSchema, col_name: str) -> DataType:
        if isinstance(schema, BooleanSchema):
            return DataType.jsonb()

        # x-pg-type extension override.
        pg_type_ext = (schema.extensions or {}).get("x-pg-type")
        if isinstance(pg_type_ext, str):
            return DataType(base=PgDataType.CUSTOM, custom=pg_type_ext)

        # $ref → JSONB.
        if schema.ref:
            return DataType.jsonb()

        # anyOf / oneOf: collapse [T, null] → T; otherwise JSONB.
        for applicator in (schema.any_of, schema.one_of):
            if applicator is not None:
                non_null = [
                    s
                    for s in applicator
                    if not (isinstance(s, ObjectSchema) and s.type == JsonSchemaType.NULL)
                ]
                if len(non_null) == 1:
                    return self._schema_to_data_type(non_null[0], col_name)
                self._warn(
                    f"anyOf/oneOf with {len(applicator)} branches; using JSONB for {col_name!r}.",
                    code="anyof-fallback",
                    schema=schema,
                )
                return DataType.jsonb()

        # Type array [T, null] → T.
        if isinstance(schema.type, frozenset):
            non_null = schema.type - {JsonSchemaType.NULL}
            if len(non_null) == 1:
                return self._type_to_data_type(next(iter(non_null)), schema, col_name)
            self._warn(
                f"Union type {sorted(str(t) for t in schema.type)}; using JSONB for {col_name!r}.",
                code="multi-type-fallback",
                schema=schema,
            )
            return DataType.jsonb()

        if schema.type is not None:
            return self._type_to_data_type(schema.type, schema, col_name)

        return DataType.jsonb()

    def _type_to_data_type(
        self, t: JsonSchemaType, schema: ObjectSchema, col_name: str
    ) -> DataType:
        if t == JsonSchemaType.STRING:
            return _string_type(schema)
        if t == JsonSchemaType.ARRAY:
            return self._array_type(schema, col_name)
        if t == JsonSchemaType.NULL:
            self._warn(
                f"Column {col_name!r} has type null; falling back to TEXT.",
                code="null-type-fallback",
                schema=schema,
            )
            return DataType.text()
        return _SIMPLE_TYPE_MAP.get(t, DataType.jsonb())

    def _array_type(self, schema: ObjectSchema, col_name: str) -> DataType:
        if schema.items is not None and isinstance(schema.items, ObjectSchema):
            item_type = self._schema_to_data_type(schema.items, col_name + "_item")
            if item_type.base not in {PgDataType.JSONB, PgDataType.ARRAY}:
                return DataType.array_of(item_type)
        self._warn(
            f"Array with non-simple items; using JSONB for {col_name!r}.",
            code="array-fallback",
            schema=schema,
        )
        return DataType.jsonb()

    def _check_exprs(
        self, schema: ObjectSchema, col_name: str, data_type: DataType
    ) -> list[str]:
        exprs: list[str] = []

        # Numeric range constraints.
        if schema.minimum is not None:
            exprs.append(f"{col_name} >= {_num_literal(schema.minimum)}")
        if schema.exclusive_minimum is not None:
            exprs.append(f"{col_name} > {_num_literal(schema.exclusive_minimum)}")
        if schema.maximum is not None:
            exprs.append(f"{col_name} <= {_num_literal(schema.maximum)}")
        if schema.exclusive_maximum is not None:
            exprs.append(f"{col_name} < {_num_literal(schema.exclusive_maximum)}")

        # String length constraints.
        if schema.min_length is not None:
            exprs.append(f"char_length({col_name}) >= {schema.min_length}")
        # Skip maxLength check when VARCHAR already enforces it at the type level.
        if schema.max_length is not None and data_type.base != PgDataType.VARCHAR:
            exprs.append(f"char_length({col_name}) <= {schema.max_length}")

        # Pattern.
        if schema.pattern is not None:
            escaped = schema.pattern.replace("'", "''")
            exprs.append(f"{col_name} ~ '{escaped}'")

        # Enum: IN (...) with non-null values.
        if schema.enum is not None:
            non_null_vals = [v for v in schema.enum if v is not None]
            if non_null_vals:
                vals_str = ", ".join(_sql_literal(v) for v in non_null_vals)
                exprs.append(f"{col_name} IN ({vals_str})")

        # Const: equality check.
        if schema.const is not None:
            exprs.append(f"{col_name} = {_sql_literal(schema.const.value)}")

        return exprs

    def _warn(self, msg: str, *, code: str, schema: ObjectSchema) -> None:
        loc: SourceLocation | None = None
        if schema.source_ref:
            loc = SourceLocation(
                source_id=schema.source_ref.source_id,
                json_pointer=schema.source_ref.json_pointer,
            )
        self._warnings.append(TranspilationWarning(msg, code=code, location=loc))
