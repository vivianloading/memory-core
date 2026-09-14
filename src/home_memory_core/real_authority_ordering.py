from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import Lock, RLock, get_ident
from typing import Iterator


class RealStoreLifecycleState(StrEnum):
    ACTIVE = "active"
    CLOSING = "closing"
    DESTROYED = "destroyed"


class RealStoreLifecycleError(RuntimeError):
    """A stale or closed real-store object attempted another authority operation."""


class RealHandoffReentrancyError(RuntimeError):
    """Authority mutation/reentry was attempted from inside final handoff."""


@dataclass
class _RealAuthorityCoordinator:
    lock: RLock
    state: RealStoreLifecycleState = RealStoreLifecycleState.ACTIVE
    generation: int = 0
    handoff_thread_id: int | None = None


_REGISTRY_GUARD = Lock()
_COORDINATORS: dict[str, _RealAuthorityCoordinator] = {}


def _key_for_path(db_path: str | Path) -> str:
    return str(Path(db_path).expanduser().resolve())


def _coordinator_for_path(db_path: str | Path) -> _RealAuthorityCoordinator:
    key = _key_for_path(db_path)
    with _REGISTRY_GUARD:
        coordinator = _COORDINATORS.get(key)
        if coordinator is None:
            coordinator = _RealAuthorityCoordinator(lock=RLock())
            _COORDINATORS[key] = coordinator
        return coordinator


def capture_real_store_generation(db_path: str | Path) -> int:
    """Capture the current same-process store generation for a long-lived writer.

    Destroy + explicit re-bootstrap advances the generation. A writer holding an
    older generation then fails closed instead of silently becoming active on a
    newly-created database at the same filesystem path.
    """

    coordinator = _coordinator_for_path(db_path)
    with coordinator.lock:
        return coordinator.generation


@contextmanager
def real_authority_operation(
    db_path: str | Path,
    *,
    expected_generation: int | None = None,
) -> Iterator[None]:
    """Serialize one supported real authority/use operation for a local store.

    This is intentionally a same-process, single-store primitive. It gives HOME
    a linear order between closed real writes, source stop-use, and whole-store
    lifecycle transitions. It is not a cross-process or distributed lock.
    """

    coordinator = _coordinator_for_path(db_path)
    current_thread = get_ident()
    if coordinator.handoff_thread_id == current_thread:
        raise RealHandoffReentrancyError(
            "HOME authority operation cannot re-enter from final handoff"
        )
    with coordinator.lock:
        if coordinator.handoff_thread_id == current_thread:
            raise RealHandoffReentrancyError(
                "HOME authority operation cannot re-enter from final handoff"
            )
        if coordinator.state is not RealStoreLifecycleState.ACTIVE:
            raise RealStoreLifecycleError(
                f"real store is not active: {coordinator.state.value}"
            )
        if (
            expected_generation is not None
            and expected_generation != coordinator.generation
        ):
            raise RealStoreLifecycleError("real store object belongs to a stale generation")
        yield


@contextmanager
def real_final_handoff_operation(
    db_path: str | Path,
    *,
    expected_generation: int | None = None,
) -> Iterator[None]:
    """Hold the authority coordinator across one synchronous final disclosure.

    The active thread is marked so a trusted sink cannot re-enter HOME authority
    mutation/reset/nested-handoff paths through the coordinator's RLock. Other
    threads block until the callback has returned or unwound.
    """

    coordinator = _coordinator_for_path(db_path)
    current_thread = get_ident()
    if coordinator.handoff_thread_id == current_thread:
        raise RealHandoffReentrancyError(
            "nested final handoff is not allowed"
        )
    with coordinator.lock:
        if coordinator.state is not RealStoreLifecycleState.ACTIVE:
            raise RealStoreLifecycleError(
                f"real store is not active: {coordinator.state.value}"
            )
        if (
            expected_generation is not None
            and expected_generation != coordinator.generation
        ):
            raise RealStoreLifecycleError(
                "real store object belongs to a stale generation"
            )
        if coordinator.handoff_thread_id is not None:
            raise RealHandoffReentrancyError(
                "another final handoff is already active"
            )
        coordinator.handoff_thread_id = current_thread
        try:
            yield
        finally:
            coordinator.handoff_thread_id = None


@contextmanager
def real_authority_maintenance(db_path: str | Path) -> Iterator[None]:
    """Serialize startup/schema maintenance before the store is published."""

    with real_authority_operation(db_path):
        yield


def begin_real_store_bootstrap(db_path: str | Path) -> _RealAuthorityCoordinator:
    """Return the coordinator locked by the caller for explicit bootstrap use.

    Store-domain code uses this low-level helper so a trusted bootstrap can
    activate a new lifecycle generation after creating the domain marker.
    """

    coordinator = _coordinator_for_path(db_path)
    if coordinator.handoff_thread_id == get_ident():
        raise RealHandoffReentrancyError(
            "real-store bootstrap/reset cannot re-enter from final handoff"
        )
    return coordinator


def activate_bootstrapped_real_store(
    db_path: str | Path,
    *,
    is_new_store: bool,
) -> None:
    """Mark a trusted bootstrap as active while its coordinator lock is held."""

    coordinator = _coordinator_for_path(db_path)
    if is_new_store:
        coordinator.generation += 1
    coordinator.state = RealStoreLifecycleState.ACTIVE


def mark_real_store_closing(db_path: str | Path) -> _RealAuthorityCoordinator:
    """Return coordinator for a reset operation; caller must hold its lock."""

    coordinator = _coordinator_for_path(db_path)
    if coordinator.state is not RealStoreLifecycleState.ACTIVE:
        raise RealStoreLifecycleError(
            f"real store cannot begin reset from {coordinator.state.value}"
        )
    coordinator.state = RealStoreLifecycleState.CLOSING
    coordinator.generation += 1
    return coordinator


def mark_real_store_destroyed(db_path: str | Path) -> None:
    coordinator = _coordinator_for_path(db_path)
    coordinator.state = RealStoreLifecycleState.DESTROYED


def restore_real_store_active_after_failed_reset(db_path: str | Path) -> None:
    """Fail a pre-destruction reset without leaving a healthy store closed.

    The reset generation is still advanced, deliberately invalidating writer
    objects that overlapped the failed lifecycle attempt. Fresh writer objects
    may be constructed after the caller has handled the failure.
    """

    coordinator = _coordinator_for_path(db_path)
    coordinator.state = RealStoreLifecycleState.ACTIVE


def real_authority_lock_for_path(db_path: str | Path) -> RLock:
    """Compatibility access for old local code; prefer real_authority_operation."""

    return _coordinator_for_path(db_path).lock
