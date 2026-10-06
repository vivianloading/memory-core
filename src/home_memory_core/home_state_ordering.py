from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from threading import Condition, Lock, get_ident
from uuid import uuid4

from home_memory_core.process_boundary import current_home_process_instance_id


_HOME_STATE_COORDINATOR_REGISTRY_GUARD = Lock()
_HOME_STATE_COORDINATORS: dict[
    str,
    "HomeStateOrderingCoordinator",
] = {}
_HOME_STATE_CUT_MARKER = object()
_HOME_STATE_WRITE_PERMIT_MARKER = object()


class HomeStateOrderingError(RuntimeError):
    """HOME same-process ordering contract was violated."""


class HomeStateOrderingReentryError(HomeStateOrderingError):
    """Unsafe same-thread writer/cut re-entry was attempted."""


class HomeStateOrderingIntegrityError(HomeStateOrderingError):
    """A process-local ordering witness no longer matches live state."""


@dataclass(frozen=True)
class HomeStateCut:
    coordinator_id: str
    canonical_db_binding_digest: str
    generation: int
    home_process_instance_id: str
    owner_thread_id: int
    cut_id: str
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _HOME_STATE_CUT_MARKER:
            raise HomeStateOrderingIntegrityError(
                "HOME state cut was not issued by the live coordinator"
            )
        _text("coordinator_id", self.coordinator_id)
        _digest(
            "canonical_db_binding_digest",
            self.canonical_db_binding_digest,
        )
        if (
            not isinstance(self.generation, int)
            or isinstance(self.generation, bool)
            or self.generation < 0
        ):
            raise HomeStateOrderingIntegrityError(
                "HOME state cut generation must be non-negative integer"
            )
        _text(
            "home_process_instance_id",
            self.home_process_instance_id,
        )
        if (
            not isinstance(self.owner_thread_id, int)
            or isinstance(self.owner_thread_id, bool)
            or self.owner_thread_id <= 0
        ):
            raise HomeStateOrderingIntegrityError(
                "HOME state cut owner thread id is invalid"
            )
        _text("cut_id", self.cut_id)


class HomeStateWritePermit:
    """Internal process-local permit for one supported semantic write."""

    def __init__(
        self,
        *,
        coordinator: "HomeStateOrderingCoordinator",
        owner_thread_id: int,
    ) -> None:
        self._coordinator = coordinator
        self._owner_thread_id = owner_thread_id
        self._marker = _HOME_STATE_WRITE_PERMIT_MARKER
        self._commit_recorded = False
        self._released = False

    @property
    def commit_recorded(self) -> bool:
        return self._commit_recorded

    def record_successful_commit(self) -> int:
        if self._marker is not _HOME_STATE_WRITE_PERMIT_MARKER:
            raise HomeStateOrderingIntegrityError(
                "HOME write permit marker is invalid"
            )
        if self._released:
            raise HomeStateOrderingIntegrityError(
                "released HOME write permit cannot record commit"
            )
        if self._commit_recorded:
            raise HomeStateOrderingIntegrityError(
                "HOME write permit can record only one successful commit"
            )
        generation = self._coordinator._record_successful_commit(
            permit=self,
            owner_thread_id=self._owner_thread_id,
        )
        self._commit_recorded = True
        return generation

    def release(self) -> None:
        if self._released:
            return
        self._coordinator._release_writer(
            permit=self,
            owner_thread_id=self._owner_thread_id,
        )
        self._released = True


class HomeStateOrderingCoordinator:
    """Serialize supported HOME semantic writes with short local handoff cuts.

    Scope is one Python process and one resolved SQLite path. Raw SQLite and
    other processes are intentionally outside this v0.1 contract.
    """

    def __init__(self, *, db_path: str | Path) -> None:
        resolved = Path(db_path).expanduser().resolve()
        self._resolved_db_path = resolved
        self._canonical_db_binding_digest = sha256(
            str(resolved).encode("utf-8")
        ).hexdigest()
        self._coordinator_id = f"home-ordering-{uuid4().hex}"
        self._home_process_instance_id = (
            current_home_process_instance_id()
        )
        self._condition = Condition(Lock())
        self._generation = 0
        self._writer_owner_thread_id: int | None = None
        self._writer_permit: HomeStateWritePermit | None = None
        self._active_cut: HomeStateCut | None = None

    @property
    def coordinator_id(self) -> str:
        return self._coordinator_id

    @property
    def canonical_db_binding_digest(self) -> str:
        return self._canonical_db_binding_digest

    @property
    def generation(self) -> int:
        self._require_live_process()
        with self._condition:
            return self._generation

    def require_writer_entry_allowed(self) -> None:
        """Fail closed on unsafe same-thread writer re-entry without waiting.

        This is a preflight only. It grants no writer permit and does not
        serialize against other threads. Canonical writer entry must still call
        acquire_writer() after any outer store-specific lock is acquired.
        """
        self._require_live_process()
        owner = get_ident()
        with self._condition:
            self._reject_unsafe_writer_reentry(owner_thread_id=owner)

    def acquire_writer(self) -> HomeStateWritePermit:
        self._require_live_process()
        owner = get_ident()
        with self._condition:
            self._reject_unsafe_writer_reentry(owner_thread_id=owner)

            while (
                self._active_cut is not None
                or self._writer_owner_thread_id is not None
            ):
                self._condition.wait()

            permit = HomeStateWritePermit(
                coordinator=self,
                owner_thread_id=owner,
            )
            self._writer_owner_thread_id = owner
            self._writer_permit = permit
            return permit

    def acquire_cut(self) -> HomeStateCut:
        self._require_live_process()
        owner = get_ident()
        with self._condition:
            if (
                self._active_cut is not None
                and self._active_cut.owner_thread_id == owner
            ):
                raise HomeStateOrderingReentryError(
                    "nested HOME delivery cut is not allowed"
                )
            if self._writer_owner_thread_id == owner:
                raise HomeStateOrderingReentryError(
                    "HOME delivery cut cannot begin inside a supported writer"
                )

            while (
                self._active_cut is not None
                or self._writer_owner_thread_id is not None
            ):
                self._condition.wait()

            cut = HomeStateCut(
                coordinator_id=self._coordinator_id,
                canonical_db_binding_digest=(
                    self._canonical_db_binding_digest
                ),
                generation=self._generation,
                home_process_instance_id=(
                    self._home_process_instance_id
                ),
                owner_thread_id=owner,
                cut_id=f"home-cut-{uuid4().hex}",
                _marker=_HOME_STATE_CUT_MARKER,
            )
            self._active_cut = cut
            return cut

    def require_active_cut(self, *, cut: HomeStateCut) -> None:
        self._require_live_process()
        if not isinstance(cut, HomeStateCut):
            raise TypeError("cut must be HomeStateCut")
        owner = get_ident()
        with self._condition:
            if self._active_cut is not cut:
                raise HomeStateOrderingIntegrityError(
                    "HOME state cut is not the exact active cut"
                )
            if (
                cut.home_process_instance_id
                != self._home_process_instance_id
            ):
                raise HomeStateOrderingIntegrityError(
                    "HOME state cut belongs to another process incarnation"
                )
            if cut.coordinator_id != self._coordinator_id:
                raise HomeStateOrderingIntegrityError(
                    "HOME state cut belongs to another coordinator"
                )
            if (
                cut.canonical_db_binding_digest
                != self._canonical_db_binding_digest
            ):
                raise HomeStateOrderingIntegrityError(
                    "HOME state cut database binding changed"
                )
            if cut.owner_thread_id != owner:
                raise HomeStateOrderingIntegrityError(
                    "HOME state cut can be used only by its owning thread"
                )
            if cut.generation != self._generation:
                raise HomeStateOrderingIntegrityError(
                    "HOME state generation changed inside active cut"
                )

    def release_cut(self, *, cut: HomeStateCut) -> None:
        self._require_live_process()
        if not isinstance(cut, HomeStateCut):
            raise TypeError("cut must be HomeStateCut")
        owner = get_ident()
        with self._condition:
            if self._active_cut is not cut:
                raise HomeStateOrderingIntegrityError(
                    "cannot release a non-active HOME state cut"
                )
            if cut.owner_thread_id != owner:
                raise HomeStateOrderingIntegrityError(
                    "HOME state cut must be released by its owner thread"
                )
            if cut.generation != self._generation:
                raise HomeStateOrderingIntegrityError(
                    "HOME state generation changed before cut release"
                )
            self._active_cut = None
            self._condition.notify_all()

    def _record_successful_commit(
        self,
        *,
        permit: HomeStateWritePermit,
        owner_thread_id: int,
    ) -> int:
        self._require_live_process()
        with self._condition:
            self._require_live_writer(
                permit=permit,
                owner_thread_id=owner_thread_id,
            )
            self._generation += 1
            return self._generation

    def _release_writer(
        self,
        *,
        permit: HomeStateWritePermit,
        owner_thread_id: int,
    ) -> None:
        self._require_live_process()
        with self._condition:
            self._require_live_writer(
                permit=permit,
                owner_thread_id=owner_thread_id,
            )
            self._writer_owner_thread_id = None
            self._writer_permit = None
            self._condition.notify_all()

    def _reject_unsafe_writer_reentry(
        self,
        *,
        owner_thread_id: int,
    ) -> None:
        if (
            self._active_cut is not None
            and self._active_cut.owner_thread_id == owner_thread_id
        ):
            raise HomeStateOrderingReentryError(
                "same-thread HOME writer cannot run inside a delivery cut"
            )
        if self._writer_owner_thread_id == owner_thread_id:
            raise HomeStateOrderingReentryError(
                "nested HOME supported writer transaction is not allowed"
            )

    def _require_live_process(self) -> None:
        current = current_home_process_instance_id()
        if current != self._home_process_instance_id:
            raise HomeStateOrderingIntegrityError(
                "HOME state coordinator belongs to another process incarnation"
            )

    def _require_live_writer(
        self,
        *,
        permit: HomeStateWritePermit,
        owner_thread_id: int,
    ) -> None:
        if (
            self._writer_owner_thread_id != owner_thread_id
            or self._writer_permit is not permit
            or get_ident() != owner_thread_id
        ):
            raise HomeStateOrderingIntegrityError(
                "HOME write permit is not the exact live writer permit"
            )


def home_state_coordinator_for_path(
    db_path: str | Path,
) -> HomeStateOrderingCoordinator:
    # Fail before consulting inherited process-local registries after fork.
    current_home_process_instance_id()
    resolved = Path(db_path).expanduser().resolve()
    key = str(resolved)
    with _HOME_STATE_COORDINATOR_REGISTRY_GUARD:
        coordinator = _HOME_STATE_COORDINATORS.get(key)
        if coordinator is None:
            coordinator = HomeStateOrderingCoordinator(
                db_path=resolved
            )
            _HOME_STATE_COORDINATORS[key] = coordinator
        return coordinator


def _text(field_name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise HomeStateOrderingIntegrityError(
            f"{field_name} must be non-empty text"
        )


def _digest(field_name: str, value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(
            char not in "0123456789abcdef"
            for char in value
        )
    ):
        raise HomeStateOrderingIntegrityError(
            f"{field_name} must be lowercase sha256"
        )
