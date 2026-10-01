import dataclasses
import os
from pathlib import Path
import tempfile
import unittest

import home_memory_core.living_authority as authority_module
from _trusted_test_support import (
    trusted_test_room_continuation_policy,
    trusted_test_runtime_launch_issuer,
)
from home_memory_core.host_runtime import acquire_home_single_instance
from home_memory_core.living_authority import (
    AutomaticContinuationApproval,
    RoomLaunchEvidenceError,
    RoomParticipationAuthorizationError,
    RoomParticipationGrant,
    RoomParticipationScope,
    RoomParticipationStaleError,
    SupportedRuntimeLaunchReceipt,
    TrustedLaunchEvidence,
    TrustedRoomContinuationPolicy,
    TrustedRuntimeLaunchIssuer,
    open_room_participation_authority,
)
from home_memory_core.living_continuity import (
    ContinuityEdge,
    ContinuityStatus,
    EpisodeRecord,
    RoomAttachmentEvent,
    RoomRecord,
    RoomRouteKind,
    TransferMode,
)
from home_memory_core.living_store import LivingStore
from home_memory_core.storage import MemoryStore


class RoomParticipationAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "data" / "home.db"
        MemoryStore(self.db_path).initialize()
        self.living = LivingStore(self.db_path)
        self.living.initialize()
        self.lease = acquire_home_single_instance(
            runtime_root=self.root,
            db_path=self.db_path,
        )
        self.authority = open_room_participation_authority(
            lease=self.lease,
            store=self.living,
        )
        self.launcher = trusted_test_runtime_launch_issuer(
            lease=self.lease,
            store=self.living,
        )
        self.policy = trusted_test_room_continuation_policy(
            policy_id="policy-room-r-v1",
            room_id="room-r",
            allowed_scopes={
                RoomParticipationScope.READ_HISTORY,
                RoomParticipationScope.APPEND_FIRST_PERSON,
            },
        )
        self._seed_linear_pair()

    def tearDown(self) -> None:
        if not self.lease.released:
            self.lease.release()
        self._tmp.cleanup()

    def _seed_linear_pair(
        self,
        *,
        transfer_mode: TransferMode = TransferMode.TEXT_CONTEXT_HANDOFF,
    ) -> None:
        self.living.add_room(RoomRecord(room_id="room-r"))
        self.living.add_episode(
            EpisodeRecord(
                episode_id="episode-a",
                perspective_instance_id="perspective-a",
                runtime_instance_id="runtime-a",
                model_ref="model-a",
            )
        )
        self.living.add_episode(
            EpisodeRecord(
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                runtime_instance_id="runtime-b",
                model_ref="model-b",
            )
        )
        self.living.add_continuity_edge(
            ContinuityEdge(
                edge_id="edge-a-b",
                previous_episode_id="episode-a",
                next_episode_id="episode-b",
                transfer_mode=transfer_mode,
                continuity_status=ContinuityStatus.UNKNOWN,
                support_refs=("opaque-handoff-receipt",),
            )
        )
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-a",
                episode_id="episode-a",
                route_kind=RoomRouteKind.ATTACHED,
                room_id="room-r",
                basis="existing_living_line",
            )
        )
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-b",
                episode_id="episode-b",
                route_kind=RoomRouteKind.ATTACHED,
                room_id="room-r",
                basis="ordinary_handoff",
                support_refs=("edge-a-b",),
            )
        )

    def _launch(self):
        receipt = self.launcher.record_supported_runtime_launch(
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            observed_runtime_instance_id="runtime-b",
            observed_transfer_mode=self._edge_transfer_mode(),
        )
        return self.authority.begin_trusted_continuation(
            launch_receipt=receipt,
            previous_episode_id="episode-a",
            room_id="room-r",
        )

    def _edge_transfer_mode(self) -> TransferMode:
        edges = self.living.list_continuity_edges()
        for edge in edges:
            if edge.edge_id == "edge-a-b":
                return edge.transfer_mode
        raise AssertionError("edge-a-b missing")

    def _grant(self, scopes=None):
        scopes = scopes or frozenset(
            {RoomParticipationScope.APPEND_FIRST_PERSON}
        )
        evidence = self._launch()
        proposal = self.authority.prepare_grant(
            launch_evidence=evidence,
            policy=self.policy,
            requested_scopes=frozenset(scopes),
        )
        approval = self.authority.approve_automatic_continuation(
            proposal=proposal,
            policy=self.policy,
        )
        grant = self.authority.issue_grant(
            proposal=proposal,
            approval=approval,
        )
        return evidence, proposal, approval, grant

    def test_ordinary_unknown_continuation_receives_fresh_bound_grant(self) -> None:
        evidence, _, _, grant = self._grant()

        self.assertEqual(evidence.continuity_status, ContinuityStatus.UNKNOWN)
        self.assertEqual(evidence.room_id, "room-r")
        self.assertEqual(grant.episode_id, "episode-b")
        self.assertEqual(grant.perspective_instance_id, "perspective-b")
        self.assertNotEqual(grant.grant_id, evidence.evidence_id)

        self.authority.require_grant(
            grant=grant,
            session_id=evidence.session_id,
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            room_id="room-r",
            required_scope=RoomParticipationScope.APPEND_FIRST_PERSON,
        )

    def test_model_and_runtime_change_do_not_force_identity_or_room_change(self) -> None:
        evidence = self._launch()
        self.assertEqual(evidence.continuity_status, ContinuityStatus.UNKNOWN)
        self.assertFalse(hasattr(evidence, "same_self"))
        self.assertFalse(hasattr(evidence, "different_self"))

    def test_room_attachment_alone_is_not_launch_authority(self) -> None:
        with self.assertRaises(RoomLaunchEvidenceError):
            TrustedLaunchEvidence(
                evidence_id="forged",
                runtime_launch_receipt_id="forged-runtime-launch",
                session_id="forged-session",
                home_process_instance_id="forged-process",
                host_process_instance_id="forged-host",
                previous_episode_id="episode-a",
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                room_id="room-r",
                continuity_edge_id="edge-a-b",
                previous_attachment_event_id="route-a",
                attachment_event_id="route-b",
                transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
                continuity_status=ContinuityStatus.UNKNOWN,
                _marker=object(),
            )

    def test_persisted_route_and_edge_cannot_mint_authority_without_launch_receipt(self) -> None:
        with self.assertRaises(TypeError):
            self.authority.begin_trusted_continuation(
                previous_episode_id="episode-a",
                room_id="room-r",
            )

    def test_runtime_launch_issuer_cannot_be_caller_minted(self) -> None:
        with self.assertRaises(RoomLaunchEvidenceError):
            TrustedRuntimeLaunchIssuer(
                lease=self.lease,
                store=self.living,
                _marker=object(),
            )

    def test_room_authority_cannot_self_attest_runtime_launch(self) -> None:
        self.assertFalse(
            hasattr(self.authority, "record_supported_runtime_launch")
        )

    def test_forged_runtime_launch_receipt_is_rejected(self) -> None:
        with self.assertRaises(RoomLaunchEvidenceError):
            SupportedRuntimeLaunchReceipt(
                receipt_id="forged-launch",
                session_id="forged-session",
                home_process_instance_id="forged-process",
                host_process_instance_id="forged-host",
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                runtime_instance_id="runtime-b",
                observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
                _marker=object(),
            )

    def test_runtime_launch_receipt_is_one_shot(self) -> None:
        receipt = self.launcher.record_supported_runtime_launch(
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            observed_runtime_instance_id="runtime-b",
            observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
        )
        self.authority.begin_trusted_continuation(
            launch_receipt=receipt,
            previous_episode_id="episode-a",
            room_id="room-r",
        )
        with self.assertRaises(RoomLaunchEvidenceError):
            self.authority.begin_trusted_continuation(
                launch_receipt=receipt,
                previous_episode_id="episode-a",
                room_id="room-r",
            )

    def test_observed_launch_mode_must_match_persisted_edge(self) -> None:
        receipt = self.launcher.record_supported_runtime_launch(
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            observed_runtime_instance_id="runtime-b",
            observed_transfer_mode=TransferMode.LIVE_RUNTIME,
        )
        with self.assertRaises(RoomLaunchEvidenceError):
            self.authority.begin_trusted_continuation(
                launch_receipt=receipt,
                previous_episode_id="episode-a",
                room_id="room-r",
            )

    def test_episode_cannot_receive_two_runtime_launch_receipts(self) -> None:
        first = self.launcher.record_supported_runtime_launch(
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            observed_runtime_instance_id="runtime-b",
            observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
        )
        with self.assertRaises(RoomLaunchEvidenceError):
            self.launcher.record_supported_runtime_launch(
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                observed_runtime_instance_id="runtime-b",
                observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
            )

        evidence = self.authority.begin_trusted_continuation(
            launch_receipt=first,
            previous_episode_id="episode-a",
            room_id="room-r",
        )
        self.assertEqual(evidence.episode_id, "episode-b")

    def test_runtime_launch_receipt_in_memory_tamper_is_detected(self) -> None:
        receipt = self.launcher.record_supported_runtime_launch(
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            observed_runtime_instance_id="runtime-b",
            observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
        )
        object.__setattr__(
            receipt,
            "observed_transfer_mode",
            TransferMode.LIVE_RUNTIME,
        )

        with self.assertRaises(RoomLaunchEvidenceError):
            self.authority.begin_trusted_continuation(
                launch_receipt=receipt,
                previous_episode_id="episode-a",
                room_id="room-r",
            )

    def test_missing_runtime_instance_blocks_automatic_participation(self) -> None:
        self.living.add_episode(
            EpisodeRecord(
                episode_id="episode-no-runtime",
                perspective_instance_id="perspective-no-runtime",
            )
        )
        with self.assertRaises(RoomLaunchEvidenceError):
            self.launcher.record_supported_runtime_launch(
                episode_id="episode-no-runtime",
                perspective_instance_id="perspective-no-runtime",
                observed_runtime_instance_id="runtime-invented",
                observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
            )

    def test_runtime_instance_binding_mismatch_blocks_launch(self) -> None:
        with self.assertRaises(RoomLaunchEvidenceError):
            self.launcher.record_supported_runtime_launch(
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                observed_runtime_instance_id="runtime-wrong",
                observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
            )

    def test_perspective_binding_mismatch_blocks_launch(self) -> None:
        with self.assertRaises(RoomLaunchEvidenceError):
            self.launcher.record_supported_runtime_launch(
                episode_id="episode-b",
                perspective_instance_id="perspective-a",
                observed_runtime_instance_id="runtime-b",
                observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
            )

    def test_history_reconstruction_does_not_auto_grant_participation(self) -> None:
        self.lease.release()
        self._tmp.cleanup()

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "data" / "home.db"
        MemoryStore(self.db_path).initialize()
        self.living = LivingStore(self.db_path)
        self.living.initialize()
        self.lease = acquire_home_single_instance(
            runtime_root=self.root,
            db_path=self.db_path,
        )
        self.authority = open_room_participation_authority(
            lease=self.lease,
            store=self.living,
        )
        self.launcher = trusted_test_runtime_launch_issuer(
            lease=self.lease,
            store=self.living,
        )
        self._seed_linear_pair(
            transfer_mode=TransferMode.HISTORY_RECONSTRUCTION
        )

        with self.assertRaises(RoomLaunchEvidenceError):
            self._launch()

    def test_fork_does_not_inherit_continuation_policy_by_default(self) -> None:
        self.living.add_episode(
            EpisodeRecord(
                episode_id="episode-c",
                perspective_instance_id="perspective-c",
                runtime_instance_id="runtime-c",
            )
        )
        self.living.add_continuity_edge(
            ContinuityEdge(
                edge_id="edge-a-c",
                previous_episode_id="episode-a",
                next_episode_id="episode-c",
                transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
                continuity_status=ContinuityStatus.UNKNOWN,
            )
        )

        with self.assertRaises(RoomLaunchEvidenceError):
            self._launch()

    def test_unattached_new_episode_blocks_automatic_participation(self) -> None:
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-b-unattached",
                episode_id="episode-b",
                route_kind=RoomRouteKind.UNATTACHED,
                room_id=None,
                basis="route_withdrawn",
                supersedes_attachment_event_id="route-b",
            )
        )

        with self.assertRaises(RoomLaunchEvidenceError):
            self._launch()

    def test_ambiguous_new_episode_route_blocks_automatic_participation(self) -> None:
        self.living.add_room(RoomRecord(room_id="room-other"))
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-b-competing",
                episode_id="episode-b",
                route_kind=RoomRouteKind.ATTACHED,
                room_id="room-other",
                basis="competing_route",
            )
        )

        with self.assertRaises(RoomLaunchEvidenceError):
            self._launch()

    def test_policy_does_not_auto_cross_ancestor_fork(self) -> None:
        self.living.add_episode(
            EpisodeRecord(
                episode_id="episode-fork-sibling",
                perspective_instance_id="perspective-fork-sibling",
                runtime_instance_id="runtime-fork-sibling",
            )
        )
        self.living.add_continuity_edge(
            ContinuityEdge(
                edge_id="edge-a-fork-sibling",
                previous_episode_id="episode-a",
                next_episode_id="episode-fork-sibling",
                transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
                continuity_status=ContinuityStatus.UNKNOWN,
            )
        )
        self.living.add_episode(
            EpisodeRecord(
                episode_id="episode-c-after-fork",
                perspective_instance_id="perspective-c-after-fork",
                runtime_instance_id="runtime-c-after-fork",
            )
        )
        self.living.add_continuity_edge(
            ContinuityEdge(
                edge_id="edge-b-c-after-fork",
                previous_episode_id="episode-b",
                next_episode_id="episode-c-after-fork",
                transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
                continuity_status=ContinuityStatus.UNKNOWN,
            )
        )
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-c-after-fork",
                episode_id="episode-c-after-fork",
                route_kind=RoomRouteKind.ATTACHED,
                room_id="room-r",
                basis="ordinary_handoff",
            )
        )

        receipt = self.launcher.record_supported_runtime_launch(
            episode_id="episode-c-after-fork",
            perspective_instance_id="perspective-c-after-fork",
            observed_runtime_instance_id="runtime-c-after-fork",
            observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
        )
        evidence = self.authority.begin_trusted_continuation(
            launch_receipt=receipt,
            previous_episode_id="episode-b",
            room_id="room-r",
        )

        with self.assertRaises(RoomParticipationAuthorizationError):
            self.authority.prepare_grant(
                launch_evidence=evidence,
                policy=self.policy,
                requested_scopes=frozenset(
                    {RoomParticipationScope.READ_HISTORY}
                ),
            )

    def test_sibling_branch_policy_cannot_authorize_this_branch(self) -> None:
        self.living.add_episode(
            EpisodeRecord(
                episode_id="episode-sibling",
                perspective_instance_id="perspective-sibling",
                runtime_instance_id="runtime-sibling",
            )
        )
        self.living.add_continuity_edge(
            ContinuityEdge(
                edge_id="edge-a-sibling",
                previous_episode_id="episode-a",
                next_episode_id="episode-sibling",
                transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
                continuity_status=ContinuityStatus.UNKNOWN,
            )
        )
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-sibling",
                episode_id="episode-sibling",
                route_kind=RoomRouteKind.ATTACHED,
                room_id="room-r",
                basis="fork_sibling_route",
            )
        )
        self.living.add_episode(
            EpisodeRecord(
                episode_id="episode-c-branch",
                perspective_instance_id="perspective-c-branch",
                runtime_instance_id="runtime-c-branch",
            )
        )
        self.living.add_continuity_edge(
            ContinuityEdge(
                edge_id="edge-b-c-branch",
                previous_episode_id="episode-b",
                next_episode_id="episode-c-branch",
                transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
                continuity_status=ContinuityStatus.UNKNOWN,
            )
        )
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-c-branch",
                episode_id="episode-c-branch",
                route_kind=RoomRouteKind.ATTACHED,
                room_id="room-r",
                basis="ordinary_handoff",
            )
        )
        sibling_policy = trusted_test_room_continuation_policy(
            policy_id="policy-sibling",
            room_id="room-r",
            established_episode_id="episode-sibling",
            established_attachment_event_id="route-sibling",
            allowed_scopes={
                RoomParticipationScope.READ_HISTORY,
            },
        )

        receipt = self.launcher.record_supported_runtime_launch(
            episode_id="episode-c-branch",
            perspective_instance_id="perspective-c-branch",
            observed_runtime_instance_id="runtime-c-branch",
            observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
        )
        evidence = self.authority.begin_trusted_continuation(
            launch_receipt=receipt,
            previous_episode_id="episode-b",
            room_id="room-r",
        )

        with self.assertRaises(RoomParticipationAuthorizationError):
            self.authority.prepare_grant(
                launch_evidence=evidence,
                policy=sibling_policy,
                requested_scopes=frozenset(
                    {RoomParticipationScope.READ_HISTORY}
                ),
            )

    def test_policy_reestablished_after_fork_can_continue_on_that_branch(self) -> None:
        self.living.add_episode(
            EpisodeRecord(
                episode_id="episode-fork-sibling",
                perspective_instance_id="perspective-fork-sibling",
                runtime_instance_id="runtime-fork-sibling",
            )
        )
        self.living.add_continuity_edge(
            ContinuityEdge(
                edge_id="edge-a-fork-sibling",
                previous_episode_id="episode-a",
                next_episode_id="episode-fork-sibling",
                transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
                continuity_status=ContinuityStatus.UNKNOWN,
            )
        )
        self.living.add_episode(
            EpisodeRecord(
                episode_id="episode-c-after-fork",
                perspective_instance_id="perspective-c-after-fork",
                runtime_instance_id="runtime-c-after-fork",
            )
        )
        self.living.add_continuity_edge(
            ContinuityEdge(
                edge_id="edge-b-c-after-fork",
                previous_episode_id="episode-b",
                next_episode_id="episode-c-after-fork",
                transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
                continuity_status=ContinuityStatus.UNKNOWN,
            )
        )
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-c-after-fork",
                episode_id="episode-c-after-fork",
                route_kind=RoomRouteKind.ATTACHED,
                room_id="room-r",
                basis="ordinary_handoff",
            )
        )
        branch_policy = trusted_test_room_continuation_policy(
            policy_id="policy-room-r-after-fork",
            room_id="room-r",
            established_episode_id="episode-b",
            established_attachment_event_id="route-b",
            allowed_scopes={
                RoomParticipationScope.READ_HISTORY,
            },
        )

        receipt = self.launcher.record_supported_runtime_launch(
            episode_id="episode-c-after-fork",
            perspective_instance_id="perspective-c-after-fork",
            observed_runtime_instance_id="runtime-c-after-fork",
            observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
        )
        evidence = self.authority.begin_trusted_continuation(
            launch_receipt=receipt,
            previous_episode_id="episode-b",
            room_id="room-r",
        )
        proposal = self.authority.prepare_grant(
            launch_evidence=evidence,
            policy=branch_policy,
            requested_scopes=frozenset(
                {RoomParticipationScope.READ_HISTORY}
            ),
        )
        approval = self.authority.approve_automatic_continuation(
            proposal=proposal,
            policy=branch_policy,
        )
        grant = self.authority.issue_grant(
            proposal=proposal,
            approval=approval,
        )

        self.authority.require_grant(
            grant=grant,
            session_id=evidence.session_id,
            episode_id="episode-c-after-fork",
            perspective_instance_id="perspective-c-after-fork",
            room_id="room-r",
            required_scope=RoomParticipationScope.READ_HISTORY,
        )

    def test_policy_anchor_route_revision_invalidates_grant(self) -> None:
        evidence, _, _, grant = self._grant(
            scopes=frozenset({RoomParticipationScope.READ_HISTORY})
        )
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-a-policy-revised",
                episode_id="episode-a",
                route_kind=RoomRouteKind.ATTACHED,
                room_id="room-r",
                basis="policy_anchor_route_revision",
                supersedes_attachment_event_id="route-a",
            )
        )

        with self.assertRaises(RoomParticipationStaleError):
            self.authority.require_grant(
                grant=grant,
                session_id=evidence.session_id,
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                room_id="room-r",
                required_scope=RoomParticipationScope.READ_HISTORY,
            )

    def test_new_room_route_requires_explicit_entry_instead_of_auto_policy(self) -> None:
        self.living.add_room(RoomRecord(room_id="room-new"))
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-b-new",
                episode_id="episode-b",
                route_kind=RoomRouteKind.ATTACHED,
                room_id="room-new",
                basis="late_branch_correction",
                supersedes_attachment_event_id="route-b",
            )
        )

        with self.assertRaises(RoomLaunchEvidenceError):
            self._launch()

    def test_read_history_does_not_imply_first_person_write(self) -> None:
        evidence, _, _, grant = self._grant(
            scopes=frozenset({RoomParticipationScope.READ_HISTORY})
        )

        self.authority.require_grant(
            grant=grant,
            session_id=evidence.session_id,
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            room_id="room-r",
            required_scope=RoomParticipationScope.READ_HISTORY,
        )
        with self.assertRaises(RoomParticipationAuthorizationError):
            self.authority.require_grant(
                grant=grant,
                session_id=evidence.session_id,
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                room_id="room-r",
                required_scope=RoomParticipationScope.APPEND_FIRST_PERSON,
            )

    def test_registered_policy_payload_cannot_be_mutated_to_widen_scope(self) -> None:
        evidence = self._launch()
        self.authority.prepare_grant(
            launch_evidence=evidence,
            policy=self.policy,
            requested_scopes=frozenset(
                {RoomParticipationScope.READ_HISTORY}
            ),
        )
        object.__setattr__(
            self.policy,
            "allowed_scopes",
            frozenset(
                {
                    RoomParticipationScope.READ_HISTORY,
                    RoomParticipationScope.READ_PRIVATE,
                }
            ),
        )

        with self.assertRaises(RoomParticipationAuthorizationError):
            self.authority.prepare_grant(
                launch_evidence=evidence,
                policy=self.policy,
                requested_scopes=frozenset(
                    {RoomParticipationScope.READ_PRIVATE}
                ),
            )

    def test_policy_tamper_after_grant_invalidates_use(self) -> None:
        evidence, _, _, grant = self._grant(
            scopes=frozenset({RoomParticipationScope.READ_HISTORY})
        )
        object.__setattr__(
            self.policy,
            "source_event_ref",
            "tampered-policy-event",
        )

        with self.assertRaises(RoomParticipationAuthorizationError):
            self.authority.require_grant(
                grant=grant,
                session_id=evidence.session_id,
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                room_id="room-r",
                required_scope=RoomParticipationScope.READ_HISTORY,
            )

    def test_same_policy_id_cannot_be_rebound_to_wider_payload(self) -> None:
        evidence = self._launch()
        self.authority.prepare_grant(
            launch_evidence=evidence,
            policy=self.policy,
            requested_scopes=frozenset(
                {RoomParticipationScope.READ_HISTORY}
            ),
        )
        wider = trusted_test_room_continuation_policy(
            policy_id=self.policy.policy_id,
            room_id="room-r",
            allowed_scopes={
                RoomParticipationScope.READ_HISTORY,
                RoomParticipationScope.READ_PRIVATE,
            },
            source_event_ref="different-event",
        )

        with self.assertRaises(RoomParticipationAuthorizationError):
            self.authority.prepare_grant(
                launch_evidence=evidence,
                policy=wider,
                requested_scopes=frozenset(
                    {RoomParticipationScope.READ_PRIVATE}
                ),
            )

    def test_policy_scope_cannot_be_widened_during_grant_issue(self) -> None:
        evidence = self._launch()
        with self.assertRaises(RoomParticipationAuthorizationError):
            self.authority.prepare_grant(
                launch_evidence=evidence,
                policy=self.policy,
                requested_scopes=frozenset(
                    {
                        RoomParticipationScope.READ_HISTORY,
                        RoomParticipationScope.READ_PRIVATE,
                    }
                ),
            )

    def test_approval_is_bound_to_exact_proposal_not_lookalike_scope(self) -> None:
        evidence = self._launch()
        proposal_read = self.authority.prepare_grant(
            launch_evidence=evidence,
            policy=self.policy,
            requested_scopes=frozenset(
                {RoomParticipationScope.READ_HISTORY}
            ),
        )
        proposal_write = self.authority.prepare_grant(
            launch_evidence=evidence,
            policy=self.policy,
            requested_scopes=frozenset(
                {RoomParticipationScope.APPEND_FIRST_PERSON}
            ),
        )
        approval_read = self.authority.approve_automatic_continuation(
            proposal=proposal_read,
            policy=self.policy,
        )

        with self.assertRaises(RoomParticipationAuthorizationError):
            self.authority.issue_grant(
                proposal=proposal_write,
                approval=approval_read,
            )

    def test_grant_proposal_in_memory_tamper_is_detected(self) -> None:
        evidence = self._launch()
        proposal = self.authority.prepare_grant(
            launch_evidence=evidence,
            policy=self.policy,
            requested_scopes=frozenset(
                {RoomParticipationScope.READ_HISTORY}
            ),
        )
        object.__setattr__(proposal, "room_id", "room-forged")

        with self.assertRaises(RoomParticipationAuthorizationError):
            self.authority.approve_automatic_continuation(
                proposal=proposal,
                policy=self.policy,
            )

    def test_approval_in_memory_tamper_is_detected(self) -> None:
        evidence = self._launch()
        proposal = self.authority.prepare_grant(
            launch_evidence=evidence,
            policy=self.policy,
            requested_scopes=frozenset(
                {RoomParticipationScope.READ_HISTORY}
            ),
        )
        approval = self.authority.approve_automatic_continuation(
            proposal=proposal,
            policy=self.policy,
        )
        object.__setattr__(approval, "binding_digest", "0" * 64)

        with self.assertRaises(RoomParticipationAuthorizationError):
            self.authority.issue_grant(
                proposal=proposal,
                approval=approval,
            )

    def test_grant_proposal_cannot_receive_multiple_approvals(self) -> None:
        evidence = self._launch()
        proposal = self.authority.prepare_grant(
            launch_evidence=evidence,
            policy=self.policy,
            requested_scopes=frozenset(
                {RoomParticipationScope.READ_HISTORY}
            ),
        )
        self.authority.approve_automatic_continuation(
            proposal=proposal,
            policy=self.policy,
        )

        with self.assertRaises(RoomParticipationAuthorizationError):
            self.authority.approve_automatic_continuation(
                proposal=proposal,
                policy=self.policy,
            )

    def test_automatic_approval_is_one_shot(self) -> None:
        evidence = self._launch()
        proposal = self.authority.prepare_grant(
            launch_evidence=evidence,
            policy=self.policy,
            requested_scopes=frozenset(
                {RoomParticipationScope.READ_HISTORY}
            ),
        )
        approval = self.authority.approve_automatic_continuation(
            proposal=proposal,
            policy=self.policy,
        )
        self.authority.issue_grant(
            proposal=proposal,
            approval=approval,
        )

        with self.assertRaises(RoomParticipationAuthorizationError):
            self.authority.issue_grant(
                proposal=proposal,
                approval=approval,
            )

    def test_grant_in_memory_tamper_cannot_widen_scope_even_with_new_digest(self) -> None:
        evidence, _, _, grant = self._grant(
            scopes=frozenset({RoomParticipationScope.READ_HISTORY})
        )
        widened = frozenset(
            {
                RoomParticipationScope.READ_HISTORY,
                RoomParticipationScope.READ_PRIVATE,
            }
        )
        object.__setattr__(grant, "scopes", widened)
        object.__setattr__(
            grant,
            "binding_digest",
            authority_module._grant_binding_digest(
                launch_evidence_id=grant.launch_evidence_id,
                policy_fingerprint=grant.policy_fingerprint,
                session_id=grant.session_id,
                episode_id=grant.episode_id,
                perspective_instance_id=grant.perspective_instance_id,
                room_id=grant.room_id,
                policy_id=grant.policy_id,
                policy_issuance_id=grant.policy_issuance_id,
                scopes=widened,
            ),
        )

        with self.assertRaises(RoomParticipationAuthorizationError):
            self.authority.require_grant(
                grant=grant,
                session_id=evidence.session_id,
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                room_id="room-r",
                required_scope=RoomParticipationScope.READ_PRIVATE,
            )

    def test_current_stance_scope_cannot_exist_without_first_person_append(self) -> None:
        with self.assertRaises(RoomParticipationAuthorizationError):
            trusted_test_room_continuation_policy(
                policy_id="policy-invalid-stance-only",
                room_id="room-r",
                allowed_scopes={
                    RoomParticipationScope.CHANGE_CURRENT_STANCE,
                },
            )

    def test_current_stance_grant_requires_and_preserves_first_person_scope(self) -> None:
        policy = trusted_test_room_continuation_policy(
            policy_id="policy-room-r-stance",
            room_id="room-r",
            allowed_scopes={
                RoomParticipationScope.APPEND_FIRST_PERSON,
                RoomParticipationScope.CHANGE_CURRENT_STANCE,
            },
        )
        evidence = self._launch()
        proposal = self.authority.prepare_grant(
            launch_evidence=evidence,
            policy=policy,
            requested_scopes=frozenset(
                {
                    RoomParticipationScope.APPEND_FIRST_PERSON,
                    RoomParticipationScope.CHANGE_CURRENT_STANCE,
                }
            ),
        )
        approval = self.authority.approve_automatic_continuation(
            proposal=proposal,
            policy=policy,
        )
        grant = self.authority.issue_grant(
            proposal=proposal,
            approval=approval,
        )

        self.authority.require_grant(
            grant=grant,
            session_id=evidence.session_id,
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            room_id="room-r",
            required_scope=RoomParticipationScope.CHANGE_CURRENT_STANCE,
        )
        self.authority.require_grant(
            grant=grant,
            session_id=evidence.session_id,
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            room_id="room-r",
            required_scope=RoomParticipationScope.APPEND_FIRST_PERSON,
        )

    def test_append_first_person_does_not_imply_change_current_stance(self) -> None:
        evidence, _, _, grant = self._grant(
            scopes=frozenset(
                {RoomParticipationScope.APPEND_FIRST_PERSON}
            )
        )
        with self.assertRaises(RoomParticipationAuthorizationError):
            self.authority.require_grant(
                grant=grant,
                session_id=evidence.session_id,
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                room_id="room-r",
                required_scope=RoomParticipationScope.CHANGE_CURRENT_STANCE,
            )

    def test_grant_target_binding_rejects_episode_perspective_room_or_session_swap(self) -> None:
        evidence, _, _, grant = self._grant()

        mismatches = (
            dict(session_id="other-session"),
            dict(episode_id="episode-a"),
            dict(perspective_instance_id="perspective-a"),
            dict(room_id="other-room"),
        )
        base = {
            "session_id": evidence.session_id,
            "episode_id": "episode-b",
            "perspective_instance_id": "perspective-b",
            "room_id": "room-r",
        }
        for mismatch in mismatches:
            supplied = dict(base)
            supplied.update(mismatch)
            with self.assertRaises(RoomParticipationAuthorizationError):
                self.authority.require_grant(
                    grant=grant,
                    required_scope=(
                        RoomParticipationScope.APPEND_FIRST_PERSON
                    ),
                    **supplied,
                )

    def test_forged_policy_cannot_mint_grant(self) -> None:
        with self.assertRaises(RoomParticipationAuthorizationError):
            TrustedRoomContinuationPolicy(
                policy_id="forged",
                issuance_id="forged-issuance",
                room_id="room-r",
                established_episode_id="episode-a",
                established_attachment_event_id="route-a",
                allowed_scopes=frozenset(
                    {RoomParticipationScope.APPEND_FIRST_PERSON}
                ),
                source_event_ref="user-says-so",
                _marker=object(),
            )

    def test_same_host_lease_reuses_one_authority_registry(self) -> None:
        evidence, _, _, grant = self._grant()
        reopened = open_room_participation_authority(
            lease=self.lease,
            store=self.living,
        )

        self.assertIs(reopened, self.authority)
        reopened.require_grant(
            grant=grant,
            session_id=evidence.session_id,
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            room_id="room-r",
            required_scope=RoomParticipationScope.APPEND_FIRST_PERSON,
        )

    def test_policy_suspension_revokes_grant_without_rewriting_room_intent(self) -> None:
        evidence, _, _, grant = self._grant()
        self.authority.suspend_policy(policy_id=self.policy.policy_id)

        with self.assertRaises(RoomParticipationAuthorizationError):
            self.authority.require_grant(
                grant=grant,
                session_id=evidence.session_id,
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                room_id="room-r",
                required_scope=RoomParticipationScope.APPEND_FIRST_PERSON,
            )

        with self.assertRaises(RoomParticipationStaleError):
            self.authority.prepare_grant(
                launch_evidence=evidence,
                policy=self.policy,
                requested_scopes=frozenset(
                    {RoomParticipationScope.READ_HISTORY}
                ),
            )

    def test_successor_launch_revokes_predecessor_episode_grant(self) -> None:
        evidence, _, _, grant = self._grant()

        self.living.add_episode(
            EpisodeRecord(
                episode_id="episode-c",
                perspective_instance_id="perspective-c",
                runtime_instance_id="runtime-c",
            )
        )
        self.living.add_continuity_edge(
            ContinuityEdge(
                edge_id="edge-b-c",
                previous_episode_id="episode-b",
                next_episode_id="episode-c",
                transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
                continuity_status=ContinuityStatus.UNKNOWN,
            )
        )
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-c",
                episode_id="episode-c",
                route_kind=RoomRouteKind.ATTACHED,
                room_id="room-r",
                basis="ordinary_handoff",
            )
        )

        receipt = self.launcher.record_supported_runtime_launch(
            episode_id="episode-c",
            perspective_instance_id="perspective-c",
            observed_runtime_instance_id="runtime-c",
            observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
        )
        self.authority.begin_trusted_continuation(
            launch_receipt=receipt,
            previous_episode_id="episode-b",
            room_id="room-r",
        )

        with self.assertRaises(RoomParticipationStaleError):
            self.authority.require_grant(
                grant=grant,
                session_id=evidence.session_id,
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                room_id="room-r",
                required_scope=RoomParticipationScope.APPEND_FIRST_PERSON,
            )

    def test_new_runtime_cannot_reuse_existing_episode(self) -> None:
        evidence, _, _, grant = self._grant()

        with self.assertRaises(RoomLaunchEvidenceError):
            self.launcher.record_supported_runtime_launch(
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                observed_runtime_instance_id="runtime-b",
                observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
            )

        self.authority.require_grant(
            grant=grant,
            session_id=evidence.session_id,
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            room_id="room-r",
            required_scope=RoomParticipationScope.APPEND_FIRST_PERSON,
        )

    def test_previous_route_revision_even_same_room_invalidates_grant(self) -> None:
        evidence, _, _, grant = self._grant()
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-a-revised",
                episode_id="episode-a",
                route_kind=RoomRouteKind.ATTACHED,
                room_id="room-r",
                basis="same_room_provenance_revision",
                supersedes_attachment_event_id="route-a",
            )
        )

        with self.assertRaises(RoomParticipationStaleError):
            self.authority.require_grant(
                grant=grant,
                session_id=evidence.session_id,
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                room_id="room-r",
                required_scope=RoomParticipationScope.APPEND_FIRST_PERSON,
            )

    def test_route_correction_after_issue_invalidates_grant(self) -> None:
        evidence, _, _, grant = self._grant()
        self.living.add_room(RoomRecord(room_id="room-corrected"))
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-b-corrected",
                episode_id="episode-b",
                route_kind=RoomRouteKind.ATTACHED,
                room_id="room-corrected",
                basis="late_route_correction",
                supersedes_attachment_event_id="route-b",
            )
        )

        with self.assertRaises(RoomParticipationStaleError):
            self.authority.require_grant(
                grant=grant,
                session_id=evidence.session_id,
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                room_id="room-r",
                required_scope=RoomParticipationScope.APPEND_FIRST_PERSON,
            )

    def test_late_fork_discovery_invalidates_existing_grant(self) -> None:
        evidence, _, _, grant = self._grant()
        self.living.add_episode(
            EpisodeRecord(
                episode_id="episode-fork",
                perspective_instance_id="perspective-fork",
            )
        )
        self.living.add_continuity_edge(
            ContinuityEdge(
                edge_id="edge-a-fork",
                previous_episode_id="episode-a",
                next_episode_id="episode-fork",
                transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
                continuity_status=ContinuityStatus.UNKNOWN,
            )
        )

        with self.assertRaises(RoomParticipationStaleError):
            self.authority.require_grant(
                grant=grant,
                session_id=evidence.session_id,
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                room_id="room-r",
                required_scope=RoomParticipationScope.APPEND_FIRST_PERSON,
            )

    def test_old_launch_receipt_does_not_cross_host_incarnation(self) -> None:
        receipt = self.launcher.record_supported_runtime_launch(
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            observed_runtime_instance_id="runtime-b",
            observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
        )

        self.lease.release()
        self.lease = acquire_home_single_instance(
            runtime_root=self.root,
            db_path=self.db_path,
        )
        self.authority = open_room_participation_authority(
            lease=self.lease,
            store=self.living,
        )
        self.launcher = trusted_test_runtime_launch_issuer(
            lease=self.lease,
            store=self.living,
        )

        with self.assertRaises(RoomLaunchEvidenceError):
            self.authority.begin_trusted_continuation(
                launch_receipt=receipt,
                previous_episode_id="episode-a",
                room_id="room-r",
            )

    def test_old_grant_does_not_cross_host_incarnation(self) -> None:
        evidence, _, _, grant = self._grant()

        self.lease.release()
        self.lease = acquire_home_single_instance(
            runtime_root=self.root,
            db_path=self.db_path,
        )
        self.authority = open_room_participation_authority(
            lease=self.lease,
            store=self.living,
        )
        self.launcher = trusted_test_runtime_launch_issuer(
            lease=self.lease,
            store=self.living,
        )

        with self.assertRaises(RoomParticipationAuthorizationError):
            self.authority.require_grant(
                grant=grant,
                session_id=evidence.session_id,
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                room_id="room-r",
                required_scope=RoomParticipationScope.APPEND_FIRST_PERSON,
            )

    def test_released_host_lease_invalidates_grant(self) -> None:
        evidence, _, _, grant = self._grant()
        self.lease.release()

        with self.assertRaises(RoomParticipationStaleError):
            self.authority.require_grant(
                grant=grant,
                session_id=evidence.session_id,
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                room_id="room-r",
                required_scope=RoomParticipationScope.APPEND_FIRST_PERSON,
            )

    def test_grant_schema_has_no_identity_verdict_or_adoption_field(self) -> None:
        fields = {field.name for field in dataclasses.fields(RoomParticipationGrant)}
        self.assertNotIn("same_self", fields)
        self.assertNotIn("different_self", fields)
        self.assertNotIn("adopted", fields)
        self.assertNotIn("adoption_event_id", fields)

    @unittest.skipUnless(hasattr(os, "fork"), "fork isolation is POSIX-only")
    def test_forked_child_cannot_consume_parent_launch_receipt(self) -> None:
        receipt = self.launcher.record_supported_runtime_launch(
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            observed_runtime_instance_id="runtime-b",
            observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
        )
        pid = os.fork()
        if pid == 0:  # pragma: no cover - child assertion
            try:
                self.authority.begin_trusted_continuation(
                    launch_receipt=receipt,
                    previous_episode_id="episode-a",
                    room_id="room-r",
                )
            except Exception:
                os._exit(0)
            os._exit(2)

        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)

        evidence = self.authority.begin_trusted_continuation(
            launch_receipt=receipt,
            previous_episode_id="episode-a",
            room_id="room-r",
        )
        self.assertEqual(evidence.episode_id, "episode-b")

    @unittest.skipUnless(hasattr(os, "fork"), "fork isolation is POSIX-only")
    def test_forked_child_cannot_reuse_parent_grant(self) -> None:
        evidence, _, _, grant = self._grant()
        pid = os.fork()
        if pid == 0:  # pragma: no cover - child assertion
            try:
                self.authority.require_grant(
                    grant=grant,
                    session_id=evidence.session_id,
                    episode_id="episode-b",
                    perspective_instance_id="perspective-b",
                    room_id="room-r",
                    required_scope=(
                        RoomParticipationScope.APPEND_FIRST_PERSON
                    ),
                )
            except Exception:
                os._exit(0)
            os._exit(2)

        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)


if __name__ == "__main__":
    unittest.main()
