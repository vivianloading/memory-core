import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from home_memory_core.current_store import CurrentSourceBinding, CurrentStore
from home_memory_core.current_use import CurrentPresentUseStatus, CurrentPresentUseStore
from home_memory_core.current_use_asof import (
    HistoricalCurrentUseStatus,
    HistoricalCurrentUseStore,
    HistoricalSuppressionBlockStatus,
)
from home_memory_core.current_view import (
    CurrentNamespace,
    CurrentStateKind,
    CurrentStateRecord,
    DowngradeRule,
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
from home_memory_core.storage import (
    SOURCE_SUPPRESSION_TIMING_TABLE,
    SUPPRESSION_SCHEMA_MARKER_TABLE,
    SUPPRESSION_SCHEMA_VERSION,
    MemoryStore,
)
from home_memory_core.suppression import (
    create_suppression_record,
    create_timed_suppression_record,
)


UTC = timezone.utc


class HistoricalSuppressionAsOfTests(unittest.TestCase):
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
                basis="synthetic-asof",
            )
        )

        self.current = CurrentStore(self.db)
        self.current.initialize()
        self.present = CurrentPresentUseStore(self.db)
        self.history = HistoricalCurrentUseStore(self.db)
        self.t0 = datetime(2026, 1, 1, 9, tzinfo=UTC)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def binding(self, label: str) -> CurrentSourceBinding:
        source = create_source_record(
            source_id=f"src-{label}",
            content=f"synthetic evidence for {label}",
            authored_by="asof-test",
            scope="room-r",
        )
        self.memory.add_source(source)
        return CurrentSourceBinding(
            source_ref=f"ref-{label}",
            evidence=create_evidence_ref(
                source=source,
                start_char=0,
                end_char=len(source.content),
            ),
        )

    def state(
        self,
        state_id: str,
        binding: CurrentSourceBinding,
        *,
        recorded_at: datetime | None = None,
        supersedes_state_id: str | None = None,
    ) -> CurrentStateRecord:
        when = recorded_at or self.t0
        return CurrentStateRecord(
            state_id=state_id,
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key="project.status",
            state_kind=CurrentStateKind.PROJECT_STATUS,
            value=state_id,
            event_time=self.t0,
            recorded_at=when,
            valid_from=self.t0,
            validity_rule=ValidityRule.DURABLE_UNTIL_CHANGED,
            downgrade_rule=DowngradeRule.NONE,
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id="episode-a",
            perspective_instance_id="perspective-a",
            source_refs=(binding.source_ref,),
            supersedes_state_id=supersedes_state_id,
        )

    def timed_suppress(
        self,
        binding: CurrentSourceBinding,
        *,
        suppression_id: str,
        effective_at: datetime,
        recorded_at: datetime,
    ) -> None:
        self.memory.suppress_source(
            create_timed_suppression_record(
                suppression_id=suppression_id,
                source_id=binding.evidence.source_id,
                requested_by="asof-test",
                reason="synthetic timed stop-use",
                effective_at=effective_at,
                recorded_at=recorded_at,
            )
        )

    def test_timed_suppression_changes_only_views_at_or_after_record_time(self) -> None:
        binding = self.binding("timed")
        record = self.state("state-timed", binding)
        self.current.add_state_record(record=record, source_bindings=(binding,))
        stop_time = self.t0 + timedelta(hours=2)
        self.timed_suppress(
            binding,
            suppression_id="stop-timed",
            effective_at=stop_time,
            recorded_at=stop_time,
        )

        before = self.history.state_decision(
            state_id=record.state_id,
            as_of=stop_time - timedelta(microseconds=1),
        )
        at = self.history.state_decision(
            state_id=record.state_id,
            as_of=stop_time,
        )

        self.assertEqual(
            before.status,
            HistoricalCurrentUseStatus.NOT_SUPPRESSED_AS_OF,
        )
        self.assertEqual(at.status, HistoricalCurrentUseStatus.SUPPRESSED_AS_OF)
        self.assertEqual(at.blocks[0].suppression_id, "stop-timed")
        self.assertEqual(
            at.blocks[0].status,
            HistoricalSuppressionBlockStatus.SUPPRESSED_AS_OF,
        )
        self.assertEqual(
            self.present.state_decision(record.state_id).status,
            CurrentPresentUseStatus.SUPPRESSED,
        )

    def test_late_recorded_retroactive_suppression_does_not_rewrite_earlier_view(self) -> None:
        binding = self.binding("late")
        record = self.state("state-late", binding)
        self.current.add_state_record(record=record, source_bindings=(binding,))
        effective_at = self.t0 + timedelta(hours=1)
        recorded_at = self.t0 + timedelta(hours=4)
        self.timed_suppress(
            binding,
            suppression_id="stop-late",
            effective_at=effective_at,
            recorded_at=recorded_at,
        )

        between = self.history.state_decision(
            state_id=record.state_id,
            as_of=self.t0 + timedelta(hours=2),
        )
        after_record = self.history.state_decision(
            state_id=record.state_id,
            as_of=recorded_at,
        )

        self.assertEqual(
            between.status,
            HistoricalCurrentUseStatus.NOT_SUPPRESSED_AS_OF,
        )
        self.assertEqual(
            after_record.status,
            HistoricalCurrentUseStatus.SUPPRESSED_AS_OF,
        )

    def test_legacy_untimed_suppression_is_present_blocking_but_historically_unknown(self) -> None:
        binding = self.binding("legacy")
        record = self.state("state-legacy", binding)
        self.current.add_state_record(record=record, source_bindings=(binding,))
        self.memory.suppress_source(
            create_suppression_record(
                suppression_id="stop-legacy",
                source_id=binding.evidence.source_id,
                requested_by="legacy-test",
                reason="timing never recorded",
            )
        )

        decision = self.history.state_decision(
            state_id=record.state_id,
            as_of=self.t0 + timedelta(days=10),
        )
        self.assertEqual(
            decision.status,
            HistoricalCurrentUseStatus.TIMING_UNKNOWN,
        )
        self.assertEqual(len(decision.blocks), 1)
        self.assertEqual(
            decision.blocks[0].status,
            HistoricalSuppressionBlockStatus.TIMING_UNKNOWN,
        )
        self.assertIsNone(decision.blocks[0].effective_instant_us)
        self.assertIsNone(decision.blocks[0].recorded_instant_us)
        self.assertEqual(
            self.present.state_decision(record.state_id).status,
            CurrentPresentUseStatus.SUPPRESSED,
        )

    def test_timed_ancestor_suppression_propagates_to_known_descendant(self) -> None:
        parent_binding = self.binding("ancestor")
        parent = self.state("parent", parent_binding)
        self.current.add_state_record(
            record=parent,
            source_bindings=(parent_binding,),
        )
        child_binding = self.binding("descendant")
        child = self.state(
            "child",
            child_binding,
            recorded_at=self.t0 + timedelta(hours=1),
            supersedes_state_id=parent.state_id,
        )
        self.current.add_state_record(
            record=child,
            source_bindings=(child_binding,),
        )
        stop_time = self.t0 + timedelta(hours=2)
        self.timed_suppress(
            parent_binding,
            suppression_id="stop-ancestor",
            effective_at=stop_time,
            recorded_at=stop_time,
        )

        before = self.history.state_decision(
            state_id=child.state_id,
            as_of=self.t0 + timedelta(hours=1, minutes=30),
        )
        after = self.history.state_decision(
            state_id=child.state_id,
            as_of=stop_time,
        )
        self.assertEqual(
            before.status,
            HistoricalCurrentUseStatus.NOT_SUPPRESSED_AS_OF,
        )
        self.assertEqual(
            after.status,
            HistoricalCurrentUseStatus.SUPPRESSED_AS_OF,
        )
        self.assertEqual(after.blocks[0].origin_effect_id, parent.state_id)

    def test_future_record_is_not_known_and_is_absent_from_historical_list(self) -> None:
        binding = self.binding("future")
        future = self.state(
            "future-state",
            binding,
            recorded_at=self.t0 + timedelta(hours=3),
        )
        self.current.add_state_record(record=future, source_bindings=(binding,))

        direct = self.history.state_decision(
            state_id=future.state_id,
            as_of=self.t0 + timedelta(hours=1),
        )
        listed = self.history.list_decisions(
            as_of=self.t0 + timedelta(hours=1),
        )

        self.assertEqual(
            direct.status,
            HistoricalCurrentUseStatus.NOT_KNOWN_AS_OF,
        )
        self.assertNotIn(
            future.state_id,
            tuple(item.effect_id for item in listed),
        )

    def test_equivalent_offsets_produce_same_historical_cut(self) -> None:
        binding = self.binding("offset")
        record = self.state("state-offset", binding)
        self.current.add_state_record(record=record, source_bindings=(binding,))
        stop_utc = self.t0 + timedelta(hours=2)
        stop_plus8 = stop_utc.astimezone(timezone(timedelta(hours=8)))
        self.timed_suppress(
            binding,
            suppression_id="stop-offset",
            effective_at=stop_plus8,
            recorded_at=stop_plus8,
        )

        utc_decision = self.history.state_decision(
            state_id=record.state_id,
            as_of=stop_utc,
        )
        plus8_decision = self.history.state_decision(
            state_id=record.state_id,
            as_of=stop_plus8,
        )
        self.assertEqual(utc_decision, plus8_decision)

    def test_v01_marker_upgrade_preserves_legacy_suppression_as_timing_unknown(self) -> None:
        binding = self.binding("upgrade")
        record = self.state("state-upgrade", binding)
        self.current.add_state_record(record=record, source_bindings=(binding,))
        self.memory.suppress_source(
            create_suppression_record(
                suppression_id="stop-upgrade",
                source_id=binding.evidence.source_id,
                requested_by="legacy-test",
                reason="pre-3B1 stop-use",
            )
        )

        connection = sqlite3.connect(self.db)
        try:
            connection.execute(f"DROP TABLE {SOURCE_SUPPRESSION_TIMING_TABLE}")
            connection.execute(f"DROP TABLE {SUPPRESSION_SCHEMA_MARKER_TABLE}")
            connection.execute(
                f"""
                CREATE TABLE {SUPPRESSION_SCHEMA_MARKER_TABLE} (
                    marker_key TEXT PRIMARY KEY
                        CHECK (marker_key='source_suppression_schema'),
                    schema_version TEXT NOT NULL
                        CHECK (schema_version='source-suppression-v0.1')
                ) WITHOUT ROWID
                """
            )
            connection.execute(
                f"""
                INSERT INTO {SUPPRESSION_SCHEMA_MARKER_TABLE}
                VALUES ('source_suppression_schema','source-suppression-v0.1')
                """
            )
            connection.execute(
                f"""
                CREATE TRIGGER source_suppression_schema_marker_no_update
                BEFORE UPDATE ON {SUPPRESSION_SCHEMA_MARKER_TABLE}
                BEGIN
                    SELECT RAISE(ABORT,'source suppression schema marker is immutable');
                END
                """
            )
            connection.execute(
                f"""
                CREATE TRIGGER source_suppression_schema_marker_no_delete
                BEFORE DELETE ON {SUPPRESSION_SCHEMA_MARKER_TABLE}
                BEGIN
                    SELECT RAISE(ABORT,'source suppression schema marker is immutable');
                END
                """
            )
            connection.commit()
        finally:
            connection.close()

        MemoryStore(self.db).initialize()

        check = sqlite3.connect(self.db)
        try:
            marker = check.execute(
                f"""
                SELECT schema_version
                FROM {SUPPRESSION_SCHEMA_MARKER_TABLE}
                WHERE marker_key='source_suppression_schema'
                """
            ).fetchone()[0]
            timing_count = check.execute(
                f"SELECT count(*) FROM {SOURCE_SUPPRESSION_TIMING_TABLE}"
            ).fetchone()[0]
        finally:
            check.close()

        self.assertEqual(marker, SUPPRESSION_SCHEMA_VERSION)
        self.assertEqual(timing_count, 0)
        decision = self.history.state_decision(
            state_id=record.state_id,
            as_of=self.t0 + timedelta(days=30),
        )
        self.assertEqual(
            decision.status,
            HistoricalCurrentUseStatus.TIMING_UNKNOWN,
        )


if __name__ == "__main__":
    unittest.main()
