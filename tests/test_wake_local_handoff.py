import inspect
import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from _suppression_test_support import (
    create_test_suppression_record as create_suppression_record,
)
from _trusted_test_support import (
    trusted_test_room_continuation_policy,
    trusted_test_runtime_launch_issuer,
)

from home_memory_core.current_admission import (
    CurrentAdmissionStore,
    open_current_admission_authority,
)
from home_memory_core.current_resolver import open_current_resolver
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
from home_memory_core.home_state_ordering import (
    HomeStateOrderingReentryError,
    home_state_coordinator_for_path,
)
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
from home_memory_core.wake_issuance import open_wake_issuance_authority
from home_memory_core.wake_local_handoff import (
    LocalWakeTransportBoundary,
    WakeLocalHandoffAuthorizationError,
    WakeLocalHandoffIntegrityError,
    open_wake_local_handoff_authority,
)
from home_memory_core.wake_packet import (
    WakeAuthority,
    WakeLayerAvailability,
)


UTC = timezone.utc


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        return self.value


class WakeLocalHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "data" / "home.db"

        self.memory = MemoryStore(self.db)
        self.memory.initialize()

        self.living = LivingStore(self.db)
        self.living.initialize()
        self.living.add_room(RoomRecord(room_id="room-r"))
        for episode_id, perspective_id, runtime_id in (
            ("episode-a", "perspective-a", "runtime-a"),
            ("episode-b", "perspective-b", "runtime-b"),
            ("episode-c", "perspective-c", "runtime-c"),
        ):
            self.living.add_episode(
                EpisodeRecord(
                    episode_id=episode_id,
                    perspective_instance_id=perspective_id,
                    runtime_instance_id=runtime_id,
                )
            )

        self.living.add_continuity_edge(
            ContinuityEdge(
                edge_id="edge-a-b",
                previous_episode_id="episode-a",
                next_episode_id="episode-b",
                transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
                continuity_status=ContinuityStatus.UNKNOWN,
                support_refs=("opaque-continuity-support",),
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
            policy_id="policy-wake-local-handoff",
            room_id="room-r",
            allowed_scopes={
                RoomParticipationScope.APPEND_FIRST_PERSON,
                RoomParticipationScope.CHANGE_CURRENT_STANCE,
            },
        )
        self.grant = self._grant()

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

        self.as_of = datetime(
            2026, 10, 6, 9, 0, tzinfo=UTC
        )
        self.clock = FixedClock(self.as_of)
        self.issuer = open_wake_issuance_authority(
            living_store=self.living,
            current_resolver=self.resolver,
            clock=self.clock,
        )
        self.handoff = open_wake_local_handoff_authority(
            wake_issuance_authority=self.issuer,
        )
        self.boundary = self.handoff.local_transport_boundary
        self.coordinator = home_state_coordinator_for_path(
            self.db
        )

        self.assertIs(
            self.memory._home_state_coordinator,
            self.coordinator,
        )
        self.assertIs(
            self.living._home_state_coordinator,
            self.coordinator,
        )
        self.assertIs(
            self.current._home_state_coordinator,
            self.coordinator,
        )

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

    def _new_binding(
        self,
        ref: str,
    ) -> tuple[CurrentSourceBinding, object]:
        source = create_source_record(
            source_id=f"src-{ref}",
            content=f"synthetic handoff evidence:{ref}",
            authored_by="synthetic-handoff-test",
            scope="room-r",
        )
        self.memory.add_source(source)
        return (
            CurrentSourceBinding(
                ref,
                create_evidence_ref(
                    source=source,
                    start_char=0,
                    end_char=len(source.content),
                ),
            ),
            source,
        )

    def _state_record(
        self,
        *,
        state_id: str,
        key: str,
        value: str,
        ref: str,
    ) -> CurrentStateRecord:
        return CurrentStateRecord(
            state_id=state_id,
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key=key,
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

    def _admit_state(
        self,
        *,
        state_id: str,
        key: str,
        value: str,
    ):
        ref = f"ref-{state_id}"
        binding, source = self._new_binding(ref)
        record = self._state_record(
            state_id=state_id,
            key=key,
            value=value,
            ref=ref,
        )
        receipt = self.admission.admit_room_state(
            record=record,
            source_bindings=(binding,),
            grant=self.grant,
        )
        return record, receipt, source

    def _payload_for_receipt(self, receipt):
        envelope = self.boundary.require_live_acceptance(
            receipt=receipt
        )
        return envelope, json.loads(
            envelope.rendered.payload_json
        )

    def _assert_writer_waits_during_local_accept(
        self,
        writer,
    ):
        accept_entered = threading.Event()
        release_accept = threading.Event()
        writer_done = threading.Event()
        handoff_done = threading.Event()
        errors = []
        order = []
        result = {}

        original = self.boundary._accept_exact

        def paused_accept(*, envelope, cut):
            self.coordinator.require_active_cut(cut=cut)
            self.assertEqual(
                self.coordinator.generation,
                cut.generation,
            )
            accept_entered.set()
            if not release_accept.wait(timeout=2):
                raise AssertionError(
                    "local accept test release timed out"
                )
            receipt = original(
                envelope=envelope,
                cut=cut,
            )
            order.append("accepted")
            self.assertEqual(
                self.coordinator.generation,
                cut.generation,
            )
            return receipt

        def run_handoff() -> None:
            try:
                result["receipt"] = self.handoff.handoff(
                    request_id="request-concurrent",
                    episode_id="episode-b",
                    user_input="synthetic request",
                )
                handoff_done.set()
            except BaseException as error:
                errors.append(error)

        def run_writer() -> None:
            try:
                writer()
                order.append("writer_done")
                writer_done.set()
            except BaseException as error:
                errors.append(error)

        with patch.object(
            self.boundary,
            "_accept_exact",
            side_effect=paused_accept,
        ):
            handoff_thread = threading.Thread(
                target=run_handoff
            )
            handoff_thread.start()
            self.assertTrue(
                accept_entered.wait(timeout=2)
            )
            cut_generation = self.coordinator.generation

            writer_thread = threading.Thread(
                target=run_writer
            )
            writer_thread.start()
            time.sleep(0.1)
            self.assertFalse(writer_done.is_set())
            self.assertEqual(
                self.coordinator.generation,
                cut_generation,
            )

            release_accept.set()
            handoff_thread.join(timeout=3)
            writer_thread.join(timeout=3)

        self.assertEqual(errors, [])
        self.assertTrue(handoff_done.is_set())
        self.assertTrue(writer_done.is_set())
        self.assertLess(
            order.index("accepted"),
            order.index("writer_done"),
        )
        receipt = result["receipt"]
        self.assertEqual(
            receipt.generation,
            cut_generation,
        )
        self.assertGreater(
            self.coordinator.generation,
            cut_generation,
        )
        return receipt

    def test_handoff_freshly_builds_and_locally_accepts_exact_envelope(self) -> None:
        self._admit_state(
            state_id="state-home",
            key="project.home.status",
            value="building",
        )
        before_generation = self.coordinator.generation

        receipt = self.handoff.handoff(
            request_id="request-1",
            episode_id="episode-b",
            user_input="hello HOME",
        )

        self.assertEqual(
            self.coordinator.generation,
            before_generation,
        )
        self.assertEqual(
            receipt.generation,
            before_generation,
        )
        self.assertEqual(
            receipt.acceptance_status,
            "accepted_local",
        )

        envelope, payload = self._payload_for_receipt(
            receipt
        )
        self.assertEqual(envelope.request_id, "request-1")
        self.assertEqual(envelope.episode_id, "episode-b")
        self.assertEqual(envelope.user_input, "hello HOME")
        self.assertEqual(
            envelope.wake_id,
            receipt.wake_id,
        )
        self.assertEqual(
            envelope.issuance_id,
            receipt.issuance_id,
        )
        self.assertEqual(
            envelope.rendered.receipt.payload_digest,
            receipt.rendered_payload_digest,
        )
        self.assertEqual(
            envelope.rendered.receipt.plan_digest,
            receipt.presentation_plan_digest,
        )
        self.assertEqual(
            payload["model_delivery_authority"],
            "none",
        )
        room_blocks = payload["presentation"]["layers"][2]["blocks"]
        self.assertEqual(
            room_blocks[0]["candidates"][0]["value"],
            "building",
        )

    def test_public_handoff_has_no_callback_or_prebuilt_artifact_parameters(self) -> None:
        parameters = set(
            inspect.signature(
                self.handoff.handoff
            ).parameters
        )
        self.assertEqual(
            parameters,
            {"request_id", "episode_id", "user_input"},
        )
        for forbidden in (
            "callback",
            "transport_handoff",
            "issued",
            "packet",
            "plan",
            "rendered",
            "envelope",
            "as_of",
        ):
            self.assertNotIn(forbidden, parameters)

        with self.assertRaises(TypeError):
            self.handoff.handoff(
                request_id="request-bad",
                episode_id="episode-c",
                user_input="x",
                issued=object(),
            )

    def test_retry_gets_fresh_wake_issuance_nonce_and_receipt(self) -> None:
        first = self.handoff.handoff(
            request_id="request-retry",
            episode_id="episode-c",
            user_input="retry me",
        )
        second = self.handoff.handoff(
            request_id="request-retry",
            episode_id="episode-c",
            user_input="retry me",
        )

        first_env = self.boundary.require_live_acceptance(
            receipt=first
        )
        second_env = self.boundary.require_live_acceptance(
            receipt=second
        )
        self.assertNotEqual(first.handoff_id, second.handoff_id)
        self.assertNotEqual(first.wake_id, second.wake_id)
        self.assertNotEqual(
            first.issuance_id,
            second.issuance_id,
        )
        self.assertNotEqual(
            first.handoff_nonce,
            second.handoff_nonce,
        )
        self.assertNotEqual(
            first.envelope_digest,
            second.envelope_digest,
        )
        self.assertIsNot(first_env, second_env)

    def test_accepted_nonce_cannot_be_accepted_again(self) -> None:
        receipt = self.handoff.handoff(
            request_id="request-once",
            episode_id="episode-c",
            user_input="once",
        )
        envelope = self.boundary.require_live_acceptance(
            receipt=receipt
        )

        cut = self.coordinator.acquire_cut()
        try:
            with self.assertRaises(
                WakeLocalHandoffAuthorizationError
            ):
                self.boundary._accept_exact(
                    envelope=envelope,
                    cut=cut,
                )
        finally:
            self.coordinator.release_cut(cut=cut)

    def test_copied_receipt_is_not_live_acceptance_proof(self) -> None:
        receipt = self.handoff.handoff(
            request_id="request-copy",
            episode_id="episode-c",
            user_input="copy",
        )
        copied = replace(receipt)
        self.assertIsNot(copied, receipt)

        with self.assertRaises(
            WakeLocalHandoffAuthorizationError
        ):
            self.boundary.require_live_acceptance(
                receipt=copied
            )

    def test_mutated_accepted_envelope_breaks_live_acceptance_digest(self) -> None:
        receipt = self.handoff.handoff(
            request_id="request-mutation",
            episode_id="episode-c",
            user_input="original",
        )
        envelope = self.boundary.require_live_acceptance(
            receipt=receipt
        )
        object.__setattr__(
            envelope,
            "user_input",
            "changed-after-local-accept",
        )

        with self.assertRaises(
            WakeLocalHandoffIntegrityError
        ):
            self.boundary.require_live_acceptance(
                receipt=receipt
            )

    def test_same_thread_supported_writer_inside_cut_fails_closed(self) -> None:
        cut = self.coordinator.acquire_cut()
        try:
            source = create_source_record(
                source_id="source-reentrant",
                content="synthetic",
                authored_by="test",
                scope="room-r",
            )
            with self.assertRaises(
                HomeStateOrderingReentryError
            ):
                self.memory.add_source(source)

            with self.assertRaises(
                HomeStateOrderingReentryError
            ):
                self.living.add_room(
                    RoomRecord(room_id="room-reentrant")
                )
        finally:
            self.coordinator.release_cut(cut=cut)

    def test_living_route_writer_waits_until_local_acceptance(self) -> None:
        correction = RoomAttachmentEvent(
            attachment_event_id="route-b-correction",
            episode_id="episode-b",
            route_kind=RoomRouteKind.UNATTACHED,
            room_id=None,
            basis="concurrent-correction",
            supersedes_attachment_event_id="route-b",
        )

        receipt = self._assert_writer_waits_during_local_accept(
            lambda: self.living.add_room_attachment(
                correction
            )
        )
        envelope, payload = self._payload_for_receipt(
            receipt
        )
        self.assertEqual(
            payload["presentation"]["layers"][0]["blocks"][0]["route_decision"],
            "attached",
        )
        self.assertEqual(envelope.episode_id, "episode-b")
        self.assertEqual(
            self.living.resolve_room_attachment(
                episode_id="episode-b"
            ).decision,
            "unattached",
        )

    def test_source_suppression_waits_until_local_acceptance(self) -> None:
        _record, _receipt, source = self._admit_state(
            state_id="state-suppress",
            key="project.suppress",
            value="visible-at-cut",
        )
        suppression = create_suppression_record(
            suppression_id="suppression-handoff",
            source_id=source.source_id,
            requested_by="vivi",
            reason="stop use after local acceptance",
        )

        receipt = self._assert_writer_waits_during_local_accept(
            lambda: self.memory.suppress_source(
                suppression
            )
        )
        _envelope, payload = self._payload_for_receipt(
            receipt
        )
        values = [
            candidate["value"]
            for block in payload["presentation"]["layers"][2]["blocks"]
            for candidate in block["candidates"]
        ]
        self.assertIn("visible-at-cut", values)
        self.assertFalse(
            self.memory.is_source_usable(source.source_id)
        )

    def test_current_admission_waits_until_local_acceptance(self) -> None:
        ref = "ref-state-waiting"
        binding, _source = self._new_binding(ref)
        record = self._state_record(
            state_id="state-waiting",
            key="project.waiting",
            value="committed-after-cut",
            ref=ref,
        )

        receipt = self._assert_writer_waits_during_local_accept(
            lambda: self.admission.admit_room_state(
                record=record,
                source_bindings=(binding,),
                grant=self.grant,
            )
        )
        _envelope, payload = self._payload_for_receipt(
            receipt
        )
        values = [
            candidate["value"]
            for block in payload["presentation"]["layers"][2]["blocks"]
            for candidate in block["candidates"]
        ]
        self.assertNotIn("committed-after-cut", values)

        later = self.handoff.handoff(
            request_id="request-after-current",
            episode_id="episode-b",
            user_input="fresh after writer",
        )
        _later_env, later_payload = self._payload_for_receipt(
            later
        )
        later_values = [
            candidate["value"]
            for block in later_payload["presentation"]["layers"][2]["blocks"]
            for candidate in block["candidates"]
        ]
        self.assertIn(
            "committed-after-cut",
            later_values,
        )

    def test_writer_committed_first_is_visible_to_fresh_handoff(self) -> None:
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-b-before",
                episode_id="episode-b",
                route_kind=RoomRouteKind.UNATTACHED,
                room_id=None,
                basis="writer-first",
                supersedes_attachment_event_id="route-b",
            )
        )
        generation = self.coordinator.generation

        receipt = self.handoff.handoff(
            request_id="request-writer-first",
            episode_id="episode-b",
            user_input="see newest route",
        )
        self.assertEqual(receipt.generation, generation)
        _envelope, payload = self._payload_for_receipt(
            receipt
        )
        map_block = payload["presentation"]["layers"][0]["blocks"][0]
        self.assertEqual(
            map_block["route_decision"],
            "unattached",
        )
        self.assertEqual(
            payload["presentation"]["layers"][2]["availability"],
            WakeLayerAvailability.UNAVAILABLE.value,
        )
        self.assertEqual(
            payload["presentation"]["layers"][2]["blocks"],
            [],
        )

    def test_generation_increments_once_on_success_and_not_on_failed_write(self) -> None:
        start = self.coordinator.generation
        self.living.add_room(
            RoomRecord(room_id="room-generation")
        )
        self.assertEqual(
            self.coordinator.generation,
            start + 1,
        )

        with self.assertRaises(Exception):
            self.living.add_room(
                RoomRecord(room_id="room-generation")
            )
        self.assertEqual(
            self.coordinator.generation,
            start + 1,
        )

        source = create_source_record(
            source_id="source-generation",
            content="generation",
            authored_by="test",
            scope="room-r",
        )
        self.memory.add_source(source)
        self.assertEqual(
            self.coordinator.generation,
            start + 2,
        )

    def test_failed_fresh_issue_releases_cut_without_acceptance(self) -> None:
        before = self.coordinator.generation
        with self.assertRaises(KeyError):
            self.handoff.handoff(
                request_id="request-missing",
                episode_id="episode-missing",
                user_input="missing",
            )

        self.assertEqual(
            self.coordinator.generation,
            before,
        )
        permit = self.coordinator.acquire_writer()
        permit.release()

    def test_handoff_artifacts_grant_no_model_or_speech_authority(self) -> None:
        receipt = self.handoff.handoff(
            request_id="request-authority",
            episode_id="episode-c",
            user_input="data only",
        )
        envelope = self.boundary.require_live_acceptance(
            receipt=receipt
        )

        for boundary in (
            receipt.use_boundary,
            envelope.use_boundary,
            envelope.rendered.use_boundary,
        ):
            self.assertEqual(
                boundary.instruction_authority,
                WakeAuthority.NONE,
            )
            self.assertEqual(
                boundary.current_first_person_speech_authority,
                WakeAuthority.NONE,
            )
            self.assertEqual(
                boundary.identity_continuity_claim_authority,
                WakeAuthority.NONE,
            )
            self.assertEqual(
                boundary.relationship_claim_authority,
                WakeAuthority.NONE,
            )
            self.assertEqual(
                boundary.model_delivery_authority,
                WakeAuthority.NONE,
            )
            self.assertEqual(
                boundary.memory_write_authority,
                WakeAuthority.NONE,
            )

        self.assertFalse(hasattr(envelope, "system_prompt"))
        self.assertFalse(hasattr(envelope, "tools"))
        self.assertFalse(hasattr(envelope, "model_request"))
        self.assertFalse(hasattr(envelope, "transport_handoff"))
        self.assertFalse(hasattr(receipt, "model_response"))
        self.assertFalse(hasattr(receipt, "network_status"))


if __name__ == "__main__":
    unittest.main()
