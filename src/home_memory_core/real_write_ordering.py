from __future__ import annotations

from pathlib import Path
from threading import RLock

from home_memory_core.real_authority_ordering import real_authority_lock_for_path


def real_write_ordering_lock_for_path(db_path: str | Path) -> RLock:
    """Compatibility wrapper retained after #06a.5 authority-ordering rename.

    New real-data code must use `real_authority_operation(...)` so lifecycle and
    stale-generation checks are enforced. This function exists only to avoid a
    silent import break for code written before the rename.
    """

    return real_authority_lock_for_path(db_path)
