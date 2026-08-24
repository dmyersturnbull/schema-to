"""Reading of the `x-pydantic-*` extension keywords that drive Pydantic generation.

These keywords supply info necessary for Pydantic-specific choices that plain
JSON Schema carries no equivalent for.

| Keyword | Goes on | Value | Effect |
|---|---|---|---|
| `x-pydantic-frozen` | schema | `true` | Emit an immutable model (`ConfigDict(frozen=True)`). |
| `x-pydantic-skip` | property | `true` | Do not emit a field for this property. |
| `x-pydantic-class` | schema | a name | Use this class/alias name instead of the `$defs` key. |
| `x-pydantic-enum` | schema with `enum` | `true` / a name / `{name?, base?}` | Emit an `Enum` class instead of `Literal[...]`. |

`x-pydantic-class` on a `$defs` entry also renames every `$ref` pointing at it,
so the two stay consistent: name the entry once, and its declaration, any
Read/Write split, and every reference to it all use the new name.

Example using these:

```yaml
Point:
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
CustomerId:
  x-pydantic-class: CustomerIdentifier
  type: string
```

## `x-pydantic-enum`

Placed on any schema carrying `enum`, this generates a real `enum.Enum` subclass instead of the default `Literal[...]`.
It accepts three shapes:

- `true`: derive both the class name and the base from context.
- a string: use it as the class name; derive the base from context.
- an object `{"name": ..., "base": ...}`: either key may be given alone, falling back to the derived value for the other.

The base (`Enum`, `StrEnum`, or `IntEnum`) is auto-detected from the enum's value types when not given explicitly:
all-`string` values get `StrEnum`, all-`integer` values get `IntEnum` (JSON `true`/`false` do not count as integers here), and anything else that is still a JSON scalar (a mix of types, or `number`/`boolean`/`null` values) gets a plain `Enum`.
A `list`- or `dict`-valued enum entry cannot be expressed as an `Enum` member and falls back to `Literal[...]` with a warning, even when `x-pydantic-enum` is set.

`base` may also name a custom class (e.g. `"DashReplacingEnum"`) instead of one of the three stdlib names.
No import is generated for it, since the generator does not yet know how to import a user-supplied base class, so the generated module is expected to already have it in scope.

Where the class name is *derived* rather than given explicitly, a property-level `enum` uses the enclosing class's name plus the property name (e.g. a `status` property on `Order` becomes `OrderStatus`), avoiding collisions between same-named properties on unrelated schemas.
A top-level (`$defs` entry or root schema) `enum` keeps its existing name resolution (`x-pydantic-class`, then `title`, etc.), since letting `x-pydantic-enum`'s own `name` rename a `$defs` entry would silently diverge from what `$ref`s targeting it resolve to.

Each member's name is derived from its value (e.g. `"active"` becomes `ACTIVE`).
`auto()` is used in place of an explicit value where it would produce the same result: for `StrEnum`, when the value equals the member name lower-cased; for `IntEnum`, when every value in the enum forms the sequence `1, 2, 3, ...` in declaration order.

Example:
```yaml
Order:
  type: object
  properties:
    status:
      type: string
      enum: ["active", "inactive"]
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
