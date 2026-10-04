from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import sqlite3

from home_memory_core.current_store import (
    CurrentStore,
    CurrentStoreIntegrityError,
)
from home_memory_core.current_store_schema import (
    CURRENT_END_EVIDENCE_TABLE,
    CURRENT_END_TABLE,
    CURRENT_STATE_EVIDENCE_TABLE,
    CURRENT_STATE_TABLE,
)
from home_memory_core.storage import assert_source_suppression_ledger
from home_memory_core.suppression import SuppressedMemoryError


class CurrentPresentUseError(RuntimeError):
    """Base error for the synthetic Current present-use projection."""


class CurrentPresentUseIntegrityError(CurrentPresentUseError):
    """Current present-use provenance is incomplete or structurally unsafe."""


class CurrentEffectSuppressedError(SuppressedMemoryError):
    """A historical Current effect exists but is no longer permitted for use."""

    def __init__(self, decision: "CurrentPresentUseDecision") -> None:
        self.decision = decision
        blocked = ",".join(block.source_id for block in decision.blocks)
        super().__init__(
            f"Current {decision.effect_kind.value} {decision.effect_id} "
            f"is suppressed by source stop-use: {blocked}"
        )


class CurrentUseEffectKind(StrEnum):
    STATE = "state"
    END_EVENT = "end_event"


class CurrentPresentUseStatus(StrEnum):
    USABLE = "usable"
    SUPPRESSED = "suppressed"


@dataclass(frozen=True)
class CurrentSuppressionBlock:
    source_ref: str
    source_id: str
    suppression_id: str
    origin_effect_kind: CurrentUseEffectKind
    origin_effect_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.origin_effect_kind, CurrentUseEffectKind):
            raise CurrentPresentUseIntegrityError(
                "origin_effect_kind must use CurrentUseEffectKind"
            )
        for field_name, value in {
            "source_ref": self.source_ref,
            "source_id": self.source_id,
            "suppression_id": self.suppression_id,
            "origin_effect_id": self.origin_effect_id,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise CurrentPresentUseIntegrityError(
                    f"{field_name} must be non-empty text"
                )


@dataclass(frozen=True)
class CurrentPresentUseDecision:
    effect_kind: CurrentUseEffectKind
    effect_id: str
    status: CurrentPresentUseStatus
    blocks: tuple[CurrentSuppressionBlock, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.effect_kind, CurrentUseEffectKind):
            raise CurrentPresentUseIntegrityError(
                "effect_kind must use CurrentUseEffectKind"
            )
        if not isinstance(self.effect_id, str) or not self.effect_id.strip():
            raise CurrentPresentUseIntegrityError(
                "effect_id must be non-empty text"
            )
        if not isinstance(self.status, CurrentPresentUseStatus):
            raise CurrentPresentUseIntegrityError(
                "status must use CurrentPresentUseStatus"
            )
        if self.status is CurrentPresentUseStatus.USABLE and self.blocks:
            raise CurrentPresentUseIntegrityError(
                "usable Current effect cannot carry suppression blocks"
            )
        if self.status is CurrentPresentUseStatus.SUPPRESSED and not self.blocks:
            raise CurrentPresentUseIntegrityError(
                "suppressed Current effect requires exact suppression blocks"
            )


class CurrentPresentUseStore:
    """Read-only present-use eligibility above immutable Current history.

    This is not a Current resolver and does not choose a fallback historical
    state. It only says whether one persisted effect may participate in present
    use under the source-suppression snapshot being read.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def state_decision(self, state_id: str) -> CurrentPresentUseDecision:
        connection = self._read_connection()
        try:
            return _current_effect_use_decision(
                connection=connection,
                effect_kind=CurrentUseEffectKind.STATE,
                effect_id=state_id,
            )
        finally:
            connection.close()

    def end_event_decision(self, end_event_id: str) -> CurrentPresentUseDecision:
        connection = self._read_connection()
        try:
            return _current_effect_use_decision(
                connection=connection,
                effect_kind=CurrentUseEffectKind.END_EVENT,
                effect_id=end_event_id,
            )
        finally:
            connection.close()

    def list_decisions(self) -> tuple[CurrentPresentUseDecision, ...]:
        connection = self._read_connection()
        try:
            decisions: list[CurrentPresentUseDecision] = []
            for row in connection.execute(
                f"SELECT state_id FROM {CURRENT_STATE_TABLE} ORDER BY state_id"
            ).fetchall():
                decisions.append(
                    _current_effect_use_decision(
                        connection=connection,
                        effect_kind=CurrentUseEffectKind.STATE,
                        effect_id=row["state_id"],
                    )
                )
            for row in connection.execute(
                f"SELECT end_event_id FROM {CURRENT_END_TABLE} ORDER BY end_event_id"
            ).fetchall():
                decisions.append(
                    _current_effect_use_decision(
                        connection=connection,
                        effect_kind=CurrentUseEffectKind.END_EVENT,
                        effect_id=row["end_event_id"],
                    )
                )
            return tuple(decisions)
        finally:
            connection.close()

    def _read_connection(self) -> sqlite3.Connection:
        try:
            connection = CurrentStore(self.db_path)._read_connection()
            assert_source_suppression_ledger(connection)
            return connection
        except Exception:
            if "connection" in locals():
                connection.close()
            raise


def require_current_effect_usable(
    *,
    connection: sqlite3.Connection,
    effect_kind: CurrentUseEffectKind,
    effect_id: str,
) -> CurrentPresentUseDecision:
    """Require present usability inside an already-established DB snapshot."""

    assert_source_suppression_ledger(connection)
    decision = _current_effect_use_decision(
        connection=connection,
        effect_kind=effect_kind,
        effect_id=effect_id,
    )
    if decision.status is CurrentPresentUseStatus.SUPPRESSED:
        raise CurrentEffectSuppressedError(decision)
    return decision


def _current_effect_use_decision(
    *,
    connection: sqlite3.Connection,
    effect_kind: CurrentUseEffectKind,
    effect_id: str,
    state_memo: dict[str, CurrentPresentUseDecision] | None = None,
) -> CurrentPresentUseDecision:
    """Derive one exact effect eligibility decision without mutating history.

    Suppression propagates forward through semantic dependency:
    state -> superseding state descendants, and state -> targeting end events.
    """

    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be sqlite3.Connection")
    if not isinstance(effect_kind, CurrentUseEffectKind):
        raise TypeError("effect_kind must use CurrentUseEffectKind")
    if not isinstance(effect_id, str) or not effect_id.strip():
        raise ValueError("effect_id cannot be empty")

    memo = state_memo if state_memo is not None else {}
    if effect_kind is CurrentUseEffectKind.STATE:
        return _state_use_decision(
            connection=connection,
            state_id=effect_id,
            memo=memo,
            visiting=set(),
        )
    return _end_event_use_decision(
        connection=connection,
        end_event_id=effect_id,
        memo=memo,
    )


def _state_use_decision(
    *,
    connection: sqlite3.Connection,
    state_id: str,
    memo: dict[str, CurrentPresentUseDecision],
    visiting: set[str],
) -> CurrentPresentUseDecision:
    cached = memo.get(state_id)
    if cached is not None:
        return cached
    if state_id in visiting:
        raise CurrentPresentUseIntegrityError(
            "Current suppression lineage contains a cycle"
        )

    row = connection.execute(
        f"SELECT supersedes_state_id FROM {CURRENT_STATE_TABLE} WHERE state_id=?",
        (state_id,),
    ).fetchone()
    if row is None:
        raise KeyError(state_id)

    visiting.add(state_id)
    try:
        blocks = list(
            _direct_suppression_blocks(
                connection=connection,
                evidence_table=CURRENT_STATE_EVIDENCE_TABLE,
                id_column="state_id",
                effect_id=state_id,
                origin_effect_kind=CurrentUseEffectKind.STATE,
            )
        )
        parent_id = row["supersedes_state_id"]
        if parent_id is not None:
            parent = _state_use_decision(
                connection=connection,
                state_id=parent_id,
                memo=memo,
                visiting=visiting,
            )
            blocks.extend(parent.blocks)
        decision = _decision(
            effect_kind=CurrentUseEffectKind.STATE,
            effect_id=state_id,
            blocks=_dedupe_blocks(tuple(blocks)),
        )
        memo[state_id] = decision
        return decision
    finally:
        visiting.remove(state_id)


def _end_event_use_decision(
    *,
    connection: sqlite3.Connection,
    end_event_id: str,
    memo: dict[str, CurrentPresentUseDecision],
) -> CurrentPresentUseDecision:
    row = connection.execute(
        f"SELECT state_id FROM {CURRENT_END_TABLE} WHERE end_event_id=?",
        (end_event_id,),
    ).fetchone()
    if row is None:
        raise KeyError(end_event_id)

    blocks = list(
        _direct_suppression_blocks(
            connection=connection,
            evidence_table=CURRENT_END_EVIDENCE_TABLE,
            id_column="end_event_id",
            effect_id=end_event_id,
            origin_effect_kind=CurrentUseEffectKind.END_EVENT,
        )
    )
    target = _state_use_decision(
        connection=connection,
        state_id=row["state_id"],
        memo=memo,
        visiting=set(),
    )
    blocks.extend(target.blocks)
    return _decision(
        effect_kind=CurrentUseEffectKind.END_EVENT,
        effect_id=end_event_id,
        blocks=_dedupe_blocks(tuple(blocks)),
    )


def _direct_suppression_blocks(
    *,
    connection: sqlite3.Connection,
    evidence_table: str,
    id_column: str,
    effect_id: str,
    origin_effect_kind: CurrentUseEffectKind,
) -> tuple[CurrentSuppressionBlock, ...]:
    rows = connection.execute(
        f"""
        SELECT
            evidence.source_ref,
            evidence.source_id,
            suppressions.suppression_id
        FROM {evidence_table} AS evidence
        LEFT JOIN source_suppressions AS suppressions
          ON suppressions.source_id=evidence.source_id
        WHERE evidence.{id_column}=?
        ORDER BY evidence.position
        """,
        (effect_id,),
    ).fetchall()
    if not rows:
        raise CurrentPresentUseIntegrityError(
            "Current effect has no exact evidence bindings"
        )
    return tuple(
        CurrentSuppressionBlock(
            source_ref=row["source_ref"],
            source_id=row["source_id"],
            suppression_id=row["suppression_id"],
            origin_effect_kind=origin_effect_kind,
            origin_effect_id=effect_id,
        )
        for row in rows
        if row["suppression_id"] is not None
    )


def _dedupe_blocks(
    blocks: tuple[CurrentSuppressionBlock, ...],
) -> tuple[CurrentSuppressionBlock, ...]:
    seen: set[tuple[str, str, str, CurrentUseEffectKind, str]] = set()
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


def _decision(
    *,
    effect_kind: CurrentUseEffectKind,
    effect_id: str,
    blocks: tuple[CurrentSuppressionBlock, ...],
) -> CurrentPresentUseDecision:
    return CurrentPresentUseDecision(
        effect_kind=effect_kind,
        effect_id=effect_id,
        status=(
            CurrentPresentUseStatus.SUPPRESSED
            if blocks
            else CurrentPresentUseStatus.USABLE
        ),
        blocks=blocks,
    )
