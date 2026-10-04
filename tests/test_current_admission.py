import dataclasses
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import home_memory_core.current_admission as admission_module
from _trusted_test_support import (
    trusted_test_room_continuation_policy,
    trusted_test_runtime_launch_issuer,
)
from home_memory_core.current_admission import (
    CURRENT_END_ADMISSION_TABLE,
    CURRENT_STATE_ADMISSION_TABLE,
    CurrentAdmissionAuthorizationError,
    CurrentAdmissionConflictError,
    CurrentAdmissionEffectKind,
    CurrentAdmissionReceipt,
    CurrentAdmissionStore,
    open_current_admission_authority,
)
from home_memory_core.current_store import (
    CurrentSourceBinding,
    CurrentStore,
    CurrentStoreIntegrityError,
)
from home_memory_core.current_store_schema import (
    CURRENT_END_TABLE,
    CURRENT_STATE_TABLE,
)
from home_memory_core.current_view import (
    CurrentNamespace,
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
    RoomParticipationStaleError,
    open_room_participation_authority,
)
from home_memory_core.process_boundary import HomeProcessIsolationError
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


UTC = timezone.utc


class CurrentAdmissionTests(unittest.TestCase):
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
        self.t0 = datetime(2026, 1, 1, 9, tzinfo=UTC)

    def tearDown(self) -> None:
        if not self.lease.released:
            self.lease.release()
        self.tmp.cleanup()

    def binding(self, ref: str) -> CurrentSourceBinding:
        source = create_source_record(
            source_id=f"src-{ref}",
            content=f"evidence:{ref}",
            authored_by="synthetic-admission-test",
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

    def clone_database(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db) as source, sqlite3.connect(target) as clone:
            source.backup(clone)

    def table_count(self, path: Path, table: str) -> int:
        with sqlite3.connect(path) as connection:
            return int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])

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

    def grant(self, scopes=None):
        scopes = frozenset(
            scopes
            or {
                RoomParticipationScope.APPEND_FIRST_PERSON,
                RoomParticipationScope.CHANGE_CURRENT_STANCE,
            }
        )
        receipt = self.launcher.record_supported_runtime_launch(
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            observed_runtime_instance_id="runtime-b",
            observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
        )
        evidence = self.room_authority.begin_trusted_continuation(
            launch_receipt=receipt,
            previous_episode_id="episode-a",
            room_id="room-r",
        )
        proposal = self.room_authority.prepare_grant(
            launch_evidence=evidence,
            policy=self.policy,
            requested_scopes=scopes,
        )
        approval = self.room_authority.approve_automatic_continuation(
            proposal=proposal,
            policy=self.policy,
        )
        return self.room_authority.issue_grant(
            proposal=proposal,
            approval=approval,
        )

    def admit_state(self, state_id: str, *, grant=None, **changes):
        record = self.room_state(state_id, **changes)
        receipt = self.admission.admit_room_state(
            record=record,
            source_bindings=(self.binding(record.source_refs[0]),),
            grant=grant or self.grant(),
        )
        return record, receipt

    def test_open_rejects_mismatched_store_before_installing_admission_schema(self) -> None:
        other_db = self.root / "other" / "home.db"
        other_memory = MemoryStore(other_db)
        other_memory.initialize()
        LivingStore(other_db).initialize()
        CurrentStore(other_db).initialize()
        other_admission = CurrentAdmissionStore(other_db)

        with self.assertRaises(CurrentAdmissionAuthorizationError):
            open_current_admission_authority(
                current_store=self.current,
                admission_store=other_admission,
                room_authority=self.room_authority,
            )

        connection = sqlite3.connect(other_db)
        try:
            installed = connection.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type='table' AND name='current_admission_schema_marker'
                """
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNone(installed)

    def test_room_state_admission_binds_live_grant_and_exact_effect(self) -> None:
        record, receipt = self.admit_state("state-a")

        self.assertEqual(receipt.effect_kind, CurrentAdmissionEffectKind.STATE)
        self.assertEqual(receipt.effect_id, record.state_id)
        self.assertEqual(receipt.room_attachment_event_id, "route-b")
        self.assertEqual(
            receipt.required_scope,
            RoomParticipationScope.CHANGE_CURRENT_STANCE,
        )
        self.admission.require_live_receipt(
            receipt=receipt,
            effect_kind=CurrentAdmissionEffectKind.STATE,
            effect_id=record.state_id,
        )

        audits = self.admission_store.list_for_audit()
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].admission_id, receipt.admission_id)
        self.assertEqual(audits[0].effect_digest, receipt.effect_digest)
        self.assertEqual(
            audits[0].admission_binding_digest,
            receipt.admission_binding_digest,
        )

    def test_non_grant_object_is_rejected_before_current_write(self) -> None:
        record = self.room_state("not-a-grant")
        with self.assertRaises(CurrentAdmissionAuthorizationError):
            self.admission.admit_room_state(
                record=record,
                source_bindings=(self.binding(record.source_refs[0]),),
                grant=object(),
            )

        self.assertEqual(self.current.list_states_for_audit(), ())
        self.assertEqual(self.admission_store.list_for_audit(), ())

    def test_room_grant_without_change_current_scope_cannot_admit(self) -> None:
        grant = self.grant(
            scopes={RoomParticipationScope.APPEND_FIRST_PERSON}
        )
        record = self.room_state("no-current-scope")

        with self.assertRaises(PermissionError):
            self.admission.admit_room_state(
                record=record,
                source_bindings=(self.binding(record.source_refs[0]),),
                grant=grant,
            )

        self.assertEqual(self.current.list_states_for_audit(), ())
        self.assertEqual(self.admission_store.list_for_audit(), ())

    def test_shared_state_cannot_use_room_admission_path(self) -> None:
        grant = self.grant()
        record = CurrentStateRecord(
            state_id="shared-state",
            namespace=CurrentNamespace.SHARED,
            owner_id="shared-home",
            key="shared.status",
            state_kind=CurrentStateKind.SHARED_STATE,
            value="open",
            event_time=self.t0,
            recorded_at=self.t0,
            valid_from=self.t0,
            validity_rule=ValidityRule.DURABLE_UNTIL_CHANGED,
            downgrade_rule=DowngradeRule.NONE,
            semantic_change_authority=SemanticChangeAuthority.SHARED_GOVERNANCE,
            source_refs=("ref-shared",),
        )

        with self.assertRaises(CurrentAdmissionAuthorizationError):
            self.admission.admit_room_state(
                record=record,
                source_bindings=(self.binding("ref-shared"),),
                grant=grant,
            )

        self.assertEqual(self.current.list_states_for_audit(), ())
        self.assertEqual(self.admission_store.list_for_audit(), ())

    def test_existing_slice1_row_cannot_be_admitted_after_the_fact(self) -> None:
        record = self.room_state("historical-only")
        binding = self.binding(record.source_refs[0])
        self.current.add_state_record(
            record=record,
            source_bindings=(binding,),
        )
        grant = self.grant()

        with self.assertRaises(CurrentAdmissionConflictError):
            self.admission.admit_room_state(
                record=record,
                source_bindings=(binding,),
                grant=grant,
            )

        self.assertEqual(
            tuple(item.record.state_id for item in self.current.list_states_for_audit()),
            ("historical-only",),
        )
        self.assertEqual(self.admission_store.list_for_audit(), ())

    def test_supersession_requires_live_parent_admission_receipt(self) -> None:
        raw = self.room_state("raw-parent")
        self.current.add_state_record(
            record=raw,
            source_bindings=(self.binding(raw.source_refs[0]),),
        )
        child = self.room_state(
            "child",
            supersedes_state_id=raw.state_id,
        )

        with self.assertRaises(CurrentAdmissionAuthorizationError):
            self.admission.admit_room_state(
                record=child,
                source_bindings=(self.binding(child.source_refs[0]),),
                grant=self.grant(),
            )

        self.assertEqual(
            tuple(item.record.state_id for item in self.current.list_states_for_audit()),
            ("raw-parent",),
        )
        self.assertEqual(self.admission_store.list_for_audit(), ())

    def test_admitted_supersession_binds_parent_receipt(self) -> None:
        grant = self.grant()
        parent, parent_receipt = self.admit_state(
            "parent",
            grant=grant,
        )
        child = self.room_state(
            "child",
            supersedes_state_id=parent.state_id,
        )
        child_receipt = self.admission.admit_room_state(
            record=child,
            source_bindings=(self.binding(child.source_refs[0]),),
            grant=grant,
            supersedes_receipt=parent_receipt,
        )

        self.assertEqual(
            child_receipt.predecessor_admission_id,
            parent_receipt.admission_id,
        )
        audits = self.admission_store.list_for_audit()
        self.assertEqual(len(audits), 2)

    def test_end_event_requires_and_binds_admitted_target(self) -> None:
        grant = self.grant()
        state, state_receipt = self.admit_state("state-a", grant=grant)
        event = CurrentStateEndEvent(
            end_event_id="end-a",
            state_id=state.state_id,
            ended_at=self.t0 + timedelta(minutes=5),
            recorded_at=self.t0 + timedelta(minutes=5),
            end_kind=EndKind.EXPLICIT_END,
            reason="synthetic end",
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            source_refs=("ref-end-a",),
        )
        end_receipt = self.admission.admit_room_end_event(
            event=event,
            source_bindings=(self.binding("ref-end-a"),),
            grant=grant,
            target_state_receipt=state_receipt,
        )

        self.assertEqual(
            end_receipt.predecessor_admission_id,
            state_receipt.admission_id,
        )
        self.assertEqual(
            end_receipt.effect_kind,
            CurrentAdmissionEffectKind.END_EVENT,
        )
        self.admission.require_live_receipt(
            receipt=end_receipt,
            effect_kind=CurrentAdmissionEffectKind.END_EVENT,
            effect_id=event.end_event_id,
        )

    def test_copied_or_reconstructed_receipt_is_not_live_authority(self) -> None:
        record, receipt = self.admit_state("state-a")
        copied = dataclasses.replace(receipt)

        with self.assertRaises(CurrentAdmissionAuthorizationError):
            self.admission.require_live_receipt(
                receipt=copied,
                effect_kind=CurrentAdmissionEffectKind.STATE,
                effect_id=record.state_id,
            )

        forged = CurrentAdmissionReceipt(
            **{
                **dataclasses.asdict(receipt),
                "_marker": admission_module._ADMISSION_RECEIPT_MARKER,
            }
        )
        with self.assertRaises(CurrentAdmissionAuthorizationError):
            self.admission.require_live_receipt(
                receipt=forged,
                effect_kind=CurrentAdmissionEffectKind.STATE,
                effect_id=record.state_id,
            )

    def test_live_receipt_rejects_corrupted_source_provenance(self) -> None:
        record = self.room_state("state-a")
        binding = self.binding(record.source_refs[0])
        receipt = self.admission.admit_room_state(
            record=record,
            source_bindings=(binding,),
            grant=self.grant(),
        )

        connection = sqlite3.connect(self.db)
        try:
            connection.execute(
                "UPDATE sources SET content=? WHERE source_id=?",
                ("tampered evidence", binding.evidence.source_id),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(CurrentStoreIntegrityError):
            self.admission.require_live_receipt(
                receipt=receipt,
                effect_kind=CurrentAdmissionEffectKind.STATE,
                effect_id=record.state_id,
            )

    def test_public_store_path_drift_cannot_redirect_admitted_effect(self) -> None:
        grant = self.grant()
        record = self.room_state("absolute-db-drift")
        binding = self.binding(record.source_refs[0])
        other_db = self.root / "other" / "home.db"
        self.clone_database(other_db)

        original_current_path = self.current.db_path
        original_admission_path = self.admission_store.db_path
        try:
            self.current.db_path = other_db
            self.admission_store.db_path = other_db
            with self.assertRaises(CurrentAdmissionAuthorizationError):
                self.admission.admit_room_state(
                    record=record,
                    source_bindings=(binding,),
                    grant=grant,
                )
        finally:
            self.current.db_path = original_current_path
            self.admission_store.db_path = original_admission_path

        self.assertEqual(self.table_count(self.db, CURRENT_STATE_TABLE), 0)
        self.assertEqual(self.table_count(self.db, CURRENT_STATE_ADMISSION_TABLE), 0)
        self.assertEqual(self.table_count(other_db, CURRENT_STATE_TABLE), 0)
        self.assertEqual(self.table_count(other_db, CURRENT_STATE_ADMISSION_TABLE), 0)

    def test_relative_store_path_cwd_drift_cannot_redirect_admitted_effect(self) -> None:
        grant = self.grant()
        record = self.room_state("relative-db-drift")
        binding = self.binding(record.source_refs[0])
        other_db = self.root / "relative-other" / "home.db"
        self.clone_database(other_db)

        original_cwd = Path.cwd()
        original_current_path = self.current.db_path
        original_admission_path = self.admission_store.db_path
        try:
            os.chdir(self.db.parent)
            self.current.db_path = Path("home.db")
            self.admission_store.db_path = Path("home.db")
            # The relative configuration still resolves to the leased DB here.
            os.chdir(other_db.parent)
            with self.assertRaises(CurrentAdmissionAuthorizationError):
                self.admission.admit_room_state(
                    record=record,
                    source_bindings=(binding,),
                    grant=grant,
                )
        finally:
            os.chdir(original_cwd)
            self.current.db_path = original_current_path
            self.admission_store.db_path = original_admission_path

        self.assertEqual(self.table_count(self.db, CURRENT_STATE_TABLE), 0)
        self.assertEqual(self.table_count(self.db, CURRENT_STATE_ADMISSION_TABLE), 0)
        self.assertEqual(self.table_count(other_db, CURRENT_STATE_TABLE), 0)
        self.assertEqual(self.table_count(other_db, CURRENT_STATE_ADMISSION_TABLE), 0)

    def test_database_binding_drift_blocks_supersession_and_end_event(self) -> None:
        grant = self.grant()
        parent, parent_receipt = self.admit_state("binding-parent", grant=grant)
        child = self.room_state(
            "binding-child",
            supersedes_state_id=parent.state_id,
        )
        child_binding = self.binding(child.source_refs[0])
        event = CurrentStateEndEvent(
            end_event_id="binding-end",
            state_id=parent.state_id,
            ended_at=self.t0 + timedelta(minutes=5),
            recorded_at=self.t0 + timedelta(minutes=5),
            end_kind=EndKind.EXPLICIT_END,
            reason="synthetic binding drift",
            semantic_change_authority=SemanticChangeAuthority.ROOM_FIRST_PERSON,
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
            source_refs=("ref-binding-end",),
        )
        end_binding = self.binding(event.source_refs[0])
        other_db = self.root / "lineage-other" / "home.db"
        self.clone_database(other_db)

        original_current_path = self.current.db_path
        original_admission_path = self.admission_store.db_path
        try:
            self.current.db_path = other_db
            self.admission_store.db_path = other_db
            with self.assertRaises(CurrentAdmissionAuthorizationError):
                self.admission.admit_room_state(
                    record=child,
                    source_bindings=(child_binding,),
                    grant=grant,
                    supersedes_receipt=parent_receipt,
                )
            with self.assertRaises(CurrentAdmissionAuthorizationError):
                self.admission.admit_room_end_event(
                    event=event,
                    source_bindings=(end_binding,),
                    grant=grant,
                    target_state_receipt=parent_receipt,
                )
        finally:
            self.current.db_path = original_current_path
            self.admission_store.db_path = original_admission_path

        self.assertEqual(self.table_count(self.db, CURRENT_STATE_TABLE), 1)
        self.assertEqual(self.table_count(self.db, CURRENT_END_TABLE), 0)
        self.assertEqual(self.table_count(self.db, CURRENT_STATE_ADMISSION_TABLE), 1)
        self.assertEqual(self.table_count(self.db, CURRENT_END_ADMISSION_TABLE), 0)
        self.assertEqual(self.table_count(other_db, CURRENT_STATE_TABLE), 1)
        self.assertEqual(self.table_count(other_db, CURRENT_END_TABLE), 0)
        self.assertEqual(self.table_count(other_db, CURRENT_STATE_ADMISSION_TABLE), 1)
        self.assertEqual(self.table_count(other_db, CURRENT_END_ADMISSION_TABLE), 0)

    @unittest.skipUnless(hasattr(os, "fork"), "requires POSIX fork semantics")
    def test_fork_child_cannot_reuse_live_current_admission_receipt(self) -> None:
        record, receipt = self.admit_state("fork-isolation")

        self.admission.require_live_receipt(
            receipt=receipt,
            effect_kind=CurrentAdmissionEffectKind.STATE,
            effect_id=record.state_id,
        )

        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(read_fd)
            try:
                try:
                    self.admission.require_live_receipt(
                        receipt=receipt,
                        effect_kind=CurrentAdmissionEffectKind.STATE,
                        effect_id=record.state_id,
                    )
                except Exception as error:
                    result = type(error).__name__
                else:
                    result = "ACCEPTED"
                os.write(write_fd, result.encode("utf-8"))
            finally:
                os.close(write_fd)
                os._exit(0)

        os.close(write_fd)
        try:
            with os.fdopen(read_fd, "rb", closefd=True) as stream:
                child_result = stream.read().decode("utf-8")
            _, status = os.waitpid(pid, 0)
        finally:
            try:
                os.close(read_fd)
            except OSError:
                pass

        self.assertEqual(status, 0)
        self.assertEqual(child_result, HomeProcessIsolationError.__name__)
        self.admission.require_live_receipt(
            receipt=receipt,
            effect_kind=CurrentAdmissionEffectKind.STATE,
            effect_id=record.state_id,
        )

    def test_durable_audit_does_not_recreate_live_receipt(self) -> None:
        record, receipt = self.admit_state("state-a")
        restarted_authority = admission_module.CurrentAdmissionAuthority(
            current_store=self.current,
            admission_store=self.admission_store,
            room_authority=self.room_authority,
            _marker=admission_module._ADMISSION_AUTHORITY_MARKER,
        )

        self.assertEqual(len(self.admission_store.list_for_audit()), 1)
        with self.assertRaises(CurrentAdmissionAuthorizationError):
            restarted_authority.require_live_receipt(
                receipt=receipt,
                effect_kind=CurrentAdmissionEffectKind.STATE,
                effect_id=record.state_id,
            )

    def test_admission_audit_rejects_upstream_living_schema_drift(self) -> None:
        self.admit_state("state-a")
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("DROP TRIGGER living_rooms_no_delete")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(Exception):
            self.admission_store.list_for_audit()

    def test_suspended_grant_rolls_back_current_effect(self) -> None:
        grant = self.grant()
        self.room_authority.suspend_policy(policy_id=self.policy.policy_id)
        record = self.room_state("suspended")

        with self.assertRaises(RoomParticipationStaleError):
            self.admission.admit_room_state(
                record=record,
                source_bindings=(self.binding(record.source_refs[0]),),
                grant=grant,
            )

        self.assertEqual(self.current.list_states_for_audit(), ())
        self.assertEqual(self.admission_store.list_for_audit(), ())

    def test_route_change_before_admission_invalidates_grant_and_writes_nothing(self) -> None:
        grant = self.grant()
        self.living.add_room_attachment(
            RoomAttachmentEvent(
                attachment_event_id="route-b-detached",
                episode_id="episode-b",
                route_kind=RoomRouteKind.UNATTACHED,
                room_id=None,
                basis="synthetic route correction",
                supersedes_attachment_event_id="route-b",
            )
        )
        record = self.room_state("route-stale")

        with self.assertRaises(RoomParticipationStaleError):
            self.admission.admit_room_state(
                record=record,
                source_bindings=(self.binding(record.source_refs[0]),),
                grant=grant,
            )

        self.assertEqual(self.current.list_states_for_audit(), ())
        self.assertEqual(self.admission_store.list_for_audit(), ())

    def test_admission_failure_after_current_insert_rolls_back_effect(self) -> None:
        grant = self.grant()
        first = self.room_state(
            "first",
            key="project.home.first",
        )
        second = self.room_state(
            "second",
            key="project.home.second",
        )

        with patch(
            "home_memory_core.current_admission.secrets.token_hex",
            return_value="fixed-admission",
        ):
            self.admission.admit_room_state(
                record=first,
                source_bindings=(self.binding(first.source_refs[0]),),
                grant=grant,
            )

        with patch(
            "home_memory_core.current_admission.secrets.token_hex",
            return_value="fixed-admission",
        ):
            with self.assertRaises(CurrentAdmissionConflictError):
                self.admission.admit_room_state(
                    record=second,
                    source_bindings=(self.binding(second.source_refs[0]),),
                    grant=grant,
                )

        self.assertEqual(
            tuple(item.record.state_id for item in self.current.list_states_for_audit()),
            ("first",),
        )
        self.assertEqual(len(self.admission_store.list_for_audit()), 1)

    def test_grant_operation_holds_host_lease_until_effect_boundary_exits(self) -> None:
        grant = self.grant()
        release_started = Event()
        release_finished = Event()

        def release_lease() -> None:
            release_started.set()
            self.lease.release()
            release_finished.set()

        thread = Thread(target=release_lease)
        with self.room_authority._hold_grant_for_operation(
            grant=grant,
            session_id=grant.session_id,
            episode_id=grant.episode_id,
            perspective_instance_id=grant.perspective_instance_id,
            room_id=grant.room_id,
            required_scope=RoomParticipationScope.CHANGE_CURRENT_STANCE,
        ):
            thread.start()
            self.assertTrue(release_started.wait(1.0))
            thread.join(timeout=0.1)
            self.assertTrue(
                thread.is_alive(),
                "lease.release() must block while the authorized effect holds the host lease",
            )
            self.assertFalse(self.lease.released)

        thread.join(timeout=1.0)
        self.assertFalse(thread.is_alive())
        self.assertTrue(release_finished.is_set())
        self.assertTrue(self.lease.released)

    def test_admission_rows_are_append_only_and_schema_audited(self) -> None:
        record, _ = self.admit_state("state-a")

        connection = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    f"UPDATE {CURRENT_STATE_ADMISSION_TABLE} SET room_id='other' WHERE state_id=?",
                    (record.state_id,),
                )
            connection.rollback()
            connection.execute(
                f"""
                CREATE UNIQUE INDEX current_admission_hidden_singleton
                ON {CURRENT_STATE_ADMISSION_TABLE}(room_id)
                """
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(Exception):
            self.admission_store.list_for_audit()


if __name__ == "__main__":
    unittest.main()
