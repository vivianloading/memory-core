from home_memory_core.interpretation import InterpretationRecord
from home_memory_core.revision import SupersessionRecord


def resolve_interpretation_status(
    *,
    interpretation: InterpretationRecord,
    supersessions: tuple[SupersessionRecord, ...],
) -> str:
    validate_supersession_graph(supersessions=supersessions)

    interpretation_id = interpretation.interpretation_id

    outgoing_ids = {
        supersession.previous_interpretation_id
        for supersession in supersessions
    }

    if interpretation_id in outgoing_ids:
        return "superseded"

    terminal_ids = _resolve_lineage_terminal_ids_unchecked(
        interpretation_id=interpretation_id,
        supersessions=supersessions,
    )

    if len(terminal_ids) > 1:
        return "conflicting"

    return "current"


def resolve_lineage_terminal_ids(
    *,
    interpretation_id: str,
    supersessions: tuple[SupersessionRecord, ...],
) -> frozenset[str]:
    validate_supersession_graph(supersessions=supersessions)

    return _resolve_lineage_terminal_ids_unchecked(
        interpretation_id=interpretation_id,
        supersessions=supersessions,
    )


def validate_supersession_graph(
    *,
    supersessions: tuple[SupersessionRecord, ...],
) -> None:
    seen_edges: set[tuple[str, str]] = set()
    adjacency: dict[str, set[str]] = {}
    incoming_parent: dict[str, str] = {}
    all_ids: set[str] = set()

    for supersession in supersessions:
        previous_id = supersession.previous_interpretation_id
        new_id = supersession.new_interpretation_id
        edge = (previous_id, new_id)

        if edge in seen_edges:
            raise ValueError("supersession graph contains a duplicate edge")

        existing_parent = incoming_parent.get(new_id)

        if (
            existing_parent is not None
            and existing_parent != previous_id
        ):
            raise ValueError(
                "supersession graph contains an implicit merge"
            )

        incoming_parent[new_id] = previous_id
        seen_edges.add(edge)
        adjacency.setdefault(previous_id, set()).add(new_id)
        all_ids.add(previous_id)
        all_ids.add(new_id)

    visited: set[str] = set()
    active: set[str] = set()

    def visit(interpretation_id: str) -> None:
        if interpretation_id in active:
            raise ValueError("supersession graph contains a cycle")

        if interpretation_id in visited:
            return

        active.add(interpretation_id)

        for next_id in adjacency.get(interpretation_id, set()):
            visit(next_id)

        active.remove(interpretation_id)
        visited.add(interpretation_id)

    for interpretation_id in all_ids:
        visit(interpretation_id)


def _resolve_lineage_terminal_ids_unchecked(
    *,
    interpretation_id: str,
    supersessions: tuple[SupersessionRecord, ...],
) -> frozenset[str]:
    lineage_ids = _find_lineage_ids(
        interpretation_id=interpretation_id,
        supersessions=supersessions,
    )

    outgoing_ids = {
        supersession.previous_interpretation_id
        for supersession in supersessions
    }

    return frozenset(
        candidate_id
        for candidate_id in lineage_ids
        if candidate_id not in outgoing_ids
    )


def _find_lineage_ids(
    *,
    interpretation_id: str,
    supersessions: tuple[SupersessionRecord, ...],
) -> set[str]:
    lineage_ids = {interpretation_id}
    pending = [interpretation_id]

    while pending:
        current_id = pending.pop()

        for supersession in supersessions:
            connected_id = None

            if supersession.previous_interpretation_id == current_id:
                connected_id = supersession.new_interpretation_id
            elif supersession.new_interpretation_id == current_id:
                connected_id = supersession.previous_interpretation_id

            if (
                connected_id is not None
                and connected_id not in lineage_ids
            ):
                lineage_ids.add(connected_id)
                pending.append(connected_id)

    return lineage_ids
