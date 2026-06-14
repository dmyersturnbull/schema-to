from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

__all__ = ["MediaType", "MediaTypes"]


@dataclass(frozen=True, slots=True)
class MediaType:
    """An [IANA media type](https://www.iana.org/assignments/media-types/)."""

    type: str
    subtype: str
    params: tuple[MediaTypeParam, ...] = ()

    @property
    def essence(self) -> str:
        return f"{self.type}/{self.subtype}"

    @property
    def string(self) -> str:
        return self.essence + "".join(f";{k}={v}" for k, v in self.params)

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
