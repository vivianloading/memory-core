import unittest
from datetime import datetime, timedelta, timezone

from home_memory_core.current_resolver import (
    CurrentResolvedView,
    CurrentResolverDecision,
    CurrentResolverDependency,
    CurrentResolverStatus,
)
from home_memory_core.current_use import (
    CurrentSuppressionBlock,
    CurrentUseEffectKind,
)
from home_memory_core.current_view import (
    CurrentCandidate,
    CurrentNamespace,
    CurrentResolution,
    CurrentStanding,
    CurrentStateKind,
    CurrentStateRecord,
    DowngradeRule,
    SemanticChangeAuthority,
    ValidityRule,
)
from home_memory_core.living_continuity import (
    ContinuityEdge,
    ContinuityStatus,
    EpisodeRecord,
    RoomAttachmentResolution,
    TransferMode,
)
from home_memory_core.wake_packet import (
    WakeAuthority,
    WakeLayer,
    WakeLayerAvailability,
    WakePacketError,
    WakePrivacyScopeKind,
    assemble_wake_packet_v0_1,
)


UTC = timezone.utc


class WakePacketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.t0 = datetime(2026, 10, 5, 9, tzinfo=UTC)
        self.episode = EpisodeRecord(
            episode_id="episode-wake",
            perspective_instance_id="perspective-wake",
            runtime_instance_id="runtime-wake",
        )
        self.route = RoomAttachmentResolution(
            episode_id=self.episode.episode_id,
            decision="attached",
            room_id="room-wake",
            active_attachment_event_id="route-wake",
        )
        self.edge = ContinuityEdge(
            edge_id="edge-previous-wake",
            previous_episode_id="episode-previous",
            next_episode_id=self.episode.episode_id,
            transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
            continuity_status=ContinuityStatus.UNKNOWN,
        )

    def state(
        self,
        state_id: str,
        *,
        key: str = "project.status",
        value: str = "building",
    ) -> CurrentStateRecord:
        return CurrentStateRecord(
            state_id=state_id,
            namespace=CurrentNamespace.ROOM,
            owner_id="room-wake",
            key=key,
            state_kind=CurrentStateKind.PROJECT_STATUS,
            value=value,
            event_time=self.t0,
            recorded_at=self.t0,
            valid_from=self.t0,
            validity_rule=ValidityRule.DURABLE_UNTIL_CHANGED,
            downgrade_rule=DowngradeRule.NONE,
            semantic_change_authority=(
                SemanticChangeAuthority.ROOM_FIRST_PERSON
            ),
            episode_id=self.episode.episode_id,
            perspective_instance_id=(
                self.episode.perspective_instance_id
            ),
            source_refs=(f"ref-{state_id}",),
        )

    def resolved_decision(
        self,
        *,
        state_id: str = "state-current",
        key: str = "project.status",
        value: str = "building",
        standing: CurrentStanding = CurrentStanding.CURRENT,
        candidates: tuple[CurrentCandidate, ...] | None = None,
    ) -> CurrentResolverDecision:
        if candidates is None:
            record = self.state(
                state_id,
                key=key,
                value=value,
            )
            candidates = (
                CurrentCandidate(
                    record=record,
                    end_events=(),
                    standing=standing,
                    reason_codes=("CANDIDATE",),
                ),
            )
        semantic = CurrentResolution(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-wake",
            key=key,
            standing=standing,
            current_state_ids=tuple(
                candidate.state_id
                for candidate in candidates
                if candidate.standing in {
                    CurrentStanding.CURRENT,
                    CurrentStanding.LAST_KNOWN,
                    CurrentStanding.UNRESOLVED,
                }
            ),
            historical_state_ids=(),
            future_state_ids=(),
            candidates=candidates,
            reason_codes=("SEMANTIC_RESULT",),
        )
        return CurrentResolverDecision(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-wake",
            key=key,
            as_of=self.t0,
            status=CurrentResolverStatus.RESOLVED,
            semantic_resolution=semantic,
            dependencies=tuple(
                CurrentResolverDependency(
                    effect_kind=CurrentUseEffectKind.STATE,
                    effect_id=candidate.state_id,
                )
                for candidate in candidates
            ),
            blocks=(),
            missing_live_admission_effects=(),
            reason_codes=("SEMANTIC_DEPENDENCIES_USABLE",),
        )

    def view(
        self,
        *decisions: CurrentResolverDecision,
        as_of: datetime | None = None,
    ) -> CurrentResolvedView:
        return CurrentResolvedView(
            as_of=as_of or self.t0,
            namespace=CurrentNamespace.ROOM,
            owner_id="room-wake",
            items=tuple(decisions),
        )

    def assemble(self, *, room_current=None):
        return assemble_wake_packet_v0_1(
            wake_id="wake-1",
            as_of=self.t0,
            episode=self.episode,
            route=self.route,
            continuity_edges=(self.edge,),
            room_current=room_current,
        )

    def test_map_carries_route_and_perspective_without_identity_claim(self) -> None:
        packet, receipt = self.assemble(
            room_current=self.view()
        )

        item = packet.map.item
        self.assertEqual(
            packet.map.availability,
            WakeLayerAvailability.READY,
        )
        self.assertEqual(item.episode_id, "episode-wake")
        self.assertEqual(
            item.perspective_instance_id,
            "perspective-wake",
        )
        self.assertEqual(item.room_id, "room-wake")
        self.assertEqual(
            item.privacy_scope.kind,
            WakePrivacyScopeKind.EPISODE,
        )
        self.assertEqual(
            item.incoming_continuity.continuity_status,
            "unknown",
        )
        self.assertEqual(
            item.use_boundary.identity_continuity_claim_authority,
            WakeAuthority.NONE,
        )
        self.assertEqual(
            receipt.included_item_ids,
            ("map:episode-wake",),
        )

    def test_wake_use_boundary_rejects_caller_minted_authority(self) -> None:
        from home_memory_core.wake_packet import WakeUseBoundary

        with self.assertRaises(WakePacketError):
            WakeUseBoundary(
                current_first_person_speech_authority="granted",
            )
        with self.assertRaises(WakePacketError):
            WakeUseBoundary(memory_write_authority="granted")

    def test_five_layers_are_explicit_even_when_not_implemented(self) -> None:
        packet, receipt = self.assemble(
            room_current=self.view()
        )

        self.assertEqual(
            packet.shared_now.availability,
            WakeLayerAvailability.CLOSED,
        )
        self.assertEqual(
            packet.shared_now.reason_codes,
            ("SHARED_OPERATIONAL_CURRENT_CLOSED",),
        )
        self.assertEqual(
            packet.recent_life.availability,
            WakeLayerAvailability.UNAVAILABLE,
        )
        self.assertEqual(
            packet.nearby_doors.availability,
            WakeLayerAvailability.UNAVAILABLE,
        )
        self.assertEqual(
            tuple(layer for layer, _ in receipt.layer_availability),
            (
                WakeLayer.MAP,
                WakeLayer.SHARED_NOW,
                WakeLayer.ROOM_NOW,
                WakeLayer.RECENT_LIFE,
                WakeLayer.NEARBY_DOORS,
            ),
        )

    def test_resolved_room_current_keeps_attribution_and_has_no_speech_authority(self) -> None:
        decision = self.resolved_decision()
        packet, receipt = self.assemble(
            room_current=self.view(decision)
        )

        self.assertEqual(
            packet.room_now.availability,
            WakeLayerAvailability.READY,
        )
        self.assertEqual(len(packet.room_now.items), 1)
        item = packet.room_now.items[0]
        self.assertEqual(item.key, "project.status")
        self.assertEqual(item.standing, CurrentStanding.CURRENT)
        self.assertEqual(item.candidates[0].value, "building")
        self.assertEqual(
            item.candidates[0].perspective_instance_id,
            "perspective-wake",
        )
        self.assertEqual(
            item.candidates[0].semantic_change_authority,
            "room_first_person",
        )
        self.assertEqual(
            item.candidates[0].source_refs,
            ("ref-state-current",),
        )
        self.assertEqual(
            item.use_boundary.current_first_person_speech_authority,
            WakeAuthority.NONE,
        )
        self.assertEqual(
            item.use_boundary.instruction_authority,
            WakeAuthority.NONE,
        )
        self.assertEqual(
            item.use_boundary.model_delivery_authority,
            WakeAuthority.NONE,
        )
        self.assertEqual(
            item.use_boundary.memory_write_authority,
            WakeAuthority.NONE,
        )
        self.assertIn(item.item_id, receipt.included_item_ids)

    def test_inactive_head_candidate_does_not_enter_room_now(self) -> None:
        active = self.state("active-state", value="ACTIVE")
        inactive = self.state("ended-head", value="ENDED_OLD_VALUE")
        candidates = (
            CurrentCandidate(
                record=active,
                end_events=(),
                standing=CurrentStanding.CURRENT,
                reason_codes=("DURABLE_UNTIL_CHANGED",),
            ),
            CurrentCandidate(
                record=inactive,
                end_events=(),
                standing=CurrentStanding.ENDED,
                reason_codes=("EXPLICIT_END_EVENT",),
            ),
        )
        semantic = CurrentResolution(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-wake",
            key="project.status",
            standing=CurrentStanding.CURRENT,
            current_state_ids=(active.state_id,),
            historical_state_ids=(inactive.state_id,),
            future_state_ids=(),
            candidates=candidates,
            reason_codes=("DURABLE_UNTIL_CHANGED",),
        )
        decision = CurrentResolverDecision(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-wake",
            key="project.status",
            as_of=self.t0,
            status=CurrentResolverStatus.RESOLVED,
            semantic_resolution=semantic,
            dependencies=(
                CurrentResolverDependency(
                    effect_kind=CurrentUseEffectKind.STATE,
                    effect_id=active.state_id,
                ),
            ),
            blocks=(),
            missing_live_admission_effects=(),
            reason_codes=("SEMANTIC_DEPENDENCIES_USABLE",),
        )

        packet, _ = self.assemble(
            room_current=self.view(decision)
        )

        item = packet.room_now.items[0]
        self.assertEqual(
            tuple(candidate.state_id for candidate in item.candidates),
            (active.state_id,),
        )
        self.assertNotIn("ENDED_OLD_VALUE", repr(packet))

    def test_blocked_current_value_never_enters_packet(self) -> None:
        secret = self.state(
            "blocked-state",
            value="DO_NOT_CARRY_THIS_VALUE",
        )
        semantic = CurrentResolution(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-wake",
            key=secret.key,
            standing=CurrentStanding.CURRENT,
            current_state_ids=(secret.state_id,),
            historical_state_ids=(),
            future_state_ids=(),
            candidates=(
                CurrentCandidate(
                    record=secret,
                    end_events=(),
                    standing=CurrentStanding.CURRENT,
                    reason_codes=("CANDIDATE",),
                ),
            ),
            reason_codes=("ONE_ELIGIBLE_HEAD",),
        )
        block = CurrentSuppressionBlock(
            source_ref=secret.source_refs[0],
            source_id="source-secret",
            suppression_id="stop-secret",
            origin_effect_kind=CurrentUseEffectKind.STATE,
            origin_effect_id=secret.state_id,
        )
        decision = CurrentResolverDecision(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-wake",
            key=secret.key,
            as_of=self.t0,
            status=CurrentResolverStatus.BLOCKED_UNKNOWN,
            semantic_resolution=semantic,
            dependencies=(
                CurrentResolverDependency(
                    effect_kind=CurrentUseEffectKind.STATE,
                    effect_id=secret.state_id,
                ),
            ),
            blocks=(block,),
            missing_live_admission_effects=(),
            reason_codes=("SEMANTIC_DEPENDENCY_SUPPRESSED",),
        )

        packet, receipt = self.assemble(
            room_current=self.view(decision)
        )

        self.assertEqual(
            packet.room_now.availability,
            WakeLayerAvailability.PARTIAL,
        )
        self.assertEqual(packet.room_now.items, ())
        self.assertEqual(len(receipt.omissions), 1)
        omission = receipt.omissions[0]
        self.assertEqual(
            omission.classification,
            "operationally_withheld",
        )
        self.assertEqual(
            omission.audit_refs,
            ("suppression:stop-secret",),
        )
        self.assertNotIn(
            "DO_NOT_CARRY_THIS_VALUE",
            repr(packet),
        )
        self.assertNotIn(
            "DO_NOT_CARRY_THIS_VALUE",
            repr(receipt),
        )

    def test_missing_live_admission_proof_is_partial_without_value(self) -> None:
        decision = CurrentResolverDecision(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-wake",
            key="project.status",
            as_of=self.t0,
            status=(
                CurrentResolverStatus.ADMISSION_PROOF_UNAVAILABLE
            ),
            semantic_resolution=None,
            dependencies=(),
            blocks=(),
            missing_live_admission_effects=(
                CurrentResolverDependency(
                    effect_kind=CurrentUseEffectKind.STATE,
                    effect_id="state-missing-proof",
                ),
            ),
            reason_codes=("LIVE_ADMISSION_PROOF_UNAVAILABLE",),
        )

        packet, receipt = self.assemble(
            room_current=self.view(decision)
        )

        self.assertEqual(
            packet.room_now.availability,
            WakeLayerAvailability.PARTIAL,
        )
        self.assertEqual(packet.room_now.items, ())
        self.assertEqual(
            receipt.omissions[0].audit_refs,
            ("effect:state:state-missing-proof",),
        )

    def test_conflict_is_carried_as_conflict_without_winner_selection(self) -> None:
        a = self.state("state-a", value="A")
        b = self.state("state-b", value="B")
        candidates = (
            CurrentCandidate(
                record=a,
                end_events=(),
                standing=CurrentStanding.CURRENT,
                reason_codes=("HEAD",),
            ),
            CurrentCandidate(
                record=b,
                end_events=(),
                standing=CurrentStanding.CURRENT,
                reason_codes=("HEAD",),
            ),
        )
        decision = self.resolved_decision(
            key="project.status",
            standing=CurrentStanding.CONFLICTING,
            candidates=candidates,
        )

        packet, _ = self.assemble(
            room_current=self.view(decision)
        )

        item = packet.room_now.items[0]
        self.assertEqual(
            item.standing,
            CurrentStanding.CONFLICTING,
        )
        self.assertEqual(
            tuple(candidate.value for candidate in item.candidates),
            ("A", "B"),
        )

    def test_ended_result_is_not_carried_but_does_not_make_layer_partial(self) -> None:
        record = self.state("ended-state")
        candidate = CurrentCandidate(
            record=record,
            end_events=(),
            standing=CurrentStanding.ENDED,
            reason_codes=("ENDED",),
        )
        decision = self.resolved_decision(
            standing=CurrentStanding.ENDED,
            candidates=(candidate,),
        )

        packet, receipt = self.assemble(
            room_current=self.view(decision)
        )

        self.assertEqual(
            packet.room_now.availability,
            WakeLayerAvailability.READY,
        )
        self.assertEqual(packet.room_now.items, ())
        self.assertEqual(
            receipt.omissions[0].classification,
            "not_carried_semantic_standing",
        )
        self.assertEqual(
            receipt.omissions[0].reason_codes,
            ("STANDING_ENDED",),
        )

    def test_unattached_episode_has_episode_scoped_map_and_no_room_now(self) -> None:
        route = RoomAttachmentResolution(
            episode_id=self.episode.episode_id,
            decision="unattached",
            room_id=None,
            active_attachment_event_id="route-unattached",
        )

        packet, _ = assemble_wake_packet_v0_1(
            wake_id="wake-unattached",
            as_of=self.t0,
            episode=self.episode,
            route=route,
            continuity_edges=(self.edge,),
            room_current=None,
        )

        self.assertEqual(
            packet.map.item.privacy_scope.kind,
            WakePrivacyScopeKind.EPISODE,
        )
        self.assertEqual(
            packet.room_now.availability,
            WakeLayerAvailability.UNAVAILABLE,
        )
        self.assertEqual(
            packet.room_now.reason_codes,
            ("EPISODE_NOT_ATTACHED_TO_ROOM",),
        )

    def test_room_current_owner_must_match_map_route(self) -> None:
        view = CurrentResolvedView(
            as_of=self.t0,
            namespace=CurrentNamespace.ROOM,
            owner_id="other-room",
            items=(),
        )

        with self.assertRaises(WakePacketError):
            self.assemble(room_current=view)

    def test_same_instant_different_offset_is_accepted(self) -> None:
        plus_eight = timezone(timedelta(hours=8))
        same = self.t0.astimezone(plus_eight)
        view = self.view(as_of=same)

        packet, _ = self.assemble(room_current=view)

        self.assertEqual(
            packet.room_now.availability,
            WakeLayerAvailability.READY,
        )

    def test_naive_wake_time_is_rejected(self) -> None:
        with self.assertRaises(WakePacketError):
            assemble_wake_packet_v0_1(
                wake_id="wake-naive",
                as_of=self.t0.replace(tzinfo=None),
                episode=self.episode,
                route=self.route,
                continuity_edges=(self.edge,),
                room_current=self.view(),
            )


if __name__ == "__main__":
    unittest.main()