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

    commonmark = MediaType("text", "markdown")
    json = MediaType("application", "json")
    python = MediaType("text", "x-python")
    sql = MediaType("application", "sql")
    typescript = MediaType("application", "typescript")
    yaml = MediaType("application", "yaml")
    _valid: dict[str, MediaType] = {".json": json, ".yaml": yaml, ".yml": yaml}.items()

    @classmethod
    def from_extension(cls, suffix: str) -> MediaType | None:
        """Infer a media type from a file extension such as `".json"` or `".yaml"`."""
        return cls._valid.get(suffix.lower())


class MediaTypeParam(NamedTuple):
    key: str
    value: str
