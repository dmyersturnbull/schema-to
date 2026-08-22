"""Reading of the `x-pg-*` extension keywords that drive PostgreSQL generation.

These keywords supply info necessary for PostgreSQL definitions that's not carried in JSON Schema.

| Keyword               | Goes on  | Value                                          | Effect                                     |
|-----------------------|----------|------------------------------------------------|--------------------------------------------|
| `x-pg-table`          | schema   | table name                                     | Emit a table. Absent: no table.            |
| `x-pg-pk-for`         | schema   | table name                                     | Mark as the primary-key type of that table; a `$ref` to it elsewhere becomes a foreign key. |
| `x-pg-primary-key`    | schema   | column name, or a list of them                 | Composite key. Defaults to `id`.           |
| `x-pg-primary-key`    | property | `true`                                         | Single-column key.                         |
| `x-pg-indexes`        | schema   | list of `{columns, name, method, unique, where}` | Composite or partial indexes.            |
| `x-pg-index`          | property | `true`, or `{name, method, unique, where}`     | Index on this column.                      |
| `x-pg-overflow`       | schema   | column name                                    | JSONB column for undeclared keys.          |
| `x-pg-extra-columns`  | schema   | list of `{name, type, default, not-null}`      | Columns with no property behind them.      |
| `x-pg-refs`           | property | table name, or `{table, column, on-delete, on-update}` | Foreign key.                       |
| `x-pg-column`         | property | column name                                    | Rename the column.                         |
| `x-pg-unique`         | property | `true`                                         | `UNIQUE` constraint.                       |
| `x-pg-type`           | property | a SQL type, e.g. `jsonb`                       | Override the inferred type.                |
| `x-pg-skip`           | property | `true`                                         | Do not emit a column.                      |

Example using these:

```yaml
run-version-data:
  x-pg-table: run_version
  x-pg-primary-key: [run, alias]
  x-pg-overflow: unmodelled
  x-pg-extra-columns:
    - name: loaded_at
      type: timestamptz
      not-null: true
      default: now()
  x-pg-indexes:
    - columns: [author, insert_time]
      method: btree
  type: object
  properties:
    run:
      type: string
      x-pg-refs: run
    alias:
      type: integer
    author:
      type: string
      x-pg-refs: {table: author, on-delete: restrict}
      x-pg-index: true
    is-official:
      type: boolean
      x-pg-column: official # `is-official` would otherwise be `is_official`
    wells:
      type: array
      x-pg-type: jsonb
    internal-note:
      type: string
      x-pg-skip: true
```

`x-pg-pk-for` marks a schema as the primary-key type of a table.
A `$ref` to it anywhere outside that table's own schema becomes a foreign key
to the table's primary key, with no `x-pg-refs` needed:

```yaml
author-id:
  type: string
  pattern: "^[A-Z][a-z]*$"
  x-pg-pk-for: authors

author:
  x-pg-table: authors
  type: object
  properties:
    id:
      $ref: "#/author-id"

book:
  x-pg-table: books
  type: object
  properties:
    author:
      $ref: "#/author-id" # foreign key to authors(id)
    title:
      type: string
```

A keyword whose value has the wrong shape raises `KeywordError`,
which is normally translated into a [TranspilationError][].
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from schema_to.ast.sql import ForeignKeyAction, IndexMethod
from schema_to.core import as_array, as_object
from schema_to.errors import KeywordError

if TYPE_CHECKING:
    from schema_to.core import JsonValue

__all__ = [
    "COLUMN",
    "EXTRA_COLUMNS",
    "INDEX",
    "INDEXES",
    "OVERFLOW",
    "PK_FOR",
    "PRIMARY_KEY",
    "REFS",
    "SKIP",
    "TABLE",
    "TYPE",
    "UNIQUE",
    "ExtraColumn",
    "ForeignKeyRef",
    "IndexRequest",
    "PropertyKeywords",
    "TableKeywords",
    "read_pk_for",
    "read_property_keywords",
    "read_table_keywords",
]

TABLE = "x-pg-table"
PK_FOR = "x-pg-pk-for"
PRIMARY_KEY = "x-pg-primary-key"
OVERFLOW = "x-pg-overflow"
EXTRA_COLUMNS = "x-pg-extra-columns"
INDEXES = "x-pg-indexes"
COLUMN = "x-pg-column"
UNIQUE = "x-pg-unique"
REFS = "x-pg-refs"
INDEX = "x-pg-index"
TYPE = "x-pg-type"
SKIP = "x-pg-skip"


@dataclass(frozen=True, slots=True)
class ForeignKeyRef:
    """A resolved `x-pg-refs` value.

    Attributes:
        table: Referenced table name.
        column: Referenced column, or `None` to reference its primary key.
    """

    table: str
    column: str | None = None
    on_delete: ForeignKeyAction = ForeignKeyAction.NO_ACTION
    on_update: ForeignKeyAction = ForeignKeyAction.NO_ACTION


@dataclass(frozen=True, slots=True)
class IndexRequest:
    """A resolved `x-pg-index` / `x-pg-indexes` entry."""

    columns: tuple[str, ...]
    name: str | None = None
    method: IndexMethod = IndexMethod.BTREE
    unique: bool = False
    where: str | None = None


@dataclass(frozen=True, slots=True)
class ExtraColumn:
    """A column declared by `x-pg-extra-columns`, with no property behind it.

    For values the database owns rather than the API:
    a load timestamp, a tenant discriminator, a trigger-maintained counter.
    They have no schema, so their type is given literally.
    """

    name: str
    sql_type: str
    default: str | None = None
    not_null: bool = False


@dataclass(frozen=True, slots=True)
class TableKeywords:
    """The `x-pg-*` keywords read from a schema that becomes a table."""

    table: str | None = None
    primary_key: tuple[str, ...] = ()
    overflow_column: str | None = None
    extra_columns: tuple[ExtraColumn, ...] = ()
    indexes: tuple[IndexRequest, ...] = ()


@dataclass(frozen=True, slots=True)
class PropertyKeywords:
    """The `x-pg-*` keywords read from one property of a table schema."""

    column: str | None = None
    primary_key: bool = False
    unique: bool = False
    refs: ForeignKeyRef | None = None
    index: IndexRequest | None = None
    sql_type: str | None = None
    skip: bool = False


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def read_table_keywords(extensions: Mapping[str, JsonValue], *, where: str) -> TableKeywords:
    """Read the schema-level `x-pg-*` keywords from `extensions`.

    Arguments:
        where: Human-readable name of the schema, used in error messages.
    """
    return TableKeywords(
        table=_opt_str(extensions, TABLE, where=where),
        primary_key=_str_tuple(extensions, PRIMARY_KEY, where=where),
        overflow_column=_opt_str(extensions, OVERFLOW, where=where),
        extra_columns=_read_extra_columns(extensions, where=where),
        indexes=_read_indexes(extensions, where=where),
    )


def read_property_keywords(extensions: Mapping[str, JsonValue], *, where: str) -> PropertyKeywords:
    """Read the property-level `x-pg-*` keywords from `extensions`.

    Arguments:
        where: Human-readable name of the property, used in error messages.
    """
    return PropertyKeywords(
        column=_opt_str(extensions, COLUMN, where=where),
        primary_key=_flag(extensions, PRIMARY_KEY, where=where),
        unique=_flag(extensions, UNIQUE, where=where),
        refs=_read_refs(extensions, where=where),
        index=_read_index(extensions, where=where),
        sql_type=_opt_str(extensions, TYPE, where=where),
        skip=_flag(extensions, SKIP, where=where),
    )


def read_pk_for(extensions: Mapping[str, JsonValue], *, where: str) -> str | None:
    """Read `x-pg-pk-for` from `extensions`: the table this schema is the primary key type of.

    Arguments:
        where: Human-readable name of the schema, used in error messages.
    """
    return _opt_str(extensions, PK_FOR, where=where)


# ---------------------------------------------------------------------------
# Composite keywords
# ---------------------------------------------------------------------------


def _read_refs(extensions: Mapping[str, JsonValue], *, where: str) -> ForeignKeyRef | None:
    raw = extensions.get(REFS)
    if raw is None:
        return None
    if isinstance(raw, str):
        return ForeignKeyRef(table=raw)
    entries = as_object(raw)
    if entries is None:
        raise _bad(REFS, where, "a table name or an object")
    fields = _as_str_map(entries, REFS, where)
    table = fields.get("table")
    if not table:
        raise _bad(REFS, where, "an object with a `table`")
    return ForeignKeyRef(
        table=table,
        column=fields.get("column"),
        on_delete=_action(fields.get("on-delete"), REFS, where),
        on_update=_action(fields.get("on-update"), REFS, where),
    )


def _read_index(extensions: Mapping[str, JsonValue], *, where: str) -> IndexRequest | None:
    raw = extensions.get(INDEX)
    if raw is None or raw is False:
        return None
    if raw is True:
        return IndexRequest(columns=())
    fields = as_object(raw)
    if fields is None:
        raise _bad(INDEX, where, "`true` or an object")
    return _index_from(fields, columns=(), where=where, keyword=INDEX)


def _read_extra_columns(
    extensions: Mapping[str, JsonValue], *, where: str
) -> tuple[ExtraColumn, ...]:
    raw = extensions.get(EXTRA_COLUMNS)
    if raw is None:
        return ()
    entries = as_array(raw)
    if entries is None:
        raise _bad(EXTRA_COLUMNS, where, "a list of column objects")
    out: list[ExtraColumn] = []
    for entry in entries:
        fields = as_object(entry)
        if fields is None:
            raise _bad(EXTRA_COLUMNS, where, "a list of column objects")
        name = _opt_str(fields, "name", where=where)
        sql_type = _opt_str(fields, "type", where=where)
        if not name or not sql_type:
            raise _bad(EXTRA_COLUMNS, where, "objects with both a `name` and a `type`")
        out.append(
            ExtraColumn(
                name=name,
                sql_type=sql_type,
                default=_opt_str(fields, "default", where=where),
                not_null=_flag(fields, "not-null", where=where),
            )
        )
    return tuple(out)


def _read_indexes(extensions: Mapping[str, JsonValue], *, where: str) -> tuple[IndexRequest, ...]:
    raw = extensions.get(INDEXES)
    if raw is None:
        return ()
    entries = as_array(raw)
    if entries is None:
        raise _bad(INDEXES, where, "a list of index objects")
    out: list[IndexRequest] = []
    for entry in entries:
        fields = as_object(entry)
        if fields is None:
            raise _bad(INDEXES, where, "a list of index objects")
        columns = _str_tuple(fields, "columns", where=where)
        if not columns:
            raise _bad(INDEXES, where, "objects with a non-empty `columns`")
        out.append(_index_from(fields, columns=columns, where=where, keyword=INDEXES))
    return tuple(out)


def _index_from(
    raw: Mapping[str, JsonValue], *, columns: tuple[str, ...], where: str, keyword: str
) -> IndexRequest:
    method_name = _opt_str(raw, "method", where=where)
    method = IndexMethod.BTREE
    if method_name is not None:
        found = _member(IndexMethod, method_name)
        if found is None:
            allowed = ", ".join(m.value for m in IndexMethod)
            raise _bad(keyword, where, f"a `method` of one of: {allowed}")
        method = found
    return IndexRequest(
        columns=columns,
        name=_opt_str(raw, "name", where=where),
        method=method,
        unique=_flag(raw, "unique", where=where),
        where=_opt_str(raw, "where", where=where),
    )


def _action(value: str | None, keyword: str, where: str) -> ForeignKeyAction:
    if value is None:
        return ForeignKeyAction.NO_ACTION
    found = _member(ForeignKeyAction, value.replace("-", " "))
    if found is None:
        allowed = ", ".join(a.value.replace(" ", "-") for a in ForeignKeyAction)
        raise _bad(keyword, where, f"an action of one of: {allowed}")
    return found


# ---------------------------------------------------------------------------
# Scalar readers
# ---------------------------------------------------------------------------


def _opt_str(raw: Mapping[str, JsonValue], key: str, *, where: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise _bad(key, where, "a non-empty string")
    return value


def _flag(raw: Mapping[str, JsonValue], key: str, *, where: str) -> bool:
    value = raw.get(key)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise _bad(key, where, "`true` or `false`")
    return value


def _str_tuple(raw: Mapping[str, JsonValue], key: str, *, where: str) -> tuple[str, ...]:
    """Read a keyword accepting either one string or a list of them."""
    value = raw.get(key)
    if value is None or value is False:
        return ()
    if isinstance(value, str):
        return (value,)
    entries = as_array(value)
    if entries is None or not all(isinstance(v, str) and v for v in entries):
        raise _bad(key, where, "a string or a list of strings")
    return tuple(v for v in entries if isinstance(v, str))


def _as_str_map(raw: Mapping[str, JsonValue], keyword: str, where: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str):
            raise _bad(keyword, where, "an object whose values are all strings")
        out[key] = value
    return out


def _member[E: (ForeignKeyAction, IndexMethod)](enum_cls: type[E], value: str) -> E | None:
    return next((m for m in enum_cls if m.value == value.lower()), None)


def _bad(keyword: str, where: str, expected: str) -> KeywordError:
    return KeywordError(f"{keyword} on {where} must be {expected}.")
