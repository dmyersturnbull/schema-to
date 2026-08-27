"""Reading of the `x-pydantic-*` extension keywords that drive Pydantic generation.

| Keyword | Goes on | Value | Effect |
|---|---|---|---|
| `x-pydantic-frozen` | schema | `true` | Apply `ConfigDict(frozen=True)`. |
| `x-pydantic-skip` | property | `true` | Do not emit a field for this property. |
| `x-pydantic-class` | schema | a name | Use this class/alias name instead of the `$defs` key. |
| `x-pydantic-enum` | schema with `enum` | `true` / a name / `{name?, base?}` | Emit an `Enum` class instead of `Literal[...]`. |

Example using these:

```yaml
Point:
  x-pydantic-class: XyPoint
  x-pydantic-frozen: true
  type: object
  properties:
    x:
      type: number
    y:
      type: number
    internal-cache:
      type: string
      x-pydantic-skip: true
```

## `x-pydantic-enum`

Placed on any schema carrying `enum`, generates a Python enum instead of a `Literal`.
It accepts three shapes:

- boolean (`true`; `false` has no effect)
- string (the class name)
- object `{name?, base?}`

If `name` is not provided, it is inferred:

- If defined in `properties`, uses `{ToPascalCase(enclosing_class_name)}{ToPascalCase(property_name)}`
- If defined outside with name `def_name`, uses `ToPascalCase(def_name)`.

If `base` is not provided, it is inferred:

- If all members are strings, uses `StrEnum`.
- If all members are integers, uses `IntEnum`.
- If otherwise all members are primitives (including mixtures like integer ∪ boolean ∪ null), uses `Enum`.
- Else (meaning 1 or more members are compound types), warns and falls back to `Literal`.

Each member name is `TO_SCREAMING_SNAKE_CASE(to_string(to_value))`.
`auto()` is used in place of an explicit value where it would produce the same result.

Example:
```yaml
Order:
  type: object
  properties:
    status:
      type: string
      enum:
        - active
        - inactive
      x-pydantic-enum: true
```

generates:

```python
class OrderStatus(StrEnum):
    ACTIVE = auto()
    INACTIVE = auto()


class Order(BaseModel):
    status: OrderStatus
```

A keyword whose value has the wrong shape raises `KeywordError`,
which is normally translated into a [TranspilationError][].
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from schema_to.core import as_object
from schema_to.errors import KeywordError

if TYPE_CHECKING:
    from schema_to.core import JsonValue

__all__ = [
    "CLASS",
    "ENUM",
    "FROZEN",
    "SKIP",
    "EnumKeyword",
    "read_class",
    "read_enum",
    "read_frozen",
    "read_skip",
]

FROZEN = "x-pydantic-frozen"
SKIP = "x-pydantic-skip"
CLASS = "x-pydantic-class"
ENUM = "x-pydantic-enum"


def read_frozen(extensions: Mapping[str, JsonValue], *, where: str) -> bool:
    """Read the schema-level `x-pydantic-frozen` keyword from `extensions`."""
    return _flag(extensions, FROZEN, where=where)


def read_skip(extensions: Mapping[str, JsonValue], *, where: str) -> bool:
    """Read the property-level `x-pydantic-skip` keyword from `extensions`."""
    return _flag(extensions, SKIP, where=where)


def read_class(extensions: Mapping[str, JsonValue], *, where: str) -> str | None:
    """Read the schema-level `x-pydantic-class` keyword from `extensions`."""
    value = extensions.get(CLASS)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        msg = f"{CLASS} on {where} must be a non-empty string."
        raise KeywordError(msg)
    return value


@dataclass(frozen=True, slots=True)
class EnumKeyword:
    """A parsed `x-pydantic-enum` value.

    Attributes:
        name: Explicit class name, or `None` to derive one from context.
        base: Explicit base (`"Enum"`, `"StrEnum"`, `"IntEnum"`, or a custom name),
            or `None` to auto-detect from the enum's value types.
    """

    name: str | None = None
    base: str | None = None


def read_enum(extensions: Mapping[str, JsonValue], *, where: str) -> EnumKeyword | None:
    """Read the schema-level `x-pydantic-enum` keyword from `extensions`."""
    value = extensions.get(ENUM)
    if value is None:
        return None
    if isinstance(value, bool):
        return EnumKeyword() if value else None
    if isinstance(value, str):
        if not value:
            msg = f"{ENUM} on {where} must be `true`, a non-empty string, or an object."
            raise KeywordError(msg)
        return EnumKeyword(name=value)
    obj = as_object(value)
    if obj is None:
        msg = f"{ENUM} on {where} must be `true`, a non-empty string, or an object."
        raise KeywordError(msg)
    extra = set(obj) - {"name", "base"}
    if extra:
        msg = f"{ENUM} on {where} has unrecognized keys: {sorted(extra)}."
        raise KeywordError(msg)
    name = _opt_str(obj, "name", where=where, keyword=ENUM)
    base = _opt_str(obj, "base", where=where, keyword=ENUM)
    if name is None and base is None:
        msg = f"{ENUM} on {where} must set at least one of `name` or `base`."
        raise KeywordError(msg)
    return EnumKeyword(name=name, base=base)


def _opt_str(obj: Mapping[str, JsonValue], key: str, *, where: str, keyword: str) -> str | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        msg = f"{keyword}.{key} on {where} must be a non-empty string."
        raise KeywordError(msg)
    return value


def _flag(raw: Mapping[str, JsonValue], key: str, *, where: str) -> bool:
    value = raw.get(key)
    if value is None:
        return False
    if not isinstance(value, bool):
        msg = f"{key} on {where} must be `true` or `false`."
        raise KeywordError(msg)
    return value
