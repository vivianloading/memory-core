from home_memory_core.interpretation import InterpretationRecord
from home_memory_core.revision import SupersessionRecord


def resolve_interpretation_status(
    *,
    interpretation: InterpretationRecord,
    supersessions: tuple[SupersessionRecord, ...],
) -> str:
    for supersession in supersessions:
        if (
            supersession.previous_interpretation_id
            == interpretation.interpretation_id
        ):
            return "superseded"

    return "current"