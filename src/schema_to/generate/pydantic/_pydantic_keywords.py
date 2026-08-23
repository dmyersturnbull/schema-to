"""Reading of the `x-pydantic-*` extension keywords that drive Pydantic generation.

These keywords supply info necessary for Pydantic-specific choices that plain
JSON Schema carries no equivalent for.

| Keyword              | Goes on  | Value    | Effect                                            |
|-----------------------|----------|----------|-----------------------------------------------------|
| `x-pydantic-frozen`  | schema   | `true`   | Emit an immutable model (`ConfigDict(frozen=True)`). |
| `x-pydantic-skip`    | property | `true`   | Do not emit a field for this property.            |
| `x-pydantic-class`   | schema   | a name   | Use this class/alias name instead of the `$defs` key. |

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

A keyword whose value has the wrong shape raises `KeywordError`,
which is normally translated into a [TranspilationError][].
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING

from schema_to.errors import KeywordError

if TYPE_CHECKING:
    from schema_to.core import JsonValue

__all__ = ["CLASS", "FROZEN", "SKIP", "read_class", "read_frozen", "read_skip"]

FROZEN = "x-pydantic-frozen"
SKIP = "x-pydantic-skip"
CLASS = "x-pydantic-class"


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


def _flag(raw: Mapping[str, JsonValue], key: str, *, where: str) -> bool:
    value = raw.get(key)
    if value is None:
        return False
    if not isinstance(value, bool):
        msg = f"{key} on {where} must be `true` or `false`."
        raise KeywordError(msg)
    return value
