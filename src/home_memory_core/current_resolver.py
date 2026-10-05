from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
import sqlite3

from home_memory_core.current_admission import (
    CURRENT_END_ADMISSION_TABLE,
    CURRENT_STATE_ADMISSION_TABLE,
    CurrentAdmissionAuthority,
    CurrentAdmissionEffectKind,
    CurrentAdmissionReceipt,
    assert_current_admission_data_integrity,
    assert_current_admission_schema,
)
from home_memory_core.current_store import (
    CurrentStore,
    _end_from_row,
    _read_bindings,
    _state_from_row,
)
from home_memory_core.current_store_schema import (
    CURRENT_END_EVIDENCE_TABLE,
    CURRENT_END_TABLE,
    CURRENT_STATE_EVIDENCE_TABLE,
    CURRENT_STATE_TABLE,
)
from home_memory_core.current_use import (
    CurrentPresentUseStatus,
    CurrentSuppressionBlock,
    CurrentUseEffectKind,
    _current_effect_use_decision,
)
from home_memory_core.current_view import (
    CurrentNamespace,
    CurrentResolution,
    CurrentStanding,
    CurrentStateEndEvent,
    CurrentStateRecord,
    resolve_current_state,
)
from home_memory_core.storage import assert_source_suppression_ledger


_CURRENT_RESOLVER_MARKER = object()


class CurrentResolverError(RuntimeError):
    """Base error for present Current resolution."""


class CurrentResolverClosedBoundaryError(CurrentResolverError):
    """The requested Current namespace has no operational resolver path yet."""


class CurrentResolverStatus(StrEnum):
    RESOLVED = "resolved"
    BLOCKED_UNKNOWN = "blocked_unknown"
    ADMISSION_PROOF_UNAVAILABLE = "admission_proof_unavailable"


@dataclass(frozen=True)
class CurrentResolverDependency:
    effect_kind: CurrentUseEffectKind
    effect_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.effect_kind, CurrentUseEffectKind):
            raise CurrentResolverError(
                "effect_kind must use CurrentUseEffectKind"
            )
        if not isinstance(self.effect_id, str) or not self.effect_id.strip():
            raise CurrentResolverError("effect_id must be non-empty text")


@dataclass(frozen=True)
class CurrentResolverDecision:
    """Safe present-use decision plus inspectable semantic derivation."""

    namespace: CurrentNamespace
    owner_id: str
    key: str
    as_of: datetime
    status: CurrentResolverStatus
    semantic_resolution: CurrentResolution | None
    dependencies: tuple[CurrentResolverDependency, ...]
    blocks: tuple[CurrentSuppressionBlock, ...]
    missing_live_admission_effects: tuple[CurrentResolverDependency, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, CurrentNamespace):
            raise CurrentResolverError("namespace must use CurrentNamespace")
        for field_name in ("owner_id", "key"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise CurrentResolverError(
                    f"{field_name} must be non-empty text"
                )
        _require_aware("as_of", self.as_of)
        if not isinstance(self.status, CurrentResolverStatus):
            raise CurrentResolverError(
                "status must use CurrentResolverStatus"
            )
        if self.semantic_resolution is not None:
            if not isinstance(self.semantic_resolution, CurrentResolution):
                raise CurrentResolverError(
                    "semantic_resolution must use CurrentResolution"
                )
            if (
                self.semantic_resolution.namespace is not self.namespace
                or self.semantic_resolution.owner_id != self.owner_id
                or self.semantic_resolution.key != self.key
            ):
                raise CurrentResolverError(
                    "semantic resolution identity does not match resolver decision"
                )

        if self.status is CurrentResolverStatus.RESOLVED:
            if (
                self.semantic_resolution is None
                or self.blocks
                or self.missing_live_admission_effects
            ):
                raise CurrentResolverError(
                    "resolved Current decision has inconsistent proof state"
                )
        elif self.status is CurrentResolverStatus.BLOCKED_UNKNOWN:
            if (
                self.semantic_resolution is None
                or not self.blocks
                or self.missing_live_admission_effects
            ):
                raise CurrentResolverError(
                    "blocked_unknown requires semantic result and suppression blocks"
                )
        elif self.status is CurrentResolverStatus.ADMISSION_PROOF_UNAVAILABLE:
            if (
                self.semantic_resolution is not None
                or self.blocks
                or not self.missing_live_admission_effects
            ):
                raise CurrentResolverError(
                    "admission_proof_unavailable requires exact missing live proof"
                )

    @property
    def usable_standing(self) -> CurrentStanding | None:
        if self.status is not CurrentResolverStatus.RESOLVED:
            return None
        assert self.semantic_resolution is not None
        return self.semantic_resolution.standing

    @property
    def usable_current_state_ids(self) -> tuple[str, ...]:
        if self.status is not CurrentResolverStatus.RESOLVED:
            return ()
        assert self.semantic_resolution is not None
        return self.semantic_resolution.current_state_ids


@dataclass(frozen=True)
class CurrentResolvedView:
    as_of: datetime
    namespace: CurrentNamespace
    owner_id: str
    items: tuple[CurrentResolverDecision, ...]


class CurrentResolver:
    """Read-only Room Current resolver bound to one live admission authority.

    Durable admission audit is corroborating history, never sufficient proof of
    operational admission. Only receipts actually issued by the bound live
    CurrentAdmissionAuthority may authorize effects to enter semantic Current.

    If durable admission-shaped history exists without matching live proof,
    v0.1 reports ADMISSION_PROOF_UNAVAILABLE rather than guessing across the
    process boundary.
    """

    def __init__(
        self,
        *,
        admission_authority: CurrentAdmissionAuthority,
        _marker: object,
    ) -> None:
        if _marker is not _CURRENT_RESOLVER_MARKER:
            raise CurrentResolverError(
                "CurrentResolver must be opened through HOME"
            )
        if not isinstance(admission_authority, CurrentAdmissionAuthority):
            raise TypeError(
                "admission_authority must be CurrentAdmissionAuthority"
            )
        admission_authority._assert_live_authority_binding()
        self._admission_authority = admission_authority
        self._canonical_db_path = Path(
            admission_authority._canonical_db_path
        ).resolve()

    def resolve_key(
        self,
        *,
        namespace: CurrentNamespace,
        owner_id: str,
        key: str,
        as_of: datetime,
    ) -> CurrentResolverDecision:
        _validate_request(
            namespace=namespace,
            owner_id=owner_id,
            key=key,
            as_of=as_of,
        )
        self._assert_live_binding()
        connection = self._read_connection()
        try:
            receipts = (
                self._admission_authority
                ._snapshot_live_receipts_for_resolution(
                    connection=connection,
                )
            )
            missing = _missing_live_admission_effects(
                connection=connection,
                namespace=namespace,
                owner_id=owner_id,
                key=key,
                as_of=as_of,
                receipts=receipts,
            )
            if missing:
                return CurrentResolverDecision(
                    namespace=namespace,
                    owner_id=owner_id,
                    key=key,
                    as_of=as_of,
                    status=(
                        CurrentResolverStatus.ADMISSION_PROOF_UNAVAILABLE
                    ),
                    semantic_resolution=None,
                    dependencies=(),
                    blocks=(),
                    missing_live_admission_effects=missing,
                    reason_codes=("LIVE_ADMISSION_PROOF_UNAVAILABLE",),
                )

            records, end_events = _read_live_admitted_history(
                connection=connection,
                receipts=receipts,
            )
            return _resolve_key_in_connection(
                connection=connection,
                namespace=namespace,
                owner_id=owner_id,
                key=key,
                as_of=as_of,
                records=records,
                end_events=end_events,
            )
        finally:
            connection.close()

    def resolve_owner(
        self,
        *,
        namespace: CurrentNamespace,
        owner_id: str,
        as_of: datetime,
    ) -> CurrentResolvedView:
        _validate_owner_request(
            namespace=namespace,
            owner_id=owner_id,
            as_of=as_of,
        )
        self._assert_live_binding()
        connection = self._read_connection()
        try:
            receipts = (
                self._admission_authority
                ._snapshot_live_receipts_for_resolution(
                    connection=connection,
                )
            )
            keys = _operational_keys(
                connection=connection,
                namespace=namespace,
                owner_id=owner_id,
                as_of=as_of,
            )
            items = tuple(
                self._resolve_key_with_receipts(
                    connection=connection,
                    receipts=receipts,
                    namespace=namespace,
                    owner_id=owner_id,
                    key=key,
                    as_of=as_of,
                )
                for key in keys
            )
            return CurrentResolvedView(
                as_of=as_of,
                namespace=namespace,
                owner_id=owner_id,
                items=items,
            )
        finally:
            connection.close()

    def _resolve_key_with_receipts(
        self,
        *,
        connection: sqlite3.Connection,
        receipts: tuple[CurrentAdmissionReceipt, ...],
        namespace: CurrentNamespace,
        owner_id: str,
        key: str,
        as_of: datetime,
    ) -> CurrentResolverDecision:
        missing = _missing_live_admission_effects(
            connection=connection,
            namespace=namespace,
            owner_id=owner_id,
            key=key,
            as_of=as_of,
            receipts=receipts,
        )
        if missing:
            return CurrentResolverDecision(
                namespace=namespace,
                owner_id=owner_id,
                key=key,
                as_of=as_of,
                status=CurrentResolverStatus.ADMISSION_PROOF_UNAVAILABLE,
                semantic_resolution=None,
                dependencies=(),
                blocks=(),
                missing_live_admission_effects=missing,
                reason_codes=("LIVE_ADMISSION_PROOF_UNAVAILABLE",),
            )
        records, end_events = _read_live_admitted_history(
            connection=connection,
            receipts=receipts,
        )
        return _resolve_key_in_connection(
            connection=connection,
            namespace=namespace,
            owner_id=owner_id,
            key=key,
            as_of=as_of,
            records=records,
            end_events=end_events,
        )

    def _assert_live_binding(self) -> None:
        self._admission_authority._assert_live_authority_binding()
        current = Path(
            self._admission_authority._canonical_db_path
        ).resolve()
        if current != self._canonical_db_path:
            raise CurrentResolverError(
                "Current Resolver canonical database binding changed"
            )

    def _read_connection(self) -> sqlite3.Connection:
        try:
            connection = CurrentStore(
                self._canonical_db_path
            )._read_connection()
            assert_current_admission_schema(connection)
            assert_current_admission_data_integrity(connection)
            assert_source_suppression_ledger(connection)
            return connection
        except Exception:
            if "connection" in locals():
                connection.close()
            raise


def open_current_resolver(
    *,
    admission_authority: CurrentAdmissionAuthority,
) -> CurrentResolver:
    if not isinstance(admission_authority, CurrentAdmissionAuthority):
        raise TypeError(
            "admission_authority must be CurrentAdmissionAuthority"
        )
    admission_authority._assert_live_authority_binding()
    return CurrentResolver(
        admission_authority=admission_authority,
        _marker=_CURRENT_RESOLVER_MARKER,
    )


def _resolve_key_in_connection(
    *,
    connection: sqlite3.Connection,
    namespace: CurrentNamespace,
    owner_id: str,
    key: str,
    as_of: datetime,
    records: tuple[CurrentStateRecord, ...],
    end_events: tuple[CurrentStateEndEvent, ...],
) -> CurrentResolverDecision:
    semantic = resolve_current_state(
        namespace=namespace,
        owner_id=owner_id,
        key=key,
        records=records,
        end_events=end_events,
        as_of=as_of,
    )
    dependencies = _semantic_dependencies(semantic)
    blocks: list[CurrentSuppressionBlock] = []
    for dependency in dependencies:
        decision = _current_effect_use_decision(
            connection=connection,
            effect_kind=dependency.effect_kind,
            effect_id=dependency.effect_id,
        )
        if decision.status is CurrentPresentUseStatus.SUPPRESSED:
            blocks.extend(decision.blocks)

    exact_blocks = _dedupe_blocks(tuple(blocks))
    if exact_blocks:
        return CurrentResolverDecision(
            namespace=namespace,
            owner_id=owner_id,
            key=key,
            as_of=as_of,
            status=CurrentResolverStatus.BLOCKED_UNKNOWN,
            semantic_resolution=semantic,
            dependencies=dependencies,
            blocks=exact_blocks,
            missing_live_admission_effects=(),
            reason_codes=("SEMANTIC_DEPENDENCY_SUPPRESSED",),
        )
    return CurrentResolverDecision(
        namespace=namespace,
        owner_id=owner_id,
        key=key,
        as_of=as_of,
        status=CurrentResolverStatus.RESOLVED,
        semantic_resolution=semantic,
        dependencies=dependencies,
        blocks=(),
        missing_live_admission_effects=(),
        reason_codes=("SEMANTIC_DEPENDENCIES_USABLE",),
    )


def _missing_live_admission_effects(
    *,
    connection: sqlite3.Connection,
    namespace: CurrentNamespace,
    owner_id: str,
    key: str,
    as_of: datetime,
    receipts: tuple[CurrentAdmissionReceipt, ...],
) -> tuple[CurrentResolverDependency, ...]:
    """Find durable admission-shaped effects lacking live process proof.

    Durable audit rows are used only to deny/fail closed here. They never
    authorize semantic inclusion.
    """

    live_state_ids = {
        receipt.effect_id
        for receipt in receipts
        if receipt.effect_kind is CurrentAdmissionEffectKind.STATE
    }
    live_end_ids = {
        receipt.effect_id
        for receipt in receipts
        if receipt.effect_kind is CurrentAdmissionEffectKind.END_EVENT
    }
    cut = _instant(as_of)
    missing: list[CurrentResolverDependency] = []

    state_rows = connection.execute(
        f"""
        SELECT state.state_id
        FROM {CURRENT_STATE_TABLE} AS state
        JOIN {CURRENT_STATE_ADMISSION_TABLE} AS admission
          ON admission.state_id=state.state_id
        WHERE state.namespace=?
          AND state.owner_id=?
          AND state.key=?
          AND state.recorded_instant_us<=?
        ORDER BY state.state_id
        """,
        (namespace.value, owner_id, key, cut),
    ).fetchall()
    for row in state_rows:
        if row["state_id"] not in live_state_ids:
            missing.append(
                CurrentResolverDependency(
                    effect_kind=CurrentUseEffectKind.STATE,
                    effect_id=row["state_id"],
                )
            )

    end_rows = connection.execute(
        f"""
        SELECT event.end_event_id
        FROM {CURRENT_END_TABLE} AS event
        JOIN {CURRENT_END_ADMISSION_TABLE} AS admission
          ON admission.end_event_id=event.end_event_id
        JOIN {CURRENT_STATE_TABLE} AS state
          ON state.state_id=event.state_id
        WHERE state.namespace=?
          AND state.owner_id=?
          AND state.key=?
          AND event.recorded_instant_us<=?
        ORDER BY event.end_event_id
        """,
        (namespace.value, owner_id, key, cut),
    ).fetchall()
    for row in end_rows:
        if row["end_event_id"] not in live_end_ids:
            missing.append(
                CurrentResolverDependency(
                    effect_kind=CurrentUseEffectKind.END_EVENT,
                    effect_id=row["end_event_id"],
                )
            )

    return _dedupe_dependencies(tuple(missing))


def _operational_keys(
    *,
    connection: sqlite3.Connection,
    namespace: CurrentNamespace,
    owner_id: str,
    as_of: datetime,
) -> tuple[str, ...]:
    cut = _instant(as_of)
    rows = connection.execute(
        f"""
        SELECT DISTINCT state.key
        FROM {CURRENT_STATE_TABLE} AS state
        JOIN {CURRENT_STATE_ADMISSION_TABLE} AS admission
          ON admission.state_id=state.state_id
        WHERE state.namespace=?
          AND state.owner_id=?
          AND state.recorded_instant_us<=?
        ORDER BY state.key
        """,
        (namespace.value, owner_id, cut),
    ).fetchall()
    return tuple(row["key"] for row in rows)


def _read_live_admitted_history(
    *,
    connection: sqlite3.Connection,
    receipts: tuple[CurrentAdmissionReceipt, ...],
) -> tuple[
    tuple[CurrentStateRecord, ...],
    tuple[CurrentStateEndEvent, ...],
]:
    state_ids = {
        receipt.effect_id
        for receipt in receipts
        if receipt.effect_kind is CurrentAdmissionEffectKind.STATE
    }
    end_ids = {
        receipt.effect_id
        for receipt in receipts
        if receipt.effect_kind is CurrentAdmissionEffectKind.END_EVENT
    }

    records: list[CurrentStateRecord] = []
    for row in connection.execute(
        f"SELECT * FROM {CURRENT_STATE_TABLE} ORDER BY state_id"
    ).fetchall():
        if row["state_id"] not in state_ids:
            continue
        bindings = _read_bindings(
            connection,
            CURRENT_STATE_EVIDENCE_TABLE,
            "state_id",
            row["state_id"],
        )
        records.append(_state_from_row(row, bindings))

    end_events: list[CurrentStateEndEvent] = []
    for row in connection.execute(
        f"SELECT * FROM {CURRENT_END_TABLE} ORDER BY end_event_id"
    ).fetchall():
        if row["end_event_id"] not in end_ids:
            continue
        bindings = _read_bindings(
            connection,
            CURRENT_END_EVIDENCE_TABLE,
            "end_event_id",
            row["end_event_id"],
        )
        end_events.append(_end_from_row(row, bindings))

    return tuple(records), tuple(end_events)


def _semantic_dependencies(
    semantic: CurrentResolution,
) -> tuple[CurrentResolverDependency, ...]:
    dependencies: list[CurrentResolverDependency] = []
    for candidate in semantic.candidates:
        dependencies.append(
            CurrentResolverDependency(
                effect_kind=CurrentUseEffectKind.STATE,
                effect_id=candidate.state_id,
            )
        )
        for event in candidate.end_events:
            dependencies.append(
                CurrentResolverDependency(
                    effect_kind=CurrentUseEffectKind.END_EVENT,
                    effect_id=event.end_event_id,
                )
            )
    return _dedupe_dependencies(tuple(dependencies))


def _dedupe_dependencies(
    dependencies: tuple[CurrentResolverDependency, ...],
) -> tuple[CurrentResolverDependency, ...]:
    seen: set[tuple[CurrentUseEffectKind, str]] = set()
    result: list[CurrentResolverDependency] = []
    for dependency in dependencies:
        identity = (dependency.effect_kind, dependency.effect_id)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(dependency)
    return tuple(result)


def _dedupe_blocks(
    blocks: tuple[CurrentSuppressionBlock, ...],
) -> tuple[CurrentSuppressionBlock, ...]:
    seen: set[
        tuple[str, str, str, CurrentUseEffectKind, str]
    ] = set()
    result: list[CurrentSuppressionBlock] = []
    for block in blocks:
        identity = (
            block.source_ref,
            block.source_id,
            block.suppression_id,
            block.origin_effect_kind,
            block.origin_effect_id,
        )
        if identity in seen:
            continue
        seen.add(identity)
        result.append(block)
    return tuple(result)


def _validate_owner_request(
    *,
    namespace: CurrentNamespace,
    owner_id: str,
    as_of: datetime,
) -> None:
    if not isinstance(namespace, CurrentNamespace):
        raise CurrentResolverError("namespace must use CurrentNamespace")
    if namespace is not CurrentNamespace.ROOM:
        raise CurrentResolverClosedBoundaryError(
            "Current Resolver v0.1 is Room-only until Shared admission exists"
        )
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise CurrentResolverError("owner_id must be non-empty text")
    _require_aware("as_of", as_of)


def _validate_request(
    *,
    namespace: CurrentNamespace,
    owner_id: str,
    key: str,
    as_of: datetime,
) -> None:
    _validate_owner_request(
        namespace=namespace,
        owner_id=owner_id,
        as_of=as_of,
    )
    if not isinstance(key, str) or not key.strip():
        raise CurrentResolverError("key must be non-empty text")


def _require_aware(field_name: str, value: datetime) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise CurrentResolverError(
            f"{field_name} must be timezone-aware"
        )


def _instant(value: datetime) -> int:
    _require_aware("timestamp", value)
    offset = value.utcoffset()
    assert offset is not None
    wall_micros = (
        (
            (
                (value.toordinal() * 24 + value.hour) * 60
                + value.minute
            )
            * 60
            + value.second
        )
        * 1_000_000
        + value.microsecond
    )
    offset_micros = (
        (offset.days * 86_400 + offset.seconds) * 1_000_000
        + offset.microseconds
    )
    return wall_micros - offset_micros
