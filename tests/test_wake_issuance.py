import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from _trusted_test_support import (
    trusted_test_room_continuation_policy,
    trusted_test_runtime_launch_issuer,
)

import home_memory_core.wake_issuance as issuance_module
from home_memory_core.current_admission import (
    CurrentAdmissionStore,
    open_current_admission_authority,
)
from home_memory_core.current_resolver import (
    CurrentResolverStatus,
    open_current_resolver,
)
from home_memory_core.current_store import (
    CurrentSourceBinding,
    CurrentStore,
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
from home_memory_core.host_runtime import acquire_home_single_instance
from home_memory_core.living_authority import (
    RoomParticipationScope,
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
from home_memory_core.source import create_source_record
from home_memory_core.storage import MemoryStore
from home_memory_core.wake_issuance import (
    IssuedWakePacket,
    WakeIssuanceAuthorizationError,
    WakeIssuanceIntegrityError,
    WakeIssuanceReceipt,
    open_wake_issuance_authority,
)
from home_memory_core.wake_packet import (
    WakeInputTrust,
    WakeLayer,
    WakeLayerAvailability,
    WakeOmission,
    WakePacketError,
    WakePrivacyScope,
    WakePrivacyScopeKind,
)


UTC = timezone.utc


class CountingClock:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.value


class WakeIssuanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "data" / "home.db"

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
        self.living.add_episode(
            EpisodeRecord(
                episode_id="episode-b",
                perspective_instance_id="perspective-b",
                runtime_instance_id="runtime-b",
            )
        )
        self.living.add_episode(
            EpisodeRecord(
                episode_id="episode-c",
                perspective_instance_id="perspective-c",
                runtime_instance_id="runtime-c",
            )
        )
        self.living.add_continuity_edge(
            ContinuityEdge(
                edge_id="edge-a-b",
                previous_episode_id="episode-a",
                next_episode_id="episode-b",
                transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
                continuity_status=ContinuityStatus.UNKNOWN,
                support_refs=("opaque-edge-support",),
            )
        )
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-a",
                episode_id="episode-a",
                route_kind=RoomRouteKind.ATTACHED,
                room_id="room-r",
                basis="existing-room-line",
            )
        )
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-b",
                episode_id="episode-b",
                route_kind=RoomRouteKind.ATTACHED,
                room_id="room-r",
                basis="supported-continuation",
                support_refs=("opaque-route-support",),
            )
        )
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-c",
                episode_id="episode-c",
                route_kind=RoomRouteKind.UNATTACHED,
                room_id=None,
                basis="explicitly-unattached",
            )
        )

        self.lease = acquire_home_single_instance(
            runtime_root=self.root,
            db_path=self.db,
        )
        self.room_authority = open_room_participation_authority(
            lease=self.lease,
            store=self.living,
        )
        self.launcher = trusted_test_runtime_launch_issuer(
            lease=self.lease,
            store=self.living,
        )
        self.policy = trusted_test_room_continuation_policy(
            lease=self.lease,
            store=self.living,
            policy_id="policy-room-r-wake-issuance",
            room_id="room-r",
            allowed_scopes={
                RoomParticipationScope.APPEND_FIRST_PERSON,
                RoomParticipationScope.CHANGE_CURRENT_STANCE,
            },
        )

        self.current = CurrentStore(self.db)
        self.current.initialize()
        self.admission_store = CurrentAdmissionStore(self.db)
        self.admission_store.initialize()
        self.admission = open_current_admission_authority(
            current_store=self.current,
            admission_store=self.admission_store,
            room_authority=self.room_authority,
        )
        self.resolver = open_current_resolver(
            admission_authority=self.admission,
        )

        self.as_of = datetime(2026, 10, 5, 20, 30, tzinfo=UTC)
        self.clock = CountingClock(self.as_of)
        self.issuer = open_wake_issuance_authority(
            living_store=self.living,
            current_resolver=self.resolver,
            clock=self.clock,
        )
        self.grant = self._grant()

    def tearDown(self) -> None:
        if not self.lease.released:
            self.lease.release()
        self.tmp.cleanup()

    def _grant(self):
        launch = self.launcher.record_supported_runtime_launch(
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            observed_runtime_instance_id="runtime-b",
            observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
        )
        evidence = self.room_authority.begin_trusted_continuation(
            launch_receipt=launch,
            previous_episode_id="episode-a",
            room_id="room-r",
        )
        proposal = self.room_authority.prepare_grant(
            launch_evidence=evidence,
            policy=self.policy,
            requested_scopes=frozenset(
                {
                    RoomParticipationScope.APPEND_FIRST_PERSON,
                    RoomParticipationScope.CHANGE_CURRENT_STANCE,
                }
            ),
        )
        approval = self.room_authority.approve_automatic_continuation(
            proposal=proposal,
            policy=self.policy,
        )
        return self.room_authority.issue_grant(
            proposal=proposal,
            approval=approval,
        )

    def _binding(self, ref: str) -> CurrentSourceBinding:
        source = create_source_record(
            source_id=f"src-{ref}",
            content=f"wake issuance evidence:{ref}",
            authored_by="synthetic-wake-issuance-test",
            scope="room-r",
        )
        self.memory.add_source(source)
        return CurrentSourceBinding(
            ref,
            create_evidence_ref(
                source=source,
                start_char=0,
                end_char=len(source.content),
            ),
        )

    def _admit_state(
        self,
        *,
        state_id: str = "state-issued",
        value: str = "building",
    ):
        ref = f"ref-{state_id}"
        record = CurrentStateRecord(
            state_id=state_id,
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key="project.home.status",
            state_kind=CurrentStateKind.PROJECT_STATUS,
            value=value,
            event_time=self.as_of,
            recorded_at=self.as_of,
            valid_from=self.as_of,
            validity_rule=ValidityRule.DURABLE_UNTIL_CHANGED,
            downgrade_rule=DowngradeRule.NONE,
            semantic_change_authority=(
                SemanticChangeAuthority.ROOM_FIRST_PERSON
            ),
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            source_refs=(ref,),
        )
        receipt = self.admission.admit_room_state(
            record=record,
            source_bindings=(self._binding(ref),),
            grant=self.grant,
        )
        return record, receipt

    def _dump_database(self) -> str:
        connection = sqlite3.connect(self.db)
        try:
            return "\n".join(connection.iterdump())
        finally:
            connection.close()

    def test_issue_reads_canonical_living_and_live_current(self) -> None:
        record, _ = self._admit_state()

        issued = self.issuer.issue(episode_id="episode-b")

        self.assertEqual(self.clock.calls, 1)
        self.assertEqual(issued.packet.episode_id, "episode-b")
        self.assertEqual(
            issued.packet.input_trust,
            WakeInputTrust.TYPED_CALLER_INPUT,
        )
        self.assertEqual(
            issued.packet.map.item.room_id,
            "room-r",
        )
        self.assertEqual(
            issued.packet.map.item.incoming_continuity.edge_id,
            "edge-a-b",
        )
        self.assertEqual(len(issued.packet.room_now.items), 1)
        candidate = issued.packet.room_now.items[0].candidates[0]
        self.assertEqual(candidate.state_id, record.state_id)
        self.assertEqual(candidate.value, record.value)
        self.assertNotIn(
            "opaque-edge-support",
            repr(issued.packet),
        )
        self.assertNotIn(
            "opaque-route-support",
            repr(issued.packet),
        )
        self.assertIs(
            self.issuer.require_live_issuance(issued=issued),
            issued.packet,
        )

    def test_issue_accepts_only_episode_request_not_typed_fake_inputs(self) -> None:
        with self.assertRaises(TypeError):
            self.issuer.issue(
                episode_id="episode-b",
                episode=object(),
            )
        with self.assertRaises(TypeError):
            self.issuer.issue(
                episode_id="episode-b",
                room_current=object(),
            )

    def test_living_and_current_use_same_sqlite_snapshot_connection(self) -> None:
        self._admit_state()
        seen = {}
        living_read = LivingStore._read_all_episodes
        current_read = self.resolver.__class__._resolve_owner_in_connection

        def wrapped_living(store, connection):
            seen["living"] = id(connection)
            self.assertTrue(connection.in_transaction)
            self.assertEqual(
                connection.execute("PRAGMA query_only").fetchone()[0],
                1,
            )
            return living_read(store, connection)

        def wrapped_current(resolver, **kwargs):
            connection = kwargs["connection"]
            seen["current"] = id(connection)
            self.assertTrue(connection.in_transaction)
            return current_read(resolver, **kwargs)

        with patch.object(
            LivingStore,
            "_read_all_episodes",
            autospec=True,
            side_effect=wrapped_living,
        ), patch.object(
            self.resolver.__class__,
            "_resolve_owner_in_connection",
            autospec=True,
            side_effect=wrapped_current,
        ):
            self.issuer.issue(episode_id="episode-b")

        self.assertEqual(seen["living"], seen["current"])

    def test_caller_owned_living_instance_method_cannot_forge_operational_reads(self) -> None:
        self._admit_state()
        fake = EpisodeRecord(
            episode_id="episode-b",
            perspective_instance_id="forged-perspective",
            runtime_instance_id="forged-runtime",
        )

        with patch.object(
            self.living,
            "_read_all_episodes",
            return_value=(fake,),
        ):
            issued = self.issuer.issue(episode_id="episode-b")

        self.assertEqual(
            issued.packet.perspective_instance_id,
            "perspective-b",
        )
        self.assertNotEqual(
            issued.packet.perspective_instance_id,
            fake.perspective_instance_id,
        )

    def test_concurrent_route_write_cannot_tear_one_issuance_snapshot(self) -> None:
        self._admit_state()
        connection = sqlite3.connect(self.db)
        try:
            mode = connection.execute(
                "PRAGMA journal_mode=WAL"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(str(mode).lower(), "wal")

        original = LivingStore._read_all_episodes
        wrote = {"done": False}

        def interleave_route_write(store, read_connection):
            episodes = original(store, read_connection)
            if not wrote["done"]:
                wrote["done"] = True
                self.living.add_room_attachment(
                    RoomAttachmentEvent(
                        attachment_event_id="route-b-unattached",
                        episode_id="episode-b",
                        route_kind=RoomRouteKind.UNATTACHED,
                        room_id=None,
                        basis="concurrent-correction",
                        supersedes_attachment_event_id="route-b",
                    )
                )
            return episodes

        with patch.object(
            LivingStore,
            "_read_all_episodes",
            autospec=True,
            side_effect=interleave_route_write,
        ):
            issued = self.issuer.issue(episode_id="episode-b")

        self.assertTrue(wrote["done"])
        self.assertEqual(
            issued.packet.map.item.route_decision.value,
            "attached",
        )
        self.assertEqual(issued.packet.map.item.room_id, "room-r")
        self.assertEqual(len(issued.packet.room_now.items), 1)

        canonical_after = self.living.resolve_room_attachment(
            episode_id="episode-b",
        )
        self.assertEqual(canonical_after.decision, "unattached")
        self.assertIsNone(canonical_after.room_id)

    def test_caller_owned_resolver_instance_method_cannot_replace_operational_resolution(self) -> None:
        record, _ = self._admit_state()

        with patch.object(
            self.resolver,
            "_resolve_owner_in_connection",
            side_effect=AssertionError(
                "caller-owned resolver instance method must not run"
            ),
        ):
            issued = self.issuer.issue(episode_id="episode-b")

        self.assertEqual(
            issued.packet.room_now.items[0].candidates[0].state_id,
            record.state_id,
        )

    def test_issuance_is_database_read_only(self) -> None:
        self._admit_state()
        before = self._dump_database()

        self.issuer.issue(episode_id="episode-b")

        self.assertEqual(self._dump_database(), before)

    def test_unattached_episode_issues_without_room_current(self) -> None:
        issued = self.issuer.issue(episode_id="episode-c")

        self.assertEqual(
            issued.packet.map.item.route_decision.value,
            "unattached",
        )
        self.assertEqual(
            issued.packet.room_now.availability,
            WakeLayerAvailability.UNAVAILABLE,
        )
        self.assertEqual(issued.packet.room_now.items, ())
        self.issuer.require_live_issuance(issued=issued)

    def test_missing_live_current_admission_proof_stays_withheld(self) -> None:
        record, _ = self._admit_state()
        with self.admission._receipt_guard:
            self.admission._receipts.clear()

        issued = self.issuer.issue(episode_id="episode-b")

        self.assertEqual(
            issued.packet.room_now.availability,
            WakeLayerAvailability.PARTIAL,
        )
        self.assertEqual(issued.packet.room_now.items, ())
        self.assertNotIn(record.value, repr(issued.packet))
        self.assertNotIn(record.value, repr(issued.assembly_receipt))
        self.assertTrue(
            any(
                omission.layer is WakeLayer.ROOM_NOW
                and omission.classification
                == "operationally_withheld"
                for omission in issued.assembly_receipt.omissions
            )
        )

    def test_receipt_cannot_be_caller_minted(self) -> None:
        issued = self.issuer.issue(episode_id="episode-b")
        receipt = issued.issuance_receipt

        with self.assertRaises(WakeIssuanceAuthorizationError):
            WakeIssuanceReceipt(
                issuance_id="forged",
                issuance_version=receipt.issuance_version,
                authority_id=receipt.authority_id,
                home_process_instance_id=(
                    receipt.home_process_instance_id
                ),
                canonical_db_binding_digest=(
                    receipt.canonical_db_binding_digest
                ),
                wake_id=receipt.wake_id,
                episode_id=receipt.episode_id,
                as_of=receipt.as_of,
                packet_digest=receipt.packet_digest,
                assembly_receipt_digest=(
                    receipt.assembly_receipt_digest
                ),
                _marker=object(),
            )

    def test_replaced_marker_valid_receipt_is_not_live_proof(self) -> None:
        issued = self.issuer.issue(episode_id="episode-b")
        copied_receipt = replace(
            issued.issuance_receipt,
            issuance_id="wake-issuance-copied",
        )
        copied = IssuedWakePacket(
            packet=issued.packet,
            assembly_receipt=issued.assembly_receipt,
            issuance_receipt=copied_receipt,
        )

        with self.assertRaises(WakeIssuanceAuthorizationError):
            self.issuer.require_live_issuance(issued=copied)

    def test_foreign_authority_cannot_verify_receipt(self) -> None:
        issued = self.issuer.issue(episode_id="episode-b")
        foreign = open_wake_issuance_authority(
            living_store=self.living,
            current_resolver=self.resolver,
            clock=CountingClock(self.as_of),
        )
        self.assertNotEqual(
            foreign.authority_id,
            self.issuer.authority_id,
        )

        with self.assertRaises(WakeIssuanceAuthorizationError):
            foreign.require_live_issuance(issued=issued)

    def test_nested_packet_mutation_breaks_issuance_digest(self) -> None:
        self._admit_state()
        issued = self.issuer.issue(episode_id="episode-b")
        item = issued.packet.room_now.items[0]
        candidate = item.candidates[0]
        changed_candidate = replace(
            candidate,
            value="tampered-but-type-valid",
        )
        changed_item = replace(
            item,
            candidates=(changed_candidate,),
        )
        changed_packet = replace(
            issued.packet,
            room_now=replace(
                issued.packet.room_now,
                items=(changed_item,),
            ),
        )

        with self.assertRaises(WakeIssuanceIntegrityError):
            IssuedWakePacket(
                packet=changed_packet,
                assembly_receipt=issued.assembly_receipt,
                issuance_receipt=issued.issuance_receipt,
            )

    def test_in_place_frozen_packet_mutation_is_detected_at_live_verify(self) -> None:
        self._admit_state()
        issued = self.issuer.issue(episode_id="episode-b")
        candidate = issued.packet.room_now.items[0].candidates[0]
        object.__setattr__(
            candidate,
            "value",
            "mutated-after-issued-wrapper-construction",
        )

        with self.assertRaises(WakeIssuanceIntegrityError):
            self.issuer.require_live_issuance(issued=issued)

    def test_assembly_receipt_mutation_breaks_issuance_digest(self) -> None:
        issued = self.issuer.issue(episode_id="episode-b")
        changed_assembly = replace(
            issued.assembly_receipt,
            omissions=(
                *issued.assembly_receipt.omissions,
                WakeOmission(
                    layer=WakeLayer.RECENT_LIFE,
                    subject_ref="fake",
                    classification="fake",
                    reason_codes=("FAKE",),
                ),
            ),
        )

        with self.assertRaises(WakeIssuanceIntegrityError):
            IssuedWakePacket(
                packet=issued.packet,
                assembly_receipt=changed_assembly,
                issuance_receipt=issued.issuance_receipt,
            )

    def test_identity_and_time_rebinding_breaks_issued_wrapper(self) -> None:
        issued = self.issuer.issue(episode_id="episode-b")

        # Packet-level semantic identity already rejects an isolated Episode
        # rewrite before issuance verification is reached.
        with self.assertRaises(WakePacketError):
            replace(issued.packet, episode_id="episode-other")

        for changed in (
            replace(issued.packet, wake_id="wake-other"),
            replace(
                issued.packet,
                as_of=datetime(2026, 10, 5, 21, tzinfo=UTC),
            ),
        ):
            with self.assertRaises(WakeIssuanceIntegrityError):
                IssuedWakePacket(
                    packet=changed,
                    assembly_receipt=issued.assembly_receipt,
                    issuance_receipt=issued.issuance_receipt,
                )

        changed_receipt = replace(
            issued.issuance_receipt,
            episode_id="episode-other",
        )
        with self.assertRaises(WakeIssuanceIntegrityError):
            IssuedWakePacket(
                packet=issued.packet,
                assembly_receipt=issued.assembly_receipt,
                issuance_receipt=changed_receipt,
            )

    def test_naive_clock_fails_before_canonical_read(self) -> None:
        naive = CountingClock(datetime(2026, 10, 5, 20, 30))
        issuer = open_wake_issuance_authority(
            living_store=self.living,
            current_resolver=self.resolver,
            clock=naive,
        )
        with patch.object(
            self.resolver.__class__,
            "_read_connection",
            autospec=True,
            wraps=self.resolver.__class__._read_connection,
        ) as read:
            with self.assertRaises(WakeIssuanceIntegrityError):
                issuer.issue(episode_id="episode-b")
        self.assertEqual(naive.calls, 1)
        read.assert_not_called()

    def test_clock_is_called_exactly_once_per_issue(self) -> None:
        self.issuer.issue(episode_id="episode-b")
        self.assertEqual(self.clock.calls, 1)
        self.issuer.issue(episode_id="episode-c")
        self.assertEqual(self.clock.calls, 2)

    def test_mismatched_canonical_database_roots_are_rejected(self) -> None:
        other_db = self.root / "other" / "home.db"
        MemoryStore(other_db).initialize()
        other_living = LivingStore(other_db)
        other_living.initialize()

        with self.assertRaises(WakeIssuanceAuthorizationError):
            open_wake_issuance_authority(
                living_store=other_living,
                current_resolver=self.resolver,
                clock=CountingClock(self.as_of),
            )

    def test_living_store_path_drift_invalidates_live_authority(self) -> None:
        issued = self.issuer.issue(episode_id="episode-b")
        original = self.living.db_path
        self.living.db_path = self.root / "drifted" / "home.db"
        try:
            with self.assertRaises(
                WakeIssuanceAuthorizationError
            ):
                self.issuer.require_live_issuance(issued=issued)
        finally:
            self.living.db_path = original

    def test_issued_wrapper_has_no_renderer_or_model_capability_fields(self) -> None:
        issued = self.issuer.issue(episode_id="episode-b")

        self.assertEqual(
            set(issued.__dataclass_fields__),
            {"packet", "assembly_receipt", "issuance_receipt"},
        )
        self.assertFalse(hasattr(issued, "system_prompt"))
        self.assertFalse(hasattr(issued, "model_request"))
        self.assertFalse(hasattr(issued, "tools"))
        self.assertEqual(
            issued.packet.use_boundary.model_delivery_authority.value,
            "none",
        )
        self.assertEqual(
            issued.packet.use_boundary.current_first_person_speech_authority.value,
            "none",
        )

    def test_canonical_db_binding_is_digest_not_machine_path(self) -> None:
        issued = self.issuer.issue(episode_id="episode-b")
        receipt = issued.issuance_receipt

        self.assertEqual(len(receipt.canonical_db_binding_digest), 64)
        self.assertNotIn(str(self.db), repr(receipt))
        self.assertNotIn(str(self.root), repr(receipt))


if __name__ == "__main__":
    unittest.main()