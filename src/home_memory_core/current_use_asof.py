from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
import sqlite3

from home_memory_core.current_store import CurrentStore
from home_memory_core.current_store_schema import (
    CURRENT_END_EVIDENCE_TABLE,
    CURRENT_END_TABLE,
    CURRENT_STATE_EVIDENCE_TABLE,
    CURRENT_STATE_TABLE,
)
from home_memory_core.current_use import CurrentUseEffectKind
from home_memory_core.storage import assert_source_suppression_ledger
from home_memory_core.suppression import suppression_instant
from home_memory_core.suppression_asof import (
    SuppressionAsOfStatus,
    _source_decision_in_connection,
)


class HistoricalCurrentUseError(RuntimeError):
    """Base error for deterministic historical stop-use projection."""


class HistoricalCurrentUseIntegrityError(HistoricalCurrentUseError):
    """Persisted history cannot support a trustworthy historical projection."""


class HistoricalCurrentUseStatus(StrEnum):
    NOT_KNOWN_AS_OF = "not_known_as_of"
    NOT_SUPPRESSED_AS_OF = "not_suppressed_as_of"
    SUPPRESSED_AS_OF = "suppressed_as_of"
    TIMING_UNKNOWN = "timing_unknown"


class HistoricalSuppressionBlockStatus(StrEnum):
    SUPPRESSED_AS_OF = "suppressed_as_of"
    TIMING_UNKNOWN = "timing_unknown"


@dataclass(frozen=True)
class HistoricalSuppressionBlock:
    source_ref: str
    source_id: str
    suppression_id: str
    origin_effect_kind: CurrentUseEffectKind
    origin_effect_id: str
    status: HistoricalSuppressionBlockStatus
    effective_instant_us: int | None
    recorded_instant_us: int | None

    def __post_init__(self) -> None:
        for field_name in (
            "source_ref",
            "source_id",
            "suppression_id",
            "origin_effect_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise HistoricalCurrentUseIntegrityError(
                    f"{field_name} must be non-empty text"
                )
        if not isinstance(self.origin_effect_kind, CurrentUseEffectKind):
            raise HistoricalCurrentUseIntegrityError(
                "origin_effect_kind must use CurrentUseEffectKind"
            )
        if not isinstance(self.status, HistoricalSuppressionBlockStatus):
            raise HistoricalCurrentUseIntegrityError(
                "status must use HistoricalSuppressionBlockStatus"
            )
        if self.status is HistoricalSuppressionBlockStatus.TIMING_UNKNOWN:
            if (
                self.effective_instant_us is not None
                or self.recorded_instant_us is not None
            ):
                raise HistoricalCurrentUseIntegrityError(
                    "timing_unknown block cannot claim exact timing"
                )
        else:
            if (
                not isinstance(self.effective_instant_us, int)
                or not isinstance(self.recorded_instant_us, int)
            ):
                raise HistoricalCurrentUseIntegrityError(
                    "suppressed_as_of block requires exact timing"
                )
            if self.effective_instant_us > self.recorded_instant_us:
                raise HistoricalCurrentUseIntegrityError(
                    "suppression effective instant cannot follow record instant"
                )


@dataclass(frozen=True)
class HistoricalCurrentUseDecision:
    effect_kind: CurrentUseEffectKind
    effect_id: str
    as_of_instant_us: int
    status: HistoricalCurrentUseStatus
    blocks: tuple[HistoricalSuppressionBlock, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.effect_kind, CurrentUseEffectKind):
            raise HistoricalCurrentUseIntegrityError(
                "effect_kind must use CurrentUseEffectKind"
            )
        if not isinstance(self.effect_id, str) or not self.effect_id.strip():
            raise HistoricalCurrentUseIntegrityError(
                "effect_id must be non-empty text"
            )
        if not isinstance(self.as_of_instant_us, int):
            raise HistoricalCurrentUseIntegrityError(
                "as_of_instant_us must be integer"
            )
        if not isinstance(self.status, HistoricalCurrentUseStatus):
            raise HistoricalCurrentUseIntegrityError(
                "status must use HistoricalCurrentUseStatus"
            )

        definite = any(
            block.status is HistoricalSuppressionBlockStatus.SUPPRESSED_AS_OF
            for block in self.blocks
        )
        unknown = any(
            block.status is HistoricalSuppressionBlockStatus.TIMING_UNKNOWN
            for block in self.blocks
        )
        if self.status is HistoricalCurrentUseStatus.NOT_KNOWN_AS_OF:
            if self.blocks:
                raise HistoricalCurrentUseIntegrityError(
                    "not-known historical effect cannot carry suppression blocks"
                )
        elif self.status is HistoricalCurrentUseStatus.NOT_SUPPRESSED_AS_OF:
            if self.blocks:
                raise HistoricalCurrentUseIntegrityError(
                    "not-suppressed historical effect cannot carry blocks"
                )
        elif self.status is HistoricalCurrentUseStatus.SUPPRESSED_AS_OF:
            if not definite:
                raise HistoricalCurrentUseIntegrityError(
                    "suppressed historical decision requires a definite block"
                )
        elif self.status is HistoricalCurrentUseStatus.TIMING_UNKNOWN:
            if definite or not unknown:
                raise HistoricalCurrentUseIntegrityError(
                    "timing-unknown decision requires unknown blocks and no definite block"
                )


class HistoricalCurrentUseStore:
    """Read-only historical stop-use projection for persisted Current effects.

    This does not resolve Current standing, choose fallback state, or authorize
    present operational use. It answers only what suppression evidence had
    historical standing at one explicit as-of instant.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def state_decision(
        self,
        *,
        state_id: str,
        as_of: datetime,
    ) -> HistoricalCurrentUseDecision:
        as_of_us = suppression_instant(as_of)
        connection = self._read_connection()
        try:
            return _historical_effect_decision(
                connection=connection,
                effect_kind=CurrentUseEffectKind.STATE,
                effect_id=state_id,
                as_of_us=as_of_us,
            )
        finally:
            connection.close()

    def end_event_decision(
        self,
        *,
        end_event_id: str,
        as_of: datetime,
    ) -> HistoricalCurrentUseDecision:
        as_of_us = suppression_instant(as_of)
        connection = self._read_connection()
        try:
            return _historical_effect_decision(
                connection=connection,
                effect_kind=CurrentUseEffectKind.END_EVENT,
                effect_id=end_event_id,
                as_of_us=as_of_us,
            )
        finally:
            connection.close()

    def list_decisions(
        self,
        *,
        as_of: datetime,
    ) -> tuple[HistoricalCurrentUseDecision, ...]:
        as_of_us = suppression_instant(as_of)
        connection = self._read_connection()
        try:
            memo: dict[str, HistoricalCurrentUseDecision] = {}
            decisions: list[HistoricalCurrentUseDecision] = []
            for row in connection.execute(
                f"""
                SELECT state_id FROM {CURRENT_STATE_TABLE}
                WHERE recorded_instant_us<=?
                ORDER BY state_id
                """,
                (as_of_us,),
            ).fetchall():
                decisions.append(
                    _historical_effect_decision(
                        connection=connection,
                        effect_kind=CurrentUseEffectKind.STATE,
                        effect_id=row["state_id"],
                        as_of_us=as_of_us,
                        state_memo=memo,
                    )
                )
            for row in connection.execute(
                f"""
                SELECT end_event_id FROM {CURRENT_END_TABLE}
                WHERE recorded_instant_us<=?
                ORDER BY end_event_id
                """,
                (as_of_us,),
            ).fetchall():
                decisions.append(
                    _historical_effect_decision(
                        connection=connection,
                        effect_kind=CurrentUseEffectKind.END_EVENT,
                        effect_id=row["end_event_id"],
                        as_of_us=as_of_us,
                        state_memo=memo,
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


def _historical_effect_decision(
    *,
    connection: sqlite3.Connection,
    effect_kind: CurrentUseEffectKind,
    effect_id: str,
    as_of_us: int,
    state_memo: dict[str, HistoricalCurrentUseDecision] | None = None,
) -> HistoricalCurrentUseDecision:
    if not isinstance(effect_kind, CurrentUseEffectKind):
        raise TypeError("effect_kind must use CurrentUseEffectKind")
    if not isinstance(effect_id, str) or not effect_id.strip():
        raise ValueError("effect_id cannot be empty")
    if not isinstance(as_of_us, int):
        raise TypeError("as_of_us must be integer")

    memo = state_memo if state_memo is not None else {}
    if effect_kind is CurrentUseEffectKind.STATE:
        return _historical_state_decision(
            connection=connection,
            state_id=effect_id,
            as_of_us=as_of_us,
            memo=memo,
            visiting=set(),
        )
    return _historical_end_decision(
        connection=connection,
        end_event_id=effect_id,
        as_of_us=as_of_us,
        memo=memo,
    )


def _historical_state_decision(
    *,
    connection: sqlite3.Connection,
    state_id: str,
    as_of_us: int,
    memo: dict[str, HistoricalCurrentUseDecision],
    visiting: set[str],
) -> HistoricalCurrentUseDecision:
    cached = memo.get(state_id)
    if cached is not None:
        return cached
    if state_id in visiting:
        raise HistoricalCurrentUseIntegrityError(
            "historical Current suppression lineage contains a cycle"
        )

    row = connection.execute(
        f"""
        SELECT supersedes_state_id,recorded_instant_us
        FROM {CURRENT_STATE_TABLE}
        WHERE state_id=?
        """,
        (state_id,),
    ).fetchone()
    if row is None:
        raise KeyError(state_id)
    if row["recorded_instant_us"] > as_of_us:
        return _decision(
            effect_kind=CurrentUseEffectKind.STATE,
            effect_id=state_id,
            as_of_us=as_of_us,
            blocks=(),
            not_known=True,
        )

    visiting.add(state_id)
    try:
        blocks = list(
            _direct_historical_blocks(
                connection=connection,
                evidence_table=CURRENT_STATE_EVIDENCE_TABLE,
                id_column="state_id",
                effect_id=state_id,
                origin_effect_kind=CurrentUseEffectKind.STATE,
                as_of_us=as_of_us,
            )
        )
        parent_id = row["supersedes_state_id"]
        if parent_id is not None:
            parent = _historical_state_decision(
                connection=connection,
                state_id=parent_id,
                as_of_us=as_of_us,
                memo=memo,
                visiting=visiting,
            )
            if parent.status is HistoricalCurrentUseStatus.NOT_KNOWN_AS_OF:
                raise HistoricalCurrentUseIntegrityError(
                    "known Current state has predecessor unknown at the same as-of"
                )
            blocks.extend(parent.blocks)
        decision = _decision(
            effect_kind=CurrentUseEffectKind.STATE,
            effect_id=state_id,
            as_of_us=as_of_us,
            blocks=_dedupe_blocks(tuple(blocks)),
        )
        memo[state_id] = decision
        return decision
    finally:
        visiting.remove(state_id)


def _historical_end_decision(
    *,
    connection: sqlite3.Connection,
    end_event_id: str,
    as_of_us: int,
    memo: dict[str, HistoricalCurrentUseDecision],
) -> HistoricalCurrentUseDecision:
    row = connection.execute(
        f"""
        SELECT state_id,recorded_instant_us
        FROM {CURRENT_END_TABLE}
        WHERE end_event_id=?
        """,
        (end_event_id,),
    ).fetchone()
    if row is None:
        raise KeyError(end_event_id)
    if row["recorded_instant_us"] > as_of_us:
        return _decision(
            effect_kind=CurrentUseEffectKind.END_EVENT,
            effect_id=end_event_id,
            as_of_us=as_of_us,
            blocks=(),
            not_known=True,
        )

    blocks = list(
        _direct_historical_blocks(
            connection=connection,
            evidence_table=CURRENT_END_EVIDENCE_TABLE,
            id_column="end_event_id",
            effect_id=end_event_id,
            origin_effect_kind=CurrentUseEffectKind.END_EVENT,
            as_of_us=as_of_us,
        )
    )
    target = _historical_state_decision(
        connection=connection,
        state_id=row["state_id"],
        as_of_us=as_of_us,
        memo=memo,
        visiting=set(),
    )
    if target.status is HistoricalCurrentUseStatus.NOT_KNOWN_AS_OF:
        raise HistoricalCurrentUseIntegrityError(
            "known Current end event has target unknown at the same as-of"
        )
    blocks.extend(target.blocks)
    return _decision(
        effect_kind=CurrentUseEffectKind.END_EVENT,
        effect_id=end_event_id,
        as_of_us=as_of_us,
        blocks=_dedupe_blocks(tuple(blocks)),
    )


def _direct_historical_blocks(
    *,
    connection: sqlite3.Connection,
    evidence_table: str,
    id_column: str,
    effect_id: str,
    origin_effect_kind: CurrentUseEffectKind,
    as_of_us: int,
) -> tuple[HistoricalSuppressionBlock, ...]:
    rows = connection.execute(
        f"""
        SELECT source_ref,source_id
        FROM {evidence_table}
        WHERE {id_column}=?
        ORDER BY position
        """,
        (effect_id,),
    ).fetchall()
    if not rows:
        raise HistoricalCurrentUseIntegrityError(
            "Current effect has no exact evidence bindings"
        )

    blocks: list[HistoricalSuppressionBlock] = []
    for row in rows:
        source_decision = _source_decision_in_connection(
            connection=connection,
            source_id=row["source_id"],
            as_of_us=as_of_us,
        )
        if (
            source_decision.status
            is SuppressionAsOfStatus.NOT_SUPPRESSED_AS_OF
        ):
            continue

        if source_decision.status is SuppressionAsOfStatus.TIMING_UNKNOWN:
            assert source_decision.suppression_id is not None
            blocks.append(
                HistoricalSuppressionBlock(
                    source_ref=row["source_ref"],
                    source_id=row["source_id"],
                    suppression_id=source_decision.suppression_id,
                    origin_effect_kind=origin_effect_kind,
                    origin_effect_id=effect_id,
                    status=HistoricalSuppressionBlockStatus.TIMING_UNKNOWN,
                    effective_instant_us=None,
                    recorded_instant_us=None,
                )
            )
            continue

        assert (
            source_decision.status
            is SuppressionAsOfStatus.SUPPRESSED_AS_OF
        )
        assert source_decision.suppression_id is not None
        assert source_decision.effective_instant_us is not None
        assert source_decision.recorded_instant_us is not None
        blocks.append(
            HistoricalSuppressionBlock(
                source_ref=row["source_ref"],
                source_id=row["source_id"],
                suppression_id=source_decision.suppression_id,
                origin_effect_kind=origin_effect_kind,
                origin_effect_id=effect_id,
                status=HistoricalSuppressionBlockStatus.SUPPRESSED_AS_OF,
                effective_instant_us=source_decision.effective_instant_us,
                recorded_instant_us=source_decision.recorded_instant_us,
            )
        )

    return tuple(blocks)


def _dedupe_blocks(
    blocks: tuple[HistoricalSuppressionBlock, ...],
) -> tuple[HistoricalSuppressionBlock, ...]:
    seen: set[
        tuple[
            str,
            str,
            str,
            CurrentUseEffectKind,
            str,
            HistoricalSuppressionBlockStatus,
            int | None,
            int | None,
        ]
    ] = set()
    result: list[HistoricalSuppressionBlock] = []
    for block in blocks:
        key = (
            block.source_ref,
            block.source_id,
            block.suppression_id,
            block.origin_effect_kind,
            block.origin_effect_id,
            block.status,
            block.effective_instant_us,
            block.recorded_instant_us,
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
    as_of_us: int,
    blocks: tuple[HistoricalSuppressionBlock, ...],
    not_known: bool = False,
) -> HistoricalCurrentUseDecision:
    if not_known:
        status = HistoricalCurrentUseStatus.NOT_KNOWN_AS_OF
    elif any(
        block.status is HistoricalSuppressionBlockStatus.SUPPRESSED_AS_OF
        for block in blocks
    ):
        status = HistoricalCurrentUseStatus.SUPPRESSED_AS_OF
    elif any(
        block.status is HistoricalSuppressionBlockStatus.TIMING_UNKNOWN
        for block in blocks
    ):
        status = HistoricalCurrentUseStatus.TIMING_UNKNOWN
    else:
        status = HistoricalCurrentUseStatus.NOT_SUPPRESSED_AS_OF

    return HistoricalCurrentUseDecision(
        effect_kind=effect_kind,
        effect_id=effect_id,
        as_of_instant_us=as_of_us,
        status=status,
        blocks=blocks,
    )
