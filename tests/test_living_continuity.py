import dataclasses
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


from home_memory_core.living_continuity import (
    ContinuityEdge,
    ContinuityStatus,
    EpisodeRecord,
    LivingContinuityError,
    RoomAttachmentEvent,
    RoomRecord,
    RoomRouteKind,
    TransferMode,
    resolve_room_attachment,
)


class LivingContinuityTest(unittest.TestCase):
    def test_unknown_continuity_can_route_next_episode_to_same_room(self) -> None:
        room = RoomRecord(room_id="room-r")
        first = EpisodeRecord(
            episode_id="episode-31",
            perspective_instance_id="perspective-31",
        )
        second = EpisodeRecord(
            episode_id="episode-32",
            perspective_instance_id="perspective-32",
        )
        edge = ContinuityEdge(
            edge_id="edge-31-32",
            previous_episode_id=first.episode_id,
            next_episode_id=second.episode_id,
            transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
            continuity_status=ContinuityStatus.UNKNOWN,
            evidence_refs=("handoff-receipt-1",),
        )
        attachment = RoomAttachmentEvent(
            attachment_event_id="attachment-32",
            episode_id=second.episode_id,
            route_kind=RoomRouteKind.ATTACHED,
            room_id=room.room_id,
            basis="ordinary_handoff",
            evidence_refs=(edge.edge_id,),
        )

        resolution = resolve_room_attachment(
            episode_id=second.episode_id,
            events=(attachment,),
        )

        self.assertEqual(edge.continuity_status, ContinuityStatus.UNKNOWN)
        self.assertEqual(resolution.decision, "attached")
        self.assertEqual(resolution.room_id, room.room_id)

    def test_room_route_does_not_encode_same_self_verdict(self) -> None:
        continuity_fields = {
            field.name for field in dataclasses.fields(ContinuityEdge)
        }
        attachment_fields = {
            field.name for field in dataclasses.fields(RoomAttachmentEvent)
        }

        self.assertNotIn("same_self", continuity_fields)
        self.assertNotIn("same_self", attachment_fields)
        self.assertNotIn("identity", continuity_fields)
        self.assertNotIn("identity", attachment_fields)

    def test_native_checkpoint_mode_does_not_force_verified_status(self) -> None:
        edge = ContinuityEdge(
            edge_id="checkpoint-edge",
            previous_episode_id="episode-a",
            next_episode_id="episode-b",
            transfer_mode=TransferMode.NATIVE_CHECKPOINT_RESUME,
            continuity_status=ContinuityStatus.UNKNOWN,
        )

        self.assertEqual(
            edge.transfer_mode,
            TransferMode.NATIVE_CHECKPOINT_RESUME,
        )
        self.assertEqual(edge.continuity_status, ContinuityStatus.UNKNOWN)

    def test_late_fork_correction_preserves_old_attachment_event(self) -> None:
        original = RoomAttachmentEvent(
            attachment_event_id="attach-original",
            episode_id="episode-38",
            route_kind=RoomRouteKind.ATTACHED,
            room_id="room-r",
            basis="ordinary_handoff",
        )
        correction = RoomAttachmentEvent(
            attachment_event_id="attach-correction",
            episode_id="episode-38",
            route_kind=RoomRouteKind.ATTACHED,
            room_id="room-r2",
            basis="late_fork_correction",
            supersedes_attachment_event_id=original.attachment_event_id,
            evidence_refs=("fork-evidence-1",),
        )

        resolution = resolve_room_attachment(
            episode_id="episode-38",
            events=(original, correction),
        )

        self.assertEqual(original.room_id, "room-r")
        self.assertEqual(
            correction.supersedes_attachment_event_id,
            original.attachment_event_id,
        )
        self.assertEqual(resolution.decision, "attached")
        self.assertEqual(resolution.room_id, "room-r2")
        self.assertEqual(
            resolution.active_attachment_event_id,
            correction.attachment_event_id,
        )

    def test_explicit_unattachment_can_supersede_prior_room_route(self) -> None:
        original = RoomAttachmentEvent(
            attachment_event_id="attach-original",
            episode_id="episode-44",
            route_kind=RoomRouteKind.ATTACHED,
            room_id="room-r",
            basis="ordinary_handoff",
        )
        correction = RoomAttachmentEvent(
            attachment_event_id="attach-none",
            episode_id="episode-44",
            route_kind=RoomRouteKind.UNATTACHED,
            room_id=None,
            basis="route_correction",
            supersedes_attachment_event_id=original.attachment_event_id,
        )

        resolution = resolve_room_attachment(
            episode_id="episode-44",
            events=(original, correction),
        )

        self.assertEqual(resolution.decision, "unattached")
        self.assertIsNone(resolution.room_id)
        self.assertEqual(
            resolution.active_attachment_event_id,
            correction.attachment_event_id,
        )

    def test_competing_attachment_heads_stay_unresolved(self) -> None:
        root = RoomAttachmentEvent(
            attachment_event_id="attach-root",
            episode_id="episode-51",
            route_kind=RoomRouteKind.ATTACHED,
            room_id="room-r",
            basis="ordinary_handoff",
        )
        left = RoomAttachmentEvent(
            attachment_event_id="attach-left",
            episode_id="episode-51",
            route_kind=RoomRouteKind.ATTACHED,
            room_id="room-left",
            basis="fork_candidate",
            supersedes_attachment_event_id=root.attachment_event_id,
        )
        right = RoomAttachmentEvent(
            attachment_event_id="attach-right",
            episode_id="episode-51",
            route_kind=RoomRouteKind.ATTACHED,
            room_id="room-right",
            basis="fork_candidate",
            supersedes_attachment_event_id=root.attachment_event_id,
        )

        resolution = resolve_room_attachment(
            episode_id="episode-51",
            events=(root, left, right),
        )

        self.assertEqual(resolution.decision, "unresolved")
        self.assertIsNone(resolution.room_id)
        self.assertIn(
            "MULTIPLE_ACTIVE_ATTACHMENT_HEADS",
            resolution.reason_codes,
        )

    def test_cross_episode_attachment_supersession_is_rejected(self) -> None:
        first = RoomAttachmentEvent(
            attachment_event_id="attach-a",
            episode_id="episode-a",
            route_kind=RoomRouteKind.ATTACHED,
            room_id="room-a",
            basis="ordinary_handoff",
        )
        second = RoomAttachmentEvent(
            attachment_event_id="attach-b",
            episode_id="episode-b",
            route_kind=RoomRouteKind.ATTACHED,
            room_id="room-b",
            basis="route_correction",
            supersedes_attachment_event_id=first.attachment_event_id,
        )

        with self.assertRaises(LivingContinuityError):
            resolve_room_attachment(
                episode_id="episode-b",
                events=(first, second),
            )

    def test_continuity_edge_rejects_self_loop(self) -> None:
        with self.assertRaises(LivingContinuityError):
            ContinuityEdge(
                edge_id="edge-self",
                previous_episode_id="episode-a",
                next_episode_id="episode-a",
                transfer_mode=TransferMode.LIVE_RUNTIME,
                continuity_status=ContinuityStatus.VERIFIED,
            )

    def test_multiple_episodes_can_keep_distinct_perspectives_in_one_room(self) -> None:
        room = RoomRecord(room_id="room-r")
        first = EpisodeRecord(
            episode_id="episode-1",
            perspective_instance_id="perspective-a",
        )
        second = EpisodeRecord(
            episode_id="episode-2",
            perspective_instance_id="perspective-b",
        )
        first_route = RoomAttachmentEvent(
            attachment_event_id="route-1",
            episode_id=first.episode_id,
            route_kind=RoomRouteKind.ATTACHED,
            room_id=room.room_id,
            basis="initial_room_route",
        )
        second_route = RoomAttachmentEvent(
            attachment_event_id="route-2",
            episode_id=second.episode_id,
            route_kind=RoomRouteKind.ATTACHED,
            room_id=room.room_id,
            basis="ordinary_handoff",
        )

        self.assertNotEqual(
            first.perspective_instance_id,
            second.perspective_instance_id,
        )
        self.assertEqual(
            resolve_room_attachment(
                episode_id=first.episode_id,
                events=(first_route, second_route),
            ).room_id,
            room.room_id,
        )
        self.assertEqual(
            resolve_room_attachment(
                episode_id=second.episode_id,
                events=(first_route, second_route),
            ).room_id,
            room.room_id,
        )


if __name__ == "__main__":
    unittest.main()
