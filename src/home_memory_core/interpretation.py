from dataclasses import dataclass

from home_memory_core.evidence import EvidenceRef


@dataclass(frozen=True)
class InterpretationRecord:
    interpretation_id: str
    text: str
    perspective_owner: str
    about_subject: str
    scope: str
    evidence: tuple[EvidenceRef, ...]


def create_interpretation_record(
    *,
    interpretation_id: str,
    text: str,
    perspective_owner: str,
    about_subject: str,
    scope: str,
    evidence: tuple[EvidenceRef, ...],
) -> InterpretationRecord:
    if not evidence:
        raise ValueError("interpretation must have at least one evidence reference")

    return InterpretationRecord(
        interpretation_id=interpretation_id,
        text=text,
        perspective_owner=perspective_owner,
        about_subject=about_subject,
        scope=scope,
        evidence=evidence,
    )