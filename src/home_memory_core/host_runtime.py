from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import sys
from threading import RLock
from typing import IO, Iterator

from home_memory_core.process_boundary import (
    HomeProcessIsolationError,
    require_home_process,
)


class HostRuntimeLeaseError(RuntimeError):
    """The supported HOME host runtime could not acquire exclusive ownership."""


class HostRuntimeConfigurationError(RuntimeError):
    """The supported HOME host runtime configuration is unsafe or inconsistent."""


_HOME_SINGLE_INSTANCE_LEASE_MARKER = object()


@dataclass(frozen=True)
class HomeHostRuntimeIdentity:
    """Canonical host paths and one process-local runtime identity.

    This object does not grant memory authority. It only describes the local
    deployment instance that must hold the single-process lease before opening
    HOME through the supported mini-host path.
    """

    runtime_root: Path
    db_path: Path
    process_instance_id: str
    owner_pid: int
    lock_path: Path
    real_data_allowed: bool = False


class HomeSingleInstanceLease:
    """OS-backed exclusive lease for the supported single-process HOME host.

    The lock is advisory with respect to arbitrary external programs, so the
    contract is deliberately narrow: every supported HOME mini-host entry point
    must acquire this lease before opening the canonical database. Direct SQL or
    processes that bypass this boundary remain unsupported.
    """

    def __init__(
        self,
        *,
        identity: HomeHostRuntimeIdentity,
        handle: IO[bytes],
        _marker: object,
    ) -> None:
        if _marker is not _HOME_SINGLE_INSTANCE_LEASE_MARKER:
            raise HostRuntimeLeaseError(
                "HOME host lease must be acquired through the supported runtime boundary"
            )
        self._trust_marker = _HOME_SINGLE_INSTANCE_LEASE_MARKER
        self._identity = identity
        self._handle = handle
        self._released = False
        self._guard = RLock()

    @property
    def identity(self) -> HomeHostRuntimeIdentity:
        self._assert_owner_process()
        with self._guard:
            return self._identity

    @property
    def released(self) -> bool:
        self._assert_owner_process()
        with self._guard:
            return self._released

    @contextmanager
    def _hold_active_for_authority(self) -> Iterator[None]:
        """Keep this host lease live across one synchronous authority effect."""

        self._assert_owner_process()
        with self._guard:
            if self._released:
                raise HostRuntimeLeaseError(
                    "released HOME host lease cannot authorize an effect"
                )
            yield

    def release(self) -> None:
        self._assert_owner_process()
        with self._guard:
            if self._released:
                return
            _unlock_file(self._handle)
            self._handle.close()
            self._released = True

    def __enter__(self) -> HomeSingleInstanceLease:
        self._assert_owner_process()
        if self._released:
            raise HostRuntimeLeaseError("released HOME host lease cannot be reused")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    def _assert_owner_process(self) -> None:
        if (
            getattr(self, "_trust_marker", None)
            is not _HOME_SINGLE_INSTANCE_LEASE_MARKER
        ):
            raise HostRuntimeLeaseError(
                "HOME host lease was not acquired through the supported runtime boundary"
            )
        try:
            require_home_process()
        except HomeProcessIsolationError as exc:
            raise HostRuntimeLeaseError(
                "forked child cannot use or release the parent HOME host lease"
            ) from exc
        if os.getpid() != self._identity.owner_pid:
            raise HostRuntimeLeaseError(
                "HOME host lease belongs to another process"
            )


def acquire_home_single_instance(
    *,
    runtime_root: str | Path,
    db_path: str | Path,
    real_data_allowed: bool = False,
) -> HomeSingleInstanceLease:
    """Acquire the supported one-process host boundary for one HOME runtime.

    This milestone intentionally refuses real personal data. A later explicit
    real-data GO must introduce the production enablement path; callers cannot
    flip it here.
    """

    require_home_process()

    if real_data_allowed:
        raise HostRuntimeConfigurationError(
            "mini-host runtime remains closed to real personal data"
        )

    root = _canonical_path(runtime_root)
    database = _canonical_path(db_path)
    if not _is_within(database, root):
        raise HostRuntimeConfigurationError(
            "HOME database must remain inside the canonical runtime root"
        )

    root.mkdir(parents=True, exist_ok=True)
    database.parent.mkdir(parents=True, exist_ok=True)

    # The lease is keyed by the canonical database, not only runtime_root.
    # Nested runtime roots that name the same DB must therefore contend on the
    # same OS lock rather than creating independent locks.
    lock_path = database.parent / ".home-runtime.lock"
    handle = _open_lock_file(lock_path)
    try:
        _try_lock_file(handle)
    except Exception:
        handle.close()
        raise

    identity = HomeHostRuntimeIdentity(
        runtime_root=root,
        db_path=database,
        process_instance_id=f"host-{secrets.token_hex(16)}",
        owner_pid=os.getpid(),
        lock_path=lock_path,
        real_data_allowed=False,
    )

    try:
        _write_lock_metadata(handle, identity)
    except Exception:
        _unlock_file(handle)
        handle.close()
        raise

    return HomeSingleInstanceLease(
        identity=identity,
        handle=handle,
        _marker=_HOME_SINGLE_INSTANCE_LEASE_MARKER,
    )



def _open_lock_file(lock_path: Path) -> IO[bytes]:
    """Open the lock file with sharing compatible with Windows byte locking.

    CPython's ordinary file-open sharing on Windows is not a contract HOME
    should rely on for the contention path.  We explicitly allow other
    handles to open the file, then let the byte-range lock decide ownership.
    """

    if sys.platform != "win32":
        return lock_path.open("a+b", buffering=0)

    import ctypes
    from ctypes import wintypes
    import msvcrt

    generic_read = 0x80000000
    generic_write = 0x40000000
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    file_share_delete = 0x00000004
    open_always = 4
    file_attribute_normal = 0x00000080

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE

    win_handle = create_file(
        str(lock_path),
        generic_read | generic_write,
        file_share_read | file_share_write | file_share_delete,
        None,
        open_always,
        file_attribute_normal,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if win_handle == invalid_handle:
        error = ctypes.get_last_error()
        raise OSError(error, ctypes.FormatError(error), str(lock_path))

    flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
    try:
        fd = msvcrt.open_osfhandle(int(win_handle), flags)
    except Exception:
        kernel32.CloseHandle(win_handle)
        raise

    try:
        return os.fdopen(fd, "r+b", buffering=0)
    except Exception:
        os.close(fd)
        raise

def _canonical_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    try:
        return path.resolve(strict=False)
    except OSError as exc:
        raise HostRuntimeConfigurationError(
            f"cannot canonicalize HOME host path: {path}"
        ) from exc



def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _write_lock_metadata(
    handle: IO[bytes],
    identity: HomeHostRuntimeIdentity,
) -> None:
    metadata = {
        "schema": "home-single-instance-v0.1",
        "pid": os.getpid(),
        "process_instance_id": identity.process_instance_id,
        "owner_pid": identity.owner_pid,
        "lock_path": str(identity.lock_path),
        "runtime_root": str(identity.runtime_root),
        "db_path": str(identity.db_path),
        "real_data_allowed": False,
    }
    encoded = (json.dumps(metadata, sort_keys=True) + "\n").encode("utf-8")
    handle.seek(0)
    handle.truncate(0)
    handle.write(encoded)
    handle.flush()
    try:
        os.fsync(handle.fileno())
    except OSError:
        # Metadata is diagnostic only; the OS lock, not fsync, is the lease.
        pass


def _try_lock_file(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        # Avoid reading byte 0 before attempting the lock.  On Windows, a
        # competing process may already hold a mandatory byte-range lock there,
        # and even a probe read can fail with PermissionError.  File size can be
        # inspected without touching the locked range.
        if os.fstat(handle.fileno()).st_size == 0:
            handle.seek(0)
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise HostRuntimeLeaseError(
                "another supported HOME process already owns this runtime"
            ) from exc
        return

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise HostRuntimeLeaseError(
            "another supported HOME process already owns this runtime"
        ) from exc


def _unlock_file(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
