from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Set as AbstractSet

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
    # Others
    commonmark = MediaType("text", "markdown")
    python = MediaType("text", "x-python")
    sql = MediaType("application", "sql")
    typescript = MediaType("application", "typescript")

    _input_suffixes: Mapping[str, MediaType] = {".json": json, ".yaml": yaml, ".yml": yaml}
    input_suffixes: AbstractSet[str] = _input_suffixes.keys()

    @classmethod
    def from_input_suffix(cls, suffix: str) -> MediaType:
        """Infer a media type from a file extension such as `".json"` or `".yaml"`."""
        if found := cls._input_suffixes.get(suffix.lower()):
            return found
        msg = (
            f"The suffix {suffix} is not an allowed input file extension."
            f" Use one of: {', '.join(cls.input_suffixes)}"
        )
        raise ValueError(msg)


class MediaTypeParam(NamedTuple):
    key: str
    value: str
