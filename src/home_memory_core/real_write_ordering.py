from __future__ import annotations

from pathlib import Path
from threading import Lock, RLock


_REAL_WRITE_LOCK_REGISTRY_GUARD = Lock()
_REAL_WRITE_LOCKS: dict[str, RLock] = {}


def real_write_ordering_lock_for_path(db_path: str | Path) -> RLock:
    """Return the same-process ordering lock for one real HOME store.

    Every closed real-data write path that performs authorization followed by a
    commit must share this lock. It is intentionally only a first local-pilot
    primitive; it is not sufficient for multi-process writers or remote policy
    authorities.
    """

    key = str(Path(db_path).expanduser().resolve())
    with _REAL_WRITE_LOCK_REGISTRY_GUARD:
        lock = _REAL_WRITE_LOCKS.get(key)
        if lock is None:
            lock = RLock()
            _REAL_WRITE_LOCKS[key] = lock
        return lock
