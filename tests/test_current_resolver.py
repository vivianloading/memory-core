import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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


UTC = timezone.utc


class CurrentResolverTests(unittest.TestCase):
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
                basis="synthetic-current-resolver",
            )
        )

        self.current = CurrentStore(self.db)
        self.current.initialize()
        self.resolver = CurrentResolver(self.db)
        self.t0 = datetime(2026, 1, 2, 9, tzinfo=UTC)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def binding(self, source_ref: str) -> CurrentSourceBinding:
        source = create_source_record(
            source_id=f"src-{source_ref}",
            content=f"synthetic evidence for {source_ref}",
            authored_by="current-resolver-test",
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
        key: str = "project.status",
        source_ref: str | None = None,
        supersedes_state_id: str | None = None,
        valid_from: datetime | None = None,
    ) -> CurrentStateRecord:
        ref = source_ref or f"ref-{state_id}"
        return CurrentStateRecord(
            state_id=state_id,
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key=key,
            state_kind=CurrentStateKind.PROJECT_STATUS,
            value=state_id,
            event_time=self.t0,
            recorded_at=self.t0,
            valid_from=valid_from or self.t0,
            validity_rule=ValidityRule.DURABLE_UNTIL_CHANGED,
            downgrade_rule=DowngradeRule.NONE,
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id="episode-a",
            perspective_instance_id="perspective-a",
            source_refs=(ref,),
            supersedes_state_id=supersedes_state_id,
        )

    def add_state(
        self,
        record: CurrentStateRecord,
    ) -> CurrentSourceBinding:
        binding = self.binding(record.source_refs[0])
        self.current.add_state_record(
            record=record,
            source_bindings=(binding,),
        )
        return binding

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

    def test_usable_head_resolves_without_changing_current_semantics(self) -> None:
        record = self.state("state-a")
        self.add_state(record)

        decision = self.resolver.resolve_key(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key=record.key,
            as_of=self.t0,
        )

        self.assertEqual(decision.status, CurrentResolverStatus.RESOLVED)
        self.assertEqual(decision.usable_standing, CurrentStanding.CURRENT)
        self.assertEqual(
            decision.semantic_resolution.current_state_ids,
            ("state-a",),
        )
        self.assertEqual(decision.blocks, ())

    def test_suppressed_successor_blocks_without_resurrecting_parent(self) -> None:
        parent = self.state("parent")
        self.add_state(parent)
        child = self.state(
            "child",
            supersedes_state_id=parent.state_id,
        )
        child_binding = self.add_state(child)
        self.suppress(child_binding, "stop-child")

        decision = self.resolver.resolve_key(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key=parent.key,
            as_of=self.t0,
        )

        self.assertEqual(
            decision.status,
            CurrentResolverStatus.BLOCKED_UNKNOWN,
        )
        self.assertIsNone(decision.usable_standing)
        self.assertEqual(
            decision.semantic_resolution.current_state_ids,
            ("child",),
        )
        self.assertNotIn(
            "parent",
            decision.semantic_resolution.current_state_ids,
        )
        self.assertEqual(
            tuple(block.suppression_id for block in decision.blocks),
            ("stop-child",),
        )

    def test_suppressed_effective_end_does_not_revive_target(self) -> None:
        state = self.state("ended-state")
        self.add_state(state)
        event = CurrentStateEndEvent(
            end_event_id="end-a",
            state_id=state.state_id,
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.EXPLICIT_END,
            reason="synthetic end",
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id="episode-a",
            perspective_instance_id="perspective-a",
            source_refs=("ref-end-a",),
        )
        end_binding = self.binding("ref-end-a")
        self.current.add_end_event(
            event=event,
            source_bindings=(end_binding,),
        )
        self.suppress(end_binding, "stop-end-a")

        decision = self.resolver.resolve_key(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key=state.key,
            as_of=self.t0,
        )

        self.assertEqual(
            decision.semantic_resolution.standing,
            CurrentStanding.ENDED,
        )
        self.assertEqual(
            decision.status,
            CurrentResolverStatus.BLOCKED_UNKNOWN,
        )
        self.assertIsNone(decision.usable_standing)
        self.assertEqual(
            tuple(block.suppression_id for block in decision.blocks),
            ("stop-end-a",),
        )

    def test_suppressed_conflict_participant_does_not_choose_other_head(self) -> None:
        first = self.state("head-a")
        self.add_state(first)
        second = self.state("head-b")
        second_binding = self.add_state(second)
        self.suppress(second_binding, "stop-head-b")

        decision = self.resolver.resolve_key(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key=first.key,
            as_of=self.t0,
        )

        self.assertEqual(
            decision.semantic_resolution.standing,
            CurrentStanding.CONFLICTING,
        )
        self.assertEqual(
            set(decision.semantic_resolution.current_state_ids),
            {"head-a", "head-b"},
        )
        self.assertEqual(
            decision.status,
            CurrentResolverStatus.BLOCKED_UNKNOWN,
        )
        self.assertIsNone(decision.usable_standing)

    def test_suppression_on_other_key_does_not_poison_resolution(self) -> None:
        target = self.state("target", key="project.target")
        self.add_state(target)
        other = self.state("other", key="project.other")
        other_binding = self.add_state(other)
        self.suppress(other_binding, "stop-other")

        decision = self.resolver.resolve_key(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key=target.key,
            as_of=self.t0,
        )

        self.assertEqual(decision.status, CurrentResolverStatus.RESOLVED)
        self.assertEqual(decision.usable_standing, CurrentStanding.CURRENT)
        self.assertEqual(decision.blocks, ())

    def test_future_suppressed_successor_does_not_change_earlier_cut(self) -> None:
        parent = self.state("earlier")
        self.add_state(parent)
        future = self.state(
            "future-child",
            supersedes_state_id=parent.state_id,
            valid_from=self.t0 + timedelta(days=2),
        )
        future_binding = self.add_state(future)
        self.suppress(future_binding, "stop-future")

        decision = self.resolver.resolve_key(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key=parent.key,
            as_of=self.t0,
        )

        self.assertEqual(decision.status, CurrentResolverStatus.RESOLVED)
        self.assertEqual(decision.usable_standing, CurrentStanding.CURRENT)
        self.assertEqual(
            decision.semantic_resolution.current_state_ids,
            ("earlier",),
        )


if __name__ == "__main__":
    unittest.main()
