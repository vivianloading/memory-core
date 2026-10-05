from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
import sqlite3

from home_memory_core.current_admission import (
    CURRENT_END_ADMISSION_TABLE,
    CURRENT_STATE_ADMISSION_TABLE,
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


class CurrentResolverError(RuntimeError):
    """Base error for present Current resolution above admitted persisted history."""


class CurrentResolverClosedBoundaryError(CurrentResolverError):
    """The requested Current namespace has no operational admission path yet."""


class CurrentResolverStatus(StrEnum):
    RESOLVED = "resolved"
    BLOCKED_UNKNOWN = "blocked_unknown"


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
    """Safe present-use decision plus the admitted semantic audit result."""

    namespace: CurrentNamespace
    owner_id: str
    key: str
    as_of: datetime
    status: CurrentResolverStatus
    audit_resolution: CurrentResolution
    dependencies: tuple[CurrentResolverDependency, ...]
    blocks: tuple[CurrentSuppressionBlock, ...]
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
        if not isinstance(self.audit_resolution, CurrentResolution):
            raise CurrentResolverError(
                "audit_resolution must use CurrentResolution"
            )
        if (
            self.audit_resolution.namespace is not self.namespace
            or self.audit_resolution.owner_id != self.owner_id
            or self.audit_resolution.key != self.key
        ):
            raise CurrentResolverError(
                "audit resolution identity does not match resolver decision"
            )
        if self.status is CurrentResolverStatus.RESOLVED:
            if self.blocks:
                raise CurrentResolverError(
                    "resolved Current decision cannot carry suppression blocks"
                )
        elif not self.blocks:
            raise CurrentResolverError(
                "blocked_unknown Current decision requires suppression blocks"
            )

    @property
    def usable_standing(self) -> CurrentStanding | None:
        if self.status is CurrentResolverStatus.BLOCKED_UNKNOWN:
            return None
        return self.audit_resolution.standing

    @property
    def usable_current_state_ids(self) -> tuple[str, ...]:
        if self.status is CurrentResolverStatus.BLOCKED_UNKNOWN:
            return ()
        return self.audit_resolution.current_state_ids


@dataclass(frozen=True)
class CurrentResolvedView:
    as_of: datetime
    namespace: CurrentNamespace
    owner_id: str
    items: tuple[CurrentResolverDecision, ...]


class CurrentResolver:
    """Read-only Room Current resolver.

    v0.1 resolves only effects that crossed durable Room Current admission.
    Persisted-but-unadmitted history remains audit-only and cannot shape the
    operational semantic input. Suppression is then overlaid without filtering
    admitted history or manufacturing fallback.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

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
        connection = self._read_connection()
        try:
            records, end_events = _read_admitted_history(connection)
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
        connection = self._read_connection()
        try:
            records, end_events = _read_admitted_history(connection)
            keys = tuple(
                sorted(
                    {
                        record.key
                        for record in records
                        if (
                            record.namespace is namespace
                            and record.owner_id == owner_id
                            and _instant(record.recorded_at) <= _instant(as_of)
                        )
                    }
                )
            )
            items = tuple(
                _resolve_key_in_connection(
                    connection=connection,
                    namespace=namespace,
                    owner_id=owner_id,
                    key=key,
                    as_of=as_of,
                    records=records,
                    end_events=end_events,
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

    def _read_connection(self) -> sqlite3.Connection:
        try:
            connection = CurrentStore(self.db_path)._read_connection()
            assert_current_admission_schema(connection)
            assert_current_admission_data_integrity(connection)
            assert_source_suppression_ledger(connection)
            return connection
        except Exception:
            if "connection" in locals():
                connection.close()
            raise


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
            audit_resolution=semantic,
            dependencies=dependencies,
            blocks=exact_blocks,
            reason_codes=("SEMANTIC_DEPENDENCY_SUPPRESSED",),
        )
    return CurrentResolverDecision(
        namespace=namespace,
        owner_id=owner_id,
        key=key,
        as_of=as_of,
        status=CurrentResolverStatus.RESOLVED,
        audit_resolution=semantic,
        dependencies=dependencies,
        blocks=(),
        reason_codes=("SEMANTIC_DEPENDENCIES_USABLE",),
    )


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


def _read_admitted_history(
    connection: sqlite3.Connection,
) -> tuple[
    tuple[CurrentStateRecord, ...],
    tuple[CurrentStateEndEvent, ...],
]:
    admitted_state_ids = {
        row["state_id"]
        for row in connection.execute(
            f"SELECT state_id FROM {CURRENT_STATE_ADMISSION_TABLE}"
        ).fetchall()
    }
    admitted_end_ids = {
        row["end_event_id"]
        for row in connection.execute(
            f"SELECT end_event_id FROM {CURRENT_END_ADMISSION_TABLE}"
        ).fetchall()
    }

    records: list[CurrentStateRecord] = []
    for row in connection.execute(
        f"SELECT * FROM {CURRENT_STATE_TABLE} ORDER BY state_id"
    ).fetchall():
        if row["state_id"] not in admitted_state_ids:
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
        if row["end_event_id"] not in admitted_end_ids:
            continue
        bindings = _read_bindings(
            connection,
            CURRENT_END_EVIDENCE_TABLE,
            "end_event_id",
            row["end_event_id"],
        )
        end_events.append(_end_from_row(row, bindings))

    return tuple(records), tuple(end_events)


def _dedupe_dependencies(
    dependencies: tuple[CurrentResolverDependency, ...],
) -> tuple[CurrentResolverDependency, ...]:
    seen: set[tuple[CurrentUseEffectKind, str]] = set()
    result: list[CurrentResolverDependency] = []
    for dependency in dependencies:
        key = (dependency.effect_kind, dependency.effect_id)
        if key in seen:
            continue
        seen.add(key)
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
        key = (
            block.source_ref,
            block.source_id,
            block.suppression_id,
            block.origin_effect_kind,
            block.origin_effect_id,
        )
        if key in seen:
            continue
        seen.add(key)
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
