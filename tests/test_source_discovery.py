import dataclasses
import inspect
import tempfile
import threading
import unittest
from pathlib import Path

from _suppression_test_support import create_test_suppression_record as create_suppression_record
from home_memory_core.evidence import create_evidence_ref
from home_memory_core.interpretation import create_interpretation_record
from home_memory_core.revision import create_supersession_record
from home_memory_core.source import create_source_record
from home_memory_core.source_discovery import (
    DISCOVERY_AUTHORITY,
    QUERY_RULE,
    SourceDiscoveryError,
    SourceDiscoveryIntegrityError,
    SourceLinkedReadOnlyDiscovery,
)
from home_memory_core.storage import MemoryStore
from home_memory_core.thread import (
    create_interpretation_thread,
    create_thread_admission,
)


class SourceLinkedReadOnlyDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "memory.sqlite3"
        self.store = MemoryStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_exact_referenced_span_match_returns_thread_id_only(self) -> None:
        thread, _interpretation, _source = self._thread_with_single_evidence(
            interpretation_id="i-exact",
            content="Synthetic Miyakojima memory.",
            start=10,
            end=20,
        )
        result = self._publish(query="Miyakojima")

        self.assertEqual(result.thread_ids, (thread.thread_id,))
        self.assertEqual(result.authority, DISCOVERY_AUTHORITY)
        self.assertTrue(result.complete_for_rule)
        self.assertFalse(hasattr(result, "source_text"))
        self.assertFalse(hasattr(result, "interpretation_text"))

    def test_unreferenced_text_in_same_source_does_not_match(self) -> None:
        content = "I enjoy cooking. Miyakojima"
        _thread, _interpretation, _source = self._thread_with_single_evidence(
            interpretation_id="i-unreferenced",
            content=content,
            start=0,
            end=len("I enjoy cooking."),
        )

        result = self._publish(query="Miyakojima")
        self.assertEqual(result.thread_ids, ())

    def test_query_does_not_stitch_separate_evidence_spans(self) -> None:
        thread = self._add_thread()
        source = self._add_source("s-split", "Miya--kojima")
        interpretation = self._add_interpretation(
            interpretation_id="i-split",
            evidence=(
                create_evidence_ref(source=source, start_char=0, end_char=4),
                create_evidence_ref(source=source, start_char=6, end_char=12),
            ),
        )
        self._admit(thread, interpretation)

        result = self._publish(query="Miyakojima")
        self.assertEqual(result.thread_ids, ())

    def test_suppressed_source_has_zero_discovery_influence(self) -> None:
        eligible_thread, _i1, _s1 = self._thread_with_single_evidence(
            interpretation_id="i-eligible",
            content="Miyakojima eligible",
            start=0,
            end=len("Miyakojima eligible"),
        )
        _blocked_thread, _i2, blocked_source = self._thread_with_single_evidence(
            interpretation_id="i-blocked",
            content="Miyakojima blocked",
            start=0,
            end=len("Miyakojima blocked"),
        )
        self.store.suppress_source(
            create_suppression_record(
                suppression_id="suppressed-blocked",
                source_id=blocked_source.source_id,
                requested_by="vivi",
                reason="synthetic stop-use",
            )
        )

        result = self._publish(query="Miyakojima")
        self.assertEqual(result.thread_ids, (eligible_thread.thread_id,))
        self.assertTrue(all(
            locator.source_id != blocked_source.source_id
            for locator in result.receipt.internal_match_locators
        ))

    def test_usable_source_cannot_bridge_through_blocked_interpretation(self) -> None:
        thread = self._add_thread()
        source_match = self._add_source("s-match", "Miyakojima usable")
        source_block = self._add_source("s-block", "required companion evidence")
        interpretation = self._add_interpretation(
            interpretation_id="i-two-evidence",
            evidence=(
                create_evidence_ref(
                    source=source_match,
                    start_char=0,
                    end_char=len(source_match.content),
                ),
                create_evidence_ref(
                    source=source_block,
                    start_char=0,
                    end_char=len(source_block.content),
                ),
            ),
        )
        self._admit(thread, interpretation)
        self.store.suppress_source(
            create_suppression_record(
                suppression_id="suppressed-companion",
                source_id=source_block.source_id,
                requested_by="vivi",
                reason="block owning interpretation",
            )
        )

        result = self._publish(query="Miyakojima")
        self.assertEqual(result.thread_ids, ())

    def test_inconsistent_thread_membership_metadata_aborts_discovery(self) -> None:
        original_thread, interpretation, _source = self._thread_with_single_evidence(
            interpretation_id="i-membership-integrity",
            content="needle",
            start=0,
            end=6,
        )
        incompatible_thread = create_interpretation_thread(
            question="Incompatible synthetic thread",
            perspective_owner="other-owner",
            perspective_instance_id="other-instance",
            about_subject="other-subject",
            scope="shared",
        )
        self.store.add_thread(incompatible_thread)

        with self.store._connection() as connection:
            connection.execute(
                """
                UPDATE interpretation_thread_memberships
                SET thread_id = ?,
                    perspective_instance_id = ?,
                    admitted_by_instance_id = ?
                WHERE interpretation_id = ?
                """,
                (
                    incompatible_thread.thread_id,
                    incompatible_thread.perspective_instance_id,
                    incompatible_thread.perspective_instance_id,
                    interpretation.interpretation_id,
                ),
            )

        gate = SourceLinkedReadOnlyDiscovery(self.store)
        called = False

        def handoff(_result):
            nonlocal called
            called = True

        with self.assertRaises(SourceDiscoveryIntegrityError):
            gate.handoff(query="needle", result_handoff=handoff)

        self.assertFalse(called)
        self.assertNotEqual(original_thread.thread_id, incompatible_thread.thread_id)

    def test_unadmitted_interpretation_cannot_create_discovery_hit(self) -> None:
        source = self._add_source("s-unadmitted", "Miyakojima")
        self._add_interpretation(
            interpretation_id="i-unadmitted",
            evidence=(
                create_evidence_ref(source=source, start_char=0, end_char=len(source.content)),
            ),
        )

        result = self._publish(query="Miyakojima")
        self.assertEqual(result.thread_ids, ())

    def test_supersession_reason_evidence_is_not_an_ordinary_discovery_channel(self) -> None:
        thread = self._add_thread()
        source_a = self._add_source("s-a", "tea preference")
        source_b = self._add_source("s-b", "updated tea preference")
        reason = self._add_source("s-reason", "Miyakojima correction process")
        a = self._add_interpretation(
            interpretation_id="i-a",
            evidence=(create_evidence_ref(source=source_a, start_char=0, end_char=len(source_a.content)),),
        )
        b = self._add_interpretation(
            interpretation_id="i-b",
            evidence=(create_evidence_ref(source=source_b, start_char=0, end_char=len(source_b.content)),),
        )
        self._admit(thread, a)
        self._admit(thread, b)
        self.store.add_supersession(
            create_supersession_record(
                previous=a,
                new=b,
                reason_evidence=(
                    create_evidence_ref(source=reason, start_char=0, end_char=len(reason.content)),
                ),
            )
        )

        result = self._publish(query="Miyakojima")
        self.assertEqual(result.thread_ids, ())

    def test_literal_unicode_rule_has_no_casefold_normalization_or_wildcards(self) -> None:
        thread, _interpretation, _source = self._thread_with_single_evidence(
            interpretation_id="i-literal",
            content="Straße é 100% <tool> 👍🏽",
            start=0,
            end=len("Straße é 100% <tool> 👍🏽"),
        )

        self.assertEqual(self._publish(query="Straße").thread_ids, (thread.thread_id,))
        self.assertEqual(self._publish(query="STRASSE").thread_ids, ())
        self.assertEqual(self._publish(query="e\u0301").thread_ids, ())
        self.assertEqual(self._publish(query="%").thread_ids, (thread.thread_id,))
        self.assertEqual(self._publish(query="<tool>").thread_ids, (thread.thread_id,))
        self.assertEqual(self._publish(query="👍").thread_ids, (thread.thread_id,))
        self.assertEqual(self._publish(query=" ").thread_ids, (thread.thread_id,))

    def test_empty_and_surrogate_queries_are_rejected_without_repair(self) -> None:
        gate = SourceLinkedReadOnlyDiscovery(self.store)
        with self.assertRaises(SourceDiscoveryError):
            gate.handoff(query="", result_handoff=lambda _result: None)
        with self.assertRaises(SourceDiscoveryError):
            gate.handoff(query="\ud800", result_handoff=lambda _result: None)

    def test_too_many_matches_returns_no_partial_thread_set(self) -> None:
        first, _i1, _s1 = self._thread_with_single_evidence(
            interpretation_id="i-limit-1", content="needle one", start=0, end=10
        )
        second, _i2, _s2 = self._thread_with_single_evidence(
            interpretation_id="i-limit-2", content="needle two", start=0, end=10
        )
        _third, _i3, _s3 = self._thread_with_single_evidence(
            interpretation_id="i-limit-3", content="needle tri", start=0, end=10
        )
        captured = []
        gate = SourceLinkedReadOnlyDiscovery(self.store, max_thread_matches=2)
        receipt = gate.handoff(query="needle", result_handoff=captured.append)
        result = captured[0]

        self.assertEqual(result.status, "too_many_matches")
        self.assertFalse(result.complete_for_rule)
        self.assertIsNone(result.thread_ids)
        self.assertEqual(receipt.matched_thread_ids, ())
        self.assertEqual(receipt.internal_match_locators, ())
        self.assertNotEqual(first.thread_id, second.thread_id)

    def test_complete_result_is_deduplicated_and_stably_sorted(self) -> None:
        thread = self._add_thread()
        source = self._add_source("s-duplicate", "needle needle")
        interpretation = self._add_interpretation(
            interpretation_id="i-duplicate",
            evidence=(
                create_evidence_ref(source=source, start_char=0, end_char=6),
                create_evidence_ref(source=source, start_char=7, end_char=13),
            ),
        )
        self._admit(thread, interpretation)
        other, _i2, _s2 = self._thread_with_single_evidence(
            interpretation_id="i-other", content="needle other", start=0, end=6
        )

        result = self._publish(query="needle")
        self.assertEqual(result.thread_ids, tuple(sorted((thread.thread_id, other.thread_id))))
        self.assertEqual(result.receipt.query_rule_version, QUERY_RULE)
        self.assertEqual(result.receipt.authority, "none")

    def test_receipt_is_frozen_and_non_authoritative(self) -> None:
        self._thread_with_single_evidence(
            interpretation_id="i-receipt", content="needle", start=0, end=6
        )
        result = self._publish(query="needle")

        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.receipt.result_status = "current"  # type: ignore[misc]
        self.assertEqual(result.receipt.authority, "none")
        self.assertFalse(hasattr(result.receipt, "score"))
        self.assertFalse(hasattr(result.receipt, "importance"))

    def test_payload_integrity_failure_aborts_instead_of_returning_partial_results(self) -> None:
        self._thread_with_single_evidence(
            interpretation_id="i-tamper", content="needle", start=0, end=6
        )
        with self.store._connection() as connection:
            connection.execute(
                "UPDATE sources SET content = ? WHERE source_id = ?",
                ("changed", "s-i-tamper"),
            )

        gate = SourceLinkedReadOnlyDiscovery(self.store)
        called = False
        def handoff(_result):
            nonlocal called
            called = True
        with self.assertRaises(SourceDiscoveryIntegrityError):
            gate.handoff(query="needle", result_handoff=handoff)
        self.assertFalse(called)

    def test_discovery_publication_is_ordered_against_suppression_commit(self) -> None:
        _thread, _interpretation, source = self._thread_with_single_evidence(
            interpretation_id="i-order", content="needle", start=0, end=6
        )
        gate = SourceLinkedReadOnlyDiscovery(self.store)
        published = threading.Event()
        release = threading.Event()
        suppression_finished = threading.Event()

        def result_handoff(result):
            self.assertEqual(result.status, "ok")
            published.set()
            self.assertFalse(suppression_finished.is_set())
            release.wait(timeout=5)

        def run_discovery():
            gate.handoff(query="needle", result_handoff=result_handoff)

        def run_suppression():
            published.wait(timeout=5)
            other_store = MemoryStore(self.db_path)
            other_store.suppress_source(
                create_suppression_record(
                    suppression_id="suppression-order",
                    source_id=source.source_id,
                    requested_by="vivi",
                    reason="ordering test",
                )
            )
            suppression_finished.set()

        discovery_thread = threading.Thread(target=run_discovery)
        suppression_thread = threading.Thread(target=run_suppression)
        discovery_thread.start()
        suppression_thread.start()
        self.assertTrue(published.wait(timeout=5))
        self.assertFalse(suppression_finished.wait(timeout=0.1))
        release.set()
        discovery_thread.join(timeout=5)
        suppression_thread.join(timeout=5)
        self.assertTrue(suppression_finished.is_set())

        # A fresh publication after committed suppression cannot reuse the old hit.
        fresh = self._publish(query="needle")
        self.assertEqual(fresh.thread_ids, ())

    def test_discovery_is_read_only(self) -> None:
        self._thread_with_single_evidence(
            interpretation_id="i-readonly", content="needle", start=0, end=6
        )
        before = self._row_counts()
        self._publish(query="needle")
        self.assertEqual(self._row_counts(), before)

    def test_module_has_no_interpretation_text_supersession_search_or_audit_reader(self) -> None:
        import home_memory_core.source_discovery as module

        source = inspect.getsource(module)
        self.assertNotIn("interpretations.text", source)
        self.assertNotIn("supersession_evidence", source)
        self.assertNotIn("get_source_for_audit", source)
        self.assertNotIn("get_interpretation_for_audit", source)
        self.assertNotIn("MATCH(", source)
        self.assertNotIn("LIKE", source)

    def _publish(self, *, query: str):
        captured = []
        gate = SourceLinkedReadOnlyDiscovery(self.store)
        gate.handoff(query=query, result_handoff=captured.append)
        self.assertEqual(len(captured), 1)
        return captured[0]

    def _add_thread(self):
        thread = create_interpretation_thread(
            question="Synthetic source discovery thread",
            perspective_owner="lior",
            perspective_instance_id="lior-window-source-discovery",
            about_subject="vivi",
            scope="shared",
        )
        self.store.add_thread(thread)
        return thread

    def _add_source(self, source_id: str, content: str):
        source = create_source_record(
            source_id=source_id,
            content=content,
            authored_by="vivi",
            scope="shared",
        )
        self.store.add_source(source)
        return source

    def _add_interpretation(self, *, interpretation_id: str, evidence):
        interpretation = create_interpretation_record(
            interpretation_id=interpretation_id,
            text="Synthetic derived interpretation.",
            perspective_owner="lior",
            perspective_instance_id="lior-window-source-discovery",
            about_subject="vivi",
            scope="shared",
            evidence=tuple(evidence),
        )
        self.store.add_interpretation(interpretation)
        return interpretation

    def _admit(self, thread, interpretation) -> None:
        admission = create_thread_admission(
            thread=thread,
            interpretation=interpretation,
            admitted_by_instance_id="lior-window-source-discovery",
        )
        self.store.admit_interpretation(admission)

    def _thread_with_single_evidence(self, *, interpretation_id: str, content: str, start: int, end: int):
        thread = self._add_thread()
        source = self._add_source(f"s-{interpretation_id}", content)
        interpretation = self._add_interpretation(
            interpretation_id=interpretation_id,
            evidence=(create_evidence_ref(source=source, start_char=start, end_char=end),),
        )
        self._admit(thread, interpretation)
        return thread, interpretation, source

    def _row_counts(self):
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
        counts = {}
        with self.store._connection() as connection:
            for table in tables:
                counts[table] = connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
        return counts
