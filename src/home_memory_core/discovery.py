from __future__ import annotations

from dataclasses import dataclass

from home_memory_core.storage import MemoryStore


DISCOVERY_RULE = "thread_question_all_terms_casefold_v0.1"
DISCOVERY_AUTHORITY = "none"


class ThreadDiscoveryError(ValueError):
    """A discovery request violates the v0.1 lexical locator contract."""


@dataclass(frozen=True)
class ThreadDiscoveryResult:
    """Read-only thread locator result.

    Discovery is deliberately non-authoritative. It returns only thread IDs
    whose thread-question metadata contains every normalized query term. It
    does not inspect interpretation text, source payload, lineage resolution,
    suppression payload, or model-facing delivery state.
    """

    query: str
    normalized_terms: tuple[str, ...]
    thread_ids: tuple[str, ...]
    selection_rule: str = DISCOVERY_RULE
    authority: str = DISCOVERY_AUTHORITY
    complete_for_rule: bool = True


class ReadOnlyThreadDiscovery:
    """Synthetic-only lexical discovery over InterpretationThread.question.

    This component discovers possible thread IDs only. A returned thread ID is
    not a memory candidate and has no delivery authority. Any later model use
    must independently pass LineageResolution and the #05a delivery gate.
    """

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def discover(self, *, query: str) -> ThreadDiscoveryResult:
        terms = _normalize_query_terms(query)

        with self._store._read_snapshot() as connection:
            rows = connection.execute(
                """
                SELECT thread_id, question
                FROM interpretation_threads
                ORDER BY thread_id
                """
            ).fetchall()

        matching_thread_ids: list[str] = []
        for row in rows:
            normalized_question = row["question"].casefold()
            if all(term in normalized_question for term in terms):
                matching_thread_ids.append(row["thread_id"])

        return ThreadDiscoveryResult(
            query=query,
            normalized_terms=terms,
            thread_ids=tuple(matching_thread_ids),
        )


def _normalize_query_terms(query: str) -> tuple[str, ...]:
    if not isinstance(query, str):
        raise ThreadDiscoveryError("query must be a string")

    stripped = query.strip()
    if not stripped:
        raise ThreadDiscoveryError("query cannot be empty")

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_term in stripped.split():
        term = raw_term.casefold()
        if not term or term in seen:
            continue
        seen.add(term)
        normalized.append(term)

    if not normalized:
        raise ThreadDiscoveryError("query must contain at least one term")

    return tuple(normalized)
