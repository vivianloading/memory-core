import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _suppression_test_support import (
    create_test_suppression_record as create_suppression_record,
)
from _trusted_test_support import (
    trusted_test_room_continuation_policy,
    trusted_test_runtime_launch_issuer,
)
import home_memory_core.current_admission as admission_module
from home_memory_core.current_admission import (
    CurrentAdmissionIntegrityError,
    CurrentAdmissionStore,
    open_current_admission_authority,
)
from home_memory_core.current_resolver import (
    CurrentResolverClosedBoundaryError,
    CurrentResolverStatus,
    open_current_resolver,
)
from home_memory_core.current_store import (
    CurrentSourceBinding,
    CurrentStore,
    CurrentStoreIntegrityError,
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
from home_memory_core.suppression import SuppressionLedgerIntegrityError


UTC = timezone.utc


class CurrentResolverTests(unittest.TestCase):
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
        self.living.add_continuity_edge(
            ContinuityEdge(
                edge_id="edge-a-b",
                previous_episode_id="episode-a",
                next_episode_id="episode-b",
                transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
                continuity_status=ContinuityStatus.UNKNOWN,
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
            policy_id="policy-room-r-v1",
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
        self.t0 = datetime(2026, 1, 1, 9, tzinfo=UTC)
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

    def binding(self, ref: str) -> CurrentSourceBinding:
        source = create_source_record(
            source_id=f"src-{ref}",
            content=f"evidence:{ref}",
            authored_by="synthetic-current-resolver-test",
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
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            source_refs=(f"ref-{state_id}",),
        )
        values.update(changes)
        return CurrentStateRecord(**values)

    def admit_state(
        self,
        state_id: str,
        *,
        predecessor_receipt=None,
        **changes,
    ):
        record = self.room_state(state_id, **changes)
        binding = self.binding(record.source_refs[0])
        receipt = self.admission.admit_room_state(
            record=record,
            source_bindings=(binding,),
            grant=self.grant,
            supersedes_receipt=predecessor_receipt,
        )
        return record, binding, receipt

    def raw_state(self, state_id: str, **changes):
        record = self.room_state(state_id, **changes)
        binding = self.binding(record.source_refs[0])
        self.current.add_state_record(
            record=record,
            source_bindings=(binding,),
        )
        return record, binding

    def admit_end(self, end_id: str, state_id: str, target_receipt):
        ref = f"ref-{end_id}"
        event = CurrentStateEndEvent(
            end_event_id=end_id,
            state_id=state_id,
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.EXPLICIT_END,
            reason=end_id,
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            source_refs=(ref,),
        )
        binding = self.binding(ref)
        receipt = self.admission.admit_room_end_event(
            event=event,
            source_bindings=(binding,),
            grant=self.grant,
            target_state_receipt=target_receipt,
        )
        return event, binding, receipt

    def suppress(self, binding: CurrentSourceBinding, suppression_id: str) -> None:
        self.memory.suppress_source(
            create_suppression_record(
                suppression_id=suppression_id,
                source_id=binding.evidence.source_id,
                requested_by="synthetic-test",
                reason="stop present use",
            )
        )

    def resolve(self, *, key: str = "project.home.status", as_of=None):
        return self.resolver.resolve_key(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key=key,
            as_of=as_of or self.t0,
        )

    def test_admitted_usable_head_resolves(self) -> None:
        record, _, _ = self.admit_state("state-a")

        decision = self.resolve()

        self.assertEqual(decision.status, CurrentResolverStatus.RESOLVED)
        self.assertEqual(decision.usable_standing, CurrentStanding.CURRENT)
        self.assertEqual(
            decision.usable_current_state_ids,
            (record.state_id,),
        )
        self.assertEqual(decision.blocks, ())

    def test_raw_unadmitted_row_is_audit_only_not_present_current(self) -> None:
        raw, _ = self.raw_state("raw-only")

        decision = self.resolve()

        self.assertEqual(decision.status, CurrentResolverStatus.RESOLVED)
        self.assertEqual(decision.usable_standing, CurrentStanding.UNKNOWN)
        self.assertEqual(decision.usable_current_state_ids, ())
        self.assertEqual(decision.semantic_resolution.current_state_ids, ())
        self.assertEqual(
            self.current.get_state_for_audit(raw.state_id).record,
            raw,
        )

    def test_raw_unadmitted_child_cannot_supersede_admitted_parent(self) -> None:
        parent, _, _ = self.admit_state("parent")
        raw_child, _ = self.raw_state(
            "raw-child",
            supersedes_state_id=parent.state_id,
        )

        decision = self.resolve()

        self.assertEqual(decision.status, CurrentResolverStatus.RESOLVED)
        self.assertEqual(
            decision.usable_current_state_ids,
            (parent.state_id,),
        )
        self.assertNotIn(
            raw_child.state_id,
            decision.semantic_resolution.current_state_ids,
        )

    def test_raw_unadmitted_competing_head_cannot_manufacture_conflict(self) -> None:
        admitted, _, _ = self.admit_state("admitted")
        raw, _ = self.raw_state("raw-competitor")

        decision = self.resolve()

        self.assertEqual(decision.usable_standing, CurrentStanding.CURRENT)
        self.assertEqual(
            decision.usable_current_state_ids,
            (admitted.state_id,),
        )
        self.assertNotEqual(
            decision.semantic_resolution.standing,
            CurrentStanding.CONFLICTING,
        )
        self.assertEqual(
            self.current.get_state_for_audit(raw.state_id).record,
            raw,
        )

    def test_suppressed_admitted_successor_blocks_without_parent_fallback(self) -> None:
        parent, _, parent_receipt = self.admit_state("parent")
        child, child_binding, _ = self.admit_state(
            "child",
            predecessor_receipt=parent_receipt,
            supersedes_state_id=parent.state_id,
        )
        self.suppress(child_binding, "stop-child")

        decision = self.resolve()

        self.assertEqual(
            decision.semantic_resolution.current_state_ids,
            (child.state_id,),
        )
        self.assertEqual(
            decision.status,
            CurrentResolverStatus.BLOCKED_UNKNOWN,
        )
        self.assertIsNone(decision.usable_standing)
        self.assertEqual(decision.usable_current_state_ids, ())
        self.assertEqual(
            tuple(block.suppression_id for block in decision.blocks),
            ("stop-child",),
        )

    def test_admitted_ancestor_stop_blocks_descendant_without_rewind(self) -> None:
        root, root_binding, root_receipt = self.admit_state("root")
        child, _, child_receipt = self.admit_state(
            "child",
            predecessor_receipt=root_receipt,
            supersedes_state_id=root.state_id,
        )
        grandchild, _, _ = self.admit_state(
            "grandchild",
            predecessor_receipt=child_receipt,
            supersedes_state_id=child.state_id,
        )
        self.suppress(root_binding, "stop-root")

        decision = self.resolve()

        self.assertEqual(
            decision.semantic_resolution.current_state_ids,
            (grandchild.state_id,),
        )
        self.assertEqual(
            decision.status,
            CurrentResolverStatus.BLOCKED_UNKNOWN,
        )
        self.assertEqual(
            tuple(
                (block.suppression_id, block.origin_effect_id)
                for block in decision.blocks
            ),
            (("stop-root", root.state_id),),
        )

    def test_suppressed_admitted_end_does_not_revive_target(self) -> None:
        state, _, state_receipt = self.admit_state("ended-state")
        _, end_binding, _ = self.admit_end(
            "end-a",
            state.state_id,
            state_receipt,
        )
        self.suppress(end_binding, "stop-end-a")

        decision = self.resolve()

        self.assertEqual(
            decision.semantic_resolution.standing,
            CurrentStanding.ENDED,
        )
        self.assertEqual(
            decision.status,
            CurrentResolverStatus.BLOCKED_UNKNOWN,
        )
        self.assertIsNone(decision.usable_standing)

    def test_suppressed_admitted_conflict_participant_does_not_choose_winner(self) -> None:
        first, _, _ = self.admit_state("head-a")
        second, second_binding, _ = self.admit_state("head-b")
        self.suppress(second_binding, "stop-head-b")

        decision = self.resolve()

        self.assertEqual(
            decision.semantic_resolution.standing,
            CurrentStanding.CONFLICTING,
        )
        self.assertEqual(
            set(decision.semantic_resolution.current_state_ids),
            {first.state_id, second.state_id},
        )
        self.assertEqual(
            decision.status,
            CurrentResolverStatus.BLOCKED_UNKNOWN,
        )
        self.assertIsNone(decision.usable_standing)

    def test_suppressed_member_of_admitted_end_conflict_does_not_simplify(self) -> None:
        state, _, state_receipt = self.admit_state("ended")
        first, _, _ = self.admit_end("end-a", state.state_id, state_receipt)
        second, second_binding, _ = self.admit_end(
            "end-b",
            state.state_id,
            state_receipt,
        )
        self.suppress(second_binding, "stop-end-b")

        decision = self.resolve()

        self.assertEqual(
            decision.semantic_resolution.standing,
            CurrentStanding.CONFLICTING,
        )
        self.assertEqual(
            tuple(
                event.end_event_id
                for event in decision.semantic_resolution.candidates[0].end_events
            ),
            (first.end_event_id, second.end_event_id),
        )
        self.assertEqual(
            decision.status,
            CurrentResolverStatus.BLOCKED_UNKNOWN,
        )

    def test_suppressed_other_key_does_not_poison_resolution(self) -> None:
        target, _, _ = self.admit_state(
            "target",
            key="project.target",
        )
        _, other_binding, _ = self.admit_state(
            "other",
            key="project.other",
        )
        self.suppress(other_binding, "stop-other")

        decision = self.resolve(key="project.target")

        self.assertEqual(decision.status, CurrentResolverStatus.RESOLVED)
        self.assertEqual(decision.usable_standing, CurrentStanding.CURRENT)
        self.assertEqual(
            decision.usable_current_state_ids,
            (target.state_id,),
        )

    def test_future_suppressed_admitted_successor_does_not_change_earlier_cut(self) -> None:
        parent, _, parent_receipt = self.admit_state("earlier")
        future, future_binding, _ = self.admit_state(
            "future-child",
            predecessor_receipt=parent_receipt,
            supersedes_state_id=parent.state_id,
            valid_from=self.t0 + timedelta(days=2),
        )
        self.suppress(future_binding, "stop-future")

        decision = self.resolve(as_of=self.t0)

        self.assertEqual(decision.status, CurrentResolverStatus.RESOLVED)
        self.assertEqual(
            decision.usable_current_state_ids,
            (parent.state_id,),
        )
        self.assertIn(
            future.state_id,
            decision.semantic_resolution.future_state_ids,
        )

    def forge_state_admission_audit(
        self,
        state_id: str,
        *,
        admission_id: str = "forged-admission",
    ) -> None:
        """Manufacture only a self-consistent durable audit row.

        This deliberately bypasses CurrentAdmissionAuthority and creates no
        CurrentAdmissionReceipt. It preserves schema/triggers so the regression
        matches independent review #50.
        """

        connection = sqlite3.connect(self.db)
        connection.row_factory = sqlite3.Row
        try:
            effect_digest = admission_module._state_effect_digest(
                connection,
                state_id,
            )
            values = admission_module._grant_provenance(
                grant=self.grant,
                room_attachment_event_id="route-b",
            )
            binding_digest = admission_module._admission_binding_digest(
                admission_id=admission_id,
                effect_kind=admission_module.CurrentAdmissionEffectKind.STATE,
                effect_id=state_id,
                effect_digest=effect_digest,
                predecessor_admission_id=None,
                **values,
            )
            connection.execute(
                f"""INSERT INTO {
                    admission_module.CURRENT_STATE_ADMISSION_TABLE
                } (
                    state_id,admission_id,effect_digest,
                    admission_binding_digest,grant_id,grant_binding_digest,
                    policy_fingerprint,launch_evidence_id,policy_id,
                    policy_issuance_id,proposal_id,approval_id,session_id,
                    episode_id,perspective_instance_id,room_id,
                    room_attachment_event_id,required_scope,
                    predecessor_admission_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    state_id,
                    admission_id,
                    effect_digest,
                    binding_digest,
                    values["grant_id"],
                    values["grant_binding_digest"],
                    values["policy_fingerprint"],
                    values["launch_evidence_id"],
                    values["policy_id"],
                    values["policy_issuance_id"],
                    values["proposal_id"],
                    values["approval_id"],
                    values["session_id"],
                    values["episode_id"],
                    values["perspective_instance_id"],
                    values["room_id"],
                    values["room_attachment_event_id"],
                    values["required_scope"].value,
                    None,
                ),
            )
            connection.commit()
            admission_module.assert_current_admission_data_integrity(
                connection
            )
        finally:
            connection.close()

    def test_manufactured_durable_admission_never_becomes_operational_current(self) -> None:
        raw, _ = self.raw_state("forged-audit-only")
        self.forge_state_admission_audit(raw.state_id)

        decision = self.resolve()

        self.assertEqual(
            decision.status,
            CurrentResolverStatus.ADMISSION_PROOF_UNAVAILABLE,
        )
        self.assertIsNone(decision.semantic_resolution)
        self.assertIsNone(decision.usable_standing)
        self.assertEqual(decision.usable_current_state_ids, ())
        self.assertEqual(
            tuple(
                (item.effect_kind.value, item.effect_id)
                for item in decision.missing_live_admission_effects
            ),
            (("state", raw.state_id),),
        )

    def test_lost_process_local_receipt_is_explicitly_unavailable_not_unknown(self) -> None:
        record, _, _ = self.admit_state("restart-boundary")
        with self.admission._receipt_guard:
            self.admission._receipts.clear()

        decision = self.resolve()

        self.assertEqual(
            decision.status,
            CurrentResolverStatus.ADMISSION_PROOF_UNAVAILABLE,
        )
        self.assertIsNone(decision.semantic_resolution)
        self.assertEqual(
            tuple(
                item.effect_id
                for item in decision.missing_live_admission_effects
            ),
            (record.state_id,),
        )

    def test_shared_resolution_is_closed_until_shared_admission_exists(self) -> None:
        with self.assertRaises(CurrentResolverClosedBoundaryError):
            self.resolver.resolve_key(
                namespace=CurrentNamespace.SHARED,
                owner_id="shared-home",
                key="shared.status",
                as_of=self.t0,
            )

    def test_damaged_suppression_ledger_fails_closed(self) -> None:
        self.admit_state("state-a")
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("DROP TRIGGER source_suppressions_no_delete")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(SuppressionLedgerIntegrityError):
            self.resolve()

    def test_damaged_admission_schema_fails_closed(self) -> None:
        self.admit_state("state-a")
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("DROP TRIGGER current_state_admission_no_update")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(CurrentAdmissionIntegrityError):
            self.resolve()

    def test_damaged_current_schema_fails_closed(self) -> None:
        self.admit_state("state-a")
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("DROP TRIGGER current_state_no_update")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(CurrentStoreIntegrityError):
            self.resolve()


if __name__ == "__main__":
    unittest.main()