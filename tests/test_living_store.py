import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


from home_memory_core.living_continuity import (
    ContinuityEdge,
    ContinuityStatus,
    EpisodeRecord,
    RoomAttachmentEvent,
    RoomRecord,
    RoomRouteKind,
    TransferMode,
)
from home_memory_core.living_store import (
    ATTACHMENT_TABLE,
    CONTINUITY_EDGE_TABLE,
    EPISODE_TABLE,
    ROOM_TABLE,
    LivingStore,
    LivingStoreIntegrityError,
    assert_living_schema,
)
from home_memory_core.storage import MemoryStore
from home_memory_core.store_domain import StoreDomainError


class LivingStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_directory.name) / "home.sqlite3"
        MemoryStore(self.db_path).initialize()
        self.store = LivingStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def _episode(
        self,
        episode_id: str,
        *,
        perspective_instance_id: str | None = None,
        model_ref: str | None = None,
    ) -> EpisodeRecord:
        return EpisodeRecord(
            episode_id=episode_id,
            perspective_instance_id=(
                perspective_instance_id or f"perspective-{episode_id}"
            ),
            model_ref=model_ref,
        )

    def _edge(
        self,
        edge_id: str,
        previous_episode_id: str,
        next_episode_id: str,
        *,
        status: ContinuityStatus = ContinuityStatus.UNKNOWN,
        support_refs: tuple[str, ...] = (),
    ) -> ContinuityEdge:
        return ContinuityEdge(
            edge_id=edge_id,
            previous_episode_id=previous_episode_id,
            next_episode_id=next_episode_id,
            transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
            continuity_status=status,
            support_refs=support_refs,
        )

    def test_room_and_episode_round_trip_without_collapsing_perspective(self) -> None:
        room = RoomRecord(room_id="room-r")
        episode = self._episode(
            "episode-1",
            perspective_instance_id="perspective-window-a",
            model_ref="model-a",
        )

        self.store.add_room(room)
        self.store.add_episode(episode)

        self.assertEqual(self.store.get_room(room.room_id), room)
        self.assertEqual(self.store.get_episode(episode.episode_id), episode)

    def test_unknown_continuity_persists_while_episode_routes_to_same_room(self) -> None:
        room = RoomRecord(room_id="room-r")
        first = self._episode("episode-1")
        second = self._episode("episode-2")
        self.store.add_room(room)
        self.store.add_episode(first)
        self.store.add_episode(second)

        edge = self._edge(
            "edge-1-2",
            first.episode_id,
            second.episode_id,
            support_refs=("handoff-receipt-1",),
        )
        self.store.add_continuity_edge(edge)
        self.store.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-2",
                episode_id=second.episode_id,
                route_kind=RoomRouteKind.ATTACHED,
                room_id=room.room_id,
                basis="ordinary_handoff",
                support_refs=(edge.edge_id,),
            )
        )

        persisted_edge = self.store.list_continuity_edges()[0]
        resolution = self.store.resolve_room_attachment(
            episode_id=second.episode_id
        )

        self.assertEqual(
            persisted_edge.continuity_status,
            ContinuityStatus.UNKNOWN,
        )
        self.assertEqual(
            persisted_edge.support_refs,
            ("handoff-receipt-1",),
        )
        self.assertEqual(resolution.decision, "attached")
        self.assertEqual(resolution.room_id, room.room_id)

    def test_persistence_refuses_certainty_without_typed_verifier(self) -> None:
        first = self._episode("episode-certainty-a")
        second = self._episode("episode-certainty-b")
        self.store.add_episode(first)
        self.store.add_episode(second)

        for status in (
            ContinuityStatus.PARTIAL,
            ContinuityStatus.VERIFIED,
        ):
            support = (
                ("synthetic-support",)
                if status is ContinuityStatus.VERIFIED
                else ()
            )
            edge = ContinuityEdge(
                edge_id=f"edge-{status.value}",
                previous_episode_id=first.episode_id,
                next_episode_id=second.episode_id,
                transfer_mode=TransferMode.NATIVE_CHECKPOINT_RESUME,
                continuity_status=status,
                support_refs=support,
            )
            with self.assertRaises(LivingStoreIntegrityError):
                self.store.add_continuity_edge(edge)

        self.assertEqual(self.store.list_continuity_edges(), ())

    def test_late_room_correction_preserves_original_attachment(self) -> None:
        first_room = RoomRecord(room_id="room-r")
        fork_room = RoomRecord(room_id="room-r2")
        episode = self._episode("episode-38")
        self.store.add_room(first_room)
        self.store.add_room(fork_room)
        self.store.add_episode(episode)

        original = RoomAttachmentEvent(
            attachment_event_id="route-original",
            episode_id=episode.episode_id,
            route_kind=RoomRouteKind.ATTACHED,
            room_id=first_room.room_id,
            basis="ordinary_handoff",
        )
        correction = RoomAttachmentEvent(
            attachment_event_id="route-correction",
            episode_id=episode.episode_id,
            route_kind=RoomRouteKind.ATTACHED,
            room_id=fork_room.room_id,
            basis="late_fork_correction",
            supersedes_attachment_event_id=original.attachment_event_id,
            support_refs=("fork-review-1",),
        )

        self.store.add_room_attachment(original)
        self.store.add_room_attachment(correction)

        events = self.store.list_room_attachment_events(
            episode_id=episode.episode_id
        )
        resolution = self.store.resolve_room_attachment(
            episode_id=episode.episode_id
        )

        self.assertEqual(events, (original, correction))
        self.assertEqual(resolution.room_id, fork_room.room_id)
        self.assertEqual(
            resolution.active_attachment_event_id,
            correction.attachment_event_id,
        )

    def test_competing_room_corrections_remain_unresolved(self) -> None:
        for room_id in ("room-root", "room-left", "room-right"):
            self.store.add_room(RoomRecord(room_id=room_id))
        episode = self._episode("episode-forked-route")
        self.store.add_episode(episode)

        root = RoomAttachmentEvent(
            attachment_event_id="route-root",
            episode_id=episode.episode_id,
            route_kind=RoomRouteKind.ATTACHED,
            room_id="room-root",
            basis="ordinary_handoff",
        )
        left = RoomAttachmentEvent(
            attachment_event_id="route-left",
            episode_id=episode.episode_id,
            route_kind=RoomRouteKind.ATTACHED,
            room_id="room-left",
            basis="fork_candidate",
            supersedes_attachment_event_id=root.attachment_event_id,
        )
        right = RoomAttachmentEvent(
            attachment_event_id="route-right",
            episode_id=episode.episode_id,
            route_kind=RoomRouteKind.ATTACHED,
            room_id="room-right",
            basis="fork_candidate",
            supersedes_attachment_event_id=root.attachment_event_id,
        )

        self.store.add_room_attachment(root)
        self.store.add_room_attachment(left)
        self.store.add_room_attachment(right)

        resolution = self.store.resolve_room_attachment(
            episode_id=episode.episode_id
        )
        self.assertEqual(resolution.decision, "unresolved")
        self.assertIsNone(resolution.room_id)

    def test_continuity_fork_round_trips_as_topology(self) -> None:
        root = self._episode("episode-root")
        left = self._episode("episode-left")
        right = self._episode("episode-right")
        for episode in (root, left, right):
            self.store.add_episode(episode)

        self.store.add_continuity_edge(
            self._edge("edge-left", root.episode_id, left.episode_id)
        )
        self.store.add_continuity_edge(
            self._edge("edge-right", root.episode_id, right.episode_id)
        )

        topology = self.store.resolve_continuity_topology()

        self.assertEqual(
            topology.fork_episode_ids,
            frozenset({root.episode_id}),
        )
        self.assertEqual(
            topology.head_episode_ids,
            frozenset({left.episode_id, right.episode_id}),
        )

    def test_implicit_continuity_merge_is_rejected_before_commit(self) -> None:
        left = self._episode("episode-left")
        right = self._episode("episode-right")
        target = self._episode("episode-target")
        for episode in (left, right, target):
            self.store.add_episode(episode)

        self.store.add_continuity_edge(
            self._edge("edge-left", left.episode_id, target.episode_id)
        )

        with self.assertRaises(LivingStoreIntegrityError):
            self.store.add_continuity_edge(
                self._edge(
                    "edge-right",
                    right.episode_id,
                    target.episode_id,
                )
            )

        self.assertEqual(
            tuple(edge.edge_id for edge in self.store.list_continuity_edges()),
            ("edge-left",),
        )

    def test_core_living_rows_are_mechanically_append_only(self) -> None:
        room = RoomRecord(room_id="room-r")
        first = self._episode("episode-1")
        second = self._episode("episode-2")
        self.store.add_room(room)
        self.store.add_episode(first)
        self.store.add_episode(second)
        self.store.add_continuity_edge(
            self._edge("edge-1-2", first.episode_id, second.episode_id)
        )
        self.store.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-2",
                episode_id=second.episode_id,
                route_kind=RoomRouteKind.ATTACHED,
                room_id=room.room_id,
                basis="ordinary_handoff",
            )
        )

        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            attempts = (
                (
                    f"UPDATE {ROOM_TABLE} SET room_id='room-x' "
                    "WHERE room_id='room-r'"
                ),
                (
                    f"UPDATE {EPISODE_TABLE} "
                    "SET model_ref='changed' "
                    "WHERE episode_id='episode-1'"
                ),
                (
                    f"DELETE FROM {CONTINUITY_EDGE_TABLE} "
                    "WHERE edge_id='edge-1-2'"
                ),
                (
                    f"UPDATE {ATTACHMENT_TABLE} "
                    "SET basis='rewritten' "
                    "WHERE attachment_event_id='route-2'"
                ),
            )
            for statement in attempts:
                with self.assertRaises(sqlite3.DatabaseError):
                    connection.execute(statement)
                connection.rollback()
        finally:
            connection.close()

    def test_raw_sql_cannot_create_implicit_merge_or_cycle(self) -> None:
        for episode_id in ("raw-a", "raw-b", "raw-c"):
            self.store.add_episode(self._episode(episode_id))

        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute(
                f"""
                INSERT INTO {CONTINUITY_EDGE_TABLE} (
                    edge_id,
                    previous_episode_id,
                    next_episode_id,
                    transfer_mode,
                    continuity_status,
                    support_refs_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "raw-edge-a-c",
                    "raw-a",
                    "raw-c",
                    "text_context_handoff",
                    "unknown",
                    "[]",
                ),
            )
            connection.commit()

            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute(
                    f"""
                    INSERT INTO {CONTINUITY_EDGE_TABLE} (
                        edge_id,
                        previous_episode_id,
                        next_episode_id,
                        transfer_mode,
                        continuity_status,
                        support_refs_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "raw-edge-b-c",
                        "raw-b",
                        "raw-c",
                        "text_context_handoff",
                        "unknown",
                        "[]",
                    ),
                )
            connection.rollback()

            connection.execute(
                f"""
                INSERT INTO {CONTINUITY_EDGE_TABLE} (
                    edge_id,
                    previous_episode_id,
                    next_episode_id,
                    transfer_mode,
                    continuity_status,
                    support_refs_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "raw-edge-c-b",
                    "raw-c",
                    "raw-b",
                    "text_context_handoff",
                    "unknown",
                    "[]",
                ),
            )
            connection.commit()

            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute(
                    f"""
                    INSERT INTO {CONTINUITY_EDGE_TABLE} (
                        edge_id,
                        previous_episode_id,
                        next_episode_id,
                        transfer_mode,
                        continuity_status,
                        support_refs_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "raw-edge-b-a",
                        "raw-b",
                        "raw-a",
                        "text_context_handoff",
                        "unknown",
                        "[]",
                    ),
                )
            connection.rollback()
        finally:
            connection.close()

    def test_raw_sql_attachment_correction_cannot_cross_episode(self) -> None:
        self.store.add_room(RoomRecord(room_id="raw-room"))
        self.store.add_episode(self._episode("raw-episode-a"))
        self.store.add_episode(self._episode("raw-episode-b"))

        first = RoomAttachmentEvent(
            attachment_event_id="raw-route-a",
            episode_id="raw-episode-a",
            route_kind=RoomRouteKind.ATTACHED,
            room_id="raw-room",
            basis="initial_route",
        )
        self.store.add_room_attachment(first)

        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute(
                    f"""
                    INSERT INTO {ATTACHMENT_TABLE} (
                        attachment_event_id,
                        episode_id,
                        route_kind,
                        room_id,
                        basis,
                        supersedes_attachment_event_id,
                        support_refs_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "raw-route-b",
                        "raw-episode-b",
                        "attached",
                        "raw-room",
                        "invalid_cross_episode_correction",
                        first.attachment_event_id,
                        "[]",
                    ),
                )
            connection.rollback()
        finally:
            connection.close()

    def test_insert_or_replace_cannot_rewrite_immutable_history(self) -> None:
        for room_id in ("replace-room-1", "replace-room-2"):
            self.store.add_room(RoomRecord(room_id=room_id))
        for episode_id in ("replace-a", "replace-b", "replace-c"):
            self.store.add_episode(self._episode(episode_id))

        edge = self._edge(
            "replace-edge",
            "replace-a",
            "replace-b",
            support_refs=("old-support",),
        )
        route = RoomAttachmentEvent(
            attachment_event_id="replace-route",
            episode_id="replace-b",
            route_kind=RoomRouteKind.ATTACHED,
            room_id="replace-room-1",
            basis="original",
            support_refs=("old-route-support",),
        )
        self.store.add_continuity_edge(edge)
        self.store.add_room_attachment(route)

        for foreign_keys in (False, True):
            connection = sqlite3.connect(self.db_path)
            if foreign_keys:
                connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA recursive_triggers = OFF")
            try:
                with self.assertRaises(sqlite3.DatabaseError):
                    connection.execute(
                        f"""
                        INSERT OR REPLACE INTO {EPISODE_TABLE}
                        VALUES ('replace-c', 'p-forged', NULL, NULL)
                        """
                    )
                connection.rollback()
            finally:
                connection.close()

        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA recursive_triggers = OFF")
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute(
                    f"""
                    INSERT OR REPLACE INTO {CONTINUITY_EDGE_TABLE}
                    VALUES (
                        'replace-edge',
                        'replace-a',
                        'replace-b',
                        'text_context_handoff',
                        'unknown',
                        '["new-support"]'
                    )
                    """
                )
            connection.rollback()

            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute(
                    f"""
                    INSERT OR REPLACE INTO {CONTINUITY_EDGE_TABLE}
                    VALUES (
                        'replace-edge-new-id',
                        'replace-a',
                        'replace-b',
                        'text_context_handoff',
                        'unknown',
                        '["new-support"]'
                    )
                    """
                )
            connection.rollback()

            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute(
                    f"""
                    INSERT OR REPLACE INTO {ATTACHMENT_TABLE}
                    VALUES (
                        'replace-route',
                        'replace-b',
                        'attached',
                        'replace-room-2',
                        'rewritten',
                        NULL,
                        '[]'
                    )
                    """
                )
            connection.rollback()
        finally:
            connection.close()

        self.assertEqual(
            self.store.get_episode("replace-c").perspective_instance_id,
            "perspective-replace-c",
        )
        self.assertEqual(self.store.list_continuity_edges(), (edge,))
        self.assertEqual(
            self.store.list_room_attachment_events(
                episode_id="replace-b"
            ),
            (route,),
        )

    def test_polluted_reader_rejects_forged_partial_and_verified(self) -> None:
        for episode_id in (
            "certainty-a",
            "certainty-b",
            "certainty-c",
            "certainty-d",
        ):
            self.store.add_episode(self._episode(episode_id))

        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA ignore_check_constraints = ON")
        try:
            connection.execute(
                f"""
                INSERT INTO {CONTINUITY_EDGE_TABLE}
                VALUES (
                    'forged-verified',
                    'certainty-a',
                    'certainty-b',
                    'native_checkpoint_resume',
                    'verified',
                    '["made-up"]'
                )
                """
            )
            connection.execute(
                f"""
                INSERT INTO {CONTINUITY_EDGE_TABLE}
                VALUES (
                    'forged-partial',
                    'certainty-c',
                    'certainty-d',
                    'partial_state_resume',
                    'partial',
                    '[]'
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(LivingStoreIntegrityError):
            self.store.list_continuity_edges()
        with self.assertRaises(LivingStoreIntegrityError):
            self.store.resolve_continuity_topology()

    def test_same_name_noop_trigger_fails_schema_validation(self) -> None:
        self.store.add_episode(self._episode("trigger-episode"))

        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("DROP TRIGGER living_episodes_no_update")
            connection.execute(
                f"""
                CREATE TRIGGER living_episodes_no_update
                BEFORE UPDATE ON {EPISODE_TABLE}
                BEGIN
                    SELECT 1;
                END
                """
            )
            connection.execute(
                f"""
                UPDATE {EPISODE_TABLE}
                SET perspective_instance_id = 'p-stolen'
                WHERE episode_id = 'trigger-episode'
                """
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(LivingStoreIntegrityError):
            self.store.get_episode("trigger-episode")

    def test_generated_identity_column_fails_closed(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                f"""
                ALTER TABLE {EPISODE_TABLE}
                ADD COLUMN same_self INTEGER
                GENERATED ALWAYS AS (1) VIRTUAL
                """
            )
            connection.commit()
            with self.assertRaises(LivingStoreIntegrityError):
                assert_living_schema(connection)
        finally:
            connection.close()

    def test_invalid_room_row_is_rejected_even_if_check_was_bypassed(self) -> None:
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA ignore_check_constraints = ON")
        try:
            connection.execute(
                f"INSERT INTO {ROOM_TABLE} (room_id) VALUES ('')"
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(LivingStoreIntegrityError):
            self.store.get_room("")

    def test_phantom_routing_fails_closed_on_normal_resolver(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                f"""
                INSERT INTO {ATTACHMENT_TABLE} (
                    attachment_event_id,
                    episode_id,
                    route_kind,
                    room_id,
                    basis,
                    supersedes_attachment_event_id,
                    support_refs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "ghost-route",
                    "ghost-episode",
                    "attached",
                    "ghost-room",
                    "ordinary_handoff",
                    None,
                    "[]",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(LivingStoreIntegrityError):
            self.store.resolve_room_attachment(
                episode_id="ghost-episode"
            )

    def test_schema_drift_with_extra_identity_column_fails_closed(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                f"ALTER TABLE {EPISODE_TABLE} ADD COLUMN same_self TEXT"
            )
            connection.commit()
            with self.assertRaises(LivingStoreIntegrityError):
                assert_living_schema(connection)
        finally:
            connection.close()

    def test_living_store_refuses_unmarked_database(self) -> None:
        other_path = Path(self.temp_directory.name) / "unmarked.sqlite3"
        sqlite3.connect(other_path).close()

        with self.assertRaises(StoreDomainError):
            LivingStore(other_path).initialize()

    def test_schema_contains_no_same_self_column(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            for table in (
                ROOM_TABLE,
                EPISODE_TABLE,
                CONTINUITY_EDGE_TABLE,
                ATTACHMENT_TABLE,
            ):
                columns = {
                    row[1]
                    for row in connection.execute(
                        f"PRAGMA table_xinfo({table})"
                    ).fetchall()
                }
                self.assertNotIn("same_self", columns)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
