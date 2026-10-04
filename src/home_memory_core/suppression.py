from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

from home_memory_core.evidence import EvidenceRef
from home_memory_core.interpretation import InterpretationRecord
from home_memory_core.revision import SupersessionRecord
from home_memory_core.source import SourceRecord


_CANONICAL_DATETIME = re.compile(
    r"^(?P<wall>\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d{6})?)"
    r"(?P<sign>[+-])(?P<hours>\\d{2}):(?P<minutes>\\d{2})"
    r"(?::(?P<seconds>\\d{2})(?:\\.(?P<microseconds>\\d{6}))?)?$"
)


class SuppressedMemoryError(RuntimeError):
    pass


class SuppressionLedgerIntegrityError(RuntimeError):
    """Persisted stop-use state cannot be trusted for present-use decisions."""


@dataclass(frozen=True)
class SuppressionRecord:
    suppression_id: str
    source_id: str
    requested_by: str
    reason: str
    effective_at: datetime | None = None
    recorded_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "suppression_id",
            "source_id",
            "requested_by",
            "reason",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} cannot be empty")

        if (self.effective_at is None) != (self.recorded_at is None):
            raise ValueError(
                "effective_at and recorded_at must both be present or both absent"
            )
        if self.effective_at is not None:
            assert self.recorded_at is not None
            _require_aware("effective_at", self.effective_at)
            _require_aware("recorded_at", self.recorded_at)
            if _instant(self.effective_at) > _instant(self.recorded_at):
                raise ValueError("effective_at cannot be later than recorded_at")

    @property
    def timing_known(self) -> bool:
        return self.effective_at is not None and self.recorded_at is not None


def create_suppression_record(
    *,
    suppression_id: str,
    source_id: str,
    requested_by: str,
    reason: str,
) -> SuppressionRecord:
    """Create an explicit legacy/untimed suppression record.

    This compatibility constructor preserves Slice 3A semantics. It must not
    invent historical timing for evidence that never recorded timing.
    """
    values = {
        "suppression_id": suppression_id,
        "source_id": source_id,
        "requested_by": requested_by,
        "reason": reason,
    }

    for field_name, value in values.items():
        if not value.strip():
            raise ValueError(f"{field_name} cannot be empty")

    return SuppressionRecord(
        suppression_id=suppression_id,
        source_id=source_id,
        requested_by=requested_by,
        reason=reason,
    )


def create_timed_suppression_record(
    *,
    suppression_id: str,
    source_id: str,
    requested_by: str,
    reason: str,
    effective_at: datetime,
    recorded_at: datetime,
) -> SuppressionRecord:
    values = {
        "suppression_id": suppression_id,
        "source_id": source_id,
        "requested_by": requested_by,
        "reason": reason,
    }
    for field_name, value in values.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} cannot be empty")

    _require_aware("effective_at", effective_at)
    _require_aware("recorded_at", recorded_at)
    if _instant(effective_at) > _instant(recorded_at):
        raise ValueError("effective_at cannot be later than recorded_at")

    return SuppressionRecord(
        suppression_id=suppression_id,
        source_id=source_id,
        requested_by=requested_by,
        reason=reason,
        effective_at=effective_at,
        recorded_at=recorded_at,
    )


def suppression_instant(value: datetime) -> int:
    """Return an aware datetime as the same absolute microsecond scalar as Current."""

    return _instant(value)


def suppression_datetime_to_iso(value: datetime) -> str:
    _require_aware("timestamp", value)
    return value.isoformat()


def suppression_datetime_from_iso(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("suppression datetime payload must be text")
    match = _CANONICAL_DATETIME.fullmatch(value)
    if match is None:
        raise ValueError(
            "suppression datetime payload must use canonical datetime.isoformat encoding"
        )
    try:
        wall = datetime.fromisoformat(match.group("wall"))
        hours = int(match.group("hours"))
        minutes = int(match.group("minutes"))
        seconds = int(match.group("seconds") or "0")
        microseconds = int(match.group("microseconds") or "0")
        offset = timedelta(
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            microseconds=microseconds,
        )
        if match.group("sign") == "-":
            offset = -offset
        result = wall.replace(tzinfo=timezone(offset))
    except (ValueError, OverflowError) as error:
        raise ValueError(
            "suppression datetime payload is outside the supported aware datetime domain"
        ) from error
    if result.isoformat() != value:
        raise ValueError(
            "suppression datetime payload is not canonical for its represented instant"
        )
    return result


def _instant(value: datetime) -> int:
    _require_aware("timestamp", value)
    offset = value.utcoffset()
    assert offset is not None
    wall = (
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
    return wall - _duration_micros(offset)


def _duration_micros(value: timedelta) -> int:
    return (
        (value.days * 86_400 + value.seconds) * 1_000_000
        + value.microseconds
    )


def _require_aware(field_name: str, value: datetime) -> None:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def suppressed_source_ids(
    *,
    suppressions: tuple[SuppressionRecord, ...],
) -> frozenset[str]:
    return frozenset(
        suppression.source_id
        for suppression in suppressions
    )


def is_source_usable(
    *,
    source: SourceRecord,
    suppressions: tuple[SuppressionRecord, ...],
) -> bool:
    return source.source_id not in suppressed_source_ids(
        suppressions=suppressions
    )


def is_evidence_usable(
    *,
    evidence: EvidenceRef,
    suppressions: tuple[SuppressionRecord, ...],
) -> bool:
    return evidence.source_id not in suppressed_source_ids(
        suppressions=suppressions
    )


def is_interpretation_usable(
    *,
    interpretation: InterpretationRecord,
    suppressions: tuple[SuppressionRecord, ...],
) -> bool:
    if not interpretation.evidence:
        return False

    return all(
        is_evidence_usable(
            evidence=evidence,
            suppressions=suppressions,
        )
        for evidence in interpretation.evidence
    )


def is_supersession_usable(
    *,
    supersession: SupersessionRecord,
    previous: InterpretationRecord,
    new: InterpretationRecord,
    suppressions: tuple[SuppressionRecord, ...],
) -> bool:
    if (
        supersession.previous_interpretation_id
        != previous.interpretation_id
    ):
        return False

    if (
        supersession.new_interpretation_id
        != new.interpretation_id
    ):
        return False

    if not supersession.reason_evidence:
        return False

    return (
        is_interpretation_usable(
            interpretation=previous,
            suppressions=suppressions,
        )
        and is_interpretation_usable(
            interpretation=new,
            suppressions=suppressions,
        )
        and all(
            is_evidence_usable(
                evidence=evidence,
                suppressions=suppressions,
            )
            for evidence in supersession.reason_evidence
        )
    )