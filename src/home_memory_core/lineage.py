from dataclasses import dataclass, field


class LineageIntegrityError(ValueError):
    """Stored lineage structure is incomplete or internally inconsistent."""


_STORE_ASSEMBLED_MARKER = object()


@dataclass(frozen=True)
class LineageResolutionInput:
    """Frozen, store-assembled input for structural lineage resolution.

    This object intentionally contains no interpretation text or source
    payload. The private assembly marker prevents ordinary callers from
    accidentally presenting a hand-built partial view as a complete thread
    snapshot.
    """

    thread_id: str
    interpretation_ids: frozenset[str]
    supersession_edges: frozenset[tuple[str, str]]
    blocked_interpretation_ids: frozenset[str]
    blocked_supersession_edges: frozenset[tuple[str, str]]
    _assembly_marker: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class LineageResolution:
    thread_id: str
    structural_state: str
    structural_head_ids: frozenset[str]
    support_status: str
    decision: str
    candidate_ids: frozenset[str]
    reason_codes: tuple[str, ...]
    semantic_status: str = "not_assessed"
    world_validity: str = "not_assessed"


def _create_store_assembled_input(
    *,
    thread_id: str,
    interpretation_ids: frozenset[str],
    supersession_edges: frozenset[tuple[str, str]],
    blocked_interpretation_ids: frozenset[str],
    blocked_supersession_edges: frozenset[tuple[str, str]],
) -> LineageResolutionInput:
    return LineageResolutionInput(
        thread_id=thread_id,
        interpretation_ids=interpretation_ids,
        supersession_edges=supersession_edges,
        blocked_interpretation_ids=blocked_interpretation_ids,
        blocked_supersession_edges=blocked_supersession_edges,
        _assembly_marker=_STORE_ASSEMBLED_MARKER,
    )


def resolve_lineage(
    *,
    resolution_input: LineageResolutionInput,
) -> LineageResolution:
    """Resolve a complete thread snapshot without reading the database.

    The result is deliberately structural and policy-limited. A usable,
    single structural head is only a candidate. This function does not assess
    truth, semantic entailment, evidence sufficiency, or real-world validity.
    """

    if resolution_input._assembly_marker is not _STORE_ASSEMBLED_MARKER:
        raise LineageIntegrityError(
            "lineage resolution input must be assembled by MemoryStore"
        )

    _validate_resolution_input(resolution_input=resolution_input)

    interpretation_ids = resolution_input.interpretation_ids
    edges = resolution_input.supersession_edges

    if not interpretation_ids:
        return LineageResolution(
            thread_id=resolution_input.thread_id,
            structural_state="empty",
            structural_head_ids=frozenset(),
            support_status="not_applicable",
            decision="no_candidate",
            candidate_ids=frozenset(),
            reason_codes=("EMPTY_THREAD",),
        )

    outgoing_ids = {
        previous_id
        for previous_id, _new_id in edges
    }
    structural_head_ids = frozenset(
        interpretation_id
        for interpretation_id in interpretation_ids
        if interpretation_id not in outgoing_ids
    )

    if not structural_head_ids:
        raise LineageIntegrityError(
            "non-empty acyclic lineage has no structural head"
        )

    if len(structural_head_ids) == 1:
        structural_state = "single_head"
    else:
        structural_state = "multiple_heads"

    support_blocked = bool(
        resolution_input.blocked_interpretation_ids
        or resolution_input.blocked_supersession_edges
    )
    support_status = "blocked" if support_blocked else "clear"

    reasons: list[str] = []

    if structural_state == "multiple_heads":
        reasons.append("MULTIPLE_STRUCTURAL_HEADS")

    if support_blocked:
        reasons.append("REQUIRED_SUPPORT_BLOCKED")

    if structural_state == "single_head" and not support_blocked:
        decision = "candidate_available"
        candidate_ids = structural_head_ids
    else:
        decision = "unresolved"
        candidate_ids = frozenset()

    return LineageResolution(
        thread_id=resolution_input.thread_id,
        structural_state=structural_state,
        structural_head_ids=structural_head_ids,
        support_status=support_status,
        decision=decision,
        candidate_ids=candidate_ids,
        reason_codes=tuple(reasons),
    )


def _validate_resolution_input(
    *,
    resolution_input: LineageResolutionInput,
) -> None:
    if not resolution_input.thread_id.strip():
        raise LineageIntegrityError("thread_id cannot be empty")

    interpretation_ids = resolution_input.interpretation_ids
    edges = resolution_input.supersession_edges

    if not resolution_input.blocked_interpretation_ids.issubset(
        interpretation_ids
    ):
        raise LineageIntegrityError(
            "blocked interpretation is outside thread membership"
        )

    if not resolution_input.blocked_supersession_edges.issubset(edges):
        raise LineageIntegrityError(
            "blocked supersession edge is outside thread topology"
        )

    adjacency: dict[str, set[str]] = {}
    incoming_parent: dict[str, str] = {}

    for previous_id, new_id in edges:
        if previous_id not in interpretation_ids or new_id not in interpretation_ids:
            raise LineageIntegrityError(
                "supersession edge endpoint is outside thread membership"
            )

        if previous_id == new_id:
            raise LineageIntegrityError(
                "thread topology contains a self-loop"
            )

        existing_parent = incoming_parent.get(new_id)
        if existing_parent is not None and existing_parent != previous_id:
            raise LineageIntegrityError(
                "thread topology contains an implicit merge"
            )

        incoming_parent[new_id] = previous_id
        adjacency.setdefault(previous_id, set()).add(new_id)

    visited: set[str] = set()
    active: set[str] = set()

    def visit(interpretation_id: str) -> None:
        if interpretation_id in active:
            raise LineageIntegrityError(
                "thread topology contains a cycle"
            )
        if interpretation_id in visited:
            return

        active.add(interpretation_id)
        for next_id in adjacency.get(interpretation_id, set()):
            visit(next_id)
        active.remove(interpretation_id)
        visited.add(interpretation_id)

    for interpretation_id in interpretation_ids:
        visit(interpretation_id)
