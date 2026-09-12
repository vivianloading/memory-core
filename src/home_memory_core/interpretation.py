from dataclasses import dataclass

from home_memory_core.evidence import EvidenceRef


SYNTHETIC_UNATTRIBUTED_INSTANCE_ID = "__synthetic_unattributed__"


@dataclass(frozen=True)
class InterpretationRecord:
    interpretation_id: str
    text: str
    perspective_owner: str
    about_subject: str
    scope: str
    evidence: tuple[EvidenceRef, ...]
    perspective_instance_id: str = SYNTHETIC_UNATTRIBUTED_INSTANCE_ID


def create_interpretation_record(
    *,
    interpretation_id: str,
    text: str,
    perspective_owner: str,
    about_subject: str,
    scope: str,
    evidence: tuple[EvidenceRef, ...],
    perspective_instance_id: str = SYNTHETIC_UNATTRIBUTED_INSTANCE_ID,
) -> InterpretationRecord:
    values = {
        "interpretation_id": interpretation_id,
        "text": text,
        "perspective_owner": perspective_owner,
        "about_subject": about_subject,
        "scope": scope,
        "perspective_instance_id": perspective_instance_id,
    }

    for field_name, value in values.items():
        if not value.strip():
            raise ValueError(f"{field_name} cannot be empty")

    if not evidence:
        raise ValueError(
            "interpretation must have at least one evidence reference"
        )

    return InterpretationRecord(
        interpretation_id=interpretation_id,
        text=text,
        perspective_owner=perspective_owner,
        about_subject=about_subject,
        scope=scope,
        evidence=evidence,
        perspective_instance_id=perspective_instance_id,
    )
