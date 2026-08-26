"""Small cross-platform non-blocking process file locks."""

import os
from pathlib import Path
from typing import BinaryIO


def _lock_unix(file_handle: BinaryIO, fcntl_module=None) -> None:
    if fcntl_module is None:
        import fcntl as fcntl_module

    fcntl_module.flock(
        file_handle, fcntl_module.LOCK_EX | fcntl_module.LOCK_NB
    )


def _unlock_unix(file_handle: BinaryIO, fcntl_module=None) -> None:
    if fcntl_module is None:
        import fcntl as fcntl_module

    fcntl_module.flock(file_handle, fcntl_module.LOCK_UN)


def _lock_windows(file_handle: BinaryIO, msvcrt_module=None) -> None:
    if msvcrt_module is None:
        import msvcrt as msvcrt_module

    file_handle.seek(0)
    msvcrt_module.locking(file_handle.fileno(), msvcrt_module.LK_NBLCK, 1)


def _unlock_windows(file_handle: BinaryIO, msvcrt_module=None) -> None:
    if msvcrt_module is None:
        import msvcrt as msvcrt_module

    file_handle.seek(0)
    msvcrt_module.locking(file_handle.fileno(), msvcrt_module.LK_UNLCK, 1)


def _lock_file(file_handle: BinaryIO) -> None:
    if os.name == "nt":
        _lock_windows(file_handle)
    else:
        _lock_unix(file_handle)


def _unlock_file(file_handle: BinaryIO) -> None:
    if os.name == "nt":
        _unlock_windows(file_handle)
    else:
        _unlock_unix(file_handle)


def acquire_file_lock(path: str | os.PathLike[str]) -> BinaryIO | None:
    """Acquire an exclusive process lock without waiting."""
    file_handle = None
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        file_handle = open(path, "a+b")
        file_handle.seek(0, os.SEEK_END)
        if file_handle.tell() == 0:
            file_handle.write(b"\0")
            file_handle.flush()
        _lock_file(file_handle)
    except OSError:
        if file_handle is not None:
            file_handle.close()
        return None
    return file_handle


def release_file_lock(file_handle: BinaryIO | None) -> None:
    """Release a lock and always close its owning file handle."""
    if file_handle is None:
        return
    try:
        _unlock_file(file_handle)
    finally:
        file_handle.close()
