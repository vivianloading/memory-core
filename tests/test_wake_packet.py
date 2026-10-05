import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

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
    resolve_current_state,
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
    WakeContinuityEvidence,
    WakeCurrentCandidate,
    WakeInputTrust,
    WakeLayer,
    WakeLayerAvailability,
    WakeMapItem,
    WakePacketError,
    WakePrivacyScope,
    WakePrivacyScopeKind,
    WakeRouteDecision,
    WakeRoomNowItem,
    WakeRoomNowSection,
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
                if (
                    candidate.standing in {
                        CurrentStanding.CURRENT,
                        CurrentStanding.LAST_KNOWN,
                        CurrentStanding.UNRESOLVED,
                    }
                    or (
                        standing is CurrentStanding.CONFLICTING
                        and candidate.standing
                        is CurrentStanding.CONFLICTING
                    )
                )
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

        self.assertEqual(
            packet.input_trust,
            WakeInputTrust.TYPED_CALLER_INPUT,
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
            ContinuityStatus.UNKNOWN,
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

    def test_hand_built_map_cannot_claim_impossible_attached_route(self) -> None:
        with self.assertRaises(WakePacketError):
            WakeMapItem(
                item_id="map:bad-route",
                episode_id=self.episode.episode_id,
                perspective_instance_id=self.episode.perspective_instance_id,
                route_decision=WakeRouteDecision.ATTACHED,
                room_id=None,
                active_attachment_event_id=None,
                incoming_continuity=None,
                privacy_scope=WakePrivacyScope(
                    kind=WakePrivacyScopeKind.EPISODE,
                    scope_id=self.episode.episode_id,
                ),
            )

    def test_hand_built_map_continuity_must_point_to_map_episode(self) -> None:
        with self.assertRaises(WakePacketError):
            WakeMapItem(
                item_id="map:wrong-edge",
                episode_id=self.episode.episode_id,
                perspective_instance_id=self.episode.perspective_instance_id,
                route_decision=WakeRouteDecision.ATTACHED,
                room_id="room-wake",
                active_attachment_event_id="route-wake",
                incoming_continuity=WakeContinuityEvidence(
                    edge_id="edge-wrong",
                    previous_episode_id="episode-old",
                    next_episode_id="different-episode",
                    transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
                    continuity_status=ContinuityStatus.UNKNOWN,
                ),
                privacy_scope=WakePrivacyScope(
                    kind=WakePrivacyScopeKind.EPISODE,
                    scope_id=self.episode.episode_id,
                ),
            )

    def test_hand_built_room_now_candidate_requires_perspective_and_room_ownership(self) -> None:
        with self.assertRaises(WakePacketError):
            WakeCurrentCandidate(
                state_id="state-no-perspective",
                namespace=CurrentNamespace.ROOM,
                owner_id="room-wake",
                key="project.status",
                value="looks-plausible",
                state_kind=CurrentStateKind.PROJECT_STATUS,
                standing=CurrentStanding.CURRENT,
                semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
                event_time=self.t0,
                recorded_at=self.t0,
                valid_from=self.t0,
                validity_rule=ValidityRule.DURABLE_UNTIL_CHANGED,
                stale_after=None,
                standing_as_of=self.t0,
                episode_id=None,
                perspective_instance_id=None,
                source_refs=("ref-no-perspective",),
                end_evidence=(),
            )
        with self.assertRaises(WakePacketError):
            WakeCurrentCandidate(
                state_id="state-shared-owner",
                namespace=CurrentNamespace.ROOM,
                owner_id="room-wake",
                key="project.status",
                value="shared-shaped-value",
                state_kind=CurrentStateKind.PROJECT_STATUS,
                standing=CurrentStanding.CURRENT,
                semantic_change_authority=SemanticChangeAuthority.SHARED_GOVERNANCE,
                event_time=self.t0,
                recorded_at=self.t0,
                valid_from=self.t0,
                validity_rule=ValidityRule.DURABLE_UNTIL_CHANGED,
                stale_after=None,
                standing_as_of=self.t0,
                episode_id=self.episode.episode_id,
                perspective_instance_id=self.episode.perspective_instance_id,
                source_refs=("ref-shared-owner",),
                end_evidence=(),
            )

    def test_hand_built_room_now_candidate_requires_source_provenance(self) -> None:
        with self.assertRaises(WakePacketError):
            WakeCurrentCandidate(
                state_id="state-no-source",
                namespace=CurrentNamespace.ROOM,
                owner_id="room-wake",
                key="project.status",
                value="orphan-value",
                state_kind=CurrentStateKind.PROJECT_STATUS,
                standing=CurrentStanding.CURRENT,
                semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
                event_time=self.t0,
                recorded_at=self.t0,
                valid_from=self.t0,
                validity_rule=ValidityRule.DURABLE_UNTIL_CHANGED,
                stale_after=None,
                standing_as_of=self.t0,
                episode_id=self.episode.episode_id,
                perspective_instance_id=self.episode.perspective_instance_id,
                source_refs=(),
                end_evidence=(),
            )

    def _valid_room_item(self) -> WakeRoomNowItem:
        packet, _ = self.assemble(
            room_current=self.view(self.resolved_decision())
        )
        return packet.room_now.items[0]

    def test_room_now_section_rejects_untyped_nested_items(self) -> None:
        with self.assertRaises(WakePacketError):
            WakeRoomNowSection(
                availability=WakeLayerAvailability.READY,
                items=({"value": "not-a-wake-item"},),
                reason_codes=(),
            )

    def test_room_now_item_rejects_candidate_lookalikes_and_mutable_lists(self) -> None:
        valid = self._valid_room_item()
        with self.assertRaises(WakePacketError):
            replace(
                valid,
                candidates=(
                    SimpleNamespace(
                        state_kind=CurrentStateKind.PROJECT_STATUS,
                    ),
                ),
            )
        mutable = list(valid.candidates)
        with self.assertRaises(WakePacketError):
            replace(valid, candidates=mutable)

    def test_unavailable_lookalike_string_cannot_carry_room_items(self) -> None:
        with self.assertRaises(WakePacketError):
            WakeRoomNowSection(
                availability="unavailable",
                items=(self._valid_room_item(),),
                reason_codes=(),
            )

    def test_packet_binds_room_now_to_map_attached_room(self) -> None:
        packet, _ = self.assemble(
            room_current=self.view(self.resolved_decision())
        )
        item = packet.room_now.items[0]
        other_candidate = replace(
            item.candidates[0],
            owner_id="room-other",
        )
        other_item = replace(
            item,
            item_id="room-now:room-other:project.status",
            room_id="room-other",
            candidates=(other_candidate,),
            privacy_scope=WakePrivacyScope(
                kind=WakePrivacyScopeKind.ROOM,
                scope_id="room-other",
            ),
        )
        with self.assertRaises(WakePacketError):
            replace(
                packet,
                room_now=WakeRoomNowSection(
                    availability=WakeLayerAvailability.READY,
                    items=(other_item,),
                    reason_codes=(),
                ),
            )

    def test_unattached_map_cannot_retain_room_now_content(self) -> None:
        packet, _ = self.assemble(
            room_current=self.view(self.resolved_decision())
        )
        unattached_map = replace(
            packet.map.item,
            route_decision=WakeRouteDecision.UNATTACHED,
            room_id=None,
            active_attachment_event_id="route-unattached",
        )
        with self.assertRaises(WakePacketError):
            replace(
                packet,
                map=replace(packet.map, item=unattached_map),
            )

    def test_unattributed_perspective_sentinel_is_rejected_by_wake_types(self) -> None:
        from home_memory_core.interpretation import (
            SYNTHETIC_UNATTRIBUTED_INSTANCE_ID,
        )

        valid = self._valid_room_item()
        candidate = valid.candidates[0]
        with self.assertRaises(WakePacketError):
            replace(
                candidate,
                perspective_instance_id=SYNTHETIC_UNATTRIBUTED_INSTANCE_ID,
            )
        with self.assertRaises(WakePacketError):
            replace(
                self.assemble(room_current=self.view())[0].map.item,
                perspective_instance_id=SYNTHETIC_UNATTRIBUTED_INSTANCE_ID,
            )

    def test_dst_fold_distinguishes_different_absolute_instants(self) -> None:
        ny = ZoneInfo("America/New_York")
        fold0 = datetime(2026, 11, 1, 1, 30, tzinfo=ny, fold=0)
        fold1 = datetime(2026, 11, 1, 1, 30, tzinfo=ny, fold=1)
        self.assertNotEqual(
            fold0.astimezone(UTC),
            fold1.astimezone(UTC),
        )
        view = self.view(
            self.resolved_decision(),
            as_of=fold0,
        )
        shifted_decisions = tuple(
            replace(decision, as_of=fold0)
            for decision in view.items
        )
        view = replace(view, as_of=fold0, items=shifted_decisions)

        with self.assertRaises(WakePacketError):
            assemble_wake_packet_v0_1(
                wake_id="wake-fold-mismatch",
                as_of=fold1,
                episode=self.episode,
                route=self.route,
                continuity_edges=(self.edge,),
                room_current=view,
            )

    def test_dst_fold_equivalent_utc_instant_is_accepted(self) -> None:
        ny = ZoneInfo("America/New_York")
        fold0 = datetime(2026, 11, 1, 1, 30, tzinfo=ny, fold=0)
        same_utc = fold0.astimezone(UTC)
        decision = replace(self.resolved_decision(), as_of=fold0)
        view = self.view(decision, as_of=fold0)

        packet, _ = assemble_wake_packet_v0_1(
            wake_id="wake-fold-equivalent",
            as_of=same_utc,
            episode=self.episode,
            route=self.route,
            continuity_edges=(self.edge,),
            room_current=view,
        )

        self.assertEqual(packet.as_of, same_utc)

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
            SemanticChangeAuthority.ROOM_FIRST_PERSON,
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

    def test_standing_past_perspective_is_not_rewritten_as_waking_perspective(self) -> None:
        past = CurrentStateRecord(
            state_id="state-from-past-perspective",
            namespace=CurrentNamespace.ROOM,
            owner_id="room-wake",
            key="project.status",
            state_kind=CurrentStateKind.PROJECT_STATUS,
            value="still-standing",
            event_time=self.t0,
            recorded_at=self.t0,
            valid_from=self.t0,
            validity_rule=ValidityRule.DURABLE_UNTIL_CHANGED,
            downgrade_rule=DowngradeRule.NONE,
            semantic_change_authority=(
                SemanticChangeAuthority.ROOM_FIRST_PERSON
            ),
            episode_id="episode-previous",
            perspective_instance_id="perspective-previous",
            source_refs=("ref-past-perspective",),
        )
        candidate = CurrentCandidate(
            record=past,
            end_events=(),
            standing=CurrentStanding.CURRENT,
            reason_codes=("DURABLE_UNTIL_CHANGED",),
        )
        semantic = CurrentResolution(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-wake",
            key="project.status",
            standing=CurrentStanding.CURRENT,
            current_state_ids=(past.state_id,),
            historical_state_ids=(),
            future_state_ids=(),
            candidates=(candidate,),
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
                    effect_id=past.state_id,
                ),
            ),
            blocks=(),
            missing_live_admission_effects=(),
            reason_codes=("SEMANTIC_DEPENDENCIES_USABLE",),
        )

        packet, _ = self.assemble(
            room_current=self.view(decision)
        )

        self.assertEqual(
            packet.perspective_instance_id,
            "perspective-wake",
        )
        carried = packet.room_now.items[0].candidates[0]
        self.assertEqual(
            carried.perspective_instance_id,
            "perspective-previous",
        )
        self.assertEqual(
            carried.episode_id,
            "episode-previous",
        )
        self.assertNotEqual(
            carried.perspective_instance_id,
            packet.perspective_instance_id,
        )
        self.assertEqual(
            packet.room_now.items[0]
            .use_boundary.current_first_person_speech_authority,
            WakeAuthority.NONE,
        )

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

    def test_multi_candidate_room_now_cannot_hide_conflict(self) -> None:
        a = self.state("conflict-a", value="A")
        b = self.state("conflict-b", value="B")
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
        packet, _ = self.assemble(
            room_current=self.view(
                self.resolved_decision(
                    standing=CurrentStanding.CONFLICTING,
                    candidates=candidates,
                )
            )
        )
        valid = packet.room_now.items[0]
        self.assertEqual(valid.standing, CurrentStanding.CONFLICTING)

        with self.assertRaises(WakePacketError):
            replace(valid, standing=CurrentStanding.CURRENT)

    def test_single_candidate_conflict_label_must_match_candidate(self) -> None:
        valid = self._valid_room_item()
        self.assertEqual(len(valid.candidates), 1)
        self.assertEqual(
            valid.candidates[0].standing,
            CurrentStanding.CURRENT,
        )
        with self.assertRaises(WakePacketError):
            replace(valid, standing=CurrentStanding.CONFLICTING)

    def test_single_conflicting_candidate_remains_valid(self) -> None:
        from home_memory_core.current_view import (
            CurrentStateEndEvent,
            EndKind,
        )

        record = self.state("single-conflicting")
        end_one = CurrentStateEndEvent(
            end_event_id="single-conflict-completed",
            state_id=record.state_id,
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.COMPLETED,
            reason="completed",
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id=self.episode.episode_id,
            perspective_instance_id=self.episode.perspective_instance_id,
            source_refs=("ref-single-completed",),
        )
        end_two = CurrentStateEndEvent(
            end_event_id="single-conflict-cancelled",
            state_id=record.state_id,
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.CANCELLED,
            reason="cancelled",
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id=self.episode.episode_id,
            perspective_instance_id=self.episode.perspective_instance_id,
            source_refs=("ref-single-cancelled",),
        )
        semantic = resolve_current_state(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-wake",
            key=record.key,
            records=(record,),
            end_events=(end_one, end_two),
            as_of=self.t0,
        )
        decision = self.resolved_decision(
            standing=semantic.standing,
            candidates=semantic.candidates,
        )
        packet, _ = self.assemble(room_current=self.view(decision))
        item = packet.room_now.items[0]
        self.assertEqual(item.standing, CurrentStanding.CONFLICTING)
        self.assertEqual(len(item.candidates), 1)
        self.assertEqual(
            item.candidates[0].standing,
            CurrentStanding.CONFLICTING,
        )
        self.assertEqual(len(item.candidates[0].end_evidence), 2)

    def test_room_now_rejects_duplicate_candidate_state_ids(self) -> None:
        valid = self._valid_room_item()
        candidate = valid.candidates[0]
        with self.assertRaises(WakePacketError):
            replace(valid, candidates=(candidate, candidate))

    def test_conflict_cannot_be_split_into_duplicate_room_key_items(self) -> None:
        a = self.state("split-a", value="A")
        b = self.state("split-b", value="B")
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
        packet, _ = self.assemble(
            room_current=self.view(
                self.resolved_decision(
                    standing=CurrentStanding.CONFLICTING,
                    candidates=candidates,
                )
            )
        )
        conflict = packet.room_now.items[0]
        split = tuple(
            replace(
                conflict,
                item_id=f"{conflict.item_id}:part-{index}",
                standing=candidate.standing,
                candidates=(candidate,),
            )
            for index, candidate in enumerate(conflict.candidates)
        )

        with self.assertRaises(WakePacketError):
            replace(packet.room_now, items=split)

    def test_room_now_section_rejects_duplicate_item_ids(self) -> None:
        valid = self._valid_room_item()
        other_candidate = replace(
            valid.candidates[0],
            state_id="state-other-key-duplicate-item-id",
            key="project.other",
            source_refs=("ref-other-key-duplicate-item-id",),
        )
        other = replace(
            valid,
            key="project.other",
            candidates=(other_candidate,),
        )

        with self.assertRaises(WakePacketError):
            WakeRoomNowSection(
                availability=WakeLayerAvailability.READY,
                items=(valid, other),
                reason_codes=(),
            )

    def test_distinct_room_now_keys_remain_representable(self) -> None:
        first = self._valid_room_item()
        second_candidate = replace(
            first.candidates[0],
            state_id="state-second-key",
            key="project.other",
            source_refs=("ref-second-key",),
        )
        second = replace(
            first,
            item_id="room-now:room-wake:project.other",
            key="project.other",
            candidates=(second_candidate,),
        )

        section = WakeRoomNowSection(
            availability=WakeLayerAvailability.READY,
            items=(first, second),
            reason_codes=(),
        )

        self.assertEqual(
            tuple(item.key for item in section.items),
            ("project.status", "project.other"),
        )

    def test_candidate_retains_room_and_key_semantic_identity(self) -> None:
        valid = self._valid_room_item()
        candidate = valid.candidates[0]

        self.assertEqual(candidate.namespace, CurrentNamespace.ROOM)
        self.assertEqual(candidate.owner_id, valid.room_id)
        self.assertEqual(candidate.key, valid.key)

        with self.assertRaises(WakePacketError):
            replace(valid, key="project.relabelled")
        with self.assertRaises(WakePacketError):
            replace(
                valid,
                room_id="room-other",
                privacy_scope=WakePrivacyScope(
                    kind=WakePrivacyScopeKind.ROOM,
                    scope_id="room-other",
                ),
            )

    def test_conflict_candidates_cannot_be_split_by_relabelling_keys(self) -> None:
        a = self.state("identity-conflict-a", value="A")
        b = self.state("identity-conflict-b", value="B")
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
        packet, _ = self.assemble(
            room_current=self.view(
                self.resolved_decision(
                    standing=CurrentStanding.CONFLICTING,
                    candidates=candidates,
                )
            )
        )
        conflict = packet.room_now.items[0]

        first = replace(
            conflict,
            item_id=f"{conflict.item_id}:first",
            standing=conflict.candidates[0].standing,
            candidates=(conflict.candidates[0],),
        )
        with self.assertRaises(WakePacketError):
            replace(
                conflict,
                item_id=f"{conflict.item_id}:second",
                key="project.fake-key",
                standing=conflict.candidates[1].standing,
                candidates=(conflict.candidates[1],),
            )

        self.assertEqual(first.key, "project.status")

    def test_candidate_cannot_be_rehomed_by_outer_room_labels(self) -> None:
        donor = self._valid_room_item()

        with self.assertRaises(WakePacketError):
            replace(
                donor,
                item_id="room-now:room-other:project.status",
                room_id="room-other",
                privacy_scope=WakePrivacyScope(
                    kind=WakePrivacyScopeKind.ROOM,
                    scope_id="room-other",
                ),
            )

    def test_section_rejects_duplicate_state_identity_across_keys(self) -> None:
        first = self._valid_room_item()
        second_candidate = replace(
            first.candidates[0],
            key="project.other",
            value="different-payload",
            episode_id="episode-other",
            perspective_instance_id="perspective-other",
            source_refs=("ref-other-provenance",),
        )
        second = replace(
            first,
            item_id="room-now:room-wake:project.other",
            key="project.other",
            candidates=(second_candidate,),
        )

        with self.assertRaises(WakePacketError):
            WakeRoomNowSection(
                availability=WakeLayerAvailability.READY,
                items=(first, second),
                reason_codes=(),
            )

    def test_end_evidence_must_remain_bound_to_candidate_state(self) -> None:
        from home_memory_core.current_view import EndKind
        from home_memory_core.wake_packet import WakeEndEvidence

        valid = self._valid_room_item().candidates[0]
        evidence = WakeEndEvidence(
            end_event_id="end-other",
            state_id="different-state",
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.COMPLETED,
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id=self.episode.episode_id,
            perspective_instance_id=self.episode.perspective_instance_id,
            source_refs=("ref-end-other",),
        )

        with self.assertRaises(WakePacketError):
            replace(valid, end_evidence=(evidence,))

    def test_section_rejects_duplicate_end_event_identity(self) -> None:
        from home_memory_core.current_view import EndKind
        from home_memory_core.wake_packet import WakeEndEvidence

        first = self._valid_room_item()
        first_shared = WakeEndEvidence(
            end_event_id="end-shared-id",
            state_id=first.candidates[0].state_id,
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.COMPLETED,
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id=self.episode.episode_id,
            perspective_instance_id=self.episode.perspective_instance_id,
            source_refs=("ref-end-a",),
        )
        first_extra = replace(
            first_shared,
            end_event_id="end-first-extra",
            end_kind=EndKind.CANCELLED,
            source_refs=("ref-end-a-extra",),
        )
        first_candidate = replace(
            first.candidates[0],
            standing=CurrentStanding.CONFLICTING,
            end_evidence=(first_shared, first_extra),
        )
        first_item = replace(
            first,
            standing=CurrentStanding.CONFLICTING,
            candidates=(first_candidate,),
        )

        second_base = replace(
            first.candidates[0],
            state_id="state-second-end-owner",
            key="project.other",
            source_refs=("ref-second-end-owner",),
        )
        second_shared = WakeEndEvidence(
            end_event_id="end-shared-id",
            state_id=second_base.state_id,
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.CANCELLED,
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id="episode-second",
            perspective_instance_id="perspective-second",
            source_refs=("ref-end-b",),
        )
        second_extra = replace(
            second_shared,
            end_event_id="end-second-extra",
            end_kind=EndKind.COMPLETED,
            source_refs=("ref-end-b-extra",),
        )
        second_candidate = replace(
            second_base,
            standing=CurrentStanding.CONFLICTING,
            end_evidence=(second_shared, second_extra),
        )
        second_item = replace(
            first,
            item_id="room-now:room-wake:project.other",
            key="project.other",
            standing=CurrentStanding.CONFLICTING,
            candidates=(second_candidate,),
        )

        with self.assertRaises(WakePacketError):
            WakeRoomNowSection(
                availability=WakeLayerAvailability.READY,
                items=(first_item, second_item),
                reason_codes=(),
            )

    def test_candidate_standing_cannot_contradict_end_evidence(self) -> None:
        record = self.state("state-ended-conflict")
        from home_memory_core.current_view import (
            CurrentStateEndEvent,
            EndKind,
        )

        end_one = CurrentStateEndEvent(
            end_event_id="end-one",
            state_id=record.state_id,
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.COMPLETED,
            reason="completed",
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id=self.episode.episode_id,
            perspective_instance_id=self.episode.perspective_instance_id,
            source_refs=("ref-end-one",),
        )
        end_two = CurrentStateEndEvent(
            end_event_id="end-two",
            state_id=record.state_id,
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.CANCELLED,
            reason="cancelled",
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id=self.episode.episode_id,
            perspective_instance_id=self.episode.perspective_instance_id,
            source_refs=("ref-end-two",),
        )
        semantic = resolve_current_state(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-wake",
            key=record.key,
            records=(record,),
            end_events=(end_one, end_two),
            as_of=self.t0,
        )
        decision = self.resolved_decision(
            standing=semantic.standing,
            candidates=semantic.candidates,
        )
        packet, _ = self.assemble(room_current=self.view(decision))
        candidate = packet.room_now.items[0].candidates[0]
        self.assertEqual(candidate.standing, CurrentStanding.CONFLICTING)
        self.assertEqual(len(candidate.end_evidence), 2)

        with self.assertRaises(WakePacketError):
            replace(candidate, standing=CurrentStanding.CURRENT)

    def test_candidate_standing_is_derived_from_validity_rule(self) -> None:
        base = self._valid_room_item().candidates[0]

        open_candidate = replace(
            base,
            state_kind=CurrentStateKind.COMMITMENT,
            validity_rule=ValidityRule.OPEN_UNTIL_RESOLVED,
            standing=CurrentStanding.UNRESOLVED,
        )
        self.assertEqual(open_candidate.standing, CurrentStanding.UNRESOLVED)
        with self.assertRaises(WakePacketError):
            replace(open_candidate, standing=CurrentStanding.CURRENT)

        stale_candidate = replace(
            base,
            state_kind=CurrentStateKind.PREFERENCE,
            validity_rule=ValidityRule.STALE_TO_LAST_KNOWN,
            stale_after=timedelta(hours=1),
            event_time=self.t0 - timedelta(hours=2),
            recorded_at=self.t0 - timedelta(hours=2),
            valid_from=self.t0 - timedelta(hours=2),
            standing_as_of=self.t0,
            standing=CurrentStanding.LAST_KNOWN,
        )
        self.assertEqual(
            stale_candidate.standing,
            CurrentStanding.LAST_KNOWN,
        )
        with self.assertRaises(WakePacketError):
            replace(stale_candidate, standing=CurrentStanding.CURRENT)

    def test_candidate_standing_cut_must_match_packet_cut(self) -> None:
        packet, _ = self.assemble(
            room_current=self.view(self.resolved_decision())
        )
        item = packet.room_now.items[0]
        candidate = replace(
            item.candidates[0],
            standing_as_of=self.t0 + timedelta(hours=1),
        )
        changed_item = replace(item, candidates=(candidate,))

        with self.assertRaises(WakePacketError):
            replace(
                packet,
                room_now=replace(
                    packet.room_now,
                    items=(changed_item,),
                ),
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

    def test_receipt_preserves_exact_five_layer_order(self) -> None:
        _, receipt = self.assemble(room_current=self.view())

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