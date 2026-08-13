"""Generator: JSON Schema 2020-12 CST → PostgreSQL DDL AST.

## Mapping rules

- The root schema and each `$defs` entry are flattened (see `generate._compose`)
  and become a `CREATE TABLE` statement if the result is `object`-typed.
  Flattening merges `allOf` branches and, given a resolver, follows `$ref`,
  so a schema composed from several documents still yields one table.
- Required properties get `NOT NULL`; optional properties are nullable.
- Type mapping follows format-then-type priority with `x-pg-type` overrides:
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
- Numeric constraints map to `CHECK` expressions; `pattern` maps to `~`.
- `enum` values produce `CHECK (col IN (...))`.
- `title` / `description` populate `doc` for `COMMENT ON` emission.
- `x-pg-type` overrides the inferred type with a literal type string.
- Unsupported constructs emit `TranspilationWarning` and fall back to `JSONB`.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import orjson

from schema_to.ast.sql import (
    ColumnConstraint,
    ColumnDef,
    CreateTableStmt,
    DataType,
    PgDataType,
    SqlScript,
)
from schema_to.cst.json_schema import (
    BooleanApplicatorKeyword,
    BooleanSchema,
    JsonSchema,
    JsonSchemaDocument,
    JsonSchemaType,
    ObjectSchema,
    is_object_schema,
)
from schema_to.errors import GenerationError, SourceLocation, TranspilationWarning
from schema_to.generate._compose import SchemaFlattener
from schema_to.generate._names import quote_sql_identifier, safe_sql_identifier
from schema_to.pipeline import Transformer
from schema_to.result import Err, Ok, Result
from schema_to.serialize.json_schema import JsonSchemaSerializer

if TYPE_CHECKING:
    from collections.abc import Sequence

    from schema_to.core import JsonValue
    from schema_to.resolve.json_schema import JsonSchemaRefResolver

__all__ = ["ColumnBuilder", "PostgresTransformer"]

# ---------------------------------------------------------------------------
# Type dispatch table for simple (non-string, non-array) types
# ---------------------------------------------------------------------------

# SQL type names that `x-pg-type` may give which the generator also understands
# structurally, so that an explicit override is not opaque to later decisions.
_PG_TYPES_BY_NAME: dict[str, PgDataType] = {"json": PgDataType.JSON, "jsonb": PgDataType.JSONB}

_SIMPLE_TYPE_MAP: dict[JsonSchemaType, DataType] = {
    JsonSchemaType.INTEGER: DataType.integer(),
    JsonSchemaType.NUMBER: DataType(base=PgDataType.DOUBLE_PRECISION),
    JsonSchemaType.BOOLEAN: DataType.boolean(),
    JsonSchemaType.OBJECT: DataType.jsonb(),
}

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


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
    """Format a numeric value, dropping the `.0` suffix for whole numbers."""
    return str(v).removesuffix(".0")


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
                if not (isinstance(s, ObjectSchema) and s.get_types() == {JsonSchemaType.NULL})
            ]
            if len(applicator) > len(non_null) == 1:
                return True, non_null[0]
    non_null_from_type = schema.get_types() - {JsonSchemaType.NULL}
    if JsonSchemaType.NULL in schema.get_types() and non_null_from_type:
        return True, schema
    return False, schema


def _base_uri(schema: JsonSchema) -> str:
    """Return the document a schema came from, for resolving its relative references."""
    return schema.source_ref.source_id if schema.source_ref else ""


def _join_checks(exprs: list[str]) -> str | None:
    """Combine check expressions into a single AND-joined string, or `None`."""
    if not exprs:
        return None
    return " AND ".join(f"({e})" for e in exprs)


# ruff:ignore[too-many-return-statements]  # All `return`s are in the `match`.
def _string_type(schema: ObjectSchema) -> DataType:
    """Map a `type: string` schema (with format / maxLength) to a `DataType`."""
    match schema.format:
        case "date-time":
            return DataType(base=PgDataType.TIMESTAMPTZ)
        case "date":
            return DataType(base=PgDataType.DATE)
        case "time":
            return DataType(base=PgDataType.TIME)
        case "uuid":
            return DataType.uuid()
        case "byte":
            return DataType(base=PgDataType.BYTEA)
        case _:
            if schema.max_length is not None:
                return DataType(base=PgDataType.VARCHAR, precision=schema.max_length)
            return DataType.text()


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


@dataclass
class ColumnBuilder:
    """Builds one `ColumnDef` from a property schema.

    Shared by the single-document and table-set generators, which differ in how they
    choose tables and names but map a property to a column identically.

    Attributes:
        resolver: Resolver used when a nested `$ref` still needs following.
        validate_json: Emit a `pg_jsonschema` `CHECK` for JSON and JSONB columns.
    """

    resolver: JsonSchemaRefResolver | None = None
    validate_json: bool = False
    _warnings: list[TranspilationWarning] = field(default_factory=list, repr=False)

    @property
    def warnings(self) -> Sequence[TranspilationWarning]:
        return list(self._warnings)

    def build(
        self, col_name: str, schema: JsonSchema, *, required: bool, sql_type: str | None = None
    ) -> ColumnDef:
        """Build one column from a property schema.

        Arguments:
            col_name: The column name, already sanitised.
            schema: The property schema, already flattened.
            required: Whether the property is in the schema's `required`.
            sql_type: A SQL type overriding the inferred one.
        """
        if isinstance(schema, BooleanSchema):
            return ColumnDef(
                name=col_name,
                data_type=DataType.jsonb(),
                constraint=ColumnConstraint(not_null=required),
            )

        extra_nullable, eff_schema = _unwrap_nullable(schema)
        nullable = not required or extra_nullable

        data_type = self._resolve_data_type(eff_schema, col_name, sql_type=sql_type)
        check = (
            self._check_exprs(eff_schema, quote_sql_identifier(col_name), data_type)
            if isinstance(eff_schema, ObjectSchema)
            else ColumnConstraint()
        )
        check_expr = self._with_json_check(
            check.check_expr, eff_schema, quote_sql_identifier(col_name), data_type
        )

        doc = schema.description or schema.title
        return ColumnDef(
            name=col_name,
            data_type=data_type,
            constraint=ColumnConstraint(not_null=not nullable, check_expr=check_expr),
            doc=doc,
        )

    def _with_json_check(
        self, base: str | None, schema: JsonSchema, col_name: str, data_type: DataType
    ) -> str | None:
        """Append a `pg_jsonschema` validation check for a JSON/JSONB column."""
        if not self.validate_json or data_type.base not in {PgDataType.JSON, PgDataType.JSONB}:
            return base
        if not isinstance(schema, ObjectSchema):
            return base
        # pg_jsonschema evaluates a literal with no way to fetch a reference,
        # so every `$ref` below this column has to be resolved away first.
        standalone = SchemaFlattener(resolver=self.resolver).inline(
            schema, base_uri=_base_uri(schema)
        )
        self._warnings.extend(standalone.warnings)
        to_dump = JsonSchemaSerializer().serialize(standalone.schema)
        schema_json = orjson.dumps(to_dump).decode("utf-8")
        fn = "jsonb_matches_schema" if data_type.base == PgDataType.JSONB else "json_matches_schema"
        escaped = schema_json.replace("'", "''")
        json_check = f"{fn}('{escaped}', {col_name})"
        return f"{base} AND {json_check}" if base else json_check

    # ruff:ignore[too-many-return-statements]  # There's no helpful way to consolidate return statements.
    def _schema_to_data_type(self, schema: JsonSchema, col_name: str) -> DataType:
        # Boolean schema.
        if isinstance(schema, BooleanSchema):
            return DataType.jsonb()

        # x-pg-type extension override.
        pg_type_ext = (schema.get_extensions()).get("x-pg-type")
        if isinstance(pg_type_ext, str):
            return DataType(base=PgDataType.CUSTOM, custom=pg_type_ext)

        # $ref → JSONB.
        if schema.ref:
            return DataType.jsonb()

        # anyOf / oneOf: collapse [T, null] → T; otherwise JSONB.
        applicator_name, applicator = schema.get_boolean_applicator(
            only={BooleanApplicatorKeyword.ANY_OF, BooleanApplicatorKeyword.ONE_OF}
        )
        if applicator_name is not None:
            non_null = [s for s in applicator if s.get_types() != {JsonSchemaType.NULL}]
            if len(non_null) == 1:
                return self._schema_to_data_type(non_null[0], col_name)
            self._warn(
                f"anyOf/oneOf with {len(applicator)} branches; using JSONB for {col_name!r}.",
                code="anyof-fallback",
                schema=schema,
            )
            return DataType.jsonb()

        # Type-based dispatch using get_types().
        types = schema.get_types()
        non_null_types = types - {JsonSchemaType.NULL}
        if len(non_null_types) == 1:
            return self._type_to_data_type(next(iter(non_null_types)), schema, col_name)
        if non_null_types:
            self._warn(
                f"Union type {sorted(str(t) for t in types)}; using JSONB for {col_name!r}.",
                code="multi-type-fallback",
                schema=schema,
            )
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

    # ruff:ignore[complex-structure]  # Mostly shared structure
    def _check_exprs(
        self, schema: ObjectSchema, col_name: str, data_type: DataType
    ) -> ColumnConstraint:
        """Build the `CHECK` expression for a column.

        `col_name` must already be quoted: these expressions name the column, so a
        reserved word such as `end` needs the same quoting the column definition uses.
        """
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

        return ColumnConstraint(check_expr=_join_checks(exprs))

    def _resolve_data_type(
        self, schema: JsonSchema, col_name: str, *, sql_type: str | None
    ) -> DataType:
        """Use the declared SQL type if there is one, else infer from the schema."""
        if sql_type is None:
            return self._schema_to_data_type(schema, col_name)
        # Recognise the JSON types by name rather than treating every override as opaque,
        # so that `x-pg-type: jsonb` still gets a pg_jsonschema check like an inferred one.
        named = _PG_TYPES_BY_NAME.get(sql_type.strip().lower())
        if named is not None:
            return DataType(base=named)
        return DataType(base=PgDataType.CUSTOM, custom=sql_type)

    def _warn(self, msg: str, *, code: str, schema: ObjectSchema) -> None:
        loc: SourceLocation | None = None
        if schema.source_ref:
            loc = SourceLocation(
                doc_id=schema.source_ref.source_id, json_pointer=schema.source_ref.json_pointer
            )
        self._warnings.append(TranspilationWarning(msg, code=code, location=loc))


@dataclass
class PostgresTransformer(Transformer[JsonSchemaDocument, SqlScript]):
    """Generates a `SqlScript` with PostgreSQL DDL from a JSON Schema 2020-12 document.

    Object-typed root and `$defs` entries each become `CREATE TABLE` statements.
    Column types follow format-then-type mapping with `x-pg-type` extension overrides.

    Attributes:
        resolver: Optional resolver for cross-document `$ref` lookup.
        validate_json: When `True`, emit  `pg_jsonschema` `CHECK` constraints,
          which validate each JSON/JSONB column against its sub-schema,
          and a `CREATE EXTENSION IF NOT EXISTS pg_jsonschema;` preamble.
    """

    resolver: JsonSchemaRefResolver | None = None
    validate_json: bool = False
    _warnings: list[TranspilationWarning] = field(default_factory=list, repr=False)

    @property
    def warnings(self) -> Sequence[TranspilationWarning]:
        return list(self._warnings)

    def apply(self, input: JsonSchemaDocument) -> Result[SqlScript]:
        self._warnings.clear()
        try:
            return Ok(self._apply(input))
        except GenerationError as exc:
            return Err((exc,))

    def _apply(self, input: JsonSchemaDocument) -> SqlScript:
        sid = input.source_id
        root: ObjectSchema = self._get_as_object_schema(input)
        def_stmts = [
            self._schema_to_table(flat, safe_sql_identifier(flat.title or def_name), sid)
            for def_name, def_schema in (root.get_defs()).items()
            for flat in [self._flatten(def_schema, base_uri=sid)]
            if is_object_schema(flat)
        ]
        root_stmt = self._schema_to_table(root, safe_sql_identifier(root.title or sid), sid)
        preamble = "CREATE EXTENSION IF NOT EXISTS pg_jsonschema;" if self.validate_json else None
        return SqlScript(statements=(*def_stmts, root_stmt), source_ids=(sid,), preamble=preamble)

    def _get_as_object_schema(self, input: JsonSchemaDocument) -> ObjectSchema:
        """Return the root as a flattened object schema, or fail with what it is instead."""
        root = self._flatten(input.root, base_uri=input.source_id)
        if is_object_schema(root):
            return root
        if isinstance(root, BooleanSchema):
            found = "a boolean schema"
        else:
            types = sorted(str(t) for t in root.get_types())
            found = f"type {', '.join(types)}" if types else "no type and no properties"
        msg = f"A table requires an object schema at the document root; found {found}."
        raise GenerationError(msg)

    def _flatten(self, schema: JsonSchema, *, base_uri: str) -> JsonSchema:
        """Merge `allOf` branches and the `$ref` target into a single schema."""
        result = SchemaFlattener(resolver=self.resolver).flatten(schema, base_uri=base_uri)
        self._warnings.extend(result.warnings)
        return result.schema

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _schema_to_table(
        self, schema: ObjectSchema, table_name: str, source_id: str
    ) -> CreateTableStmt:
        required_set = schema.get_required()
        builder = ColumnBuilder(resolver=self.resolver, validate_json=self.validate_json)
        columns = [
            builder.build(
                safe_sql_identifier(prop_name),
                self._flatten(prop_schema, base_uri=source_id),
                required=prop_name in required_set,
            )
            for prop_name, prop_schema in (schema.properties or {}).items()
        ]
        self._warnings.extend(builder.warnings)
        return CreateTableStmt(
            table_name=table_name,
            columns=tuple(columns),
            if_not_exists=True,
            doc=schema.description or schema.title,
            source_ids=(source_id,),
        )
