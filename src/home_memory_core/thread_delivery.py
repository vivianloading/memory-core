from __future__ import annotations

from hashlib import sha256
from typing import Callable

from home_memory_core.delivery_boundary import (
    GateIssuedMemoryPacket,
    RequestBoundDeliveryBoundary,
    SelectionReceipt,
    SyntheticModelRequest,
    ExactSourceSpan,
    _create_gate_issued_memory_packet,
)
from home_memory_core.lineage import LineageIntegrityError, resolve_lineage
from home_memory_core.storage import MemoryStore


class ThreadDeliveryUnavailable(RuntimeError):
    """The requested thread is valid but has no deliverable candidate."""


class ThreadDeliveryIntegrityError(LineageIntegrityError):
    """Payload materialization disagrees with the authoritative thread snapshot."""


class ThreadAddressedReadOnlyDeliveryGate:
    """Synthetic-only exact-source delivery for one explicitly requested thread.

    The public operation is ``handoff``. It composes whole-thread structural
    resolution, exact payload materialization, and the request-bound delivery
    boundary. It does not expose interpretation text to the model-facing path.
    """

    def __init__(self, store: MemoryStore) -> None:
        self._store = store
        self._boundary = RequestBoundDeliveryBoundary(store)

    def handoff(
        self,
        *,
        request_id: str,
        requested_thread_id: str,
        user_input: str,
        transport_handoff: Callable[[SyntheticModelRequest], None],
    ) -> SelectionReceipt:
        return self._boundary.handoff(
            request_id=request_id,
            requested_thread_id=requested_thread_id,
            user_input=user_input,
            packet_factory=self._issue_packet,
            transport_handoff=transport_handoff,
        )

    def _issue_packet(
        self,
        request_id: str,
        requested_thread_id: str,
    ) -> GateIssuedMemoryPacket:
        if not request_id.strip():
            raise ThreadDeliveryIntegrityError("request_id cannot be empty")
        if not requested_thread_id.strip():
            raise ThreadDeliveryIntegrityError(
                "requested_thread_id cannot be empty"
            )

        with self._store._read_snapshot() as connection:
            try:
                resolution_input = (
                    self._store._build_lineage_resolution_input_from_connection(
                        connection=connection,
                        thread_id=requested_thread_id,
                    )
                )
                resolution = resolve_lineage(
                    resolution_input=resolution_input
                )
            except LineageIntegrityError as error:
                raise ThreadDeliveryIntegrityError(str(error)) from error

            if resolution.decision != "candidate_available":
                raise ThreadDeliveryUnavailable(
                    "thread has no currently deliverable structural candidate"
                )

            if len(resolution.candidate_ids) != 1:
                raise ThreadDeliveryIntegrityError(
                    "candidate_available must contain exactly one candidate"
                )

            candidate_interpretation_id = next(
                iter(resolution.candidate_ids)
            )

            if candidate_interpretation_id not in resolution_input.interpretation_ids:
                raise ThreadDeliveryIntegrityError(
                    "resolved candidate is outside thread membership"
                )

            candidate_row = connection.execute(
                """
                SELECT
                    memberships.thread_id,
                    interpretations.interpretation_id,
                    interpretations.scope
                FROM interpretations
                JOIN interpretation_thread_memberships AS memberships
                    ON memberships.interpretation_id
                    = interpretations.interpretation_id
                WHERE interpretations.interpretation_id = ?
                """,
                (candidate_interpretation_id,),
            ).fetchone()

            if candidate_row is None:
                raise ThreadDeliveryIntegrityError(
                    "resolved candidate is missing from persistent membership"
                )
            if candidate_row["thread_id"] != requested_thread_id:
                raise ThreadDeliveryIntegrityError(
                    "resolved candidate belongs to a different thread"
                )

            evidence_rows = connection.execute(
                """
                SELECT
                    evidence.position,
                    evidence.source_id,
                    evidence.source_sha256,
                    evidence.start_char,
                    evidence.end_char,
                    sources.content,
                    sources.authored_by,
                    sources.scope,
                    sources.content_sha256,
                    suppressions.source_id AS suppressed_source_id
                FROM interpretation_evidence AS evidence
                JOIN sources
                    ON sources.source_id = evidence.source_id
                LEFT JOIN source_suppressions AS suppressions
                    ON suppressions.source_id = evidence.source_id
                WHERE evidence.interpretation_id = ?
                ORDER BY evidence.position
                """,
                (candidate_interpretation_id,),
            ).fetchall()

            if not evidence_rows:
                raise ThreadDeliveryIntegrityError(
                    "deliverable candidate is missing required evidence"
                )

            expected_positions = list(range(len(evidence_rows)))
            actual_positions = [row["position"] for row in evidence_rows]
            if actual_positions != expected_positions:
                raise ThreadDeliveryIntegrityError(
                    "candidate evidence positions are incomplete"
                )

            spans: list[ExactSourceSpan] = []
            delivered_ref_tuples: list[
                tuple[str, str, int, int]
            ] = []

            for row in evidence_rows:
                if row["suppressed_source_id"] is not None:
                    raise ThreadDeliveryIntegrityError(
                        "resolved candidate depends on a suppressed source"
                    )

                content = row["content"]
                stored_source_hash = row["content_sha256"]
                evidence_hash = row["source_sha256"]
                actual_hash = sha256(content.encode("utf-8")).hexdigest()

                if actual_hash != stored_source_hash:
                    raise ThreadDeliveryIntegrityError(
                        "stored source payload hash does not match content"
                    )
                if stored_source_hash != evidence_hash:
                    raise ThreadDeliveryIntegrityError(
                        "candidate evidence hash does not match source snapshot"
                    )
                if row["scope"] != candidate_row["scope"]:
                    raise ThreadDeliveryIntegrityError(
                        "candidate evidence crosses the candidate scope"
                    )

                start_char = row["start_char"]
                end_char = row["end_char"]
                if not isinstance(start_char, int) or not isinstance(end_char, int):
                    raise ThreadDeliveryIntegrityError(
                        "candidate evidence offsets must be integers"
                    )
                if start_char < 0 or end_char <= start_char:
                    raise ThreadDeliveryIntegrityError(
                        "candidate evidence offsets are invalid"
                    )
                if end_char > len(content):
                    raise ThreadDeliveryIntegrityError(
                        "candidate evidence range exceeds source payload"
                    )

                exact_text = content[start_char:end_char]
                if not exact_text:
                    raise ThreadDeliveryIntegrityError(
                        "candidate evidence span cannot be empty"
                    )

                spans.append(
                    ExactSourceSpan(
                        source_id=row["source_id"],
                        source_sha256=evidence_hash,
                        start_char=start_char,
                        end_char=end_char,
                        exact_text=exact_text,
                        authored_by=row["authored_by"],
                        scope=row["scope"],
                    )
                )
                delivered_ref_tuples.append(
                    (
                        row["source_id"],
                        evidence_hash,
                        start_char,
                        end_char,
                    )
                )

            expected_ref_tuples = [
                (
                    row["source_id"],
                    row["source_sha256"],
                    row["start_char"],
                    row["end_char"],
                )
                for row in evidence_rows
            ]
            if delivered_ref_tuples != expected_ref_tuples:
                raise ThreadDeliveryIntegrityError(
                    "delivered evidence set differs from candidate evidence"
                )

            support_refs = self._required_resolution_support_refs(
                connection=connection,
                thread_id=requested_thread_id,
            )

            return _create_gate_issued_memory_packet(
                request_id=request_id,
                thread_id=requested_thread_id,
                candidate_interpretation_id=candidate_interpretation_id,
                evidence_spans=tuple(spans),
                required_resolution_support_refs=support_refs,
                semantic_status=resolution.semantic_status,
                world_validity=resolution.world_validity,
            )

    def _required_resolution_support_refs(
        self,
        *,
        connection,
        thread_id: str,
    ) -> tuple[str, ...]:
        interpretation_rows = connection.execute(
            """
            SELECT
                memberships.interpretation_id,
                evidence.position,
                evidence.source_id,
                evidence.source_sha256,
                evidence.start_char,
                evidence.end_char
            FROM interpretation_thread_memberships AS memberships
            JOIN interpretation_evidence AS evidence
                ON evidence.interpretation_id = memberships.interpretation_id
            WHERE memberships.thread_id = ?
            ORDER BY memberships.rowid, evidence.position
            """,
            (thread_id,),
        ).fetchall()

        supersession_rows = connection.execute(
            """
            SELECT
                supersessions.previous_interpretation_id,
                supersessions.new_interpretation_id,
                evidence.position,
                evidence.source_id,
                evidence.source_sha256,
                evidence.start_char,
                evidence.end_char
            FROM supersessions
            JOIN interpretation_thread_memberships AS previous_membership
                ON previous_membership.interpretation_id
                = supersessions.previous_interpretation_id
            JOIN interpretation_thread_memberships AS new_membership
                ON new_membership.interpretation_id
                = supersessions.new_interpretation_id
            JOIN supersession_evidence AS evidence
                ON evidence.previous_interpretation_id
                = supersessions.previous_interpretation_id
                AND evidence.new_interpretation_id
                = supersessions.new_interpretation_id
            WHERE previous_membership.thread_id = ?
                AND new_membership.thread_id = ?
            ORDER BY supersessions.rowid, evidence.position
            """,
            (thread_id, thread_id),
        ).fetchall()

        return tuple(
            [
                (
                    "interpretation:"
                    f"{row['interpretation_id']}:"
                    f"evidence:{row['position']}:"
                    f"{row['source_id']}:"
                    f"{row['source_sha256']}:"
                    f"{row['start_char']}:{row['end_char']}"
                )
                for row in interpretation_rows
            ]
            + [
                (
                    "supersession:"
                    f"{row['previous_interpretation_id']}->"
                    f"{row['new_interpretation_id']}:"
                    f"evidence:{row['position']}:"
                    f"{row['source_id']}:"
                    f"{row['source_sha256']}:"
                    f"{row['start_char']}:{row['end_char']}"
                )
                for row in supersession_rows
            ]
        )
