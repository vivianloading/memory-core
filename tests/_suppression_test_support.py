from __future__ import annotations

from datetime import datetime, timezone

from home_memory_core.suppression import (
    SuppressionRecord,
    create_timed_suppression_record,
)


_TEST_SUPPRESSION_INSTANT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def create_test_suppression_record(
    *,
    suppression_id: str,
    source_id: str,
    requested_by: str,
    reason: str,
) -> SuppressionRecord:
    """Deterministic explicit-time fixture for ordinary synthetic stop-use tests."""

    return create_timed_suppression_record(
        suppression_id=suppression_id,
        source_id=source_id,
        requested_by=requested_by,
        reason=reason,
        effective_at=_TEST_SUPPRESSION_INSTANT,
        recorded_at=_TEST_SUPPRESSION_INSTANT,
    )
