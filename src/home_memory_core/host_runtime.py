from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import sys
from typing import IO


class HostRuntimeLeaseError(RuntimeError):
    """The supported HOME host runtime could not acquire exclusive ownership."""


class HostRuntimeConfigurationError(RuntimeError):
    """The supported HOME host runtime configuration is unsafe or inconsistent."""


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
    real_data_allowed: bool = False


class HomeSingleInstanceLease:
    """OS-backed exclusive lease for the supported single-process HOME host.

    The lock is advisory with respect to arbitrary external programs, so the
    contract is deliberately narrow: every supported HOME mini-host entry point
    must acquire this lease before opening the canonical database. Direct SQL or
    processes that bypass this boundary remain unsupported.
    """

    def __init__(self, *, identity: HomeHostRuntimeIdentity, handle: IO[bytes]) -> None:
        self._identity = identity
        self._handle = handle
        self._released = False

    @property
    def identity(self) -> HomeHostRuntimeIdentity:
        return self._identity

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> None:
        if self._released:
            return
        _unlock_file(self._handle)
        self._handle.close()
        self._released = True

    def __enter__(self) -> HomeSingleInstanceLease:
        if self._released:
            raise HostRuntimeLeaseError("released HOME host lease cannot be reused")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


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

    if real_data_allowed:
        raise HostRuntimeConfigurationError(
            "mini-host runtime remains closed to real personal data"
        )

    root = _canonical_path(runtime_root)
    database = _canonical_path(db_path)
    root.mkdir(parents=True, exist_ok=True)

    lock_path = root / ".home-runtime.lock"
    handle = lock_path.open("a+b", buffering=0)
    try:
        _try_lock_file(handle)
    except Exception:
        handle.close()
        raise

    identity = HomeHostRuntimeIdentity(
        runtime_root=root,
        db_path=database,
        process_instance_id=f"host-{secrets.token_hex(16)}",
        real_data_allowed=False,
    )

    try:
        _write_lock_metadata(handle, identity)
    except Exception:
        _unlock_file(handle)
        handle.close()
        raise

    return HomeSingleInstanceLease(identity=identity, handle=handle)


def _canonical_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    try:
        return path.resolve(strict=False)
    except OSError as exc:
        raise HostRuntimeConfigurationError(
            f"cannot canonicalize HOME host path: {path}"
        ) from exc


def _write_lock_metadata(
    handle: IO[bytes],
    identity: HomeHostRuntimeIdentity,
) -> None:
    metadata = {
        "schema": "home-single-instance-v0.1",
        "pid": os.getpid(),
        "process_instance_id": identity.process_instance_id,
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

        handle.seek(0)
        # msvcrt locking requires the byte range to exist.
        if handle.read(1) == b"":
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
