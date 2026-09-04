"""The `Result` sum type: `Ok` carries a value, `Err` carries errors, both carry warnings.

Warnings travel with the result they were raised alongside, a failing one included,
so a run that fails still reports what it noticed on the way.
"""

import pytest
from tests.support.asserts import ok

from schema_to.errors import ParseError, TranspilationError, TranspilationWarning
from schema_to.result import Err, Ok

_WARN = TranspilationWarning(message="careful", code="careful")
_OTHER = TranspilationWarning(message="also", code="also")


def _error(message: str = "bad") -> TranspilationError:
    return ParseError(message)


def test_an_ok_is_ok() -> None:
    assert Ok(1).is_ok


def test_an_err_is_not_ok() -> None:
    assert not Err.of(_error()).is_ok


def test_of_wraps_a_value() -> None:
    assert Ok.of(1).value == 1


def test_of_collects_the_errors_it_is_given() -> None:
    one, two = _error("one"), _error("two")
    assert Err.of(one, two).errors == (one, two)


def test_map_applies_to_the_value() -> None:
    assert Ok(2).map(lambda v: v * 3).value == 6


def test_map_keeps_the_warnings() -> None:
    assert Ok(2, warnings=(_WARN,)).map(lambda v: v).warnings == (_WARN,)


def test_map_on_an_err_changes_nothing() -> None:
    """An `Err` short-circuits, so the function is never called."""
    failure = Err.of(_error())
    assert failure.map(lambda _: pytest.fail("should not be called")) is failure


def test_flat_map_chains_a_fallible_step() -> None:
    assert ok(Ok(2).flat_map(lambda v: Ok(v + 1))) == 3


def test_flat_map_propagates_a_failure_from_the_step() -> None:
    assert isinstance(Ok(2).flat_map(lambda _: Err.of(_error())), Err)


def test_flat_map_puts_earlier_warnings_first() -> None:
    """Warnings should read in the order they were raised, whichever side raised them."""
    chained = Ok(1, warnings=(_WARN,)).flat_map(lambda v: Ok(v, warnings=(_OTHER,)))
    assert chained.warnings == (_WARN, _OTHER)


def test_flat_map_on_an_err_changes_nothing() -> None:
    failure = Err.of(_error())
    assert failure.flat_map(lambda _: pytest.fail("should not be called")) is failure


def test_warnings_are_prepended_to_an_ok() -> None:
    assert Ok(1, warnings=(_OTHER,)).with_warnings([_WARN]).warnings == (_WARN, _OTHER)


def test_warnings_are_prepended_to_an_err() -> None:
    """A failing result carries warnings too — they are often why it failed."""
    assert Err.of(_error()).with_warnings([_WARN]).warnings == (_WARN,)


def test_adding_no_warnings_returns_the_same_result() -> None:
    result = Ok(1)
    assert result.with_warnings([]) is result


def test_merging_two_failures_keeps_every_error() -> None:
    one, two = _error("one"), _error("two")
    assert Err.of(one).merge(Err.of(two)).errors == (one, two)


def test_merging_two_failures_keeps_every_warning() -> None:
    merged = Err((_error(),), warnings=(_WARN,)).merge(Err((_error(),), warnings=(_OTHER,)))
    assert merged.warnings == (_WARN, _OTHER)


def test_two_failures_add_together() -> None:
    """`+` is `merge`, so accumulating errors across a document reads naturally."""
    one, two = _error("one"), _error("two")
    assert (Err.of(one) + Err.of(two)).errors == (one, two)
