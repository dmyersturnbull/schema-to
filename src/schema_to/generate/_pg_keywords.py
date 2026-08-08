"""Reading of the `x-pg-*` extension keywords that drive PostgreSQL generation.

JSON Schema describes the shape of a value; it does not say which schemas are tables,
which properties are keys, or how one resource points at another.
These keywords supply exactly that, and nothing else — every one of them is a
persistence decision that no standard keyword can express.

Schema-level keywords:

| Keyword            | Value                                    | Effect                          |
|--------------------|------------------------------------------|---------------------------------|
| `x-pg-table`       | table name                               | Emit a table. Absent: no table. |
| `x-pg-primary-key` | column name, or a list of them           | Composite primary key.          |
| `x-pg-extras`      | column name                              | JSONB column for undeclared keys. |
| `x-pg-indexes`     | list of index objects (see below)        | Composite or expression indexes. |

Property-level keywords:

| Keyword            | Value                                    | Effect                          |
|--------------------|------------------------------------------|---------------------------------|
| `x-pg-column`      | column name                              | Rename the column.              |
| `x-pg-primary-key` | `true`                                   | Single-column primary key.      |
| `x-pg-unique`      | `true`                                   | `UNIQUE` constraint.            |
| `x-pg-references`  | table name, or `{table, column, on-delete, on-update}` | Foreign key. |
| `x-pg-index`       | `true`, or `{name, method, unique, where}` | Index on this column.         |
| `x-pg-type`        | a literal SQL type                       | Override the inferred type.     |
| `x-pg-json`        | `true`                                   | Store as JSONB regardless of type. |
| `x-pg-skip`        | `true`                                   | Do not emit a column.           |

A keyword whose value has the wrong shape raises `GenerationError` rather than being
ignored: a misspelled foreign key that silently vanishes is worse than a failed build.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from schema_to.ast.sql import ForeignKeyAction, IndexMethod
from schema_to.errors import GenerationError

if TYPE_CHECKING:
    from schema_to.core import JsonValue

__all__ = [
    "ForeignKeyRef",
    "IndexRequest",
    "PropertyKeywords",
    "TableKeywords",
    "read_property_keywords",
    "read_table_keywords",
]

TABLE = "x-pg-table"
PRIMARY_KEY = "x-pg-primary-key"
EXTRAS = "x-pg-extras"
INDEXES = "x-pg-indexes"
COLUMN = "x-pg-column"
UNIQUE = "x-pg-unique"
REFERENCES = "x-pg-references"
INDEX = "x-pg-index"
TYPE = "x-pg-type"
JSON = "x-pg-json"
SKIP = "x-pg-skip"


@dataclass(frozen=True, slots=True)
class ForeignKeyRef:
    """A resolved `x-pg-references` value.

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
class TableKeywords:
    """The `x-pg-*` keywords read from a schema that becomes a table."""

    table: str | None = None
    primary_key: tuple[str, ...] = ()
    extras_column: str | None = None
    indexes: tuple[IndexRequest, ...] = ()


@dataclass(frozen=True, slots=True)
class PropertyKeywords:
    """The `x-pg-*` keywords read from one property of a table schema."""

    column: str | None = None
    primary_key: bool = False
    unique: bool = False
    references: ForeignKeyRef | None = None
    index: IndexRequest | None = None
    sql_type: str | None = None
    force_json: bool = False
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
        extras_column=_opt_str(extensions, EXTRAS, where=where),
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
        references=_read_references(extensions, where=where),
        index=_read_index(extensions, where=where),
        sql_type=_opt_str(extensions, TYPE, where=where),
        force_json=_flag(extensions, JSON, where=where),
        skip=_flag(extensions, SKIP, where=where),
    )


# ---------------------------------------------------------------------------
# Composite keywords
# ---------------------------------------------------------------------------


def _as_object(value: JsonValue) -> Mapping[str, JsonValue] | None:
    """Return `value` as a JSON object, or `None` if it is not one.

    The check and the cast belong together: `isinstance(v, Mapping)` narrows only to
    `Mapping[Unknown, object]`, but a value decoded from JSON or YAML always has
    string keys and JSON values.
    """
    if not isinstance(value, Mapping):
        return None
    return cast("Mapping[str, JsonValue]", value)


def _as_array(value: JsonValue) -> Sequence[JsonValue] | None:
    """Return `value` as a JSON array, or `None` if it is not one.

    A `str` is a `Sequence` but never a JSON array, so it is rejected here.
    """
    if not isinstance(value, Sequence) or isinstance(value, str):
        return None
    return cast("Sequence[JsonValue]", value)


def _read_references(extensions: Mapping[str, JsonValue], *, where: str) -> ForeignKeyRef | None:
    raw = extensions.get(REFERENCES)
    if raw is None:
        return None
    if isinstance(raw, str):
        return ForeignKeyRef(table=raw)
    entries = _as_object(raw)
    if entries is None:
        raise _bad(REFERENCES, where, "a table name or an object")
    fields = _as_str_map(entries, REFERENCES, where)
    table = fields.get("table")
    if not table:
        raise _bad(REFERENCES, where, "an object with a `table`")
    return ForeignKeyRef(
        table=table,
        column=fields.get("column"),
        on_delete=_action(fields.get("on-delete"), REFERENCES, where),
        on_update=_action(fields.get("on-update"), REFERENCES, where),
    )


def _read_index(extensions: Mapping[str, JsonValue], *, where: str) -> IndexRequest | None:
    raw = extensions.get(INDEX)
    if raw is None or raw is False:
        return None
    if raw is True:
        return IndexRequest(columns=())
    fields = _as_object(raw)
    if fields is None:
        raise _bad(INDEX, where, "`true` or an object")
    return _index_from(fields, columns=(), where=where, keyword=INDEX)


def _read_indexes(extensions: Mapping[str, JsonValue], *, where: str) -> tuple[IndexRequest, ...]:
    raw = extensions.get(INDEXES)
    if raw is None:
        return ()
    entries = _as_array(raw)
    if entries is None:
        raise _bad(INDEXES, where, "a list of index objects")
    out: list[IndexRequest] = []
    for entry in entries:
        fields = _as_object(entry)
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
    entries = _as_array(value)
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


def _bad(keyword: str, where: str, expected: str) -> GenerationError:
    return GenerationError(f"{keyword} on {where} must be {expected}.")
