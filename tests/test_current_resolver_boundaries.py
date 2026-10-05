import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from _suppression_test_support import (
    create_test_suppression_record as create_suppression_record,
)
from home_memory_core.current_resolver import (
    CurrentResolver,
    CurrentResolverStatus,
)
from home_memory_core.current_store import (
    CurrentSourceBinding,
    CurrentStore,
    CurrentStoreIntegrityError,
)
from home_memory_core.current_view import (
    CurrentNamespace,
    CurrentStanding,
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
from home_memory_core.suppression import SuppressionLedgerIntegrityError


UTC = timezone.utc


class CurrentResolverBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "home.db"
        self.memory = MemoryStore(self.db)
        self.memory.initialize()
        living = LivingStore(self.db)
        living.initialize()
        living.add_room(RoomRecord(room_id="room-r"))
        living.add_episode(
            EpisodeRecord(
                episode_id="episode-a",
                perspective_instance_id="perspective-a",
                runtime_instance_id="runtime-a",
            )
        )
        living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-a",
                episode_id="episode-a",
                route_kind=RoomRouteKind.ATTACHED,
                room_id="room-r",
                basis="synthetic-current-resolver-boundary",
            )
        )
        self.current = CurrentStore(self.db)
        self.current.initialize()
        self.resolver = CurrentResolver(self.db)
        self.t0 = datetime(2026, 1, 2, 9, tzinfo=UTC)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def binding(self, ref: str) -> CurrentSourceBinding:
        source = create_source_record(
            source_id=f"src-{ref}",
            content=f"synthetic evidence {ref}",
            authored_by="current-resolver-boundary-test",
            scope="room-r",
        )
        self.memory.add_source(source)
        return CurrentSourceBinding(
            ref,
            create_evidence_ref(
                source=source,
                start_char=0,
                end_char=len(source.content),
            ),
        )

    def state(
        self,
        state_id: str,
        *,
        supersedes: str | None = None,
    ) -> tuple[CurrentStateRecord, CurrentSourceBinding]:
        ref = f"ref-{state_id}"
        record = CurrentStateRecord(
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
            supersedes_state_id=supersedes,
            source_refs=(ref,),
        )
        return record, self.binding(ref)

    def add_state(
        self,
        state_id: str,
        *,
        supersedes: str | None = None,
    ) -> tuple[CurrentStateRecord, CurrentSourceBinding]:
        record, binding = self.state(state_id, supersedes=supersedes)
        self.current.add_state_record(
            record=record,
            source_bindings=(binding,),
        )
        return record, binding

    def suppress(
        self,
        binding: CurrentSourceBinding,
        suppression_id: str,
    ) -> None:
        self.memory.suppress_source(
            create_suppression_record(
                suppression_id=suppression_id,
                source_id=binding.evidence.source_id,
                requested_by="synthetic-test",
                reason="stop present use",
            )
        )

    def end(
        self,
        end_id: str,
        state_id: str,
    ) -> tuple[CurrentStateEndEvent, CurrentSourceBinding]:
        ref = f"ref-{end_id}"
        event = CurrentStateEndEvent(
            end_event_id=end_id,
            state_id=state_id,
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.EXPLICIT_END,
            reason=end_id,
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id="episode-a",
            perspective_instance_id="perspective-a",
            source_refs=(ref,),
        )
        binding = self.binding(ref)
        self.current.add_end_event(
            event=event,
            source_bindings=(binding,),
        )
        return event, binding

    def resolve(self):
        return self.resolver.resolve_key(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key="project.status",
            as_of=self.t0,
        )

    def test_ancestor_stop_blocks_descendant_without_rewinding_lineage(self) -> None:
        root, root_binding = self.add_state("root")
        child, _ = self.add_state("child", supersedes=root.state_id)
        grandchild, _ = self.add_state(
            "grandchild",
            supersedes=child.state_id,
        )
        self.suppress(root_binding, "stop-root")

        decision = self.resolve()

        self.assertEqual(
            decision.semantic_resolution.current_state_ids,
            (grandchild.state_id,),
        )
        self.assertEqual(
            decision.status,
            CurrentResolverStatus.BLOCKED_UNKNOWN,
        )
        self.assertIsNone(decision.usable_standing)
        self.assertEqual(
            tuple(
                (block.suppression_id, block.origin_effect_id)
                for block in decision.blocks
            ),
            (("stop-root", root.state_id),),
        )

    def test_suppressed_member_of_end_conflict_does_not_simplify_conflict(self) -> None:
        state, _ = self.add_state("ended")
        first, _ = self.end("end-a", state.state_id)
        second, second_binding = self.end("end-b", state.state_id)
        self.suppress(second_binding, "stop-end-b")

        decision = self.resolve()

        self.assertEqual(
            decision.semantic_resolution.standing,
            CurrentStanding.CONFLICTING,
        )
        self.assertEqual(
            tuple(
                event.end_event_id
                for event in decision.semantic_resolution.candidates[0].end_events
            ),
            (first.end_event_id, second.end_event_id),
        )
        self.assertEqual(
            decision.status,
            CurrentResolverStatus.BLOCKED_UNKNOWN,
        )
        self.assertIsNone(decision.usable_standing)

    def test_damaged_suppression_ledger_fails_closed_before_resolution(self) -> None:
        self.add_state("state-a")
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("DROP TRIGGER source_suppressions_no_delete")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(SuppressionLedgerIntegrityError):
            self.resolve()

    def test_damaged_current_schema_fails_closed_before_resolution(self) -> None:
        self.add_state("state-a")
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("DROP TRIGGER current_state_no_update")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(CurrentStoreIntegrityError):
            self.resolve()


if __name__ == "__main__":
    unittest.main()
