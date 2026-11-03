from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
TESTS_ROOT = REPO_ROOT / "tests"
for _path in (str(SRC_ROOT), str(TESTS_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import first_wake_lab
from home_memory_core.recent_life import (
    RecentLifeError,
    RecentLifeEvent,
    RecentLifeStore,
)
from home_memory_core.suppression import (
    create_timed_suppression_record,
)
from home_memory_core.wake_packet import (
    WAKE_PACKET_VERSION,
    WAKE_PACKET_VERSION_V0_2,
    WakeAuthority,
    WakeLayer,
    WakeLayerAvailability,
)
from home_memory_core.wake_presentation import (
    WAKE_PRESENTATION_VERSION_V0_2,
    build_wake_presentation_plan,
    render_wake_presentation,
)


UTC = timezone.utc


class RecentLifeWakeTests(unittest.TestCase):
    def _event(self) -> RecentLifeEvent:
        return RecentLifeEvent(
            event_id="recent-last-lantern-session",
            room_id=first_wake_lab.ROOM_ID,
            episode_id=(
                first_wake_lab.PREVIOUS_EPISODE_ID
            ),
            perspective_instance_id=(
                first_wake_lab.PREVIOUS_PERSPECTIVE_ID
            ),
            summary=(
                "During the previous work session, "
                "Aster and Niko completed the Lantern Atlas "
                "wiring test and stopped with the paper shade "
                "still unfinished."
            ),
            occurred_at=datetime(
                2026,
                10,
                21,
                22,
                0,
                tzinfo=UTC,
            ),
            recorded_at=datetime(
                2026,
                10,
                21,
                22,
                5,
                tzinfo=UTC,
            ),
            source_refs=(
                "src-ref-state-lantern-project",
            ),
        )

    def test_existing_first_wake_without_recent_store_remains_v01(
        self,
    ) -> None:
        with (
            first_wake_lab.SyntheticFirstWakeFixture()
            as fixture
        ):
            issued = fixture.issuer.issue(
                episode_id=(
                    first_wake_lab.FIRST_WAKE_EPISODE_ID
                )
            )
            self.assertEqual(
                issued.packet.packet_version,
                WAKE_PACKET_VERSION,
            )
            self.assertEqual(
                issued.packet.recent_life.availability,
                WakeLayerAvailability.UNAVAILABLE,
            )
            self.assertEqual(
                issued.packet.recent_life.reason_codes,
                ("NO_TYPED_RECENT_LIFE_PRODUCER",),
            )

    def test_canonical_recent_store_upgrades_wake_and_presentation(
        self,
    ) -> None:
        with (
            first_wake_lab.SyntheticFirstWakeFixture()
            as fixture
        ):
            recent = RecentLifeStore(
                fixture.db
            )
            recent.initialize()
            event = self._event()
            recent.add_event(event)

            with self.assertRaises(
                RecentLifeError
            ):
                recent.add_event(event)

            issued = fixture.issuer.issue(
                episode_id=(
                    first_wake_lab.FIRST_WAKE_EPISODE_ID
                )
            )
            packet = issued.packet
            self.assertEqual(
                packet.packet_version,
                WAKE_PACKET_VERSION_V0_2,
            )
            self.assertEqual(
                packet.recent_life.availability,
                WakeLayerAvailability.READY,
            )
            self.assertEqual(
                len(packet.recent_life.items),
                1,
            )
            item = packet.recent_life.items[0]
            self.assertEqual(
                item.event_id,
                event.event_id,
            )
            self.assertEqual(
                item.episode_id,
                first_wake_lab.PREVIOUS_EPISODE_ID,
            )
            self.assertEqual(
                item.perspective_instance_id,
                first_wake_lab.PREVIOUS_PERSPECTIVE_ID,
            )
            self.assertEqual(
                item.source_refs,
                event.source_refs,
            )
            for name in (
                "instruction_authority",
                "current_first_person_speech_authority",
                "identity_continuity_claim_authority",
                "relationship_claim_authority",
                "model_delivery_authority",
                "memory_write_authority",
            ):
                self.assertIs(
                    getattr(item.use_boundary, name),
                    WakeAuthority.NONE,
                )

            plan = build_wake_presentation_plan(
                authority=fixture.issuer,
                issued=issued,
            )
            self.assertEqual(
                plan.presentation_version,
                WAKE_PRESENTATION_VERSION_V0_2,
            )
            recent_layer = next(
                layer
                for layer in plan.layers
                if layer.layer
                is WakeLayer.RECENT_LIFE
            )
            self.assertEqual(
                recent_layer.availability,
                WakeLayerAvailability.READY,
            )
            self.assertEqual(
                len(recent_layer.blocks),
                1,
            )
            block = recent_layer.blocks[0]
            self.assertEqual(
                block.summary,
                event.summary,
            )
            self.assertEqual(
                block.episode_id,
                first_wake_lab.PREVIOUS_EPISODE_ID,
            )
            self.assertEqual(
                block.perspective_instance_id,
                first_wake_lab.PREVIOUS_PERSPECTIVE_ID,
            )
            self.assertEqual(
                block.policy.authority_ceiling.value,
                "describe_only",
            )
            self.assertEqual(
                block.policy.pronoun_policy.value,
                "no_current_first_person",
            )

            rendered = render_wake_presentation(
                authority=fixture.issuer,
                issued=issued,
                plan=plan,
            )
            payload = json.loads(
                rendered.payload_json
            )
            recent_payload = next(
                layer
                for layer in payload[
                    "presentation"
                ]["layers"]
                if layer["layer"] == "recent_life"
            )
            self.assertEqual(
                recent_payload["availability"],
                "ready",
            )
            self.assertEqual(
                recent_payload["blocks"][0][
                    "summary"
                ],
                event.summary,
            )
            self.assertEqual(
                recent_payload["blocks"][0][
                    "source_refs"
                ],
                list(event.source_refs),
            )

    def test_suppressed_source_removes_recent_event_from_wake(
        self,
    ) -> None:
        with (
            first_wake_lab.SyntheticFirstWakeFixture()
            as fixture
        ):
            recent = RecentLifeStore(
                fixture.db
            )
            recent.initialize()
            recent.add_event(
                self._event()
            )
            fixture.memory.suppress_source(
                create_timed_suppression_record(
                    suppression_id=(
                        "suppress-recent-source"
                    ),
                    source_id=(
                        "src-ref-state-lantern-project"
                    ),
                    requested_by=(
                        "synthetic-test"
                    ),
                    reason=(
                        "synthetic stop-use check"
                    ),
                    effective_at=datetime(
                        2026,
                        10,
                        21,
                        23,
                        0,
                        tzinfo=UTC,
                    ),
                    recorded_at=datetime(
                        2026,
                        10,
                        21,
                        23,
                        1,
                        tzinfo=UTC,
                    ),
                )
            )

            issued = fixture.issuer.issue(
                episode_id=(
                    first_wake_lab.FIRST_WAKE_EPISODE_ID
                )
            )
            self.assertEqual(
                issued.packet.packet_version,
                WAKE_PACKET_VERSION_V0_2,
            )
            self.assertEqual(
                issued.packet.recent_life.availability,
                WakeLayerAvailability.READY,
            )
            self.assertEqual(
                issued.packet.recent_life.items,
                (),
            )
            self.assertEqual(
                issued.packet.recent_life.reason_codes,
                ("NO_RECENT_LIFE_IN_WINDOW",),
            )


if __name__ == "__main__":
    unittest.main()
