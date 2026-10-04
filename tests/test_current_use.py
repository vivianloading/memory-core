import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from home_memory_core.current_store import CurrentSourceBinding, CurrentStore
from home_memory_core.current_use import (
    CurrentEffectSuppressedError,
    CurrentPresentUseStatus,
    CurrentPresentUseStore,
    CurrentUseEffectKind,
    _require_current_effect_usable,
)
from home_memory_core.current_view import (
    CurrentNamespace,
    CurrentStateEndEvent,
    CurrentStateKind,
    CurrentStateRecord,
    DowngradeRule,
    EndKind,
    SemanticChangeAuthority,
    ValidityRule,
)
from home_memory_core.evidence import create_evidence_ref
from home_memory_core.living_continuity import (
    EpisodeRecord,
    RoomAttachmentEvent,
    RoomRecord,
    RoomRouteKind,
)
from home_memory_core.living_store import LivingStore
from home_memory_core.source import create_source_record
from home_memory_core.storage import MemoryStore
from home_memory_core.suppression import (
    SuppressionLedgerIntegrityError,
    create_suppression_record,
)


UTC = timezone.utc


class CurrentPresentUseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "home.db"

        self.memory = MemoryStore(self.db)
        self.memory.initialize()

        self.living = LivingStore(self.db)
        self.living.initialize()
        self.living.add_room(RoomRecord(room_id="room-r"))
        self.living.add_episode(
            EpisodeRecord(
                episode_id="episode-a",
                perspective_instance_id="perspective-a",
                runtime_instance_id="runtime-a",
            )
        )
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-a",
                episode_id="episode-a",
                route_kind=RoomRouteKind.ATTACHED,
                room_id="room-r",
                basis="synthetic-current-use",
            )
        )

        self.current = CurrentStore(self.db)
        self.current.initialize()
        self.use = CurrentPresentUseStore(self.db)
        self.t0 = datetime(2026, 1, 1, 9, tzinfo=UTC)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def binding(self, source_ref: str) -> CurrentSourceBinding:
        source = create_source_record(
            source_id=f"src-{source_ref}",
            content=f"synthetic evidence for {source_ref}",
            authored_by="current-use-test",
            scope="room-r",
        )
        self.memory.add_source(source)
        return CurrentSourceBinding(
            source_ref=source_ref,
            evidence=create_evidence_ref(
                source=source,
                start_char=0,
                end_char=len(source.content),
            ),
        )

    def state(
        self,
        state_id: str,
        *,
        source_refs: tuple[str, ...] | None = None,
        supersedes_state_id: str | None = None,
    ) -> CurrentStateRecord:
        return CurrentStateRecord(
            state_id=state_id,
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key="project.status",
            state_kind=CurrentStateKind.PROJECT_STATUS,
            value=state_id,
            event_time=self.t0,
            recorded_at=self.t0,
            valid_from=self.t0,
            validity_rule=ValidityRule.DURABLE_UNTIL_CHANGED,
            downgrade_rule=DowngradeRule.NONE,
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id="episode-a",
            perspective_instance_id="perspective-a",
            source_refs=source_refs or (f"ref-{state_id}",),
            supersedes_state_id=supersedes_state_id,
        )

    def suppress(self, binding: CurrentSourceBinding, suppression_id: str) -> None:
        self.memory.suppress_source(
            create_suppression_record(
                suppression_id=suppression_id,
                source_id=binding.evidence.source_id,
                requested_by="synthetic-test",
                reason="stop present use",
            )
        )

    def test_state_history_remains_auditable_but_present_use_becomes_suppressed(self) -> None:
        record = self.state("state-a")
        binding = self.binding(record.source_refs[0])
        self.current.add_state_record(
            record=record,
            source_bindings=(binding,),
        )

        before = self.use.state_decision(record.state_id)
        self.assertEqual(before.status, CurrentPresentUseStatus.USABLE)
        self.assertEqual(before.blocks, ())

        self.suppress(binding, "stop-state-a")

        after = self.use.state_decision(record.state_id)
        self.assertEqual(after.status, CurrentPresentUseStatus.SUPPRESSED)
        self.assertEqual(
            (
                after.blocks[0].source_ref,
                after.blocks[0].source_id,
                after.blocks[0].suppression_id,
            ),
            (
                record.source_refs[0],
                binding.evidence.source_id,
                "stop-state-a",
            ),
        )

        audited = self.current.get_state_for_audit(record.state_id)
        self.assertEqual(audited.record, record)
        self.assertEqual(audited.source_bindings, (binding,))

    def test_end_event_suppression_does_not_mutate_target_state_history(self) -> None:
        record = self.state("state-a")
        state_binding = self.binding(record.source_refs[0])
        self.current.add_state_record(
            record=record,
            source_bindings=(state_binding,),
        )
        event = CurrentStateEndEvent(
            end_event_id="end-a",
            state_id=record.state_id,
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.EXPLICIT_END,
            reason="synthetic end",
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id="episode-a",
            perspective_instance_id="perspective-a",
            source_refs=("ref-end-a",),
        )
        end_binding = self.binding(event.source_refs[0])
        self.current.add_end_event(
            event=event,
            source_bindings=(end_binding,),
        )

        self.suppress(end_binding, "stop-end-a")

        self.assertEqual(
            self.use.state_decision(record.state_id).status,
            CurrentPresentUseStatus.USABLE,
        )
        self.assertEqual(
            self.use.end_event_decision(event.end_event_id).status,
            CurrentPresentUseStatus.SUPPRESSED,
        )
        self.assertEqual(
            self.current.get_end_event_for_audit(event.end_event_id).event,
            event,
        )

    def test_multiple_evidence_bindings_report_only_exact_suppression_blocks(self) -> None:
        record = self.state(
            "multi",
            source_refs=("ref-multi-a", "ref-multi-b"),
        )
        first = self.binding("ref-multi-a")
        second = self.binding("ref-multi-b")
        self.current.add_state_record(
            record=record,
            source_bindings=(first, second),
        )

        self.suppress(second, "stop-multi-b")
        decision = self.use.state_decision(record.state_id)

        self.assertEqual(decision.status, CurrentPresentUseStatus.SUPPRESSED)
        self.assertEqual(len(decision.blocks), 1)
        self.assertEqual(decision.blocks[0].source_ref, "ref-multi-b")
        self.assertEqual(decision.blocks[0].source_id, second.evidence.source_id)

    def test_parent_suppression_propagates_to_existing_superseding_child(self) -> None:
        parent = self.state("lineage-parent")
        parent_binding = self.binding(parent.source_refs[0])
        self.current.add_state_record(
            record=parent,
            source_bindings=(parent_binding,),
        )
        child = self.state(
            "lineage-child",
            supersedes_state_id=parent.state_id,
        )
        child_binding = self.binding(child.source_refs[0])
        self.current.add_state_record(
            record=child,
            source_bindings=(child_binding,),
        )

        self.suppress(parent_binding, "stop-lineage-parent")
        parent_decision = self.use.state_decision(parent.state_id)
        child_decision = self.use.state_decision(child.state_id)

        self.assertEqual(
            parent_decision.status,
            CurrentPresentUseStatus.SUPPRESSED,
        )
        self.assertEqual(
            child_decision.status,
            CurrentPresentUseStatus.SUPPRESSED,
        )
        self.assertEqual(len(child_decision.blocks), 1)
        inherited = child_decision.blocks[0]
        self.assertEqual(inherited.source_ref, parent.source_refs[0])
        self.assertEqual(inherited.source_id, parent_binding.evidence.source_id)
        self.assertEqual(inherited.suppression_id, "stop-lineage-parent")
        self.assertEqual(
            inherited.origin_effect_kind,
            CurrentUseEffectKind.STATE,
        )
        self.assertEqual(inherited.origin_effect_id, parent.state_id)

        self.assertEqual(
            tuple(item.record.state_id for item in self.current.list_states_for_audit()),
            ("lineage-child", "lineage-parent"),
        )

    def test_grandchild_reports_direct_and_inherited_suppression_blocks_in_order(self) -> None:
        root = self.state("multi-root")
        root_binding = self.binding(root.source_refs[0])
        self.current.add_state_record(
            record=root,
            source_bindings=(root_binding,),
        )
        child = self.state(
            "multi-child",
            supersedes_state_id=root.state_id,
        )
        child_binding = self.binding(child.source_refs[0])
        self.current.add_state_record(
            record=child,
            source_bindings=(child_binding,),
        )
        grandchild = self.state(
            "multi-grandchild",
            supersedes_state_id=child.state_id,
        )
        grandchild_binding = self.binding(grandchild.source_refs[0])
        self.current.add_state_record(
            record=grandchild,
            source_bindings=(grandchild_binding,),
        )

        self.suppress(root_binding, "stop-multi-root")
        self.suppress(child_binding, "stop-multi-child")

        decision = self.use.state_decision(grandchild.state_id)
        self.assertEqual(
            decision.status,
            CurrentPresentUseStatus.SUPPRESSED,
        )
        self.assertEqual(
            tuple(
                (
                    block.suppression_id,
                    block.origin_effect_id,
                    block.source_ref,
                )
                for block in decision.blocks
            ),
            (
                ("stop-multi-child", child.state_id, child.source_refs[0]),
                ("stop-multi-root", root.state_id, root.source_refs[0]),
            ),
        )

    def test_target_state_suppression_propagates_to_existing_end_event(self) -> None:
        state = self.state("target-state")
        state_binding = self.binding(state.source_refs[0])
        self.current.add_state_record(
            record=state,
            source_bindings=(state_binding,),
        )
        event = CurrentStateEndEvent(
            end_event_id="target-end",
            state_id=state.state_id,
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.EXPLICIT_END,
            reason="synthetic target end",
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id="episode-a",
            perspective_instance_id="perspective-a",
            source_refs=("ref-target-end",),
        )
        event_binding = self.binding(event.source_refs[0])
        self.current.add_end_event(
            event=event,
            source_bindings=(event_binding,),
        )

        self.suppress(state_binding, "stop-target-state")
        state_decision = self.use.state_decision(state.state_id)
        end_decision = self.use.end_event_decision(event.end_event_id)

        self.assertEqual(
            state_decision.status,
            CurrentPresentUseStatus.SUPPRESSED,
        )
        self.assertEqual(
            end_decision.status,
            CurrentPresentUseStatus.SUPPRESSED,
        )
        self.assertEqual(len(end_decision.blocks), 1)
        inherited = end_decision.blocks[0]
        self.assertEqual(inherited.source_ref, state.source_refs[0])
        self.assertEqual(
            inherited.origin_effect_kind,
            CurrentUseEffectKind.STATE,
        )
        self.assertEqual(inherited.origin_effect_id, state.state_id)
        self.assertEqual(
            self.current.get_end_event_for_audit(event.end_event_id).event,
            event,
        )

    def test_suppression_does_not_implicitly_resurrect_superseded_parent(self) -> None:
        parent = self.state("parent")
        parent_binding = self.binding(parent.source_refs[0])
        self.current.add_state_record(
            record=parent,
            source_bindings=(parent_binding,),
        )
        child = self.state(
            "child",
            supersedes_state_id=parent.state_id,
        )
        child_binding = self.binding(child.source_refs[0])
        self.current.add_state_record(
            record=child,
            source_bindings=(child_binding,),
        )

        self.suppress(child_binding, "stop-child")
        decisions = {
            decision.effect_id: decision
            for decision in self.use.list_decisions()
        }

        # Slice 3A reports eligibility for both immutable effects. It does not
        # rerun Current View with the child deleted and therefore does not
        # manufacture a fallback/resurrection decision for the parent.
        self.assertEqual(
            decisions[parent.state_id].status,
            CurrentPresentUseStatus.USABLE,
        )
        self.assertEqual(
            decisions[child.state_id].status,
            CurrentPresentUseStatus.SUPPRESSED,
        )
        self.assertEqual(
            tuple(item.record.state_id for item in self.current.list_states_for_audit()),
            ("child", "parent"),
        )

    def test_suppression_ledger_has_no_rowid_replace_channel(self) -> None:
        record = self.state("no-rowid-stop")
        binding = self.binding(record.source_refs[0])
        self.current.add_state_record(
            record=record,
            source_bindings=(binding,),
        )
        self.suppress(binding, "stop-no-rowid")

        connection = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute(
                    "SELECT rowid FROM source_suppressions"
                ).fetchall()
            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute(
                    """
                    INSERT OR REPLACE INTO source_suppressions (
                        rowid,suppression_id,source_id,requested_by,reason
                    ) VALUES (1,'replacement','other','other','replace')
                    """
                )
        finally:
            connection.close()

        decision = self.use.state_decision(record.state_id)
        self.assertEqual(
            decision.status,
            CurrentPresentUseStatus.SUPPRESSED,
        )
        self.assertEqual(decision.blocks[0].suppression_id, "stop-no-rowid")

    def test_known_legacy_suppression_table_migrates_without_resurrection(self) -> None:
        record = self.state("legacy-stop")
        binding = self.binding(record.source_refs[0])
        self.current.add_state_record(
            record=record,
            source_bindings=(binding,),
        )
        self.suppress(binding, "stop-legacy")

        connection = sqlite3.connect(self.db)
        try:
            for trigger in (
                "source_suppressions_no_replace",
                "source_suppressions_no_update",
                "source_suppressions_no_delete",
            ):
                connection.execute(f"DROP TRIGGER {trigger}")
            connection.execute(
                "ALTER TABLE source_suppressions "
                "RENAME TO source_suppressions_new_shape"
            )
            connection.execute(
                """
                CREATE TABLE source_suppressions (
                    suppression_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL UNIQUE,
                    requested_by TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    FOREIGN KEY (source_id)
                        REFERENCES sources(source_id)
                        ON DELETE RESTRICT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO source_suppressions (
                    suppression_id,source_id,requested_by,reason
                )
                SELECT suppression_id,source_id,requested_by,reason
                FROM source_suppressions_new_shape
                """
            )
            connection.execute("DROP TABLE source_suppressions_new_shape")
            connection.commit()
        finally:
            connection.close()

        MemoryStore(self.db).initialize()

        migrated = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                migrated.execute(
                    "SELECT rowid FROM source_suppressions"
                ).fetchall()
            row = migrated.execute(
                """
                SELECT suppression_id,source_id,requested_by,reason
                FROM source_suppressions
                """
            ).fetchone()
        finally:
            migrated.close()

        self.assertEqual(
            row,
            (
                "stop-legacy",
                binding.evidence.source_id,
                "synthetic-test",
                "stop present use",
            ),
        )
        self.assertEqual(
            self.use.state_decision(record.state_id).status,
            CurrentPresentUseStatus.SUPPRESSED,
        )
        self.assertEqual(
            self.current.get_state_for_audit(record.state_id).record,
            record,
        )

    def test_source_suppression_ledger_blocks_update_delete_and_replace(self) -> None:
        record = self.state("immutable-stop")
        binding = self.binding(record.source_refs[0])
        self.current.add_state_record(
            record=record,
            source_bindings=(binding,),
        )
        self.suppress(binding, "stop-immutable")

        connection = sqlite3.connect(self.db)
        try:
            connection.execute("PRAGMA recursive_triggers=OFF")
            for sql in (
                "UPDATE source_suppressions SET reason='changed' "
                "WHERE suppression_id='stop-immutable'",
                "DELETE FROM source_suppressions "
                "WHERE suppression_id='stop-immutable'",
                "INSERT OR REPLACE INTO source_suppressions "
                "(suppression_id,source_id,requested_by,reason) "
                f"VALUES ('stop-immutable','{binding.evidence.source_id}',"
                "'other','replace')",
            ):
                with self.assertRaises(sqlite3.DatabaseError):
                    connection.execute(sql)
                connection.rollback()
        finally:
            connection.close()

        with self.assertRaises(CurrentEffectSuppressedError):
            read = self.current._read_connection()
            try:
                _require_current_effect_usable(
                    connection=read,
                    effect_kind=CurrentUseEffectKind.STATE,
                    effect_id=record.state_id,
                )
            finally:
                read.close()

    def test_present_use_rejects_rebuilt_suppression_table_without_constraints(self) -> None:
        record = self.state("table-drift")
        binding = self.binding(record.source_refs[0])
        self.current.add_state_record(
            record=record,
            source_bindings=(binding,),
        )

        connection = sqlite3.connect(self.db)
        try:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute("DROP TABLE source_suppressions")
            connection.execute(
                """
                CREATE TABLE source_suppressions (
                    suppression_id TEXT,
                    source_id TEXT,
                    requested_by TEXT,
                    reason TEXT
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(SuppressionLedgerIntegrityError):
            self.use.state_decision(record.state_id)

    def test_current_write_fails_closed_on_suppression_ledger_drift_but_audit_remains(self) -> None:
        historical = self.state("historical-before-ledger-drift")
        historical_binding = self.binding(historical.source_refs[0])
        self.current.add_state_record(
            record=historical,
            source_bindings=(historical_binding,),
        )

        connection = sqlite3.connect(self.db)
        try:
            connection.execute("DROP TRIGGER source_suppressions_no_update")
            connection.commit()
        finally:
            connection.close()

        new_record = self.state("blocked-after-ledger-drift")
        new_binding = self.binding(new_record.source_refs[0])
        with self.assertRaises(SuppressionLedgerIntegrityError):
            self.current.add_state_record(
                record=new_record,
                source_bindings=(new_binding,),
            )

        self.assertEqual(
            self.current.get_state_for_audit(historical.state_id).record,
            historical,
        )
        with self.assertRaises(KeyError):
            self.current.get_state_for_audit(new_record.state_id)

    def test_initialize_does_not_silently_repair_upgraded_ledger_guard_drift(self) -> None:
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("DROP TRIGGER source_suppressions_no_delete")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(SuppressionLedgerIntegrityError):
            MemoryStore(self.db).initialize()

        check = sqlite3.connect(self.db)
        try:
            restored = check.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type='trigger'
                  AND name='source_suppressions_no_delete'
                """
            ).fetchone()
        finally:
            check.close()
        self.assertIsNone(restored)

    def test_present_use_fails_closed_if_suppression_guard_is_removed(self) -> None:
        record = self.state("guard-drift")
        binding = self.binding(record.source_refs[0])
        self.current.add_state_record(
            record=record,
            source_bindings=(binding,),
        )

        connection = sqlite3.connect(self.db)
        try:
            connection.execute("DROP TRIGGER source_suppressions_no_delete")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(SuppressionLedgerIntegrityError):
            self.use.state_decision(record.state_id)


if __name__ == "__main__":
    unittest.main()
