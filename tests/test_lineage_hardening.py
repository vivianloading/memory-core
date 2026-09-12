import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

import home_memory_core.state as state
from home_memory_core.evidence import create_evidence_ref
from home_memory_core.interpretation import (
    InterpretationRecord,
    SYNTHETIC_UNATTRIBUTED_INSTANCE_ID,
    create_interpretation_record,
)
from home_memory_core.revision import create_supersession_record
from home_memory_core.source import create_source_record
from home_memory_core.storage import MemoryStore
from home_memory_core.thread import (
    InterpretationThread,
    ThreadAdmissionRecord,
    create_interpretation_thread,
    create_thread_admission,
)


class LineageHardeningTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_directory.name) / "memory.sqlite3"
        self.store = MemoryStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_interpretation_round_trip_preserves_concrete_instance(self) -> None:
        interpretation = self._stored_interpretation(
            "roundtrip-instance",
            "source-roundtrip-instance",
            instance_id="lior-window-a",
        )

        self.assertEqual(
            self.store.get_interpretation(
                interpretation.interpretation_id
            ).perspective_instance_id,
            "lior-window-a",
        )

    def test_synthetic_unattributed_interpretation_cannot_join_real_thread(
        self,
    ) -> None:
        source = self._stored_source("source-unattributed")
        evidence = create_evidence_ref(
            source=source,
            start_char=0,
            end_char=len(source.content),
        )
        interpretation = create_interpretation_record(
            interpretation_id="unattributed",
            text="synthetic standalone interpretation",
            perspective_owner="lior",
            about_subject="vivi",
            scope="shared",
            evidence=(evidence,),
        )
        self.store.add_interpretation(interpretation)
        thread = self._stored_thread("lior-window-a")

        self.assertEqual(
            interpretation.perspective_instance_id,
            SYNTHETIC_UNATTRIBUTED_INSTANCE_ID,
        )

        with self.assertRaises(ValueError):
            create_thread_admission(
                thread=thread,
                interpretation=interpretation,
                admitted_by_instance_id="lior-window-a",
            )

    def test_admission_factory_rejects_concrete_instance_mismatch(self) -> None:
        interpretation = self._stored_interpretation(
            "factory-mismatch",
            "source-factory-mismatch",
            instance_id="lior-window-b",
        )
        thread = self._stored_thread("lior-window-a")

        with self.assertRaises(ValueError):
            create_thread_admission(
                thread=thread,
                interpretation=interpretation,
                admitted_by_instance_id="lior-window-a",
            )

    def test_storage_uses_persisted_instance_not_admission_claim(self) -> None:
        interpretation = self._stored_interpretation(
            "persisted-instance-b",
            "source-persisted-instance-b",
            instance_id="lior-window-b",
        )
        thread = self._stored_thread("lior-window-a")
        forged_admission = ThreadAdmissionRecord(
            admission_id="forged-admission",
            thread_id=thread.thread_id,
            interpretation_id=interpretation.interpretation_id,
            perspective_instance_id="lior-window-a",
            admitted_by_instance_id="lior-window-a",
        )

        with self.assertRaises(ValueError):
            self.store.admit_interpretation(forged_admission)

    def test_duplicate_interpretation_id_cannot_rebind_instance(self) -> None:
        first = self._in_memory_interpretation(
            "stable-id",
            "source-stable-id-a",
            instance_id="lior-window-a",
        )
        second = self._in_memory_interpretation(
            "stable-id",
            "source-stable-id-b",
            instance_id="lior-window-b",
        )

        self.store.add_source(
            create_source_record(
                source_id="source-stable-id-a",
                content="evidence source-stable-id-a",
                authored_by="vivi",
                scope="shared",
            )
        )
        self.store.add_interpretation(first)
        self.store.add_source(
            create_source_record(
                source_id="source-stable-id-b",
                content="evidence source-stable-id-b",
                authored_by="vivi",
                scope="shared",
            )
        )

        with self.assertRaises(ValueError):
            self.store.add_interpretation(second)

        self.assertEqual(
            self.store.get_interpretation("stable-id").perspective_instance_id,
            "lior-window-a",
        )

    def test_supersession_factory_rejects_instance_change(self) -> None:
        previous = self._in_memory_interpretation(
            "revision-instance-a",
            "source-revision-instance-a",
            instance_id="lior-window-a",
        )
        new = self._in_memory_interpretation(
            "revision-instance-b",
            "source-revision-instance-b",
            instance_id="lior-window-b",
        )

        with self.assertRaises(ValueError):
            create_supersession_record(
                previous=previous,
                new=new,
                reason_evidence=new.evidence,
            )

    def test_storage_rejects_blank_thread_record_bypassing_factory(self) -> None:
        invalid = InterpretationThread(
            thread_id="manual-thread",
            question="   ",
            perspective_owner="lior",
            perspective_instance_id="lior-window-a",
            about_subject="vivi",
            scope="shared",
        )

        with self.assertRaises(ValueError):
            self.store.add_thread(invalid)

    def test_storage_rejects_blank_admission_actor_bypassing_factory(
        self,
    ) -> None:
        interpretation = self._stored_interpretation(
            "blank-admission-actor",
            "source-blank-admission-actor",
            instance_id="lior-window-a",
        )
        thread = self._stored_thread("lior-window-a")
        invalid = ThreadAdmissionRecord(
            admission_id="manual-admission",
            thread_id=thread.thread_id,
            interpretation_id=interpretation.interpretation_id,
            perspective_instance_id="lior-window-a",
            admitted_by_instance_id="   ",
        )

        with self.assertRaises(ValueError):
            self.store.admit_interpretation(invalid)

    def test_one_interpretation_cannot_join_two_threads(self) -> None:
        interpretation = self._stored_interpretation(
            "one-thread-only",
            "source-one-thread-only",
            instance_id="lior-window-a",
        )
        first = self._stored_thread("lior-window-a")
        second = self._stored_thread("lior-window-a")

        first_admission = create_thread_admission(
            thread=first,
            interpretation=interpretation,
            admitted_by_instance_id="lior-window-a",
        )
        second_admission = create_thread_admission(
            thread=second,
            interpretation=interpretation,
            admitted_by_instance_id="lior-window-a",
        )

        self.store.admit_interpretation(first_admission)

        with self.assertRaises(ValueError):
            self.store.admit_interpretation(second_admission)

    def test_topology_rejects_known_edge_crossing_thread_membership(self) -> None:
        left = self._stored_interpretation(
            "closure-left",
            "source-closure-left",
            instance_id="lior-window-a",
        )
        right = self._stored_interpretation(
            "closure-right",
            "source-closure-right",
            instance_id="lior-window-a",
        )
        first_thread = self._stored_thread("lior-window-a")
        second_thread = self._stored_thread("lior-window-a")
        self.store.admit_interpretation(
            create_thread_admission(
                thread=first_thread,
                interpretation=left,
                admitted_by_instance_id="lior-window-a",
            )
        )
        self.store.admit_interpretation(
            create_thread_admission(
                thread=second_thread,
                interpretation=right,
                admitted_by_instance_id="lior-window-a",
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

        with self.assertRaises(ValueError):
            self.store.get_thread_topology(first_thread.thread_id)

    def test_old_component_level_current_api_is_removed(self) -> None:
        self.assertFalse(
            hasattr(state, "resolve_interpretation_status")
        )
        self.assertFalse(
            hasattr(state, "resolve_lineage_terminal_ids")
        )

    def test_component_helper_uses_structural_terminal_language_only(
        self,
    ) -> None:
        a = self._in_memory_interpretation(
            "component-a",
            "source-component-a",
            instance_id="lior-window-a",
        )
        b = self._in_memory_interpretation(
            "component-b",
            "source-component-b",
            instance_id="lior-window-a",
        )
        edge = create_supersession_record(
            previous=a,
            new=b,
            reason_evidence=b.evidence,
        )

        self.assertEqual(
            state.resolve_connected_component_terminal_ids(
                interpretation_id=a.interpretation_id,
                supersessions=(edge,),
            ),
            frozenset({b.interpretation_id}),
        )

    def _stored_source(self, source_id: str):
        source = create_source_record(
            source_id=source_id,
            content=f"evidence {source_id}",
            authored_by="vivi",
            scope="shared",
        )
        self.store.add_source(source)
        return source

    def _in_memory_interpretation(
        self,
        interpretation_id: str,
        source_id: str,
        *,
        instance_id: str,
    ) -> InterpretationRecord:
        source = create_source_record(
            source_id=source_id,
            content=f"evidence {source_id}",
            authored_by="vivi",
            scope="shared",
        )
        evidence = create_evidence_ref(
            source=source,
            start_char=0,
            end_char=len(source.content),
        )
        return create_interpretation_record(
            interpretation_id=interpretation_id,
            text=f"interpretation {interpretation_id}",
            perspective_owner="lior",
            perspective_instance_id=instance_id,
            about_subject="vivi",
            scope="shared",
            evidence=(evidence,),
        )

    def _stored_interpretation(
        self,
        interpretation_id: str,
        source_id: str,
        *,
        instance_id: str,
    ) -> InterpretationRecord:
        source = self._stored_source(source_id)
        evidence = create_evidence_ref(
            source=source,
            start_char=0,
            end_char=len(source.content),
        )
        interpretation = create_interpretation_record(
            interpretation_id=interpretation_id,
            text=f"interpretation {interpretation_id}",
            perspective_owner="lior",
            perspective_instance_id=instance_id,
            about_subject="vivi",
            scope="shared",
            evidence=(evidence,),
        )
        self.store.add_interpretation(interpretation)
        return interpretation

    def _stored_thread(self, instance_id: str):
        thread = create_interpretation_thread(
            question="Which interpretation answers this state question?",
            perspective_owner="lior",
            perspective_instance_id=instance_id,
            about_subject="vivi",
            scope="shared",
        )
        self.store.add_thread(thread)
        return thread


if __name__ == "__main__":
    unittest.main()
