from datetime import timedelta
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
from home_memory_core.current_view import (
    CurrentNamespace,
    CurrentStateKind,
    CurrentStateRecord,
    DowngradeRule,
    SemanticChangeAuthority,
    ValidityRule,
)
from home_memory_core.evidence import EvidenceRef
from home_memory_core.living_continuity import (
    RoomAttachmentEvent,
    RoomRecord,
    RoomRouteKind,
)
from home_memory_core.model_execution_contract import (
    open_model_execution_contract_boundary,
)
from home_memory_core.recent_life import (
    RECENT_LIFE_HORIZON,
    RECENT_LIFE_POLICY_V0_1,
    RecentLifeError,
    RecentLifeEvent,
)
from home_memory_core.suppression import (
    create_timed_suppression_record,
)
from home_memory_core.wake_issuance import (
    open_wake_issuance_authority,
)
from home_memory_core.wake_local_handoff import (
    open_wake_local_handoff_authority,
)
from home_memory_core.wake_model_input import (
    open_wake_model_input_boundary,
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


class RecentLifeWakeTests(unittest.TestCase):
    def _recent_issuer(self, fixture):
        return open_wake_issuance_authority(
            living_store=fixture.living,
            current_resolver=fixture.resolver,
            clock=first_wake_lab.FixedClock(
                first_wake_lab.FIXED_AS_OF
            ),
            recent_life_policy=(
                RECENT_LIFE_POLICY_V0_1
            ),
        )

    def _suppress_fixture_recent_sources(
        self,
        fixture,
    ) -> None:
        for index, source_id in enumerate(
            (
                "src-ref-state-home-founding",
                "src-ref-state-lantern-project",
                "src-ref-state-blue-cup",
                "src-ref-state-lantern-placement",
            )
        ):
            effective = (
                first_wake_lab.FIXED_AS_OF
                - timedelta(minutes=30)
            )
            fixture.memory.suppress_source(
                create_timed_suppression_record(
                    suppression_id=(
                        f"suppress-fixture-{index}"
                    ),
                    source_id=source_id,
                    requested_by="synthetic-test",
                    reason="recent-life test holdback",
                    effective_at=effective,
                    recorded_at=effective,
                )
            )

    def test_existing_first_wake_without_policy_remains_v01(
        self,
    ) -> None:
        with first_wake_lab.SyntheticFirstWakeFixture() as fixture:
            issued = fixture.issuer.issue(
                episode_id=first_wake_lab.FIRST_WAKE_EPISODE_ID
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

    def test_live_admitted_current_projects_exact_recent_life(
        self,
    ) -> None:
        with first_wake_lab.SyntheticFirstWakeFixture() as fixture:
            issuer = self._recent_issuer(fixture)
            issued = issuer.issue(
                episode_id=first_wake_lab.FIRST_WAKE_EPISODE_ID
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
                4,
            )

            for item in packet.recent_life.items:
                self.assertTrue(
                    item.state_id.startswith("state-")
                )
                self.assertTrue(
                    item.admission_id
                )
                self.assertEqual(
                    item.room_id,
                    first_wake_lab.ROOM_ID,
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
                    item.room_attachment_event_id,
                    "route-before-wake",
                )
                self.assertEqual(
                    len(item.evidence),
                    1,
                )
                evidence = item.evidence[0]
                self.assertEqual(
                    len(evidence.source_sha256),
                    64,
                )
                self.assertEqual(
                    evidence.start_char,
                    0,
                )
                self.assertGreater(
                    evidence.end_char,
                    evidence.start_char,
                )
                self.assertEqual(
                    item.source_refs,
                    (evidence.source_id,),
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
                authority=issuer,
                issued=issued,
            )
            self.assertEqual(
                plan.presentation_version,
                WAKE_PRESENTATION_VERSION_V0_2,
            )
            recent_layer = next(
                layer
                for layer in plan.layers
                if layer.layer is WakeLayer.RECENT_LIFE
            )
            self.assertEqual(
                len(recent_layer.blocks),
                4,
            )
            for block in recent_layer.blocks:
                self.assertEqual(
                    block.policy.authority_ceiling.value,
                    "describe_only",
                )
                self.assertEqual(
                    block.policy.pronoun_policy.value,
                    "no_current_first_person",
                )
                self.assertEqual(
                    len(block.evidence),
                    1,
                )

            rendered = render_wake_presentation(
                authority=issuer,
                issued=issued,
                plan=plan,
            )
            payload = json.loads(rendered.payload_json)
            recent_payload = next(
                layer
                for layer in payload["presentation"]["layers"]
                if layer["layer"] == "recent_life"
            )
            first = recent_payload["blocks"][0]
            self.assertIn(
                "state_id",
                first,
            )
            self.assertIn(
                "admission_id",
                first,
            )
            self.assertEqual(
                len(first["evidence"]),
                1,
            )
            self.assertEqual(
                len(first["evidence"][0]["source_sha256"]),
                64,
            )

    def test_recent_life_crosses_model_input_without_authority(
        self,
    ) -> None:
        with first_wake_lab.SyntheticFirstWakeFixture() as fixture:
            issuer = self._recent_issuer(fixture)
            handoff = open_wake_local_handoff_authority(
                wake_issuance_authority=issuer,
            )
            model_input = open_wake_model_input_boundary(
                local_transport_boundary=handoff.local_transport_boundary,
            )
            handoff_receipt = handoff.handoff(
                request_id="recent-life-model-input-test",
                episode_id=first_wake_lab.FIRST_WAKE_EPISODE_ID,
                user_input=first_wake_lab.FIRST_WAKE_USER_TURN,
            )
            constructed = model_input.construct(
                handoff_receipt=handoff_receipt,
            )
            contract = open_model_execution_contract_boundary(
                model_input_boundary=model_input,
            )
            prepared = contract.prepare(
                construction_receipt=constructed.receipt,
            )
            payload = json.loads(
                constructed.request.wake_context.payload_json
            )
            recent = next(
                layer
                for layer in payload["presentation"]["layers"]
                if layer["layer"] == "recent_life"
            )
            self.assertEqual(
                recent["availability"],
                "ready",
            )
            self.assertEqual(
                len(recent["blocks"]),
                4,
            )
            self.assertEqual(
                prepared.preparation.request
                .wake_data.value.payload_json,
                constructed.request.wake_context.payload_json,
            )
            for boundary in (
                constructed.request.use_boundary,
                prepared.preparation.request.use_boundary,
            ):
                for name in (
                    "instruction_authority",
                    "current_first_person_speech_authority",
                    "identity_continuity_claim_authority",
                    "relationship_claim_authority",
                    "model_delivery_authority",
                    "memory_write_authority",
                ):
                    self.assertIs(
                        getattr(boundary, name),
                        WakeAuthority.NONE,
                    )

    def test_source_suppression_removes_only_affected_recent_state(
        self,
    ) -> None:
        with first_wake_lab.SyntheticFirstWakeFixture() as fixture:
            effective = (
                first_wake_lab.FIXED_AS_OF
                - timedelta(minutes=30)
            )
            fixture.memory.suppress_source(
                create_timed_suppression_record(
                    suppression_id="suppress-lantern-project-recent",
                    source_id="src-ref-state-lantern-project",
                    requested_by="synthetic-test",
                    reason="recent-life suppression check",
                    effective_at=effective,
                    recorded_at=effective,
                )
            )
            issued = self._recent_issuer(fixture).issue(
                episode_id=first_wake_lab.FIRST_WAKE_EPISODE_ID
            )
            ids = {
                item.state_id
                for item in issued.packet.recent_life.items
            }
            self.assertNotIn(
                "state-lantern-project",
                ids,
            )
            self.assertEqual(
                len(ids),
                3,
            )

    def test_superseded_previous_episode_route_does_not_leak_old_room_recent_life(
        self,
    ) -> None:
        with first_wake_lab.SyntheticFirstWakeFixture() as fixture:
            fixture.living.add_room(
                RoomRecord(room_id="room-corrected")
            )
            fixture.living.add_room_attachment(
                RoomAttachmentEvent(
                    attachment_event_id="route-before-wake-corrected",
                    episode_id=first_wake_lab.PREVIOUS_EPISODE_ID,
                    route_kind=RoomRouteKind.ATTACHED,
                    room_id="room-corrected",
                    basis="synthetic late route correction",
                    supersedes_attachment_event_id="route-before-wake",
                )
            )
            issued = self._recent_issuer(fixture).issue(
                episode_id=first_wake_lab.FIRST_WAKE_EPISODE_ID
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

    def test_old_but_still_standing_current_state_is_not_recent(
        self,
    ) -> None:
        with first_wake_lab.SyntheticFirstWakeFixture() as fixture:
            self._suppress_fixture_recent_sources(
                fixture
            )
            binding = fixture._source_binding(
                ref="old-recent-candidate",
                content=(
                    "synthetic old Current evidence that remains standing"
                ),
            )
            old_time = (
                first_wake_lab.FIXED_AS_OF
                - RECENT_LIFE_HORIZON
                - timedelta(seconds=1)
            )
            record = CurrentStateRecord(
                state_id="state-old-still-standing",
                namespace=CurrentNamespace.ROOM,
                owner_id=first_wake_lab.ROOM_ID,
                key="project.old_standing",
                state_kind=CurrentStateKind.PROJECT_STATUS,
                value="Old standing state must not become Recent Life.",
                event_time=old_time,
                recorded_at=old_time,
                valid_from=old_time,
                validity_rule=ValidityRule.DURABLE_UNTIL_CHANGED,
                downgrade_rule=DowngradeRule.NONE,
                semantic_change_authority=(
                    SemanticChangeAuthority.ROOM_FIRST_PERSON
                ),
                episode_id=first_wake_lab.PREVIOUS_EPISODE_ID,
                perspective_instance_id=(
                    first_wake_lab.PREVIOUS_PERSPECTIVE_ID
                ),
                source_refs=("old-recent-candidate",),
            )
            fixture.admission.admit_room_state(
                record=record,
                source_bindings=(binding,),
                grant=fixture.previous_grant,
            )
            issued = self._recent_issuer(fixture).issue(
                episode_id=first_wake_lab.FIRST_WAKE_EPISODE_ID
            )
            self.assertEqual(
                issued.packet.recent_life.items,
                (),
            )
            self.assertEqual(
                issued.packet.recent_life.reason_codes,
                ("NO_RECENT_LIFE_IN_WINDOW",),
            )

    def test_recent_life_event_cannot_be_caller_minted(
        self,
    ) -> None:
        with self.assertRaises(RecentLifeError):
            RecentLifeEvent(
                event_id="caller-event",
                state_id="caller-state",
                admission_id="caller-admission",
                room_id="room-x",
                episode_id="episode-x",
                perspective_instance_id="perspective-x",
                room_attachment_event_id="route-x",
                key="project.x",
                state_kind="project_status",
                summary="caller text",
                occurred_at=first_wake_lab.FIXED_AS_OF,
                recorded_at=first_wake_lab.FIXED_AS_OF,
                evidence=(
                    EvidenceRef(
                        source_id="source-x",
                        source_sha256="0" * 64,
                        start_char=0,
                        end_char=1,
                    ),
                ),
                _marker=object(),
            )


if __name__ == "__main__":
    unittest.main()
