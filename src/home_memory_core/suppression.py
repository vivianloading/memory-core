from dataclasses import dataclass

from home_memory_core.evidence import EvidenceRef
from home_memory_core.interpretation import InterpretationRecord
from home_memory_core.revision import SupersessionRecord
from home_memory_core.source import SourceRecord


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


def create_suppression_record(
    *,
    suppression_id: str,
    source_id: str,
    requested_by: str,
    reason: str,
) -> SuppressionRecord:
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