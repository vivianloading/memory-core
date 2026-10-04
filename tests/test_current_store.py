import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from home_memory_core.current_store import (
    CurrentSourceBinding,
    CurrentStore,
    CurrentStoreConflictError,
    CurrentStoreIntegrityError,
)
from home_memory_core.current_store_schema import (
    CURRENT_END_EVIDENCE_TABLE,
    CURRENT_END_TABLE,
    CURRENT_STATE_EVIDENCE_TABLE,
    CURRENT_STATE_TABLE,
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
    resolve_current_state,
)
from home_memory_core.evidence import EvidenceRef, create_evidence_ref, read_evidence
from home_memory_core.living_continuity import (
    EpisodeRecord,
    RoomAttachmentEvent,
    RoomRecord,
    RoomRouteKind,
)
from home_memory_core.living_store import LivingStore
from home_memory_core.source import create_source_record
from home_memory_core.storage import MemoryStore
from home_memory_core.suppression import SuppressedMemoryError, create_suppression_record

UTC = timezone.utc


class CurrentStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "home.db"
        self.memory = MemoryStore(self.db)
        self.memory.initialize()
        self.living = LivingStore(self.db)
        self.living.initialize()
        self.living.add_room(RoomRecord(room_id="room-r"))
        self.living.add_episode(EpisodeRecord(
            episode_id="episode-a",
            perspective_instance_id="perspective-a",
            runtime_instance_id="runtime-a",
        ))
        self.living.add_room_attachment(RoomAttachmentEvent(
            attachment_event_id="route-a",
            episode_id="episode-a",
            route_kind=RoomRouteKind.ATTACHED,
            room_id="room-r",
            basis="synthetic-test-route",
        ))
        self.store = CurrentStore(self.db)
        self.store.initialize()
        self.t0 = datetime(2026, 1, 1, 9, tzinfo=UTC)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def binding(self, ref: str) -> CurrentSourceBinding:
        source = create_source_record(
            source_id=f"src-{ref}", content=f"evidence:{ref}",
            authored_by="synthetic-test", scope="room-r",
        )
        self.memory.add_source(source)
        return CurrentSourceBinding(
            ref,
            create_evidence_ref(source=source, start_char=0, end_char=len(source.content)),
        )

    def room_state(self, state_id: str, **changes) -> CurrentStateRecord:
        values = dict(
            state_id=state_id,
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key="project.home.status",
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
            source_refs=(f"ref-{state_id}",),
        )
        values.update(changes)
        return CurrentStateRecord(**values)

    def test_round_trip_preserves_exact_binding_and_current_semantics(self) -> None:
        record = self.room_state("state-a", source_refs=("raw", "decision"))
        bindings = (self.binding("raw"), self.binding("decision"))
        self.store.add_state_record(record=record, source_bindings=bindings)

        persisted = self.store.get_state_for_audit(record.state_id)
        self.assertEqual(persisted.record.source_refs, record.source_refs)
        self.assertEqual(persisted.source_bindings, bindings)
        self.assertEqual(persisted.room_attachment_event_id, "route-a")
        resolution = resolve_current_state(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key=record.key,
            records=(persisted.record,),
            as_of=self.t0,
        )
        self.assertEqual(resolution.standing, CurrentStanding.CURRENT)

    def test_huge_stale_duration_round_trips_without_sqlite_integer_overflow(self) -> None:
        record = self.room_state(
            "huge-stale",
            state_kind=CurrentStateKind.PREFERENCE,
            validity_rule=ValidityRule.STALE_TO_LAST_KNOWN,
            downgrade_rule=DowngradeRule.TO_LAST_KNOWN,
            stale_after=timedelta.max,
        )
        self.store.add_state_record(
            record=record, source_bindings=(self.binding(record.source_refs[0]),)
        )
        self.assertEqual(
            self.store.get_state_for_audit(record.state_id).record.stale_after,
            timedelta.max,
        )

    def test_calendar_edge_offsets_round_trip_without_utc_materialization(self) -> None:
        cases = (
            (
                "lower-edge",
                datetime(1, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=8))),
            ),
            (
                "upper-edge",
                datetime(
                    9999, 12, 31, 23, 59, 59, 999999,
                    tzinfo=timezone(timedelta(hours=-8)),
                ),
            ),
        )

        for state_id, instant in cases:
            record = self.room_state(
                state_id,
                event_time=instant,
                recorded_at=instant,
                valid_from=instant,
            )
            self.store.add_state_record(
                record=record,
                source_bindings=(self.binding(record.source_refs[0]),),
            )
            persisted = self.store.get_state_for_audit(state_id).record
            self.assertEqual(persisted.event_time.isoformat(), instant.isoformat())
            self.assertEqual(persisted.recorded_at.isoformat(), instant.isoformat())
            self.assertEqual(persisted.valid_from.isoformat(), instant.isoformat())

    def test_typed_binding_must_match_ref_source_hash_and_suppression(self) -> None:
        record = self.room_state("binding")
        good = self.binding(record.source_refs[0])
        with self.assertRaises(CurrentStoreIntegrityError):
            self.store.add_state_record(
                record=record,
                source_bindings=(CurrentSourceBinding(
                    "wrong-ref", good.evidence
                ),),
            )

        missing = CurrentSourceBinding(
            record.source_refs[0],
            EvidenceRef("missing", good.evidence.source_sha256, 0, 1),
        )
        with self.assertRaises(CurrentStoreIntegrityError):
            self.store.add_state_record(record=record, source_bindings=(missing,))

        self.memory.suppress_source(create_suppression_record(
            suppression_id="stop-1", source_id=good.evidence.source_id,
            requested_by="synthetic-test", reason="stop use",
        ))
        with self.assertRaises(SuppressedMemoryError):
            self.store.add_state_record(record=record, source_bindings=(good,))

    def test_room_episode_perspective_and_supersession_line_fail_closed(self) -> None:
        forged = self.room_state("forged", perspective_instance_id="other")
        with self.assertRaises(CurrentStoreConflictError):
            self.store.add_state_record(
                record=forged, source_bindings=(self.binding(forged.source_refs[0]),)
            )

        parent = self.room_state("parent")
        self.store.add_state_record(
            record=parent, source_bindings=(self.binding(parent.source_refs[0]),)
        )
        child = self.room_state(
            "child", key="other.key", supersedes_state_id=parent.state_id
        )
        with self.assertRaises(CurrentStoreConflictError):
            self.store.add_state_record(
                record=child, source_bindings=(self.binding(child.source_refs[0]),)
            )

    def test_room_current_requires_active_route_and_keeps_exact_route_anchor(self) -> None:
        self.living.add_room(RoomRecord(room_id="room-other"))
        self.living.add_episode(EpisodeRecord(
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            runtime_instance_id="runtime-b",
        ))
        self.living.add_room_attachment(RoomAttachmentEvent(
            attachment_event_id="route-b",
            episode_id="episode-b",
            route_kind=RoomRouteKind.ATTACHED,
            room_id="room-other",
            basis="other-room",
        ))
        cross_room = self.room_state(
            "cross-room",
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
        )
        with self.assertRaises(CurrentStoreIntegrityError):
            self.store.add_state_record(
                record=cross_room,
                source_bindings=(self.binding(cross_room.source_refs[0]),),
            )

        record = self.room_state("anchored-route")
        self.store.add_state_record(
            record=record,
            source_bindings=(self.binding(record.source_refs[0]),),
        )
        self.living.add_room(RoomRecord(room_id="room-corrected"))
        self.living.add_room_attachment(RoomAttachmentEvent(
            attachment_event_id="route-a-correction",
            episode_id="episode-a",
            route_kind=RoomRouteKind.ATTACHED,
            room_id="room-corrected",
            basis="late-route-correction",
            supersedes_attachment_event_id="route-a",
        ))

        persisted = self.store.get_state_for_audit(record.state_id)
        self.assertEqual(persisted.room_attachment_event_id, "route-a")
        self.assertEqual(persisted.record.owner_id, "room-r")

    def test_end_event_is_append_only_evidence_not_a_rewrite(self) -> None:
        record = self.room_state(
            "commitment",
            state_kind=CurrentStateKind.COMMITMENT,
            validity_rule=ValidityRule.OPEN_UNTIL_RESOLVED,
        )
        self.store.add_state_record(
            record=record, source_bindings=(self.binding(record.source_refs[0]),)
        )
        event = CurrentStateEndEvent(
            end_event_id="end-1", state_id=record.state_id,
            ended_at=self.t0 + timedelta(hours=1),
            recorded_at=self.t0 + timedelta(hours=1),
            end_kind=EndKind.COMPLETED, reason="done",
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id="episode-a", perspective_instance_id="perspective-a",
            source_refs=("end-ref",),
        )
        self.store.add_end_event(event=event, source_bindings=(self.binding("end-ref"),))
        self.assertEqual(
            self.store.get_end_event_for_audit("end-1").event.state_id,
            record.state_id,
        )

    def test_raw_sql_update_delete_replace_are_blocked(self) -> None:
        record = self.room_state("immutable")
        self.store.add_state_record(
            record=record, source_bindings=(self.binding(record.source_refs[0]),)
        )
        connection = sqlite3.connect(self.db)
        try:
            for sql in (
                f"UPDATE {CURRENT_STATE_TABLE} SET owner_id='x' WHERE state_id='immutable'",
                f"DELETE FROM {CURRENT_STATE_TABLE} WHERE state_id='immutable'",
                f"INSERT OR REPLACE INTO {CURRENT_STATE_TABLE} SELECT * FROM {CURRENT_STATE_TABLE} WHERE state_id='immutable'",
            ):
                with self.assertRaises(sqlite3.DatabaseError):
                    connection.execute(sql)
                connection.rollback()
        finally:
            connection.close()

    def test_current_history_tables_have_no_hidden_rowid_replace_channel(self) -> None:
        record = self.room_state("rowid-state")
        binding = self.binding(record.source_refs[0])
        self.store.add_state_record(record=record, source_bindings=(binding,))
        event = CurrentStateEndEvent(
            end_event_id="rowid-end",
            state_id=record.state_id,
            ended_at=self.t0 + timedelta(hours=1),
            recorded_at=self.t0 + timedelta(hours=1),
            end_kind=EndKind.EXPLICIT_END,
            reason="synthetic",
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id="episode-a",
            perspective_instance_id="perspective-a",
            source_refs=("rowid-end-ref",),
        )
        self.store.add_end_event(
            event=event,
            source_bindings=(self.binding("rowid-end-ref"),),
        )

        connection = sqlite3.connect(self.db)
        try:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute("PRAGMA recursive_triggers=OFF")
            for table in (
                CURRENT_STATE_TABLE,
                CURRENT_STATE_EVIDENCE_TABLE,
                CURRENT_END_TABLE,
                CURRENT_END_EVIDENCE_TABLE,
            ):
                with self.assertRaises(sqlite3.DatabaseError):
                    connection.execute(f"SELECT rowid FROM {table}").fetchone()
        finally:
            connection.close()

        self.assertEqual(
            self.store.get_state_for_audit(record.state_id).record.state_id,
            record.state_id,
        )
        self.assertEqual(
            self.store.get_end_event_for_audit(event.end_event_id).event.end_event_id,
            event.end_event_id,
        )

    def test_committed_evidence_set_cannot_grow_after_parent_commit(self) -> None:
        record = self.room_state("sealed-state", source_refs=("sealed-ref",))
        binding = self.binding("sealed-ref")
        self.store.add_state_record(record=record, source_bindings=(binding,))

        event = CurrentStateEndEvent(
            end_event_id="sealed-end",
            state_id=record.state_id,
            ended_at=self.t0 + timedelta(hours=1),
            recorded_at=self.t0 + timedelta(hours=1),
            end_kind=EndKind.EXPLICIT_END,
            reason="synthetic",
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id="episode-a",
            perspective_instance_id="perspective-a",
            source_refs=("sealed-end-ref",),
        )
        end_binding = self.binding("sealed-end-ref")
        self.store.add_end_event(event=event, source_bindings=(end_binding,))

        connection = sqlite3.connect(self.db)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute(
                    f"""
                    INSERT INTO {CURRENT_STATE_EVIDENCE_TABLE} (
                        state_id,position,source_ref,source_id,
                        source_sha256,start_char,end_char
                    ) VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        record.state_id, 1, "extra-ref",
                        binding.evidence.source_id,
                        binding.evidence.source_sha256,
                        binding.evidence.start_char,
                        binding.evidence.end_char,
                    ),
                )
            connection.rollback()

            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute(
                    f"""
                    INSERT INTO {CURRENT_END_EVIDENCE_TABLE} (
                        end_event_id,position,source_ref,source_id,
                        source_sha256,start_char,end_char
                    ) VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        event.end_event_id, 1, "extra-end-ref",
                        end_binding.evidence.source_id,
                        end_binding.evidence.source_sha256,
                        end_binding.evidence.start_char,
                        end_binding.evidence.end_char,
                    ),
                )
            connection.rollback()
        finally:
            connection.close()

        self.assertEqual(
            self.store.get_state_for_audit(record.state_id).record.source_refs,
            ("sealed-ref",),
        )
        self.assertEqual(
            self.store.get_end_event_for_audit(event.end_event_id).event.source_refs,
            ("sealed-end-ref",),
        )

    def test_fractional_evidence_coordinates_fail_at_current_boundary(self) -> None:
        source = create_source_record(
            source_id="src-fractional",
            content="abcd",
            authored_by="synthetic-test",
            scope="room-r",
        )
        self.memory.add_source(source)
        fractional = EvidenceRef(
            source_id=source.source_id,
            source_sha256=source.content_sha256,
            start_char=0.5,
            end_char=1.5,
        )
        with self.assertRaises(CurrentStoreIntegrityError):
            CurrentSourceBinding("fractional", fractional)

        connection = sqlite3.connect(self.db)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            record = self.room_state("fractional-raw")
            binding = self.binding(record.source_refs[0])
            self.store.add_state_record(record=record, source_bindings=(binding,))
            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute(
                    f"""
                    INSERT INTO {CURRENT_STATE_EVIDENCE_TABLE} (
                        state_id,position,source_ref,source_id,
                        source_sha256,start_char,end_char
                    ) VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        record.state_id, 1, "fractional-raw-extra",
                        source.source_id, source.content_sha256, 0.5, 1.5,
                    ),
                )
            connection.rollback()
        finally:
            connection.close()

    def test_state_kind_is_stable_per_key_but_same_kind_heads_can_conflict(self) -> None:
        first = self.room_state("kind-a")
        self.store.add_state_record(
            record=first,
            source_bindings=(self.binding(first.source_refs[0]),),
        )

        changed_kind = self.room_state(
            "kind-b",
            state_kind=CurrentStateKind.PREFERENCE,
            validity_rule=ValidityRule.DURABLE_UNTIL_CHANGED,
            downgrade_rule=DowngradeRule.NONE,
        )
        with self.assertRaises(CurrentStoreConflictError):
            self.store.add_state_record(
                record=changed_kind,
                source_bindings=(self.binding(changed_kind.source_refs[0]),),
            )

        same_kind = self.room_state("kind-c")
        self.store.add_state_record(
            record=same_kind,
            source_bindings=(self.binding(same_kind.source_refs[0]),),
        )
        persisted = self.store.list_states_for_audit()
        resolution = resolve_current_state(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key=first.key,
            records=tuple(item.record for item in persisted),
            as_of=self.t0,
        )
        self.assertEqual(resolution.standing, CurrentStanding.CONFLICTING)

    def test_nul_and_unicode_source_span_uses_python_code_point_domain(self) -> None:
        source = create_source_record(
            source_id="src-nul-unicode",
            content="A\x00😀Z",
            authored_by="synthetic-test",
            scope="room-r",
        )
        self.memory.add_source(source)
        evidence = create_evidence_ref(
            source=source,
            start_char=2,
            end_char=3,
        )
        binding = CurrentSourceBinding("nul-unicode", evidence)
        record = self.room_state(
            "nul-unicode",
            source_refs=("nul-unicode",),
        )
        self.store.add_state_record(record=record, source_bindings=(binding,))
        audited = self.store.get_state_for_audit(record.state_id)
        self.assertEqual(
            read_evidence(source=source, evidence=audited.source_bindings[0].evidence),
            "😀",
        )

    def test_orphan_evidence_is_blocked_without_foreign_keys_and_detected_by_audit(self) -> None:
        record = self.room_state("orphan-parent")
        binding = self.binding(record.source_refs[0])
        self.store.add_state_record(record=record, source_bindings=(binding,))

        connection = sqlite3.connect(self.db)
        try:
            connection.execute("PRAGMA foreign_keys=OFF")
            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute(
                    f"""
                    INSERT INTO {CURRENT_STATE_EVIDENCE_TABLE} (
                        state_id,position,source_ref,source_id,
                        source_sha256,start_char,end_char
                    ) VALUES ('absent',0,'orphan-ref',?,?,?,?)
                    """,
                    (
                        binding.evidence.source_id,
                        binding.evidence.source_sha256,
                        binding.evidence.start_char,
                        binding.evidence.end_char,
                    ),
                )
            connection.rollback()

            trigger_sql = connection.execute(
                """
                SELECT sql FROM sqlite_master
                WHERE type='trigger'
                  AND name='current_state_evidence_parent_exists'
                """
            ).fetchone()[0]
            connection.execute("DROP TRIGGER current_state_evidence_parent_exists")
            connection.execute(
                f"""
                INSERT INTO {CURRENT_STATE_EVIDENCE_TABLE} (
                    state_id,position,source_ref,source_id,
                    source_sha256,start_char,end_char
                ) VALUES ('absent',0,'orphan-ref',?,?,?,?)
                """,
                (
                    binding.evidence.source_id,
                    binding.evidence.source_sha256,
                    binding.evidence.start_char,
                    binding.evidence.end_char,
                ),
            )
            connection.execute(trigger_sql)
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(CurrentStoreIntegrityError):
            self.store.get_state_for_audit(record.state_id)

    def test_same_name_empty_trigger_is_detected_not_trusted(self) -> None:
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("DROP TRIGGER current_state_no_update")
            connection.execute(
                f"CREATE TRIGGER current_state_no_update BEFORE UPDATE ON {CURRENT_STATE_TABLE} BEGIN SELECT 1; END"
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(CurrentStoreIntegrityError):
            self.store.list_states_for_audit()

    def test_schema_literal_case_change_is_detected(self) -> None:
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("DROP TRIGGER current_state_room_exists")
            connection.execute(
                f"""
                CREATE TRIGGER current_state_room_exists
                BEFORE INSERT ON {CURRENT_STATE_TABLE}
                WHEN NEW.namespace='ROOM'
                 AND NOT EXISTS(
                    SELECT 1 FROM living_rooms
                    WHERE room_id=NEW.owner_id
                 )
                BEGIN
                    SELECT RAISE(ABORT,'Room Current owner does not exist');
                END
                """
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(CurrentStoreIntegrityError):
            self.store.list_states_for_audit()

    def test_new_binding_recomputes_stored_source_hash(self) -> None:
        record = self.room_state("corrupt-before-write")
        binding = self.binding(record.source_refs[0])
        connection = sqlite3.connect(self.db)
        try:
            connection.execute(
                "UPDATE sources SET content=? WHERE source_id=?",
                ("tampered", binding.evidence.source_id),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(CurrentStoreIntegrityError):
            self.store.add_state_record(
                record=record,
                source_bindings=(binding,),
            )

    def test_audit_recomputes_persisted_source_hash(self) -> None:
        record = self.room_state("corrupt-after-write")
        binding = self.binding(record.source_refs[0])
        self.store.add_state_record(
            record=record,
            source_bindings=(binding,),
        )

        connection = sqlite3.connect(self.db)
        try:
            connection.execute(
                "UPDATE sources SET content=? WHERE source_id=?",
                ("tampered", binding.evidence.source_id),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(CurrentStoreIntegrityError):
            self.store.get_state_for_audit(record.state_id)

    def test_unexpected_trigger_and_unique_index_are_detected(self) -> None:
        connection = sqlite3.connect(self.db)
        try:
            connection.execute(
                f"""
                CREATE TRIGGER current_hidden_behavior
                AFTER INSERT ON {CURRENT_STATE_TABLE}
                BEGIN SELECT 1; END
                """
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(CurrentStoreIntegrityError):
            self.store.list_states_for_audit()

        connection = sqlite3.connect(self.db)
        try:
            connection.execute("DROP TRIGGER current_hidden_behavior")
            connection.execute(
                f"""
                CREATE UNIQUE INDEX current_hidden_single_head
                ON {CURRENT_STATE_TABLE}(namespace, owner_id, key)
                """
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(CurrentStoreIntegrityError):
            self.store.list_states_for_audit()

    def test_shared_state_cannot_smuggle_room_provenance(self) -> None:
        shared = CurrentStateRecord(
            state_id="shared", namespace=CurrentNamespace.SHARED,
            owner_id="shared-home", key="shared.status",
            state_kind=CurrentStateKind.SHARED_STATE, value="open",
            event_time=self.t0, recorded_at=self.t0, valid_from=self.t0,
            validity_rule=ValidityRule.DURABLE_UNTIL_CHANGED,
            downgrade_rule=DowngradeRule.NONE,
            semantic_change_authority=SemanticChangeAuthority.SHARED_GOVERNANCE,
            source_refs=("shared-ref",),
        )
        self.store.add_state_record(
            record=shared, source_bindings=(self.binding("shared-ref"),)
        )
        persisted = self.store.get_state_for_audit("shared").record
        self.assertIsNone(persisted.episode_id)
        self.assertIsNone(persisted.perspective_instance_id)


if __name__ == "__main__":
    unittest.main()