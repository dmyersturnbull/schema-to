"""Unwrapping a `Result`, and reporting usefully when it holds the other variant.

[ok][] and [failure][] replace the `assert isinstance(result, Ok)` line that would otherwise open every test.
They put the accumulated messages into the failure output,
where an `isinstance` assertion would show only `False`.
"""

from collections.abc import Sequence

from schema_to.errors import TranspilationError
from schema_to.result import Err, Ok, Result


def message_of(error: TranspilationError) -> str:
    """Return `error`'s message, falling back to its `str` for a bare exception."""
    return getattr(error, "message", str(error))


def ok[T](result: Result[T]) -> T:
    """Return the value of an `Ok`, failing with the accumulated messages if it is an `Err`."""
    assert isinstance(result, Ok), f"Expected Ok, got errors: {failure(result)}"
    return result.value


def failure[T](result: Result[T]) -> Sequence[str]:
    """Return the messages of an `Err`, failing if the result is an `Ok`."""
    assert isinstance(result, Err), f"Expected Err, got Ok: {result.value!r}"
    return [message_of(e) for e in result.errors]


def warning_codes[T](result: Result[T]) -> Sequence[str]:
    """Return the codes of every warning carried by `result`, in the order they were raised."""
    return [w.code for w in result.warnings if w.code]
