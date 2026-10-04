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
    require_current_effect_usable,
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
                require_current_effect_usable(
                    connection=read,
                    effect_kind=CurrentUseEffectKind.STATE,
                    effect_id=record.state_id,
                )
            finally:
                read.close()

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
