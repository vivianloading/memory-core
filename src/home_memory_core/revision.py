from dataclasses import dataclass

from home_memory_core.evidence import EvidenceRef


@dataclass(frozen=True)
class SupersessionRecord:
    previous_interpretation_id: str
    new_interpretation_id: str
    reason_evidence: tuple[EvidenceRef, ...]


def create_supersession_record(
    *,
    previous_interpretation_id: str,
    new_interpretation_id: str,
    reason_evidence: tuple[EvidenceRef, ...],
) -> SupersessionRecord:
    if previous_interpretation_id == new_interpretation_id:
        raise ValueError("an interpretation cannot supersede itself")

    if not reason_evidence:
        raise ValueError("supersession must have evidence")

    return SupersessionRecord(
        previous_interpretation_id=previous_interpretation_id,
        new_interpretation_id=new_interpretation_id,
        reason_evidence=reason_evidence,
    )