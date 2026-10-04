from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
import sqlite3

from home_memory_core.storage import (
    SOURCE_SUPPRESSION_TIMING_TABLE,
    assert_source_suppression_ledger,
)
from home_memory_core.store_domain import assert_synthetic_store_domain
from home_memory_core.suppression import suppression_instant


class SuppressionAsOfError(RuntimeError):
    """Base error for deterministic historical suppression projection."""


class SuppressionAsOfStatus(StrEnum):
    NOT_SUPPRESSED_AS_OF = "not_suppressed_as_of"
    SUPPRESSED_AS_OF = "suppressed_as_of"
    TIMING_UNKNOWN = "timing_unknown"


@dataclass(frozen=True)
class SuppressionAsOfDecision:
    source_id: str
    as_of_instant_us: int
    status: SuppressionAsOfStatus
    suppression_id: str | None
    effective_instant_us: int | None
    recorded_instant_us: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise SuppressionAsOfError("source_id must be non-empty text")
        if not isinstance(self.as_of_instant_us, int):
            raise SuppressionAsOfError("as_of_instant_us must be integer")
        if not isinstance(self.status, SuppressionAsOfStatus):
            raise SuppressionAsOfError(
                "status must use SuppressionAsOfStatus"
            )

        if self.status is SuppressionAsOfStatus.NOT_SUPPRESSED_AS_OF:
            if any(
                value is not None
                for value in (
                    self.suppression_id,
                    self.effective_instant_us,
                    self.recorded_instant_us,
                )
            ):
                raise SuppressionAsOfError(
                    "not-suppressed decision cannot claim suppression provenance"
                )
        elif self.status is SuppressionAsOfStatus.TIMING_UNKNOWN:
            if (
                not isinstance(self.suppression_id, str)
                or not self.suppression_id.strip()
                or self.effective_instant_us is not None
                or self.recorded_instant_us is not None
            ):
                raise SuppressionAsOfError(
                    "timing-unknown decision requires suppression id and no guessed timing"
                )
        else:
            if (
                not isinstance(self.suppression_id, str)
                or not self.suppression_id.strip()
                or not isinstance(self.effective_instant_us, int)
                or not isinstance(self.recorded_instant_us, int)
            ):
                raise SuppressionAsOfError(
                    "suppressed decision requires exact suppression provenance"
                )
            if self.effective_instant_us > self.recorded_instant_us:
                raise SuppressionAsOfError(
                    "suppression effective instant cannot follow record instant"
                )


class SuppressionAsOfStore:
    """Read-only source-level historical stop-use projection."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def source_decision(
        self,
        *,
        source_id: str,
        as_of: datetime,
    ) -> SuppressionAsOfDecision:
        as_of_us = suppression_instant(as_of)
        connection = self._read_connection()
        try:
            return _source_decision_in_connection(
                connection=connection,
                source_id=source_id,
                as_of_us=as_of_us,
            )
        finally:
            connection.close()

    def _read_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            assert_synthetic_store_domain(connection)
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            assert_source_suppression_ledger(connection)
            return connection
        except Exception:
            connection.close()
            raise


def _source_decision_in_connection(
    *,
    connection: sqlite3.Connection,
    source_id: str,
    as_of_us: int,
) -> SuppressionAsOfDecision:
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id cannot be empty")
    if not isinstance(as_of_us, int):
        raise TypeError("as_of_us must be integer")

    source = connection.execute(
        "SELECT 1 FROM sources WHERE source_id=?",
        (source_id,),
    ).fetchone()
    if source is None:
        raise KeyError(source_id)

    row = connection.execute(
        f"""
        SELECT
            suppressions.suppression_id,
            timing.effective_instant_us,
            timing.recorded_instant_us
        FROM source_suppressions AS suppressions
        LEFT JOIN {SOURCE_SUPPRESSION_TIMING_TABLE} AS timing
          ON timing.suppression_id=suppressions.suppression_id
        WHERE suppressions.source_id=?
        """,
        (source_id,),
    ).fetchone()

    if row is None:
        return SuppressionAsOfDecision(
            source_id=source_id,
            as_of_instant_us=as_of_us,
            status=SuppressionAsOfStatus.NOT_SUPPRESSED_AS_OF,
            suppression_id=None,
            effective_instant_us=None,
            recorded_instant_us=None,
        )

    suppression_id = row["suppression_id"]
    effective_us = row["effective_instant_us"]
    recorded_us = row["recorded_instant_us"]
    if effective_us is None and recorded_us is None:
        return SuppressionAsOfDecision(
            source_id=source_id,
            as_of_instant_us=as_of_us,
            status=SuppressionAsOfStatus.TIMING_UNKNOWN,
            suppression_id=suppression_id,
            effective_instant_us=None,
            recorded_instant_us=None,
        )
    if not isinstance(effective_us, int) or not isinstance(recorded_us, int):
        raise SuppressionAsOfError(
            "suppression timing sidecar is partially missing"
        )

    if recorded_us <= as_of_us and effective_us <= as_of_us:
        return SuppressionAsOfDecision(
            source_id=source_id,
            as_of_instant_us=as_of_us,
            status=SuppressionAsOfStatus.SUPPRESSED_AS_OF,
            suppression_id=suppression_id,
            effective_instant_us=effective_us,
            recorded_instant_us=recorded_us,
        )

    return SuppressionAsOfDecision(
        source_id=source_id,
        as_of_instant_us=as_of_us,
        status=SuppressionAsOfStatus.NOT_SUPPRESSED_AS_OF,
        suppression_id=None,
        effective_instant_us=None,
        recorded_instant_us=None,
    )
