"""Minimal `Result[T]` sum type for error-accumulating computations.

A `Result[T]` is either `Ok[T]` (success) or `Err` (one or more fatal errors).
It models the same concept as `Either[NonEmptyList[TranspilationError], T]` in Haskell/Scala,
providing `map` and `flat_map` for sequential composition that short-circuits on the first failure.
"""


from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final, override

if TYPE_CHECKING:
    from collections.abc import Callable

    from schema_to.errors import TranspilationError

__all__ = ["Err", "Ok", "Result"]


@dataclass(frozen=True, slots=True)
class _Result(ABC):
    @property
    @abstractmethod
    def is_ok(self) -> bool:
        raise NotImplementedError


@final
@dataclass(frozen=True, slots=True)
class Ok[T](_Result):
    """Successful result carrying a value of type `T`."""

    value: T

    @classmethod
    def of(cls, v: T) -> Self:
        return cls(v)

    def map[U](self, f: Callable[[T], U]) -> Ok[U]:
        """Apply `f` to the wrapped value, returning a new `Ok`."""
        return Ok(f(self.value))

    def flat_map[U](self, f: Callable[[T], Ok[U] | Err]) -> Ok[U] | Err:
        """Chain a fallible computation; propagates `Err` from `f`."""
        return f(self.value)

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
        """Combine two `Err` values, accumulating all errors."""
        return Err(self.errors + other.errors)


type Result[T] = Ok[T] | Err
