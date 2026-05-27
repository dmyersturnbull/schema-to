"""Minimal `Result[T]` sum type for error-accumulating computations.

A `Result[T]` is either `Ok[T]` (success) or `Err` (one or more fatal errors).
It models the same concept as `Either[NonEmptyList[TranspilationError], T]` in
Haskell/Scala, providing `map` and `flat_map` for sequential composition that
short-circuits on the first failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable

    from schema_to.errors import TranspilationError

__all__ = ["Err", "Ok", "Result"]


@final
@dataclass(frozen=True, slots=True)
class Ok[T]:
    """Successful result carrying a value of type `T`."""

    value: T

    def map[U](self, f: Callable[[T], U]) -> Ok[U]:
        """Apply `f` to the wrapped value, returning a new `Ok`."""
        return Ok(f(self.value))

    def flat_map[U](self, f: Callable[[T], Ok[U] | Err]) -> Ok[U] | Err:
        """Chain a fallible computation; propagates `Err` from `f`."""
        return f(self.value)

    @property
    def is_ok(self) -> bool:
        return True


@final
@dataclass(frozen=True, slots=True)
class Err:
    """Failed result carrying at least one `TranspilationError`.

    Multiple errors are accumulated so callers receive a complete diagnostic
    report rather than stopping at the first problem.

    Attributes:
        errors: Non-empty tuple of accumulated errors.
    """

    errors: tuple[TranspilationError, ...]

    @classmethod
    def of(cls, *errors: TranspilationError) -> Self:
        return cls(tuple(errors))

    def map(self, f: object) -> Err:  # FIXME
        return self

    def flat_map(self, f: object) -> Err:  # FIXME
        return self

    @property
    def is_ok(self) -> bool:
        return False

    def merge(self, other: Err) -> Err:
        """Combine two `Err` values, accumulating all errors."""
        return Err(self.errors + other.errors)


type Result[T] = Ok[T] | Err
