from home_memory_core.revision import SupersessionRecord


def resolve_connected_component_terminal_ids(
    *,
    interpretation_id: str,
    supersessions: tuple[SupersessionRecord, ...],
) -> frozenset[str]:
    """Return structural terminals in one connected revision component.

    This helper deliberately does not claim that any terminal is the
    thread-level current truth. A thread may contain multiple disconnected
    roots, so Task #04 must resolve the complete thread topology instead.
    """
    validate_supersession_graph(supersessions=supersessions)

    component_ids = _find_connected_component_ids(
        interpretation_id=interpretation_id,
        supersessions=supersessions,
    )

    outgoing_ids = {
        supersession.previous_interpretation_id
        for supersession in supersessions
    }

    return frozenset(
        candidate_id
        for candidate_id in component_ids
        if candidate_id not in outgoing_ids
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

        if previous_id == new_id:
            raise ValueError("supersession graph contains a self-loop")

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


def _find_connected_component_ids(
    *,
    interpretation_id: str,
    supersessions: tuple[SupersessionRecord, ...],
) -> set[str]:
    component_ids = {interpretation_id}
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
                and connected_id not in component_ids
            ):
                component_ids.add(connected_id)
                pending.append(connected_id)

    return component_ids
