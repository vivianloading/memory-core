from home_memory_core.interpretation import InterpretationRecord
from home_memory_core.revision import SupersessionRecord


def resolve_interpretation_status(
    *,
    interpretation: InterpretationRecord,
    supersessions: tuple[SupersessionRecord, ...],
) -> str:
    outgoing = tuple(
        supersession
        for supersession in supersessions
        if (
            supersession.previous_interpretation_id
            == interpretation.interpretation_id
        )
    )

    if outgoing:
        return "superseded"

    incoming = tuple(
        supersession
        for supersession in supersessions
        if (
            supersession.new_interpretation_id
            == interpretation.interpretation_id
        )
    )

    for incoming_edge in incoming:
        competing_successors = tuple(
            supersession
            for supersession in supersessions
            if (
                supersession.previous_interpretation_id
                == incoming_edge.previous_interpretation_id
            )
        )

        if len(competing_successors) > 1:
            return "conflicting"

    return "current"