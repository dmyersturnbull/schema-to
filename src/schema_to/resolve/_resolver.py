"""Facade for the referencing library's internal Resolver type.

`referencing._core.Resolver` is not part of the public API of the `referencing` library.
This module provides a facade so that the internal type is referenced only here.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from referencing._core import Resolved as _Resolved
    from referencing._core import Resolver as _Resolver


__all__ = ["Resolved", "Resolver"]


class Resolved:
    """Wraps `referencing._core.Resolved` to expose a typed `.resolver`."""

    def __init__(self, inner: _Resolved) -> None:
        self._inner = inner

    @property
    def resolver(self) -> Resolver:
        return Resolver(self._inner.resolver)


class Resolver:
    """Thin facade over `referencing._core.Resolver` for type-safe ref lookups."""

    def __init__(self, inner: _Resolver) -> None:
        self._inner = inner

    def lookup(self, ref: str) -> Resolved:
        return Resolved(self._inner.lookup(ref))
