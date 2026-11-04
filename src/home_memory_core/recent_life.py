from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
import sqlite3

from home_memory_core.current_admission import (
    CURRENT_STATE_ADMISSION_TABLE,
    CurrentAdmissionEffectKind,
    CurrentAdmissionReceipt,
)
from home_memory_core.current_resolver import (
    CurrentResolver,
)
from home_memory_core.current_store import (
    _read_bindings,
    _state_from_row,
)
from home_memory_core.current_store_schema import (
    CURRENT_STATE_EVIDENCE_TABLE,
    CURRENT_STATE_TABLE,
)
from home_memory_core.current_use import (
    CurrentPresentUseStatus,
    CurrentUseEffectKind,
    _current_effect_use_decision,
)
from home_memory_core.current_view import CurrentNamespace
from home_memory_core.evidence import EvidenceRef
from home_memory_core.living_continuity import (
    LivingContinuityError,
    resolve_room_attachment,
)
from home_memory_core.living_store import (
    LivingStore,
    LivingStoreIntegrityError,
)


RECENT_LIFE_POLICY_VERSION = "recent-life-current-history-v0.1"
RECENT_LIFE_WINDOW_LIMIT = 4
RECENT_LIFE_HORIZON = timedelta(days=7)

_RECENT_LIFE_POLICY_MARKER = object()
_RECENT_LIFE_EVENT_MARKER = object()
_RECENT_LIFE_SELECTION_MARKER = object()


class RecentLifeError(RuntimeError):
    """Recent Life projection cannot be established safely."""


@dataclass(frozen=True)
class RecentLifePolicy:
    """Fixed selector policy over already-admitted Room Current history."""

    policy_version: str
    horizon: timedelta
    limit: int
    producer_kind: str
    _marker: object

    def __post_init__(self) -> None:
        if self._marker is not _RECENT_LIFE_POLICY_MARKER:
            raise RecentLifeError(
                "Recent Life policy must be HOME-owned"
            )
        if self.policy_version != RECENT_LIFE_POLICY_VERSION:
            raise RecentLifeError(
                "Recent Life policy version is invalid"
            )
        if self.horizon != RECENT_LIFE_HORIZON:
            raise RecentLifeError(
                "Recent Life horizon is not canonical"
            )
        if self.limit != RECENT_LIFE_WINDOW_LIMIT:
            raise RecentLifeError(
                "Recent Life limit is not canonical"
            )
        if (
            self.producer_kind
            != "live_admitted_room_current_history"
        ):
            raise RecentLifeError(
                "Recent Life producer kind is invalid"
            )


RECENT_LIFE_POLICY_V0_1 = RecentLifePolicy(
    policy_version=RECENT_LIFE_POLICY_VERSION,
    horizon=RECENT_LIFE_HORIZON,
    limit=RECENT_LIFE_WINDOW_LIMIT,
    producer_kind="live_admitted_room_current_history",
    _marker=_RECENT_LIFE_POLICY_MARKER,
)


@dataclass(frozen=True)
class RecentLifeEvent:
    """One recent, live-admitted Room Current change projected for Wake.

    This object is derived from already-admitted Current history. It is not a
    second write path and cannot mint a new event time, summary, Room route,
    Perspective, or evidence binding.
    """

    event_id: str
    state_id: str
    admission_id: str
    projection_kind: str
    supersedes_state_id: str | None
    room_id: str
    episode_id: str
    perspective_instance_id: str
    room_attachment_event_id: str
    key: str
    state_kind: str
    summary: str
    occurred_at: datetime
    recorded_at: datetime
    evidence: tuple[EvidenceRef, ...]
    _marker: object

    def __post_init__(self) -> None:
        if self._marker is not _RECENT_LIFE_EVENT_MARKER:
            raise RecentLifeError(
                "Recent Life event must come from the canonical projector"
            )
        for name in (
            "event_id",
            "state_id",
            "admission_id",
            "projection_kind",
            "room_id",
            "episode_id",
            "perspective_instance_id",
            "room_attachment_event_id",
            "key",
            "state_kind",
            "summary",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise RecentLifeError(
                    f"{name} must be non-empty exact str"
                )
        if self.projection_kind != "room_current_state_assertion":
            raise RecentLifeError(
                "Recent Life projection kind is invalid"
            )
        if self.supersedes_state_id is not None:
            if (
                type(self.supersedes_state_id) is not str
                or not self.supersedes_state_id.strip()
                or self.supersedes_state_id == self.state_id
            ):
                raise RecentLifeError(
                    "Recent Life supersession witness is invalid"
                )
        _aware("occurred_at", self.occurred_at)
        _aware("recorded_at", self.recorded_at)
        if _instant(self.occurred_at) > _instant(self.recorded_at):
            raise RecentLifeError(
                "Recent Life event cannot be recorded before it occurred"
            )
        if (
            not isinstance(self.evidence, tuple)
            or not self.evidence
            or any(
                not isinstance(item, EvidenceRef)
                for item in self.evidence
            )
        ):
            raise RecentLifeError(
                "Recent Life requires exact EvidenceRef provenance"
            )

    @property
    def source_refs(self) -> tuple[str, ...]:
        result: list[str] = []
        for item in self.evidence:
            if item.source_id not in result:
                result.append(item.source_id)
        return tuple(result)


class RecentLifeSelectionStatus(StrEnum):
    READY = "ready"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class RecentLifeSelection:
    policy_version: str
    status: RecentLifeSelectionStatus
    events: tuple[RecentLifeEvent, ...]
    reason_codes: tuple[str, ...]
    _marker: object

    def __post_init__(self) -> None:
        if self._marker is not _RECENT_LIFE_SELECTION_MARKER:
            raise RecentLifeError(
                "Recent Life selection must come from the canonical projector"
            )
        if self.policy_version != RECENT_LIFE_POLICY_VERSION:
            raise RecentLifeError(
                "Recent Life selection policy version is invalid"
            )
        if not isinstance(
            self.status,
            RecentLifeSelectionStatus,
        ):
            raise RecentLifeError(
                "Recent Life selection status is invalid"
            )
        if (
            not isinstance(self.events, tuple)
            or any(
                not isinstance(item, RecentLifeEvent)
                for item in self.events
            )
            or len(self.events) > RECENT_LIFE_WINDOW_LIMIT
        ):
            raise RecentLifeError(
                "Recent Life selection events are invalid"
            )
        if (
            not isinstance(self.reason_codes, tuple)
            or any(
                type(item) is not str
                or not item.strip()
                for item in self.reason_codes
            )
            or len(set(self.reason_codes))
            != len(self.reason_codes)
        ):
            raise RecentLifeError(
                "Recent Life selection reason codes are invalid"
            )
        if self.status is RecentLifeSelectionStatus.READY:
            if self.events and self.reason_codes:
                raise RecentLifeError(
                    "ready Recent Life with events cannot carry warning reasons"
                )
            if (
                not self.events
                and self.reason_codes
                != ("NO_ELIGIBLE_RECENT_LIFE_IN_WINDOW",)
            ):
                raise RecentLifeError(
                    "ready empty Recent Life requires the exact empty-window reason"
                )
        elif self.status is RecentLifeSelectionStatus.PARTIAL:
            if (
                not self.events
                or self.reason_codes
                != ("RECENT_LIFE_LIVE_ADMISSION_PROOF_PARTIAL",)
            ):
                raise RecentLifeError(
                    "partial Recent Life requires carried events and proof warning"
                )
        elif (
            self.events
            or self.reason_codes
            != ("RECENT_LIFE_LIVE_ADMISSION_PROOF_UNAVAILABLE",)
        ):
            raise RecentLifeError(
                "unavailable Recent Life requires no events and proof-unavailable reason"
            )


def select_recent_life_from_current_in_connection(
    *,
    resolver: CurrentResolver,
    living_store: LivingStore,
    connection: sqlite3.Connection,
    room_id: str,
    as_of: datetime,
    policy: RecentLifePolicy,
) -> RecentLifeSelection:
    """Project recent Room Current changes from one already-pinned HOME cut.

    Durable admission history is inspected only to distinguish a genuinely
    empty recent window from candidate history whose live admission proof is
    unavailable. Missing live proof never authorizes payload carriage.
    """

    if policy is not RECENT_LIFE_POLICY_V0_1:
        raise RecentLifeError(
            "Recent Life v0.1 accepts only the canonical policy"
        )
    if not isinstance(resolver, CurrentResolver):
        raise TypeError("resolver must be CurrentResolver")
    if not isinstance(living_store, LivingStore):
        raise TypeError("living_store must be LivingStore")
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be sqlite3.Connection")
    if not connection.in_transaction:
        raise RecentLifeError(
            "Recent Life requires the active Wake SQLite snapshot"
        )
    if type(room_id) is not str or not room_id.strip():
        raise RecentLifeError(
            "room_id must be non-empty exact str"
        )
    _aware("as_of", as_of)

    resolver._assert_live_binding()
    receipts = (
        resolver._admission_authority
        ._snapshot_live_receipts_for_resolution(
            connection=connection,
        )
    )
    receipt_by_state_id = {
        item.effect_id: item
        for item in receipts
        if item.effect_kind
        is CurrentAdmissionEffectKind.STATE
    }

    cut = _instant(as_of)
    earliest = cut - _duration_micros(
        policy.horizon
    )

    candidates: list[tuple[object, str]] = []
    rows = connection.execute(
        f"""
        SELECT state.*
        FROM {CURRENT_STATE_TABLE} AS state
        JOIN {CURRENT_STATE_ADMISSION_TABLE} AS admission
          ON admission.state_id = state.state_id
        WHERE state.namespace = ?
          AND state.owner_id = ?
          AND state.recorded_instant_us <= ?
        ORDER BY state.state_id
        """,
        (
            CurrentNamespace.ROOM.value,
            room_id,
            cut,
        ),
    ).fetchall()
    for row in rows:
        bindings = _read_bindings(
            connection,
            CURRENT_STATE_EVIDENCE_TABLE,
            "state_id",
            row["state_id"],
        )
        record = _state_from_row(
            row,
            bindings,
        )
        if (
            record.episode_id is None
            or record.perspective_instance_id is None
            or not (
                earliest
                <= _instant(record.event_time)
                <= cut
            )
            or _instant(record.recorded_at) > cut
        ):
            continue

        use = _current_effect_use_decision(
            connection=connection,
            effect_kind=CurrentUseEffectKind.STATE,
            effect_id=record.state_id,
        )
        if use.status is not CurrentPresentUseStatus.USABLE:
            continue

        attachment_id = row[
            "room_attachment_event_id"
        ]
        if (
            type(attachment_id) is not str
            or not attachment_id.strip()
        ):
            raise RecentLifeError(
                "Recent Life Room state lacks attachment provenance"
            )
        if not _attachment_still_resolves_to_same_room(
            living_store=living_store,
            connection=connection,
            episode_id=record.episode_id,
            room_id=room_id,
            attachment_event_id=attachment_id,
        ):
            continue
        candidates.append(
            (record, attachment_id)
        )

    candidates.sort(
        key=lambda pair: (
            _instant(pair[0].event_time),
            _instant(pair[0].recorded_at),
            pair[0].state_id,
        ),
        reverse=True,
    )

    result: list[RecentLifeEvent] = []
    missing_live_proof = False
    for record, attachment_id in candidates:
        receipt = receipt_by_state_id.get(
            record.state_id
        )
        if receipt is None:
            missing_live_proof = True
            continue
        if not _receipt_matches_record(
            receipt=receipt,
            record=record,
            room_id=room_id,
        ):
            raise RecentLifeError(
                "live Current admission receipt disagrees with Recent Life record"
            )
        if (
            receipt.room_attachment_event_id
            != attachment_id
        ):
            raise RecentLifeError(
                "Current admission receipt disagrees with stored Room attachment provenance"
            )

        bindings = _read_bindings(
            connection,
            CURRENT_STATE_EVIDENCE_TABLE,
            "state_id",
            record.state_id,
        )
        if not bindings:
            raise RecentLifeError(
                "Recent Life state lacks exact evidence bindings"
            )
        evidence = tuple(
            item.evidence
            for item in bindings
        )
        result.append(
            RecentLifeEvent(
                event_id=(
                    f"recent-current-state:{record.state_id}"
                ),
                state_id=record.state_id,
                admission_id=receipt.admission_id,
                projection_kind=(
                    "room_current_state_assertion"
                ),
                supersedes_state_id=(
                    record.supersedes_state_id
                ),
                room_id=room_id,
                episode_id=record.episode_id,
                perspective_instance_id=(
                    record.perspective_instance_id
                ),
                room_attachment_event_id=(
                    attachment_id
                ),
                key=record.key,
                state_kind=record.state_kind.value,
                summary=record.value,
                occurred_at=record.event_time,
                recorded_at=record.recorded_at,
                evidence=evidence,
                _marker=_RECENT_LIFE_EVENT_MARKER,
            )
        )
        if len(result) >= policy.limit:
            break

    events = tuple(result)
    if missing_live_proof:
        if events:
            status = RecentLifeSelectionStatus.PARTIAL
            reasons = (
                "RECENT_LIFE_LIVE_ADMISSION_PROOF_PARTIAL",
            )
        else:
            status = RecentLifeSelectionStatus.UNAVAILABLE
            reasons = (
                "RECENT_LIFE_LIVE_ADMISSION_PROOF_UNAVAILABLE",
            )
    else:
        status = RecentLifeSelectionStatus.READY
        reasons = (
            ()
            if events
            else (
                "NO_ELIGIBLE_RECENT_LIFE_IN_WINDOW",
            )
        )

    return RecentLifeSelection(
        policy_version=RECENT_LIFE_POLICY_VERSION,
        status=status,
        events=events,
        reason_codes=reasons,
        _marker=_RECENT_LIFE_SELECTION_MARKER,
    )


def _receipt_matches_record(
    *,
    receipt: CurrentAdmissionReceipt,
    record,
    room_id: str,
) -> bool:
    return (
        receipt.effect_kind
        is CurrentAdmissionEffectKind.STATE
        and receipt.effect_id == record.state_id
        and receipt.room_id == room_id
        and receipt.episode_id == record.episode_id
        and receipt.perspective_instance_id
        == record.perspective_instance_id
    )


def _attachment_still_resolves_to_same_room(
    *,
    living_store: LivingStore,
    connection: sqlite3.Connection,
    episode_id: str,
    room_id: str,
    attachment_event_id: str,
) -> bool:
    events = LivingStore._read_room_attachment_events(
        living_store,
        connection,
        episode_id=episode_id,
    )
    try:
        resolution = resolve_room_attachment(
            episode_id=episode_id,
            events=events,
        )
    except LivingContinuityError as exc:
        raise LivingStoreIntegrityError(
            str(exc)
        ) from exc
    return (
        resolution.decision == "attached"
        and resolution.room_id == room_id
        and resolution.active_attachment_event_id
        == attachment_event_id
    )


def _aware(
    name: str,
    value: datetime,
) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise RecentLifeError(
            f"{name} must be timezone-aware datetime"
        )


def _instant(value: datetime) -> int:
    _aware("datetime", value)
    offset = value.utcoffset()
    assert offset is not None
    wall_micros = (
        (
            (
                (value.toordinal() * 24 + value.hour)
                * 60
                + value.minute
            )
            * 60
            + value.second
        )
        * 1_000_000
        + value.microsecond
    )
    offset_micros = (
        (offset.days * 86_400 + offset.seconds)
        * 1_000_000
        + offset.microseconds
    )
    return wall_micros - offset_micros


def _duration_micros(value: timedelta) -> int:
    return (
        (value.days * 86_400 + value.seconds)
        * 1_000_000
        + value.microseconds
    )
