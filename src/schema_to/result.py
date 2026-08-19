"""Minimal `Result[T]` sum type for error-accumulating computations.

A `Result[T]` is either `Ok[T]` (success) or `Err` (one or more fatal errors).
It models the same concept as `Either[NonEmptyList[TranspilationError], T]` in Haskell/Scala,
providing `map` and `flat_map` for sequential composition that short-circuits on the first failure.

Both variants also carry `warnings`:
Non-fatal diagnostics travel with the result they were raised alongside.
[Err][] carries them, too.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Self, final, override

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from schema_to.errors import TranspilationError, TranspilationWarning

__all__ = ["Err", "Ok", "Result"]


@dataclass(frozen=True, slots=True)
class _Result(ABC):
    warnings: tuple[TranspilationWarning, ...] = field(default=(), kw_only=True)

    @property
    @abstractmethod
    def is_ok(self) -> bool:
        raise NotImplementedError

    def with_warnings(self, warnings: Sequence[TranspilationWarning]) -> Self:
        """Return a copy with `warnings` prepended, preserving success or failure."""
        if not warnings:
            return self
        return replace(self, warnings=(*warnings, *self.warnings))


@final
@dataclass(frozen=True, slots=True)
class Ok[T](_Result):
    """Successful result carrying a value of type `T`."""

    value: T

    @classmethod
    def of(cls, v: T) -> Self:
        return cls(v)

    def map[U](self, f: Callable[[T], U]) -> Ok[U]:
        """Apply `f` to the wrapped value, returning a new `Ok` with the same warnings."""
        return Ok(f(self.value), warnings=self.warnings)

    def flat_map[U](self, f: Callable[[T], Ok[U] | Err]) -> Ok[U] | Err:
        """Chain a fallible computation; propagates `Err` from `f`.

        The chained result's warnings are prefixed with this result's own,
        so they read in the order they were raised regardless of which side raised them.
        """
        return f(self.value).with_warnings(self.warnings)

    @property
    @override
    def is_ok(self) -> bool:
        return True


@final
@dataclass(frozen=True, slots=True)
class Err(_Result):
    """Failed result carrying at least one `TranspilationError`.

    Attributes:
        errors: Non-empty tuple of accumulated errors.
    """

    errors: tuple[TranspilationError, ...]

    @classmethod
    def of(cls, *errors: TranspilationError) -> Self:
        return cls(tuple(errors))

    # ruff:ignore[unused-method-argument]  # Err propagates unchanged; f is part of the Result[T] interface
    def map[T, U](self, f: Callable[[T], U]) -> Err:
        return self

    # ruff:ignore[unused-method-argument]  # same — Err short-circuits
    def flat_map[T, U](self, f: Callable[[T], Ok[U] | Err]) -> Err:
        return self

    @property
    @override
    def is_ok(self) -> bool:
        return False

    def __add__(self, other: Err) -> Err:
        return self.merge(other)

    def merge(self, other: Err) -> Err:
        """Combine two `Err` values, accumulating all errors and warnings."""
        return Err(self.errors + other.errors, warnings=self.warnings + other.warnings)


type Result[T] = Ok[T] | Err
