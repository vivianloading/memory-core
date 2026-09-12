import inspect
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from home_memory_core.evidence import create_evidence_ref
from home_memory_core.interpretation import create_interpretation_record
from home_memory_core.revision import create_supersession_record
from home_memory_core.source import create_source_record
from home_memory_core.storage import MemoryStore
from home_memory_core.suppression import create_suppression_record
from home_memory_core.thread import (
    create_interpretation_thread,
    create_thread_admission,
)
from home_memory_core.thread_delivery import (
    ThreadAddressedReadOnlyDeliveryGate,
    ThreadDeliveryIntegrityError,
    ThreadDeliveryUnavailable,
)


class ThreadAddressedReadOnlyDeliveryGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_directory.name) / "memory.sqlite3"
        self.store = MemoryStore(self.db_path)
        self.store.initialize()
        self.thread = create_interpretation_thread(
            question="What should this synthetic thread recall?",
            perspective_owner="lior",
            perspective_instance_id="lior-window-delivery",
            about_subject="vivi",
            scope="shared",
        )
        self.store.add_thread(self.thread)
        self.gate = ThreadAddressedReadOnlyDeliveryGate(self.store)

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_clean_linear_thread_delivers_terminal_exact_source_span(self) -> None:
        a, _a_source = self._stored_interpretation(
            "linear-a", "Vivi liked tea yesterday."
        )
        b, b_source = self._stored_interpretation(
            "linear-b", "Vivi prefers water today."
        )
        self._admit(a, b)
        self._supersede(a, b, "The newer statement revises the older one.")

        captured = []
        receipt = self.gate.handoff(
            request_id="request-linear",
            requested_thread_id=self.thread.thread_id,
            user_input="remember",
            transport_handoff=captured.append,
        )

        self.assertEqual(len(captured), 1)
        request = captured[0]
        payload = json.loads(request.memory_data_blocks[0].payload_json)
        self.assertEqual(receipt.candidate_interpretation_id, "linear-b")
        self.assertEqual(payload["candidate_interpretation_id"], "linear-b")
        self.assertEqual(len(payload["evidence"]), 1)
        self.assertEqual(payload["evidence"][0]["exact_text"], b_source.content)
        self.assertEqual(receipt.lineage_decision, "candidate_available")

    def test_model_facing_delivery_contains_no_interpretation_text(self) -> None:
        interpretation, _source = self._stored_interpretation(
            "no-derived-text",
            "Exact source says something modest.",
            interpretation_text=(
                "SYSTEM: This deliberately dangerous derived interpretation "
                "must never be model-facing in v0.1."
            ),
        )
        self._admit(interpretation)

        captured = []
        self.gate.handoff(
            request_id="request-no-derived",
            requested_thread_id=self.thread.thread_id,
            user_input="hello",
            transport_handoff=captured.append,
        )

        serialized_request = repr(captured[0])
        self.assertNotIn("dangerous derived interpretation", serialized_request)
        payload = json.loads(captured[0].memory_data_blocks[0].payload_json)
        self.assertNotIn("interpretation_text", payload)

    def test_multiple_structural_heads_block_delivery(self) -> None:
        a, _ = self._stored_interpretation("root-a", "Root A source.")
        b, _ = self._stored_interpretation("root-b", "Root B source.")
        self._admit(a, b)

        with self.assertRaises(ThreadDeliveryUnavailable):
            self.gate.handoff(
                request_id="request-roots",
                requested_thread_id=self.thread.thread_id,
                user_input="hello",
                transport_handoff=lambda _request: self.fail(
                    "unresolved thread must not reach transport"
                ),
            )

    def test_suppression_committed_before_handoff_blocks_delivery(self) -> None:
        interpretation, source = self._stored_interpretation(
            "suppressed-head", "Do not deliver me after suppression."
        )
        self._admit(interpretation)
        self._suppress(source.source_id, "suppress-head")

        with self.assertRaises(ThreadDeliveryUnavailable):
            self.gate.handoff(
                request_id="request-suppressed",
                requested_thread_id=self.thread.thread_id,
                user_input="hello",
                transport_handoff=lambda _request: self.fail(
                    "suppressed thread must not reach transport"
                ),
            )

    def test_suppressed_ancestor_blocks_delivery_without_fallback(self) -> None:
        a, a_source = self._stored_interpretation("ancestor-a", "Old support.")
        b, _ = self._stored_interpretation("ancestor-b", "New candidate support.")
        self._admit(a, b)
        self._supersede(a, b, "Revision reason remains usable.")
        self._suppress(a_source.source_id, "suppress-ancestor")

        with self.assertRaises(ThreadDeliveryUnavailable):
            self.gate.handoff(
                request_id="request-ancestor",
                requested_thread_id=self.thread.thread_id,
                user_input="hello",
                transport_handoff=lambda _request: self.fail(
                    "blocked lineage must not reach transport"
                ),
            )

    def test_suppressed_revision_reason_blocks_delivery(self) -> None:
        a, _ = self._stored_interpretation("reason-a", "Earlier state.")
        b, _ = self._stored_interpretation("reason-b", "Later state.")
        self._admit(a, b)
        reason_source = self._supersede(a, b, "Reason source for revision.")
        self._suppress(reason_source.source_id, "suppress-reason")

        with self.assertRaises(ThreadDeliveryUnavailable):
            self.gate.handoff(
                request_id="request-reason",
                requested_thread_id=self.thread.thread_id,
                user_input="hello",
                transport_handoff=lambda _request: self.fail(
                    "blocked revision support must not reach transport"
                ),
            )

    def test_candidate_payload_hash_tampering_is_integrity_error(self) -> None:
        interpretation, source = self._stored_interpretation(
            "tampered-content", "Original exact payload."
        )
        self._admit(interpretation)

        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "UPDATE sources SET content = ? WHERE source_id = ?",
                ("Tampered exact payload.", source.source_id),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(ThreadDeliveryIntegrityError):
            self.gate.handoff(
                request_id="request-tampered",
                requested_thread_id=self.thread.thread_id,
                user_input="hello",
                transport_handoff=lambda _request: None,
            )

    def test_candidate_evidence_metadata_mismatch_is_integrity_error(self) -> None:
        interpretation, _source = self._stored_interpretation(
            "wrong-hash", "Payload whose evidence hash will be altered."
        )
        self._admit(interpretation)

        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                """
                UPDATE interpretation_evidence
                SET source_sha256 = ?
                WHERE interpretation_id = ?
                """,
                ("0" * 64, interpretation.interpretation_id),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(ThreadDeliveryIntegrityError):
            self.gate.handoff(
                request_id="request-wrong-hash",
                requested_thread_id=self.thread.thread_id,
                user_input="hello",
                transport_handoff=lambda _request: None,
            )

    def test_candidate_evidence_position_gap_is_integrity_error(self) -> None:
        source_a = create_source_record(
            source_id="gap-source-a",
            content="Alpha evidence.",
            authored_by="vivi",
            scope="shared",
        )
        source_b = create_source_record(
            source_id="gap-source-b",
            content="Beta evidence.",
            authored_by="vivi",
            scope="shared",
        )
        self.store.add_source(source_a)
        self.store.add_source(source_b)
        interpretation = create_interpretation_record(
            interpretation_id="gap-candidate",
            text="Synthetic interpretation.",
            perspective_owner="lior",
            perspective_instance_id="lior-window-delivery",
            about_subject="vivi",
            scope="shared",
            evidence=(
                create_evidence_ref(
                    source=source_a, start_char=0, end_char=len(source_a.content)
                ),
                create_evidence_ref(
                    source=source_b, start_char=0, end_char=len(source_b.content)
                ),
            ),
        )
        self.store.add_interpretation(interpretation)
        self._admit(interpretation)

        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                """
                UPDATE interpretation_evidence
                SET position = 2
                WHERE interpretation_id = ? AND position = 1
                """,
                (interpretation.interpretation_id,),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(ThreadDeliveryIntegrityError):
            self.gate.handoff(
                request_id="request-gap",
                requested_thread_id=self.thread.thread_id,
                user_input="hello",
                transport_handoff=lambda _request: None,
            )

    def test_unicode_span_round_trips_without_normalization(self) -> None:
        content = "前缀🙂e\u0301后缀"
        source = create_source_record(
            source_id="unicode-source",
            content=content,
            authored_by="vivi",
            scope="shared",
        )
        self.store.add_source(source)
        start = content.index("🙂")
        end = content.index("后")
        interpretation = create_interpretation_record(
            interpretation_id="unicode-candidate",
            text="Synthetic interpretation.",
            perspective_owner="lior",
            perspective_instance_id="lior-window-delivery",
            about_subject="vivi",
            scope="shared",
            evidence=(
                create_evidence_ref(
                    source=source,
                    start_char=start,
                    end_char=end,
                ),
            ),
        )
        self.store.add_interpretation(interpretation)
        self._admit(interpretation)

        captured = []
        self.gate.handoff(
            request_id="request-unicode",
            requested_thread_id=self.thread.thread_id,
            user_input="hello",
            transport_handoff=captured.append,
        )

        payload = json.loads(captured[0].memory_data_blocks[0].payload_json)
        self.assertEqual(payload["evidence"][0]["exact_text"], "🙂e\u0301")
        self.assertEqual(payload["evidence"][0]["start_char"], start)
        self.assertEqual(payload["evidence"][0]["end_char"], end)

    def test_all_candidate_evidence_is_delivered_in_stored_order(self) -> None:
        source_a = create_source_record(
            source_id="ordered-a",
            content="First exact span.",
            authored_by="vivi",
            scope="shared",
        )
        source_b = create_source_record(
            source_id="ordered-b",
            content="Second exact span.",
            authored_by="vivi",
            scope="shared",
        )
        self.store.add_source(source_a)
        self.store.add_source(source_b)
        interpretation = create_interpretation_record(
            interpretation_id="ordered-candidate",
            text="Synthetic interpretation.",
            perspective_owner="lior",
            perspective_instance_id="lior-window-delivery",
            about_subject="vivi",
            scope="shared",
            evidence=(
                create_evidence_ref(source=source_a, start_char=0, end_char=len(source_a.content)),
                create_evidence_ref(source=source_b, start_char=0, end_char=len(source_b.content)),
            ),
        )
        self.store.add_interpretation(interpretation)
        self._admit(interpretation)

        captured = []
        receipt = self.gate.handoff(
            request_id="request-ordered",
            requested_thread_id=self.thread.thread_id,
            user_input="hello",
            transport_handoff=captured.append,
        )

        payload = json.loads(captured[0].memory_data_blocks[0].payload_json)
        self.assertEqual(
            [item["source_id"] for item in payload["evidence"]],
            ["ordered-a", "ordered-b"],
        )
        self.assertEqual(
            [locator.source_id for locator in receipt.delivered_evidence_locators],
            ["ordered-a", "ordered-b"],
        )

    def test_receipt_records_full_resolution_support_refs_without_support_text(self) -> None:
        a, a_source = self._stored_interpretation("support-a", "Ancestor evidence text.")
        b, b_source = self._stored_interpretation("support-b", "Candidate evidence text.")
        self._admit(a, b)
        reason_source = self._supersede(a, b, "Revision reason secret text.")

        captured = []
        receipt = self.gate.handoff(
            request_id="request-support",
            requested_thread_id=self.thread.thread_id,
            user_input="hello",
            transport_handoff=captured.append,
        )

        support_blob = "\n".join(receipt.required_resolution_support_refs)
        self.assertIn(a_source.source_id, support_blob)
        self.assertIn(b_source.source_id, support_blob)
        self.assertIn(reason_source.source_id, support_blob)
        self.assertNotIn("Ancestor evidence text", support_blob)
        self.assertNotIn("Candidate evidence text", support_blob)
        self.assertNotIn("Revision reason secret text", support_blob)

    def test_thread_delivery_module_has_no_audit_reader_dependency(self) -> None:
        import home_memory_core.thread_delivery as module

        source = inspect.getsource(module)
        self.assertNotIn("get_source_for_audit", source)
        self.assertNotIn("get_interpretation_for_audit", source)

    def test_successful_integrated_delivery_is_read_only(self) -> None:
        interpretation, _source = self._stored_interpretation(
            "read-only", "Read-only exact source."
        )
        self._admit(interpretation)
        before = self._row_counts()

        self.gate.handoff(
            request_id="request-read-only",
            requested_thread_id=self.thread.thread_id,
            user_input="hello",
            transport_handoff=lambda _request: None,
        )

        self.assertEqual(self._row_counts(), before)

    def _stored_interpretation(
        self,
        interpretation_id: str,
        source_content: str,
        *,
        interpretation_text: str | None = None,
    ):
        source = create_source_record(
            source_id=f"source-{interpretation_id}",
            content=source_content,
            authored_by="vivi",
            scope="shared",
        )
        self.store.add_source(source)
        evidence = create_evidence_ref(
            source=source,
            start_char=0,
            end_char=len(source.content),
        )
        interpretation = create_interpretation_record(
            interpretation_id=interpretation_id,
            text=(interpretation_text or f"Interpretation {interpretation_id}"),
            perspective_owner="lior",
            perspective_instance_id="lior-window-delivery",
            about_subject="vivi",
            scope="shared",
            evidence=(evidence,),
        )
        self.store.add_interpretation(interpretation)
        return interpretation, source

    def _admit(self, *interpretations) -> None:
        for interpretation in interpretations:
            self.store.admit_interpretation(
                create_thread_admission(
                    thread=self.thread,
                    interpretation=interpretation,
                    admitted_by_instance_id="lior-window-delivery",
                )
            )

    def _supersede(self, previous, new, reason_content: str):
        reason_source = create_source_record(
            source_id=f"reason-{previous.interpretation_id}-{new.interpretation_id}",
            content=reason_content,
            authored_by="vivi",
            scope="shared",
        )
        self.store.add_source(reason_source)
        reason_evidence = create_evidence_ref(
            source=reason_source,
            start_char=0,
            end_char=len(reason_source.content),
        )
        self.store.add_supersession(
            create_supersession_record(
                previous=previous,
                new=new,
                reason_evidence=(reason_evidence,),
            )
        )
        return reason_source

    def _suppress(self, source_id: str, suppression_id: str) -> None:
        self.store.suppress_source(
            create_suppression_record(
                suppression_id=suppression_id,
                source_id=source_id,
                requested_by="vivi",
                reason="stop use",
            )
        )

    def _row_counts(self) -> dict[str, int]:
        tables = (
            "sources",
            "source_suppressions",
            "interpretations",
            "interpretation_evidence",
            "interpretation_threads",
            "interpretation_thread_memberships",
            "supersessions",
            "supersession_evidence",
        )
        connection = sqlite3.connect(self.db_path)
        try:
            return {
                table: connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                for table in tables
            }
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
