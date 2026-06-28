from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NamedTuple, overload

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["MediaType", "MediaTypes"]


@dataclass(frozen=True, slots=True)
class MediaType:
    """An [IANA media type](https://www.iana.org/assignments/media-types/)."""

    type: str
    subtype: str
    params: tuple[MediaTypeParam, ...] = ()
    _param_map: dict[str, list[str]] = field(init=False)

    def __post_init__(self) -> None:
        mp: dict[str, list[str]] = defaultdict(list)
        for k, v in self.params:
            mp[k].append(v)
        object.__setattr__(self, "_param_map", mp)  # bypass frozen __setattr__

    @property
    def essence(self) -> str:
        return f"{self.type}/{self.subtype}"

    @property
    def string(self) -> str:
        return self.essence + "".join(f";{k}={v}" for k, v in self.params)

    @overload
    def get_param_value(self, key: str, default: str) -> str: ...

    @overload
    def get_param_value(self, key: str, default: str | None = None) -> str | None: ...

    def get_param_value(self, key: str, default: str | None = None) -> str | None:
        """Returns the value of the param `key`, or `default` if there are 0 or >1 unique values."""
        values = set(self.get_param_values(key))
        if len(values) == 1:
            return next(iter(values))
        return default

    def get_param_values(self, key: str) -> Sequence[str]:
        """Returns the values of param `key`, in order."""
        return list(self._param_map.get(key, []))

    def __str__(self) -> str:
        return self.string


class MediaTypes:
    """Common media type constants."""

    # JSON-compatible
    json = MediaType("application", "json")
    yaml = MediaType("application", "yaml")
    # Schema-specific
    json_schema = MediaType("application", "schema+json")
    json_schema_yaml = MediaType("application", "schema+yaml")
    openapi = MediaType("application", "vnd.oai.openapi+json")
    openapi_yaml = MediaType("application", "vnd.oai.openapi+yaml")
    # Others
    commonmark = MediaType("text", "markdown")
    python = MediaType("text", "x-python")
    sql = MediaType("application", "sql")
    typescript = MediaType("application", "typescript")


class MediaTypeParam(NamedTuple):
    key: str
    value: str
