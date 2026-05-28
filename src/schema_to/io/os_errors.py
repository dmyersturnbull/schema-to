"""More convenient exception classes for `OSError` and family."""

import errno as _errno
import os
from os import strerror as _errno_to_str
from pathlib import PurePath

__all__ = [
    "AccessDeniedError",
    "PathExistsError",
    "PathMissingError",
    "TypedIOError",
    "TypedIsADirectoryError",
    "TypedNotADirectoryError",
    "TypedOSError",
]

type Errno = int | None
type Filename = str | PurePath | None
type WinErrno = int | None

_winerror_map = {
    _errno.ENOENT: 3,  # ERROR_PATH_NOT_FOUND
    _errno.EEXIST: 80,  # ERROR_FILE_EXISTS
    _errno.EIO: 13,  # ERROR_INVALID_DATA (best guess)
    _errno.EISDIR: 183,  # ERROR_ALREADY_EXISTS
    _errno.ENOTDIR: 2,  # ERROR_FILE_NOT_FOUND
    _errno.EACCES: 5,  # ERROR_ACCESS_DENIED
    _errno.ENODEV: 55,  # ERROR_DEV_NOT_EXIST
}


def _errno_to_win(errno: Errno) -> int | None:
    if errno is None or os.name != "NT":
        return None
    return _winerror_map.get(errno)


class TypedOSError(OSError):
    def __init__(
        self,
        *,
        errno: Errno = None,
        winerror: WinErrno = None,
        filename: Filename = None,
        filename2: Filename = None,
    ) -> None:
        strerr = None if errno is None else _errno_to_str(errno)
        if winerror is None:
            winerror = _errno_to_win(errno)
        filename = str(filename) if isinstance(filename, PurePath) else filename
        filename2 = str(filename2) if isinstance(filename2, PurePath) else filename2
        super().__init__(errno, strerr, filename, winerror, filename2)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, TypedOSError):
            # Note the subtlety here!
            return type(other) is type(self) and self.args == other.args
        return NotImplemented

    def __hash__(self) -> int:
        return hash((type(self), self.args))


class TypedIOError(OSError):
    def __init__(self, *, filename: Filename = None, filename2: Filename = None) -> None:
        winerr = 13 if os.name == "NT" else None  # 13 is "invalid data"
        filename = str(filename) if isinstance(filename, PurePath) else filename
        filename2 = str(filename2) if isinstance(filename2, PurePath) else filename2
        super().__init__(_errno.EIO, _errno_to_str(_errno.EIO), filename, winerr, filename2)


class PathMissingError(FileNotFoundError):
    def __init__(self, *, filename: Filename = None) -> None:
        errno = _errno.ENOENT
        filename = str(filename) if isinstance(filename, PurePath) else filename
        super().__init__(errno, _errno_to_str(_errno.ENOENT), filename, _errno_to_win(errno), None)


class PathExistsError(FileExistsError):
    def __init__(self, *, filename: Filename = None) -> None:
        errno = _errno.ENOENT
        filename = str(filename) if isinstance(filename, PurePath) else filename
        super().__init__(errno, _errno_to_str(errno), filename, _errno_to_win(errno), None)


class AccessDeniedError(PermissionError):
    def __init__(self, *, filename: Filename = None) -> None:
        errno = _errno.EACCES
        filename = str(filename) if isinstance(filename, PurePath) else filename
        super().__init__(errno, _errno_to_str(errno), filename, _errno_to_win(errno), None)


class TypedIsADirectoryError(IsADirectoryError):
    def __init__(self, *, filename: Filename = None) -> None:
        errno = _errno.EISDIR
        filename = str(filename) if isinstance(filename, PurePath) else filename
        super().__init__(errno, _errno_to_str(errno), filename, _errno_to_win(errno), None)


class TypedNotADirectoryError(NotADirectoryError):
    def __init__(self, *, filename: Filename = None) -> None:
        errno = _errno.ENOTDIR
        filename = str(filename) if isinstance(filename, PurePath) else filename
        super().__init__(errno, _errno_to_str(errno), filename, _errno_to_win(errno), None)


class DeviceMissingError(OSError):
    def __init__(self, *, filename: Filename = None) -> None:
        errno = _errno.ENODEV
        filename = str(filename) if isinstance(filename, PurePath) else filename
        super().__init__(errno, _errno_to_str(errno), filename, _errno_to_win(errno), None)
