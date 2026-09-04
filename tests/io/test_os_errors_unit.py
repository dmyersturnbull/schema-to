"""The typed `OSError` subclasses, which carry an errno rather than making a caller pick one."""

import errno
from collections.abc import Sequence
from pathlib import PurePath
from typing import Protocol

import pytest

from schema_to.io.os_errors import (
    AccessDeniedError,
    DeviceMissingError,
    Filename,
    PathExistsError,
    PathMissingError,
    TypedIOError,
    TypedIsADirectoryError,
    TypedNotADirectoryError,
    TypedOSError,
)


class _NamesAFile(Protocol):
    """A typed error class: it takes only the filename, and knows its own errno."""

    def __call__(self, *, filename: Filename = None) -> OSError: ...


_ERRNOS: Sequence[tuple[_NamesAFile, int]] = [
    (PathMissingError, errno.ENOENT),
    (PathExistsError, errno.ENOENT),
    (AccessDeniedError, errno.EACCES),
    (TypedIsADirectoryError, errno.EISDIR),
    (TypedNotADirectoryError, errno.ENOTDIR),
    (DeviceMissingError, errno.ENODEV),
]

_BASES: Sequence[tuple[_NamesAFile, type[OSError]]] = [
    (PathMissingError, FileNotFoundError),
    (PathExistsError, FileExistsError),
    (AccessDeniedError, PermissionError),
    (TypedIsADirectoryError, IsADirectoryError),
    (TypedNotADirectoryError, NotADirectoryError),
    (DeviceMissingError, OSError),
]


@pytest.mark.parametrize(("cls", "expected"), _ERRNOS)
def test_each_class_carries_its_own_errno(cls: _NamesAFile, expected: int) -> None:
    """The point of these is that the errno comes with the class, not from the caller."""
    error = cls(filename="/tmp/x")
    assert error.errno == expected
    assert error.strerror


@pytest.mark.parametrize(("cls", "base"), _BASES)
def test_each_class_is_the_builtin_error_it_stands_in_for(
    cls: _NamesAFile, base: type[OSError]
) -> None:
    """A caller catching `FileNotFoundError` has to catch `PathMissingError` too."""
    assert isinstance(cls(filename="/tmp/x"), base)


@pytest.mark.parametrize(("cls", "_expected"), _ERRNOS)
def test_a_path_filename_is_recorded_as_text(cls: _NamesAFile, _expected: int) -> None:
    """`OSError.filename` is a string, so a `PurePath` has to be converted rather than stored."""
    error = cls(filename=PurePath("/tmp") / "thing.yaml")
    assert isinstance(error.filename, str)
    assert error.filename.endswith("thing.yaml")


def test_a_filename_may_be_omitted() -> None:
    assert PathMissingError().filename is None


def test_typed_os_error_takes_the_errno_it_is_given() -> None:
    error = TypedOSError(errno=errno.EACCES, filename="/tmp/x", filename2="/tmp/y")
    assert error.errno == errno.EACCES
    assert error.strerror
    assert (error.filename, error.filename2) == ("/tmp/x", "/tmp/y")


def test_typed_os_error_without_an_errno_has_no_message() -> None:
    error = TypedOSError()
    assert error.errno is None
    assert error.strerror is None


def test_typed_io_errors_are_always_eio() -> None:
    error = TypedIOError(filename=PurePath("/tmp/a"), filename2=PurePath("/tmp/b"))
    assert error.errno == errno.EIO
    assert (error.filename, error.filename2) == ("/tmp/a", "/tmp/b")


def test_two_typed_os_errors_with_the_same_arguments_are_equal() -> None:
    assert TypedOSError(errno=errno.EIO, filename="/x") == TypedOSError(
        errno=errno.EIO, filename="/x"
    )


def test_the_errno_is_part_of_the_comparison() -> None:
    assert TypedOSError(errno=errno.EIO) != TypedOSError(errno=errno.EACCES)


def test_a_typed_os_error_is_never_equal_to_a_plain_one() -> None:
    """`__eq__` returns `NotImplemented`, so Python falls back to identity."""
    assert TypedOSError(errno=errno.EIO) != OSError(errno.EIO, "x")


def test_equal_errors_hash_alike() -> None:
    """Equal-but-distinct errors have to share a hash to be usable in a set."""
    one = TypedOSError(errno=errno.EIO, filename="/x")
    other = TypedOSError(errno=errno.EIO, filename="/x")
    assert len({one, other}) == 1
