import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from home_memory_core.evidence import create_evidence_ref, read_evidence
from home_memory_core.interpretation import create_interpretation_record
from home_memory_core.revision import create_supersession_record
from home_memory_core.source import SourceRecord, create_source_record
from home_memory_core.state import validate_supersession_graph
from home_memory_core.storage import MemoryStore
from home_memory_core.suppression import (
    SuppressedMemoryError,
    create_suppression_record,
)
from home_memory_core.thread import (
    create_interpretation_thread,
    create_thread_admission,
)


class LineageFoundationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_directory.name) / "memory.sqlite3"
        self.store = MemoryStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_thread_ids_are_opaque_and_unique(self) -> None:
        first = self._thread(instance_id="lior-window-a")
        second = self._thread(instance_id="lior-window-a")

        self.assertTrue(first.thread_id.startswith("thread-"))
        self.assertNotEqual(first.thread_id, second.thread_id)

    def test_thread_rejects_blank_question(self) -> None:
        with self.assertRaises(ValueError):
            create_interpretation_thread(
                question="   ",
                perspective_owner="lior",
                perspective_instance_id="lior-window-a",
                about_subject="vivi",
                scope="shared",
            )

    def test_thread_admission_rejects_owner_mismatch(self) -> None:
        thread = self._thread(
            perspective_owner="lior",
            instance_id="lior-window-a",
        )
        interpretation = self._stored_interpretation(
            "i-owner-mismatch",
            "s-owner-mismatch",
            perspective_owner="miro",
        )

        with self.assertRaises(ValueError):
            create_thread_admission(
                thread=thread,
                interpretation=interpretation,
                admitted_by_instance_id="lior-window-a",
            )

    def test_interpretation_cannot_widen_evidence_scope(self) -> None:
        source = create_source_record(
            source_id="private-source",
            content="private evidence",
            authored_by="vivi",
            scope="private",
        )
        self.store.add_source(source)

        evidence = create_evidence_ref(
            source=source,
            start_char=0,
            end_char=len(source.content),
        )
        interpretation = create_interpretation_record(
            interpretation_id="shared-interpretation",
            text="derived text",
            perspective_owner="lior",
            perspective_instance_id="lior-window-a",
            about_subject="vivi",
            scope="shared",
            evidence=(evidence,),
        )

        with self.assertRaises(ValueError):
            self.store.add_interpretation(interpretation)

    def test_multiple_roots_can_exist_in_one_thread(self) -> None:
        first = self._stored_interpretation("root-a", "source-root-a")
        second = self._stored_interpretation("root-b", "source-root-b")
        thread = self._thread(instance_id="lior-window-a")
        self._admit(thread, first, second)

        topology = self.store.get_thread_topology(thread.thread_id)

        self.assertEqual(
            topology.interpretation_ids,
            frozenset({"root-a", "root-b"}),
        )
        self.assertEqual(topology.supersession_edges, frozenset())

    def test_cross_thread_supersession_is_rejected(self) -> None:
        previous = self._stored_interpretation("cross-a", "source-cross-a")
        new = self._stored_interpretation("cross-b", "source-cross-b")

        first_thread = self._thread(instance_id="lior-window-a")
        second_thread = self._thread(instance_id="lior-window-a")
        self._admit(first_thread, previous)
        self._admit(second_thread, new)

        supersession = create_supersession_record(
            previous=previous,
            new=new,
            reason_evidence=new.evidence,
        )

        with self.assertRaises(ValueError):
            self.store.add_supersession(supersession)

    def test_different_perspective_instances_cannot_share_revision_edge(
        self,
    ) -> None:
        previous = self._stored_interpretation(
            "instance-a",
            "source-instance-a",
            perspective_instance_id="lior-window-a",
        )
        new = self._stored_interpretation(
            "instance-b",
            "source-instance-b",
            perspective_instance_id="lior-window-b",
        )

        first_thread = self._thread(instance_id="lior-window-a")
        second_thread = self._thread(instance_id="lior-window-b")
        self._admit(first_thread, previous)
        self._admit(second_thread, new)

        with self.assertRaises(ValueError):
            create_supersession_record(
                previous=previous,
                new=new,
                reason_evidence=new.evidence,
            )

    def test_direct_fork_is_allowed_inside_one_thread(self) -> None:
        root = self._stored_interpretation("fork-a", "source-fork-a")
        left = self._stored_interpretation("fork-b", "source-fork-b")
        right = self._stored_interpretation("fork-c", "source-fork-c")
        thread = self._thread(instance_id="lior-window-a")
        self._admit(thread, root, left, right)

        a_to_b = create_supersession_record(
            previous=root,
            new=left,
            reason_evidence=left.evidence,
        )
        a_to_c = create_supersession_record(
            previous=root,
            new=right,
            reason_evidence=right.evidence,
        )

        self.store.add_supersession(a_to_b)
        self.store.add_supersession(a_to_c)

        topology = self.store.get_thread_topology(thread.thread_id)

        self.assertEqual(
            topology.supersession_edges,
            frozenset(
                {
                    ("fork-a", "fork-b"),
                    ("fork-a", "fork-c"),
                }
            ),
        )

    def test_graph_validator_rejects_implicit_merge(self) -> None:
        a = self._in_memory_interpretation("merge-a")
        b = self._in_memory_interpretation("merge-b")
        c = self._in_memory_interpretation("merge-c")
        d = self._in_memory_interpretation("merge-d")

        edges = (
            create_supersession_record(
                previous=a,
                new=b,
                reason_evidence=b.evidence,
            ),
            create_supersession_record(
                previous=a,
                new=c,
                reason_evidence=c.evidence,
            ),
            create_supersession_record(
                previous=b,
                new=d,
                reason_evidence=d.evidence,
            ),
            create_supersession_record(
                previous=c,
                new=d,
                reason_evidence=d.evidence,
            ),
        )

        with self.assertRaises(ValueError):
            validate_supersession_graph(supersessions=edges)

    def test_storage_rejects_second_parent_for_same_target(self) -> None:
        a = self._stored_interpretation("store-merge-a", "source-store-merge-a")
        b = self._stored_interpretation("store-merge-b", "source-store-merge-b")
        c = self._stored_interpretation("store-merge-c", "source-store-merge-c")
        d = self._stored_interpretation("store-merge-d", "source-store-merge-d")
        thread = self._thread(instance_id="lior-window-a")
        self._admit(thread, a, b, c, d)

        self.store.add_supersession(
            create_supersession_record(
                previous=a,
                new=b,
                reason_evidence=b.evidence,
            )
        )
        self.store.add_supersession(
            create_supersession_record(
                previous=a,
                new=c,
                reason_evidence=c.evidence,
            )
        )
        self.store.add_supersession(
            create_supersession_record(
                previous=b,
                new=d,
                reason_evidence=d.evidence,
            )
        )

        with self.assertRaises(ValueError):
            self.store.add_supersession(
                create_supersession_record(
                    previous=c,
                    new=d,
                    reason_evidence=d.evidence,
                )
            )

    def test_supersession_rejects_scope_change(self) -> None:
        previous = self._in_memory_interpretation(
            "scope-a",
            scope="private",
        )
        new = self._in_memory_interpretation(
            "scope-b",
            scope="shared",
        )

        with self.assertRaises(ValueError):
            create_supersession_record(
                previous=previous,
                new=new,
                reason_evidence=new.evidence,
            )

    def test_topology_remains_visible_without_suppressed_payload(self) -> None:
        interpretation = self._stored_interpretation(
            "topology-suppressed",
            "source-topology-suppressed",
        )
        thread = self._thread(instance_id="lior-window-a")
        self._admit(thread, interpretation)

        suppression = create_suppression_record(
            suppression_id="suppression-topology",
            source_id=interpretation.evidence[0].source_id,
            requested_by="vivi",
            reason="stop use",
        )
        self.store.suppress_source(suppression)

        with self.assertRaises(SuppressedMemoryError):
            self.store.get_interpretation(
                interpretation.interpretation_id
            )

        topology = self.store.get_thread_topology(thread.thread_id)
        self.assertEqual(
            topology.interpretation_ids,
            frozenset({interpretation.interpretation_id}),
        )

    def test_forged_source_hash_is_rejected_on_write(self) -> None:
        forged = SourceRecord(
            source_id="forged-source",
            content="real content",
            authored_by="vivi",
            scope="shared",
            content_sha256="0" * 64,
        )

        with self.assertRaises(ValueError):
            self.store.add_source(forged)

    def test_manual_content_tampering_is_detected_on_read(self) -> None:
        source = create_source_record(
            source_id="tampered-source",
            content="original",
            authored_by="vivi",
            scope="shared",
        )
        self.store.add_source(source)

        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                """
                UPDATE sources
                SET content = ?
                WHERE source_id = ?
                """,
                ("modified", source.source_id),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(ValueError):
            self.store.get_source_for_audit(source.source_id)

    def test_evidence_offsets_are_half_open_python_string_indices(self) -> None:
        source = create_source_record(
            source_id="unicode-source",
            content="A豆🙂B",
            authored_by="vivi",
            scope="shared",
        )
        evidence = create_evidence_ref(
            source=source,
            start_char=1,
            end_char=3,
        )

        self.assertEqual(
            read_evidence(source=source, evidence=evidence),
            "豆🙂",
        )

    def _thread(
        self,
        *,
        perspective_owner="lior",
        instance_id,
        about_subject="vivi",
        scope="shared",
    ):
        thread = create_interpretation_thread(
            question="What interpretation currently answers this one state question?",
            perspective_owner=perspective_owner,
            perspective_instance_id=instance_id,
            about_subject=about_subject,
            scope=scope,
        )
        self.store.add_thread(thread)
        return thread

    def _admit(self, thread, *interpretations) -> None:
        for interpretation in interpretations:
            admission = create_thread_admission(
                thread=thread,
                interpretation=interpretation,
                admitted_by_instance_id=thread.perspective_instance_id,
            )
            self.store.admit_interpretation(admission)

    def _stored_interpretation(
        self,
        interpretation_id,
        source_id,
        *,
        perspective_owner="lior",
        perspective_instance_id="lior-window-a",
        about_subject="vivi",
        scope="shared",
    ):
        source = create_source_record(
            source_id=source_id,
            content=f"evidence for {interpretation_id}",
            authored_by="vivi",
            scope=scope,
        )
        self.store.add_source(source)

        evidence = create_evidence_ref(
            source=source,
            start_char=0,
            end_char=len(source.content),
        )

        interpretation = create_interpretation_record(
            interpretation_id=interpretation_id,
            text=f"interpretation {interpretation_id}",
            perspective_owner=perspective_owner,
            perspective_instance_id=perspective_instance_id,
            about_subject=about_subject,
            scope=scope,
            evidence=(evidence,),
        )
        self.store.add_interpretation(interpretation)
        return interpretation

    def _in_memory_interpretation(
        self,
        interpretation_id,
        *,
        perspective_owner="lior",
        perspective_instance_id="lior-window-a",
        about_subject="vivi",
        scope="shared",
    ):
        source = create_source_record(
            source_id=f"source-{interpretation_id}",
            content=f"evidence for {interpretation_id}",
            authored_by="vivi",
            scope=scope,
        )
        evidence = create_evidence_ref(
            source=source,
            start_char=0,
            end_char=len(source.content),
        )
        return create_interpretation_record(
            interpretation_id=interpretation_id,
            text=f"interpretation {interpretation_id}",
            perspective_owner=perspective_owner,
            perspective_instance_id=perspective_instance_id,
            about_subject=about_subject,
            scope=scope,
            evidence=(evidence,),
        )


if __name__ == "__main__":
    unittest.main()
