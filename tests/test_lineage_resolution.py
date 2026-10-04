import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from _suppression_test_support import create_test_suppression_record as create_suppression_record
from home_memory_core.evidence import create_evidence_ref
from home_memory_core.interpretation import create_interpretation_record
from home_memory_core.lineage import (
    LineageIntegrityError,
    LineageResolutionInput,
    resolve_lineage,
)
from home_memory_core.revision import create_supersession_record
from home_memory_core.source import create_source_record
from home_memory_core.storage import MemoryStore
from home_memory_core.thread import (
    create_interpretation_thread,
    create_thread_admission,
)


class LineageResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_directory.name) / "memory.sqlite3"
        self.store = MemoryStore(self.db_path)
        self.store.initialize()
        self.thread = create_interpretation_thread(
            question="What is the current structural candidate?",
            perspective_owner="lior",
            perspective_instance_id="lior-window-resolution",
            about_subject="vivi",
            scope="shared",
        )
        self.store.add_thread(self.thread)

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_clean_linear_thread_returns_one_structural_candidate(self) -> None:
        a = self._stored_interpretation("linear-a")
        b = self._stored_interpretation("linear-b")
        c = self._stored_interpretation("linear-c")
        self._admit(a, b, c)
        self._supersede(a, b)
        self._supersede(b, c)

        result = resolve_lineage(
            resolution_input=self.store.get_lineage_resolution_input(
                self.thread.thread_id
            )
        )

        self.assertEqual(result.structural_state, "single_head")
        self.assertEqual(result.structural_head_ids, frozenset({"linear-c"}))
        self.assertEqual(result.support_status, "clear")
        self.assertEqual(result.decision, "candidate_available")
        self.assertEqual(result.candidate_ids, frozenset({"linear-c"}))
        self.assertEqual(result.reason_codes, ())
        self.assertEqual(result.semantic_status, "not_assessed")
        self.assertEqual(result.world_validity, "not_assessed")

    def test_direct_fork_is_multiple_heads_not_semantic_conflict(self) -> None:
        a = self._stored_interpretation("fork-a")
        b = self._stored_interpretation("fork-b")
        c = self._stored_interpretation("fork-c")
        self._admit(a, b, c)
        self._supersede(a, b)
        self._supersede(a, c)

        result = self._resolve()

        self.assertEqual(result.structural_state, "multiple_heads")
        self.assertEqual(
            result.structural_head_ids,
            frozenset({"fork-b", "fork-c"}),
        )
        self.assertEqual(result.support_status, "clear")
        self.assertEqual(result.decision, "unresolved")
        self.assertEqual(result.candidate_ids, frozenset())
        self.assertEqual(
            result.reason_codes,
            ("MULTIPLE_STRUCTURAL_HEADS",),
        )

    def test_disconnected_roots_are_multiple_heads(self) -> None:
        a = self._stored_interpretation("root-a")
        b = self._stored_interpretation("root-b")
        self._admit(a, b)

        result = self._resolve()

        self.assertEqual(result.structural_state, "multiple_heads")
        self.assertEqual(
            result.structural_head_ids,
            frozenset({"root-a", "root-b"}),
        )
        self.assertEqual(result.decision, "unresolved")

    def test_suppressing_terminal_does_not_resurrect_previous_node(self) -> None:
        a = self._stored_interpretation("terminal-a")
        b = self._stored_interpretation("terminal-b")
        c = self._stored_interpretation("terminal-c")
        self._admit(a, b, c)
        self._supersede(a, b)
        self._supersede(b, c)
        self._suppress_evidence(c, "suppress-terminal")

        result = self._resolve()

        self.assertEqual(result.structural_head_ids, frozenset({"terminal-c"}))
        self.assertEqual(result.support_status, "blocked")
        self.assertEqual(result.decision, "unresolved")
        self.assertEqual(result.candidate_ids, frozenset())
        self.assertNotIn("terminal-b", result.candidate_ids)

    def test_suppressing_one_fork_does_not_make_other_fork_win(self) -> None:
        a = self._stored_interpretation("fork-suppress-a")
        b = self._stored_interpretation("fork-suppress-b")
        c = self._stored_interpretation("fork-suppress-c")
        self._admit(a, b, c)
        self._supersede(a, b)
        self._supersede(a, c)
        self._suppress_evidence(b, "suppress-one-fork")

        result = self._resolve()

        self.assertEqual(
            result.structural_head_ids,
            frozenset({"fork-suppress-b", "fork-suppress-c"}),
        )
        self.assertEqual(result.structural_state, "multiple_heads")
        self.assertEqual(result.support_status, "blocked")
        self.assertEqual(result.decision, "unresolved")
        self.assertEqual(result.candidate_ids, frozenset())
        self.assertEqual(
            result.reason_codes,
            (
                "MULTIPLE_STRUCTURAL_HEADS",
                "REQUIRED_SUPPORT_BLOCKED",
            ),
        )

    def test_suppressing_ancestor_blocks_thread_without_changing_head(self) -> None:
        a = self._stored_interpretation("ancestor-a")
        b = self._stored_interpretation("ancestor-b")
        c = self._stored_interpretation("ancestor-c")
        self._admit(a, b, c)
        self._supersede(a, b)
        self._supersede(b, c)
        self._suppress_evidence(a, "suppress-ancestor")

        result = self._resolve()

        self.assertEqual(result.structural_head_ids, frozenset({"ancestor-c"}))
        self.assertEqual(result.support_status, "blocked")
        self.assertEqual(result.decision, "unresolved")

    def test_suppressed_revision_reason_blocks_without_removing_edge(self) -> None:
        previous = self._stored_interpretation("reason-a")
        new = self._stored_interpretation("reason-b")
        self._admit(previous, new)

        reason_source = create_source_record(
            source_id="reason-only-source",
            content="This source justifies the revision edge.",
            authored_by="vivi",
            scope="shared",
        )
        self.store.add_source(reason_source)
        reason = create_evidence_ref(
            source=reason_source,
            start_char=0,
            end_char=len(reason_source.content),
        )
        supersession = create_supersession_record(
            previous=previous,
            new=new,
            reason_evidence=(reason,),
        )
        self.store.add_supersession(supersession)
        self._suppress_source(reason_source.source_id, "suppress-reason")

        resolution_input = self.store.get_lineage_resolution_input(
            self.thread.thread_id
        )
        result = resolve_lineage(resolution_input=resolution_input)

        self.assertEqual(
            resolution_input.supersession_edges,
            frozenset({("reason-a", "reason-b")}),
        )
        self.assertEqual(
            resolution_input.blocked_supersession_edges,
            frozenset({("reason-a", "reason-b")}),
        )
        self.assertEqual(result.structural_head_ids, frozenset({"reason-b"}))
        self.assertEqual(result.support_status, "blocked")
        self.assertEqual(result.decision, "unresolved")

    def test_empty_thread_returns_no_candidate(self) -> None:
        result = self._resolve()

        self.assertEqual(result.structural_state, "empty")
        self.assertEqual(result.structural_head_ids, frozenset())
        self.assertEqual(result.support_status, "not_applicable")
        self.assertEqual(result.decision, "no_candidate")
        self.assertEqual(result.candidate_ids, frozenset())
        self.assertEqual(result.reason_codes, ("EMPTY_THREAD",))

    def test_resolution_input_rejects_known_edge_escaping_thread(self) -> None:
        left = self._stored_interpretation("escape-left")
        self._admit(left)

        other_thread = create_interpretation_thread(
            question="Other question",
            perspective_owner="lior",
            perspective_instance_id="lior-window-resolution",
            about_subject="vivi",
            scope="shared",
        )
        self.store.add_thread(other_thread)
        right = self._stored_interpretation("escape-right")
        self.store.admit_interpretation(
            create_thread_admission(
                thread=other_thread,
                interpretation=right,
                admitted_by_instance_id="lior-window-resolution",
            )
        )

        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                INSERT INTO supersessions (
                    previous_interpretation_id,
                    new_interpretation_id
                )
                VALUES (?, ?)
                """,
                (left.interpretation_id, right.interpretation_id),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(LineageIntegrityError):
            self.store.get_lineage_resolution_input(self.thread.thread_id)

    def test_missing_interpretation_evidence_is_integrity_error(self) -> None:
        interpretation = self._stored_interpretation("missing-evidence")
        self._admit(interpretation)

        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "DELETE FROM interpretation_evidence WHERE interpretation_id = ?",
                (interpretation.interpretation_id,),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(LineageIntegrityError):
            self.store.get_lineage_resolution_input(self.thread.thread_id)

    def test_missing_revision_evidence_is_integrity_error(self) -> None:
        a = self._stored_interpretation("missing-reason-a")
        b = self._stored_interpretation("missing-reason-b")
        self._admit(a, b)
        self._supersede(a, b)

        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                """
                DELETE FROM supersession_evidence
                WHERE previous_interpretation_id = ?
                  AND new_interpretation_id = ?
                """,
                (a.interpretation_id, b.interpretation_id),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(LineageIntegrityError):
            self.store.get_lineage_resolution_input(self.thread.thread_id)

    def test_hand_built_partial_input_cannot_claim_store_completeness(self) -> None:
        partial = LineageResolutionInput(
            thread_id=self.thread.thread_id,
            interpretation_ids=frozenset({"only-visible-member"}),
            supersession_edges=frozenset(),
            blocked_interpretation_ids=frozenset(),
            blocked_supersession_edges=frozenset(),
            _assembly_marker=object(),
        )

        with self.assertRaises(LineageIntegrityError):
            resolve_lineage(resolution_input=partial)

    def test_resolution_snapshot_uses_explicit_query_only_transaction(self) -> None:
        class InspectingStore(MemoryStore):
            saw_explicit_transaction = False
            saw_query_only = False

            def _build_lineage_resolution_input_from_connection(
                self,
                *,
                connection,
                thread_id,
            ):
                self.saw_explicit_transaction = connection.in_transaction
                self.saw_query_only = bool(
                    connection.execute("PRAGMA query_only").fetchone()[0]
                )
                return super()._build_lineage_resolution_input_from_connection(
                    connection=connection,
                    thread_id=thread_id,
                )

        inspecting_store = InspectingStore(self.db_path)
        inspecting_store.get_lineage_resolution_input(self.thread.thread_id)

        self.assertTrue(inspecting_store.saw_explicit_transaction)
        self.assertTrue(inspecting_store.saw_query_only)

    def test_resolution_input_assembly_does_not_read_memory_payload(self) -> None:
        interpretation = self._stored_interpretation("payload-free")
        self._admit(interpretation)

        def payload_read_forbidden(*args, **kwargs):
            raise AssertionError("resolution input must not read payload")

        self.store._get_interpretation_from_connection = payload_read_forbidden
        self.store._get_source_from_connection = payload_read_forbidden

        resolution_input = self.store.get_lineage_resolution_input(
            self.thread.thread_id
        )

        self.assertEqual(
            resolution_input.interpretation_ids,
            frozenset({"payload-free"}),
        )

    def _resolve(self):
        return resolve_lineage(
            resolution_input=self.store.get_lineage_resolution_input(
                self.thread.thread_id
            )
        )

    def _stored_interpretation(self, interpretation_id):
        source = create_source_record(
            source_id=f"source-{interpretation_id}",
            content=f"Evidence for {interpretation_id}.",
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
            text=f"Interpretation {interpretation_id}.",
            perspective_owner="lior",
            perspective_instance_id="lior-window-resolution",
            about_subject="vivi",
            scope="shared",
            evidence=(evidence,),
        )
        self.store.add_interpretation(interpretation)
        return interpretation

    def _admit(self, *interpretations) -> None:
        for interpretation in interpretations:
            self.store.admit_interpretation(
                create_thread_admission(
                    thread=self.thread,
                    interpretation=interpretation,
                    admitted_by_instance_id="lior-window-resolution",
                )
            )

    def _supersede(self, previous, new) -> None:
        self.store.add_supersession(
            create_supersession_record(
                previous=previous,
                new=new,
                reason_evidence=new.evidence,
            )
        )

    def _suppress_evidence(self, interpretation, suppression_id) -> None:
        self._suppress_source(
            interpretation.evidence[0].source_id,
            suppression_id,
        )

    def _suppress_source(self, source_id, suppression_id) -> None:
        self.store.suppress_source(
            create_suppression_record(
                suppression_id=suppression_id,
                source_id=source_id,
                requested_by="vivi",
                reason="Stop using this source for memory work.",
            )
        )


if __name__ == "__main__":
    unittest.main()
