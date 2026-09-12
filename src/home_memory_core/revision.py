from dataclasses import dataclass

from home_memory_core.evidence import EvidenceRef
from home_memory_core.interpretation import InterpretationRecord


@dataclass(frozen=True)
class SupersessionRecord:
    previous_interpretation_id: str
    new_interpretation_id: str
    reason_evidence: tuple[EvidenceRef, ...]


def create_supersession_record(
    *,
    previous: InterpretationRecord,
    new: InterpretationRecord,
    reason_evidence: tuple[EvidenceRef, ...],
) -> SupersessionRecord:
    if previous.interpretation_id == new.interpretation_id:
        raise ValueError("an interpretation cannot supersede itself")
    if previous.perspective_owner != new.perspective_owner:
        raise ValueError(
            "supersession must stay within the same perspective owner"
        )
    if previous.about_subject != new.about_subject:
        raise ValueError(
            "supersession must stay about the same subject"
        )
    if previous.scope != new.scope:
        raise ValueError(
            "supersession must stay within the same scope"
        )
    if not reason_evidence:
        raise ValueError("supersession must have evidence")
    return SupersessionRecord(
        previous_interpretation_id=previous.interpretation_id,
        new_interpretation_id=new.interpretation_id,
        reason_evidence=reason_evidence,
    )
