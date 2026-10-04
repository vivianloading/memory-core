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
from home_memory_core.revision import create_supersession_record
from home_memory_core.source import create_source_record
from home_memory_core.storage import MemoryStore
from home_memory_core.thread import (
    create_interpretation_thread,
    create_thread_admission,
)
from home_memory_core.suppression import (
    SuppressedMemoryError,
    SuppressionLedgerIntegrityError,
)


class SuppressionStorageTest(unittest.TestCase):
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

    def test_suppression_round_trip_preserves_audit_record(self) -> None:
        source = create_source_record(
            source_id="stored-message-012",
            content="这段 source 会被停止使用。",
            authored_by="vivi",
            scope="shared",
        )
        self.store.add_source(source)

        suppression = create_suppression_record(
            suppression_id="stored-suppression-001",
            source_id=source.source_id,
            requested_by="vivi",
            reason="不要再让这段 source 参与记忆工作。",
        )

        self.store.suppress_source(suppression)

        self.assertEqual(
            self.store.get_suppressions(),
            (suppression,),
        )
        self.assertFalse(
            self.store.is_source_usable(source.source_id)
        )
        with self.assertRaises(SuppressedMemoryError):
            self.store.get_source(source.source_id)

        self.assertEqual(
            self.store.get_source_for_audit(source.source_id),
            source,
        )

    def test_duplicate_source_suppression_is_rejected(self) -> None:
        source = create_source_record(
            source_id="stored-message-013",
            content="这段 source 只需要一张 active stop-use 记录。",
            authored_by="vivi",
            scope="shared",
        )
        self.store.add_source(source)

        first = create_suppression_record(
            suppression_id="stored-suppression-002",
            source_id=source.source_id,
            requested_by="vivi",
            reason="第一次停止使用。",
        )
        second = create_suppression_record(
            suppression_id="stored-suppression-003",
            source_id=source.source_id,
            requested_by="vivi",
            reason="不应该写入第二张 active 记录。",
        )

        self.store.suppress_source(first)

        with self.assertRaises(ValueError):
            self.store.suppress_source(second)

        self.assertEqual(
            self.store.get_suppressions(),
            (first,),
        )

    def test_existing_interpretation_becomes_unusable_after_suppression(
        self,
    ) -> None:
        interpretation = self._stored_interpretation(
            interpretation_id="stored-interpretation-010",
            source_id="stored-message-014",
            source_text="这段证据先被使用，后来被停止使用。",
            interpretation_text="这条旧理解仍留在历史里。",
        )

        self.assertTrue(
            self.store.is_interpretation_usable(
                interpretation.interpretation_id
            )
        )

        suppression = create_suppression_record(
            suppression_id="stored-suppression-004",
            source_id=interpretation.evidence[0].source_id,
            requested_by="vivi",
            reason="停止让这段 source 支撑 derived memory。",
        )
        self.store.suppress_source(suppression)

        self.assertFalse(
            self.store.is_interpretation_usable(
                interpretation.interpretation_id
            )
        )
        with self.assertRaises(SuppressedMemoryError):
            self.store.get_interpretation(
                interpretation.interpretation_id
            )

        self.assertEqual(
            self.store.get_interpretation_for_audit(
                interpretation.interpretation_id
            ),
            interpretation,
        )

    def test_new_interpretation_from_suppressed_source_is_rejected(
        self,
    ) -> None:
        source = create_source_record(
            source_id="stored-message-015",
            content="这段 source 已经停止使用。",
            authored_by="vivi",
            scope="shared",
        )
        self.store.add_source(source)

        suppression = create_suppression_record(
            suppression_id="stored-suppression-005",
            source_id=source.source_id,
            requested_by="vivi",
            reason="不要从它继续生成新的理解。",
        )
        self.store.suppress_source(suppression)

        evidence = create_evidence_ref(
            source=source,
            start_char=0,
            end_char=len(source.content),
        )
        interpretation = create_interpretation_record(
            interpretation_id="stored-interpretation-011",
            text="这条新理解不应该被写入。",
            perspective_owner="lior",
            perspective_instance_id="lior-window-test",
            about_subject="vivi",
            scope="shared",
            evidence=(evidence,),
        )

        with self.assertRaises(SuppressedMemoryError):
            self.store.add_interpretation(interpretation)

        with self.assertRaises(KeyError):
            self.store.get_interpretation(
                interpretation.interpretation_id
            )

    def test_interpretation_write_holds_lock_across_suppression_decision(
        self,
    ) -> None:
        source = create_source_record(
            source_id="stored-message-interpretation-race",
            content="这段 source 已经停止使用。",
            authored_by="vivi",
            scope="shared",
        )
        self.store.add_source(source)
        suppression = create_suppression_record(
            suppression_id="stored-suppression-interpretation-race",
            source_id=source.source_id,
            requested_by="vivi",
            reason="derived write 必须和 stop-use 决策属于同一个数据库现实。",
        )
        self.store.suppress_source(suppression)

        evidence = create_evidence_ref(
            source=source,
            start_char=0,
            end_char=len(source.content),
        )
        interpretation = create_interpretation_record(
            interpretation_id="stored-interpretation-race",
            text="这条 derived memory 不应该被写入。",
            perspective_owner="lior",
            perspective_instance_id="lior-window-test",
            about_subject="vivi",
            scope="shared",
            evidence=(evidence,),
        )

        observed_transactions = []
        concurrent_damage_errors = []
        db_path = self.db_path

        class InspectingStore(MemoryStore):
            def _get_suppressed_source_ids_from_connection(
                nested_self,
                *,
                connection,
            ):
                observed_transactions.append(connection.in_transaction)
                damage = sqlite3.connect(db_path, timeout=0)
                try:
                    damage.execute("PRAGMA foreign_keys=OFF")
                    damage.execute(
                        "DROP TRIGGER source_suppressions_no_delete"
                    )
                    damage.execute(
                        """
                        DELETE FROM source_suppressions
                        WHERE suppression_id=?
                        """,
                        (suppression.suppression_id,),
                    )
                    damage.commit()
                except Exception as error:
                    concurrent_damage_errors.append(error)
                    damage.rollback()
                finally:
                    damage.close()

                return super()._get_suppressed_source_ids_from_connection(
                    connection=connection,
                )

        inspecting = InspectingStore(self.db_path)
        with self.assertRaises(SuppressedMemoryError):
            inspecting.add_interpretation(interpretation)

        self.assertEqual(observed_transactions, [True])
        self.assertEqual(len(concurrent_damage_errors), 1)
        self.assertIsInstance(
            concurrent_damage_errors[0],
            sqlite3.OperationalError,
        )

        check = sqlite3.connect(self.db_path)
        try:
            suppression_count = check.execute(
                """
                SELECT count(*) FROM source_suppressions
                WHERE suppression_id=?
                """,
                (suppression.suppression_id,),
            ).fetchone()[0]
            guard_count = check.execute(
                """
                SELECT count(*) FROM sqlite_master
                WHERE type='trigger'
                  AND name='source_suppressions_no_delete'
                """
            ).fetchone()[0]
            interpretation_count = check.execute(
                """
                SELECT count(*) FROM interpretations
                WHERE interpretation_id=?
                """,
                (interpretation.interpretation_id,),
            ).fetchone()[0]
        finally:
            check.close()

        self.assertEqual(suppression_count, 1)
        self.assertEqual(guard_count, 1)
        self.assertEqual(interpretation_count, 0)

    def test_existing_supersession_becomes_unusable_after_suppression(
        self,
    ) -> None:
        previous = self._stored_interpretation(
            interpretation_id="stored-interpretation-012",
            source_id="stored-message-016",
            source_text="旧证据。",
            interpretation_text="旧理解。",
        )
        new = self._stored_interpretation(
            interpretation_id="stored-interpretation-013",
            source_id="stored-message-017",
            source_text="新证据。",
            interpretation_text="新理解。",
        )

        self._admit_same_thread(previous, new)

        supersession = create_supersession_record(
            previous=previous,
            new=new,
            reason_evidence=new.evidence,
        )
        self.store.add_supersession(supersession)

        self.assertTrue(
            self.store.is_supersession_usable(
                previous_interpretation_id=(
                    previous.interpretation_id
                ),
                new_interpretation_id=new.interpretation_id,
            )
        )

        suppression = create_suppression_record(
            suppression_id="stored-suppression-006",
            source_id=new.evidence[0].source_id,
            requested_by="vivi",
            reason="停止使用支持新理解和修订关系的 source。",
        )
        self.store.suppress_source(suppression)

        self.assertFalse(
            self.store.is_supersession_usable(
                previous_interpretation_id=(
                    previous.interpretation_id
                ),
                new_interpretation_id=new.interpretation_id,
            )
        )

        self.assertEqual(
            self.store.get_supersessions(),
            (supersession,),
        )

    def test_new_supersession_using_suppressed_memory_is_rejected(
        self,
    ) -> None:
        previous = self._stored_interpretation(
            interpretation_id="stored-interpretation-014",
            source_id="stored-message-018",
            source_text="旧证据。",
            interpretation_text="旧理解。",
        )
        new = self._stored_interpretation(
            interpretation_id="stored-interpretation-015",
            source_id="stored-message-019",
            source_text="后来被停止使用的新证据。",
            interpretation_text="新理解。",
        )

        self._admit_same_thread(previous, new)

        suppression = create_suppression_record(
            suppression_id="stored-suppression-007",
            source_id=new.evidence[0].source_id,
            requested_by="vivi",
            reason="这段新证据不再允许推动 revision。",
        )
        self.store.suppress_source(suppression)

        supersession = create_supersession_record(
            previous=previous,
            new=new,
            reason_evidence=new.evidence,
        )

        with self.assertRaises(SuppressedMemoryError):
            self.store.add_supersession(supersession)

        self.assertEqual(
            self.store.get_supersessions(),
            (),
        )

    def test_damaged_suppression_ledger_fails_closed_at_source_use(self) -> None:
        source = create_source_record(
            source_id="stored-message-damaged-ledger",
            content="这段 source 已经停止使用，损坏后也不能复活。",
            authored_by="vivi",
            scope="shared",
        )
        self.store.add_source(source)
        suppression = create_suppression_record(
            suppression_id="stored-suppression-damaged-ledger",
            source_id=source.source_id,
            requested_by="vivi",
            reason="损坏的 stop-use ledger 不能变成使用许可。",
        )
        self.store.suppress_source(suppression)

        with sqlite3.connect(self.db_path) as connection:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute(
                "DROP TRIGGER source_suppressions_no_delete"
            )
            connection.execute(
                """
                DELETE FROM source_suppressions
                WHERE suppression_id=?
                """,
                (suppression.suppression_id,),
            )

        with self.assertRaises(SuppressionLedgerIntegrityError):
            self.store.is_source_usable(source.source_id)
        with self.assertRaises(SuppressionLedgerIntegrityError):
            self.store.get_source(source.source_id)

        self.assertEqual(
            self.store.get_source_for_audit(source.source_id),
            source,
        )

        evidence = create_evidence_ref(
            source=source,
            start_char=0,
            end_char=len(source.content),
        )
        interpretation = create_interpretation_record(
            interpretation_id="stored-interpretation-damaged-ledger",
            text="损坏的 suppression ledger 不能授权新的 derived memory。",
            perspective_owner="lior",
            perspective_instance_id="lior-window-test",
            about_subject="vivi",
            scope="shared",
            evidence=(evidence,),
        )
        with self.assertRaises(SuppressionLedgerIntegrityError):
            self.store.add_interpretation(interpretation)

    def test_suppression_survives_store_reopen(self) -> None:
        source = create_source_record(
            source_id="stored-message-020",
            content="关闭程序以后也不能复活。",
            authored_by="vivi",
            scope="shared",
        )
        self.store.add_source(source)

        suppression = create_suppression_record(
            suppression_id="stored-suppression-008",
            source_id=source.source_id,
            requested_by="vivi",
            reason="重启后仍然停止使用。",
        )
        self.store.suppress_source(suppression)

        reopened_store = MemoryStore(self.db_path)
        reopened_store.initialize()

        self.assertEqual(
            reopened_store.get_suppressions(),
            (suppression,),
        )
        self.assertFalse(
            reopened_store.is_source_usable(source.source_id)
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
            perspective_owner="lior",
            perspective_instance_id="lior-window-test",
            about_subject="vivi",
            scope="shared",
            evidence=(evidence,),
        )
        self.store.add_interpretation(interpretation)

        return interpretation


if __name__ == "__main__":
    unittest.main()