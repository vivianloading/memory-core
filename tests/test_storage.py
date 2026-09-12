import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from home_memory_core.evidence import (
    EvidenceRef,
    create_evidence_ref,
)
from home_memory_core.interpretation import (
    create_interpretation_record,
)
from home_memory_core.revision import (
    SupersessionRecord,
    create_supersession_record,
)
from home_memory_core.source import create_source_record
from home_memory_core.storage import MemoryStore
from home_memory_core.thread import (
    create_interpretation_thread,
    create_thread_admission,
)


class MemoryStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temp_directory.name)
            / "memory.sqlite3"
        )

        self.store = MemoryStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_source_round_trip_preserves_exact_record(self) -> None:
        source = create_source_record(
            source_id="stored-message-001",
            content="这句话会真正落进 SQLite。",
            authored_by="vivi",
            scope="shared",
        )

        self.store.add_source(source)

        loaded = self.store.get_source(source.source_id)

        self.assertEqual(loaded, source)

    def test_duplicate_source_id_cannot_overwrite_raw_history(
        self,
    ) -> None:
        original = create_source_record(
            source_id="stored-message-002",
            content="这是原始内容。",
            authored_by="vivi",
            scope="shared",
        )

        replacement = create_source_record(
            source_id="stored-message-002",
            content="这是试图覆盖原文的新内容。",
            authored_by="vivi",
            scope="shared",
        )

        self.store.add_source(original)

        with self.assertRaises(ValueError):
            self.store.add_source(replacement)

        self.assertEqual(
            self.store.get_source("stored-message-002"),
            original,
        )

    def test_interpretation_round_trip_preserves_ordered_evidence(
        self,
    ) -> None:
        source = create_source_record(
            source_id="stored-message-003",
            content="第一段证据。中间。第二段证据。",
            authored_by="vivi",
            scope="shared",
        )

        self.store.add_source(source)

        first_text = "第一段证据"
        first_start = source.content.index(first_text)

        second_text = "第二段证据"
        second_start = source.content.index(second_text)

        first_evidence = create_evidence_ref(
            source=source,
            start_char=first_start,
            end_char=first_start + len(first_text),
        )

        second_evidence = create_evidence_ref(
            source=source,
            start_char=second_start,
            end_char=second_start + len(second_text),
        )

        interpretation = create_interpretation_record(
            interpretation_id="stored-interpretation-001",
            text="这是一个有两段依据的理解。",
            perspective_owner="lior",
            about_subject="vivi",
            scope="shared",
            evidence=(
                first_evidence,
                second_evidence,
            ),
        )

        self.store.add_interpretation(interpretation)

        loaded = self.store.get_interpretation(
            interpretation.interpretation_id
        )

        self.assertEqual(loaded, interpretation)

    def test_interpretation_rejects_missing_source(
        self,
    ) -> None:
        source = create_source_record(
            source_id="stored-message-004",
            content="这条 source 故意不存进数据库。",
            authored_by="vivi",
            scope="shared",
        )

        evidence = create_evidence_ref(
            source=source,
            start_char=0,
            end_char=len(source.content),
        )

        interpretation = create_interpretation_record(
            interpretation_id="stored-interpretation-002",
            text="不能建立在数据库不存在的 source 上。",
            perspective_owner="lior",
            perspective_instance_id="lior-window-test",
            about_subject="vivi",
            scope="shared",
            evidence=(evidence,),
        )

        with self.assertRaises(ValueError):
            self.store.add_interpretation(interpretation)

        with self.assertRaises(KeyError):
            self.store.get_interpretation(
                interpretation.interpretation_id
            )

    def test_interpretation_rejects_wrong_source_hash(
        self,
    ) -> None:
        source = create_source_record(
            source_id="stored-message-005",
            content="数据库里真正保存的是这一版。",
            authored_by="vivi",
            scope="shared",
        )

        self.store.add_source(source)

        forged_evidence = EvidenceRef(
            source_id=source.source_id,
            source_sha256="0" * 64,
            start_char=0,
            end_char=len(source.content),
        )

        interpretation = create_interpretation_record(
            interpretation_id="stored-interpretation-003",
            text="这条理解带着错误的 source fingerprint。",
            perspective_owner="lior",
            about_subject="vivi",
            scope="shared",
            evidence=(forged_evidence,),
        )

        with self.assertRaises(ValueError):
            self.store.add_interpretation(interpretation)

    def test_supersession_round_trip_preserves_reason_evidence(
        self,
    ) -> None:
        old = self._stored_interpretation(
            interpretation_id="stored-interpretation-004",
            source_id="stored-message-006",
            source_text="Vivi 今天看起来很安静。",
            interpretation_text="Vivi 可能心情不好。",
            perspective_owner="lior",
            about_subject="vivi",
        )

        new = self._stored_interpretation(
            interpretation_id="stored-interpretation-005",
            source_id="stored-message-007",
            source_text="我只是困，没有不开心。",
            interpretation_text=(
                "Vivi 当时安静主要是因为困。"
            ),
            perspective_owner="lior",
            about_subject="vivi",
        )

        self._admit_same_thread(old, new)

        supersession = create_supersession_record(
            previous=old,
            new=new,
            reason_evidence=new.evidence,
        )

        self.store.add_supersession(supersession)

        self.assertEqual(
            self.store.get_supersessions(),
            (supersession,),
        )

    def test_storage_rejects_revision_cycle(
        self,
    ) -> None:
        interpretation_a = self._stored_interpretation(
            interpretation_id="stored-interpretation-006",
            source_id="stored-message-008",
            source_text="A 的证据。",
            interpretation_text="A。",
            perspective_owner="lior",
            about_subject="vivi",
        )

        interpretation_b = self._stored_interpretation(
            interpretation_id="stored-interpretation-007",
            source_id="stored-message-009",
            source_text="B 的证据。",
            interpretation_text="B。",
            perspective_owner="lior",
            about_subject="vivi",
        )

        self._admit_same_thread(
            interpretation_a,
            interpretation_b,
        )

        a_to_b = create_supersession_record(
            previous=interpretation_a,
            new=interpretation_b,
            reason_evidence=interpretation_b.evidence,
        )

        b_to_a = create_supersession_record(
            previous=interpretation_b,
            new=interpretation_a,
            reason_evidence=interpretation_a.evidence,
        )

        self.store.add_supersession(a_to_b)

        with self.assertRaises(ValueError):
            self.store.add_supersession(b_to_a)

        self.assertEqual(
            self.store.get_supersessions(),
            (a_to_b,),
        )

    def test_storage_enforces_perspective_boundary(
        self,
    ) -> None:
        lior_interpretation = self._stored_interpretation(
            interpretation_id="stored-interpretation-008",
            source_id="stored-message-010",
            source_text="共享证据 A。",
            interpretation_text="Lior 的理解。",
            perspective_owner="lior",
            about_subject="vivi",
        )

        miro_interpretation = self._stored_interpretation(
            interpretation_id="stored-interpretation-009",
            source_id="stored-message-011",
            source_text="共享证据 B。",
            interpretation_text="Miro 的理解。",
            perspective_owner="miro",
            about_subject="vivi",
        )

        invalid_supersession = SupersessionRecord(
            previous_interpretation_id=(
                lior_interpretation.interpretation_id
            ),
            new_interpretation_id=(
                miro_interpretation.interpretation_id
            ),
            reason_evidence=miro_interpretation.evidence,
        )

        with self.assertRaises(ValueError):
            self.store.add_supersession(
                invalid_supersession
            )

    def _admit_same_thread(self, *interpretations) -> None:
        first = interpretations[0]

        thread = create_interpretation_thread(
            question="测试：这些 interpretation 是否在修订同一件事？",
            perspective_owner=first.perspective_owner,
            perspective_instance_id="lior-window-test",
            about_subject=first.about_subject,
            scope=first.scope,
        )
        self.store.add_thread(thread)

        for interpretation in interpretations:
            admission = create_thread_admission(
                thread=thread,
                interpretation=interpretation,
                admitted_by_instance_id="lior-window-test",
            )
            self.store.admit_interpretation(admission)

    def _stored_interpretation(
        self,
        *,
        interpretation_id,
        source_id,
        source_text,
        interpretation_text,
        perspective_owner,
        about_subject,
    ):
        source = create_source_record(
            source_id=source_id,
            content=source_text,
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
            text=interpretation_text,
            perspective_owner=perspective_owner,
            perspective_instance_id="lior-window-test",
            about_subject=about_subject,
            scope="shared",
            evidence=(evidence,),
        )

        self.store.add_interpretation(interpretation)

        return interpretation


if __name__ == "__main__":
    unittest.main()
