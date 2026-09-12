from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Callable
from uuid import uuid4

from home_memory_core.interpretation import SYNTHETIC_UNATTRIBUTED_INSTANCE_ID
from home_memory_core.storage import MemoryStore


QUERY_RULE = "literal_unicode_scalar_substring_v0.1"
ELIGIBILITY_RULE = "usable_admitted_interpretation_evidence_span_v0.1"
ORDERING_RULE = "thread_id_ascending_v0.1"
DISCOVERY_AUTHORITY = "none"
DEFAULT_MAX_THREAD_MATCHES = 64


class SourceDiscoveryError(ValueError):
    """A source discovery request violates the v0.1 contract."""


class SourceDiscoveryIntegrityError(RuntimeError):
    """Stored discovery data cannot be trusted as a complete eligible domain."""


@dataclass(frozen=True)
class DiscoveryMatchLocator:
    thread_id: str
    interpretation_id: str
    source_id: str
    source_sha256: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class DiscoveryReceipt:
    discovery_id: str
    exact_query_input: str
    query_rule_version: str
    eligible_domain_rule_version: str
    result_status: str
    complete_for_rule: bool
    deterministic_ordering_rule: str
    matched_thread_ids: tuple[str, ...]
    internal_match_locators: tuple[DiscoveryMatchLocator, ...]
    max_thread_matches: int
    authority: str = DISCOVERY_AUTHORITY


@dataclass(frozen=True)
class SourceDiscoveryResult:
    status: str
    complete_for_rule: bool
    thread_ids: tuple[str, ...] | None
    receipt: DiscoveryReceipt
    authority: str = DISCOVERY_AUTHORITY


class SourceLinkedReadOnlyDiscovery:
    """Synthetic-only source-linked discovery.

    A successful result means only that an exact literal occurred inside an
    exact evidence span belonging to a currently usable admitted
    interpretation. The result has no delivery or truth authority.

    Publication is callback-bound and serialized against same-process
    authority-affecting MemoryStore writes so a suppression that commits
    before publication cannot be hidden behind an older read snapshot.
    """

    def __init__(
        self,
        store: MemoryStore,
        *,
        max_thread_matches: int = DEFAULT_MAX_THREAD_MATCHES,
    ) -> None:
        if not isinstance(max_thread_matches, int) or max_thread_matches <= 0:
            raise SourceDiscoveryError(
                "max_thread_matches must be a positive integer"
            )
        self._store = store
        self._max_thread_matches = max_thread_matches

    def handoff(
        self,
        *,
        query: str,
        result_handoff: Callable[[SourceDiscoveryResult], None],
    ) -> DiscoveryReceipt:
        _validate_literal_query(query)

        # This reuses Task #05.0's same-process ordering boundary. The
        # callback invocation is the discovery publication point for v0.1.
        with self._store._request_delivery_ordering_guard():
            with self._store._read_snapshot() as connection:
                result = self._discover_in_snapshot(
                    connection=connection,
                    query=query,
                )

            result_handoff(result)
            return result.receipt

    def _discover_in_snapshot(self, *, connection, query: str) -> SourceDiscoveryResult:
        metadata_rows = connection.execute(
            """
            SELECT
                memberships.thread_id,
                memberships.admission_id,
                memberships.perspective_instance_id AS admission_instance_id,
                memberships.admitted_by_instance_id,
                interpretations.interpretation_id,
                interpretations.perspective_owner AS interpretation_owner,
                interpretations.perspective_instance_id AS interpretation_instance_id,
                interpretations.about_subject AS interpretation_subject,
                interpretations.scope AS interpretation_scope,
                threads.perspective_owner AS thread_owner,
                threads.perspective_instance_id AS thread_instance_id,
                threads.about_subject AS thread_subject,
                threads.scope AS thread_scope,
                evidence.position,
                evidence.source_id,
                evidence.source_sha256,
                evidence.start_char,
                evidence.end_char,
                sources.scope AS source_scope,
                sources.content_sha256 AS stored_source_sha256,
                suppressions.source_id AS suppressed_source_id
            FROM interpretation_thread_memberships AS memberships
            JOIN interpretations
                ON interpretations.interpretation_id
                = memberships.interpretation_id
            JOIN interpretation_threads AS threads
                ON threads.thread_id = memberships.thread_id
            JOIN interpretation_evidence AS evidence
                ON evidence.interpretation_id
                = interpretations.interpretation_id
            JOIN sources
                ON sources.source_id = evidence.source_id
            LEFT JOIN source_suppressions AS suppressions
                ON suppressions.source_id = sources.source_id
            ORDER BY
                memberships.thread_id,
                interpretations.interpretation_id,
                evidence.position
            """
        ).fetchall()

        evidence_by_interpretation: dict[str, list] = {}
        thread_by_interpretation: dict[str, str] = {}

        for row in metadata_rows:
            interpretation_id = row["interpretation_id"]
            thread_id = row["thread_id"]

            if (
                not row["admission_id"].strip()
                or not row["admitted_by_instance_id"].strip()
                or row["interpretation_owner"] != row["thread_owner"]
                or row["interpretation_instance_id"] != row["thread_instance_id"]
                or row["admission_instance_id"] != row["thread_instance_id"]
                or row["interpretation_subject"] != row["thread_subject"]
                or row["interpretation_scope"] != row["thread_scope"]
                or row["interpretation_instance_id"]
                == SYNTHETIC_UNATTRIBUTED_INSTANCE_ID
            ):
                raise SourceDiscoveryIntegrityError(
                    "thread membership metadata is internally inconsistent"
                )

            previous_thread_id = thread_by_interpretation.get(interpretation_id)
            if previous_thread_id is not None and previous_thread_id != thread_id:
                raise SourceDiscoveryIntegrityError(
                    "an interpretation is admitted to more than one thread"
                )
            thread_by_interpretation[interpretation_id] = thread_id
            evidence_by_interpretation.setdefault(interpretation_id, []).append(row)

        eligible_interpretation_ids: list[str] = []
        for interpretation_id, rows in evidence_by_interpretation.items():
            positions = [row["position"] for row in rows]
            if positions != list(range(len(rows))):
                raise SourceDiscoveryIntegrityError(
                    "interpretation evidence positions are incomplete"
                )

            blocked = False
            for row in rows:
                if row["source_scope"] != row["interpretation_scope"]:
                    raise SourceDiscoveryIntegrityError(
                        "interpretation evidence crosses scope"
                    )
                if row["stored_source_sha256"] != row["source_sha256"]:
                    raise SourceDiscoveryIntegrityError(
                        "interpretation evidence hash metadata is inconsistent"
                    )
                if row["suppressed_source_id"] is not None:
                    blocked = True

            # Conservative policy: if ANY required evidence for the owning
            # interpretation is suppressed, none of that interpretation's
            # source->thread evidence edges may influence discovery.
            if not blocked:
                eligible_interpretation_ids.append(interpretation_id)

        if not eligible_interpretation_ids:
            return self._complete_result(
                query=query,
                thread_ids=(),
                match_locators=(),
            )

        placeholders = ",".join("?" for _ in eligible_interpretation_ids)
        payload_rows = connection.execute(
            f"""
            SELECT
                memberships.thread_id,
                interpretations.interpretation_id,
                evidence.position,
                evidence.source_id,
                evidence.source_sha256,
                evidence.start_char,
                evidence.end_char,
                sources.content,
                sources.content_sha256 AS stored_source_sha256,
                suppressions.source_id AS suppressed_source_id
            FROM interpretation_thread_memberships AS memberships
            JOIN interpretations
                ON interpretations.interpretation_id
                = memberships.interpretation_id
            JOIN interpretation_evidence AS evidence
                ON evidence.interpretation_id
                = interpretations.interpretation_id
            JOIN sources
                ON sources.source_id = evidence.source_id
            LEFT JOIN source_suppressions AS suppressions
                ON suppressions.source_id = sources.source_id
            WHERE interpretations.interpretation_id IN ({placeholders})
            ORDER BY
                memberships.thread_id,
                interpretations.interpretation_id,
                evidence.position
            """,
            tuple(eligible_interpretation_ids),
        ).fetchall()

        matched_thread_ids: set[str] = set()
        match_locators: list[DiscoveryMatchLocator] = []

        for row in payload_rows:
            # This should be impossible under the same snapshot because the
            # interpretation was selected only if every evidence item was
            # unsuppressed. Fail closed if storage becomes inconsistent.
            if row["suppressed_source_id"] is not None:
                raise SourceDiscoveryIntegrityError(
                    "suppressed evidence entered the discovery payload domain"
                )

            content = row["content"]
            actual_hash = sha256(content.encode("utf-8")).hexdigest()
            stored_hash = row["stored_source_sha256"]
            evidence_hash = row["source_sha256"]
            if actual_hash != stored_hash or stored_hash != evidence_hash:
                raise SourceDiscoveryIntegrityError(
                    "source payload integrity failed during discovery"
                )

            start_char = row["start_char"]
            end_char = row["end_char"]
            if not isinstance(start_char, int) or not isinstance(end_char, int):
                raise SourceDiscoveryIntegrityError(
                    "evidence offsets must be integers"
                )
            if start_char < 0 or end_char <= start_char or end_char > len(content):
                raise SourceDiscoveryIntegrityError(
                    "evidence offsets are invalid"
                )

            exact_span = content[start_char:end_char]
            if query not in exact_span:
                continue

            thread_id = row["thread_id"]
            matched_thread_ids.add(thread_id)
            match_locators.append(
                DiscoveryMatchLocator(
                    thread_id=thread_id,
                    interpretation_id=row["interpretation_id"],
                    source_id=row["source_id"],
                    source_sha256=evidence_hash,
                    start_char=start_char,
                    end_char=end_char,
                )
            )

            if len(matched_thread_ids) > self._max_thread_matches:
                return self._too_many_result(query=query)

        ordered_thread_ids = tuple(sorted(matched_thread_ids))
        ordered_locators = tuple(
            sorted(
                match_locators,
                key=lambda item: (
                    item.thread_id,
                    item.interpretation_id,
                    item.source_id,
                    item.start_char,
                    item.end_char,
                ),
            )
        )

        return self._complete_result(
            query=query,
            thread_ids=ordered_thread_ids,
            match_locators=ordered_locators,
        )

    def _complete_result(
        self,
        *,
        query: str,
        thread_ids: tuple[str, ...],
        match_locators: tuple[DiscoveryMatchLocator, ...],
    ) -> SourceDiscoveryResult:
        receipt = DiscoveryReceipt(
            discovery_id=f"discovery-{uuid4().hex}",
            exact_query_input=query,
            query_rule_version=QUERY_RULE,
            eligible_domain_rule_version=ELIGIBILITY_RULE,
            result_status="ok",
            complete_for_rule=True,
            deterministic_ordering_rule=ORDERING_RULE,
            matched_thread_ids=thread_ids,
            internal_match_locators=match_locators,
            max_thread_matches=self._max_thread_matches,
        )
        return SourceDiscoveryResult(
            status="ok",
            complete_for_rule=True,
            thread_ids=thread_ids,
            receipt=receipt,
        )

    def _too_many_result(self, *, query: str) -> SourceDiscoveryResult:
        receipt = DiscoveryReceipt(
            discovery_id=f"discovery-{uuid4().hex}",
            exact_query_input=query,
            query_rule_version=QUERY_RULE,
            eligible_domain_rule_version=ELIGIBILITY_RULE,
            result_status="too_many_matches",
            complete_for_rule=False,
            deterministic_ordering_rule=ORDERING_RULE,
            matched_thread_ids=(),
            internal_match_locators=(),
            max_thread_matches=self._max_thread_matches,
        )
        return SourceDiscoveryResult(
            status="too_many_matches",
            complete_for_rule=False,
            thread_ids=None,
            receipt=receipt,
        )


def _validate_literal_query(query: str) -> None:
    if not isinstance(query, str):
        raise SourceDiscoveryError("query must be a string")
    if query == "":
        raise SourceDiscoveryError("query cannot be empty")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in query):
        raise SourceDiscoveryError(
            "query must contain valid Unicode scalar values"
        )
