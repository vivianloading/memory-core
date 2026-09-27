"""#08a.1b uses synthetic fixtures only. No real content or external services."""
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch

import _trusted_test_support as exercise
from test_production_authority import fixture_scope
from home_memory_core import production_schema as schema
from home_memory_core.identity_namespaces import RequestId
from home_memory_core.ingress_identity import IngressIdentityMetadata
from home_memory_core.operation_identity import OperationClass, create_operation_context
from home_memory_core.process_boundary import HomeProcessIsolationError
from home_memory_core.production_authority import (
    ProductionAuthorityError, ProductionAuthorityRoot, ProductionLifecycle,
    start_production_authority_contract,
)
from home_memory_core.production_memory import ProductionMemorySession, start_synthetic_production_memory
from home_memory_core.real_ingress import ClosedRealIngressWriter
from home_memory_core.real_normal_read import ClosedRealNormalReader
from home_memory_core.real_stop_use import ClosedRealStopUseWriter, StopUseReasonCode
from home_memory_core.source_origin import SnapshotKind
from home_memory_core.storage import MemoryStore
from home_memory_core.store_domain import StoreDomainError, create_empty_real_store, destroy_real_store


FIXTURE_ALPHA = "synthetic fixture: alpha"
FIXTURE_BETA = "synthetic fixture: beta"


@contextmanager
def traced_connections(statements):
    original = sqlite3.connect
    def connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection
    with patch.object(sqlite3, "connect", connect):
        yield


def assert_no_payload_access(test, statements):
    for sql in statements:
        normalized = " ".join(sql.lower().split())
        test.assertFalse(normalized.startswith(("select content ", "select content,",
                                               "insert into production_sources",
                                               "update production_sources")), normalized)


class ProductionMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / "fixture-production.sqlite3"
        self.scope = fixture_scope()
        self.root = self.start()
        self.owner = self.root.issue_owner()
        self.write_context = self.context(OperationClass.SOURCE_WRITE)
        self.read_context = self.context(OperationClass.NORMAL_READ)
        self.stop_context = self.context(OperationClass.SOURCE_SUPPRESS)
        self.provenance = self.root.capture_manual_event()

    def start(self):
        root = start_synthetic_production_memory(runtime_root=self.directory, db_path=self.path, scope=self.scope)
        self.addCleanup(root.close)
        return root

    def context(self, operation_class, root=None):
        root = root or self.root
        owner = self.owner if root is self.root else root.issue_owner()
        return root.issue_operation(principal=owner, operation_class=operation_class,
                                    request_id=RequestId("fixture-request"))

    def write(self, **overrides):
        args = dict(context=self.write_context, provenance=self.provenance, content=FIXTURE_ALPHA)
        args.update(overrides)
        return self.root.write_source(**args)

    def read(self, source_id, **overrides):
        return self.root.read_source(context=overrides.get("context", self.read_context), source_id=source_id)

    def stop(self, source_id, **overrides):
        return self.root.stop_use_source(context=overrides.get("context", self.stop_context), source_id=source_id)

    def execute_fixture_sql(self, *statements):
        connection = sqlite3.connect(self.path)
        try:
            with connection:
                for sql in statements:
                    connection.execute(sql)
        finally:
            connection.close()

    def test_current_session_manual_event_write_read_and_stop_use(self):
        receipt = self.write()
        result = self.read(receipt.source_id)
        self.assertEqual(result.content, FIXTURE_ALPHA)
        self.assertEqual(result.content_sha256, sha256(FIXTURE_ALPHA.encode()).hexdigest())
        self.assertEqual(result.scope, self.scope)
        self.assertEqual(result.origin_id, self.provenance.origin_id)
        self.assertEqual(result.snapshot_id, self.provenance.snapshot_id)
        self.assertFalse(receipt.exact_replay)
        self.assertTrue(self.stop(receipt.source_id).stopped)
        with self.assertRaises(ProductionAuthorityError):
            self.read(receipt.source_id)
        self.assertTrue(self.stop(receipt.source_id).stopped)  # Idempotent stop.

    def test_failed_first_commit_rolls_back_origin_stop_use_source_and_capture(self):
        before = self.path.read_bytes()
        original = schema.assert_ready
        def reject_first_payload_commit(connection, scope, incarnation):
            original(connection, scope, incarnation)
            if connection.execute("SELECT COUNT(*) FROM production_sources").fetchone() != (0,):
                raise ProductionAuthorityError("synthetic fixture: precommit failure")
        with patch.object(schema, "assert_ready", reject_first_payload_commit):
            with self.assertRaises(ProductionAuthorityError):
                self.write()
        self.assertEqual(before, self.path.read_bytes())
        connection = sqlite3.connect(self.path)
        try:
            for table in ("production_origins", "production_stop_use", "production_sources", "production_captures"):
                self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone(), (0,))
        finally:
            connection.close()
        self.assertEqual(self.read(self.write().source_id).content, FIXTURE_ALPHA)

    def test_protected_read_is_query_only_and_does_not_mutate_store(self):
        receipt = self.write()
        before, statements = self.path.read_bytes(), []
        with traced_connections(statements):
            self.assertEqual(self.read(receipt.source_id).content, FIXTURE_ALPHA)
        self.assertEqual(before, self.path.read_bytes())
        self.assertIn("PRAGMA query_only = ON", statements)
        self.assertFalse(any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements))

    def test_production_startup_contends_on_live_lease_and_restarts_after_close(self):
        from home_memory_core.host_runtime import HostRuntimeLeaseError
        with self.assertRaises(HostRuntimeLeaseError):
            self.start()
        self.assertEqual(self.root.state, ProductionLifecycle.ACTIVE)
        self.write()
        self.root.close()
        second = self.start()
        self.assertEqual(second.state, ProductionLifecycle.ACTIVE)
        self.assertNotEqual(second.session_id, self.root.session_id)

    def test_manual_event_identity_is_not_caller_metadata_or_content_hash(self):
        receipt = self.write()
        other_provenance = self.root.capture_manual_event()
        other = self.write(provenance=other_provenance)
        self.assertNotEqual(receipt.source_id, other.source_id)
        self.assertNotEqual(self.provenance.external_object_key, other_provenance.external_object_key)
        self.assertNotEqual(receipt.origin_id, other.origin_id)
        self.assertEqual(self.read(receipt.source_id).content_sha256, self.read(other.source_id).content_sha256)
        self.assertEqual(self.provenance.ingress_adapter_id, "manual_event_v0.1")
        self.assertEqual(self.provenance.adapter_version, "0.1")
        self.assertEqual(self.provenance.origin_namespace_id, self.scope.origin_namespace_id)
        self.assertEqual(self.provenance.session_id, self.root.session_id)
        with self.assertRaises(TypeError):
            self.root.capture_manual_event(external_object_key="fixture-caller-key")
        with self.assertRaises(ProductionAuthorityError):
            self.root.register_adapter(adapter_id="manual_event_v0.1", origin_namespace_id=self.scope.origin_namespace_id)
        with self.assertRaises(ProductionAuthorityError):
            self.root.issue_provenance(adapter=None, external_object_key="fixture-caller-key")
        self.assertEqual(len(self.root._adapters), 1)

    def test_recapture_preserves_origin_snapshot_and_adds_capture_identity(self):
        receipt = self.write()
        recaptured = self.root.capture_manual_event(source_id=receipt.source_id)
        replay = self.write(provenance=recaptured)
        self.assertEqual(replay.source_id, receipt.source_id)
        self.assertTrue(replay.exact_replay)
        self.assertEqual(recaptured.external_object_key, self.provenance.external_object_key)
        self.assertEqual(recaptured.snapshot_id, self.provenance.snapshot_id)
        self.assertNotEqual(recaptured.capture_event_id, self.provenance.capture_event_id)
        self.assertTrue(self.write().exact_replay)
        with self.assertRaises(ProductionAuthorityError):
            self.write(content=FIXTURE_BETA)
        self.assertEqual(self.read(receipt.source_id).content, FIXTURE_ALPHA)

    def test_new_snapshot_is_immutable_contiguous_and_not_supersession(self):
        first = self.write()
        later = self.root.capture_manual_event(source_id=first.source_id, new_snapshot=True)
        competing = self.root.capture_manual_event(source_id=first.source_id, new_snapshot=True)
        second = self.write(provenance=later, content=FIXTURE_BETA)
        self.assertEqual(later.snapshot_version, 2)
        self.assertEqual(later.origin_id, first.origin_id)
        self.assertNotEqual(first.snapshot_id, second.snapshot_id)
        with self.assertRaises(ProductionAuthorityError):
            self.write(provenance=competing, content=FIXTURE_BETA)
        self.assertEqual(self.read(first.source_id).content, FIXTURE_ALPHA)
        self.assertEqual(self.read(second.source_id).content, FIXTURE_BETA)

    def test_legacy_context_matching_owner_request_and_destination_fails_all_fronts(self):
        receipt = self.write()
        principal = exercise.trusted_test_principal_issuer(trust_source=self.owner.trust_source).issue(
            principal_id=self.scope.owner_principal_id, principal_kind=self.owner.principal_kind,
        )
        operations = (
            (OperationClass.SOURCE_WRITE, lambda c: self.write(context=c)),
            (OperationClass.NORMAL_READ, lambda c: self.read(receipt.source_id, context=c)),
            (OperationClass.SOURCE_SUPPRESS, lambda c: self.stop(receipt.source_id, context=c)),
        )
        statements = []
        with traced_connections(statements):
            for operation_class, action in operations:
                legacy = create_operation_context(principal=principal, operation_class=operation_class,
                                                  request_id=self.write_context.request_id,
                                                  destination_id=self.scope.destination_id)
                with self.subTest(operation=operation_class), self.assertRaises(ProductionAuthorityError):
                    action(legacy)
        assert_no_payload_access(self, statements)

    def test_test_minted_provenance_with_matching_visible_fields_fails(self):
        forged = exercise.trusted_test_source_origin_provenance(
            external_object_key=self.provenance.external_object_key,
            external_snapshot_key=self.provenance.snapshot_id,
            snapshot_kind=SnapshotKind.MANUAL_EVENT,
            origin_namespace_id=self.provenance.origin_namespace_id,
            ingress_adapter_id=self.provenance.ingress_adapter_id,
            adapter_version=self.provenance.adapter_version,
        )
        with self.assertRaises(ProductionAuthorityError):
            self.write(provenance=forged)

    def test_copied_authority_and_exercise_capability_policy_fail(self):
        receipt = self.write()
        bad_contexts = (
            replace(self.write_context), exercise.trusted_test_closed_real_ingress_capability(),
            exercise.trusted_test_single_owner_real_ingress_policy(
                policy_id="fixture-policy", owner_principal_id=self.scope.owner_principal_id,
                access_domain_id=self.scope.access_domain_id, origin_namespace_id=self.scope.origin_namespace_id,
            ),
        )
        for context in bad_contexts:
            with self.subTest(context=type(context).__name__), self.assertRaises(ProductionAuthorityError):
                self.write(context=context)
        with self.assertRaises(ProductionAuthorityError):
            self.write(provenance=replace(self.provenance))
        with self.assertRaises(ProductionAuthorityError):
            self.read(receipt.source_id, context=replace(self.read_context))
        with self.assertRaises(ProductionAuthorityError):
            self.stop(receipt.source_id, context=replace(self.stop_context))
        with self.assertRaises(ProductionAuthorityError):
            self.root.issue_operation(principal=replace(self.owner), request_id=RequestId("fixture"),
                                      operation_class=OperationClass.SOURCE_WRITE)

    def test_operation_class_and_scope_are_not_interchangeable(self):
        receipt = self.write()
        for action in (lambda: self.write(context=self.read_context),
                       lambda: self.read(receipt.source_id, context=self.write_context),
                       lambda: self.stop(receipt.source_id, context=self.read_context)):
            with self.assertRaises(ProductionAuthorityError):
                action()
        allowed = {OperationClass.SOURCE_WRITE, OperationClass.NORMAL_READ, OperationClass.SOURCE_SUPPRESS}
        for operation_class in set(OperationClass) - allowed:
            with self.subTest(operation=operation_class), self.assertRaises(ProductionAuthorityError):
                self.context(operation_class)
        for name, value in vars(self.scope).items():
            with self.subTest(scope=name), self.assertRaises(ProductionAuthorityError):
                with self.root._operation_admission(
                    context=self.read_context, provenance=None,
                    scope=replace(self.scope, **{name: type(value)("fixture-other")}),
                    expected_operation_class=OperationClass.NORMAL_READ,
                ):
                    self.fail("scope constraint admitted")

    def test_stop_use_dominates_replay_and_held_new_snapshot(self):
        receipt = self.write()
        replay = self.root.capture_manual_event(source_id=receipt.source_id)
        later = self.root.capture_manual_event(source_id=receipt.source_id, new_snapshot=True)
        self.stop(receipt.source_id)
        before = self.path.read_bytes()
        statements = []
        with traced_connections(statements):
            for provenance in (self.provenance, replay, later):
                with self.subTest(snapshot=provenance.snapshot_version), self.assertRaises(ProductionAuthorityError):
                    self.write(provenance=provenance)
            for new_snapshot in (False, True):
                with self.assertRaises(ProductionAuthorityError):
                    self.root.capture_manual_event(source_id=receipt.source_id, new_snapshot=new_snapshot)
            with self.assertRaises(ProductionAuthorityError):
                self.read(receipt.source_id)
        assert_no_payload_access(self, statements)
        self.assertEqual(before, self.path.read_bytes())

    def test_stop_use_covers_all_snapshots_of_origin_and_not_other_events(self):
        first = self.write()
        later = self.root.capture_manual_event(source_id=first.source_id, new_snapshot=True)
        second = self.write(provenance=later, content=FIXTURE_BETA)
        other = self.write(provenance=self.root.capture_manual_event())
        self.stop(second.source_id)
        for source_id in (first.source_id, second.source_id):
            with self.assertRaises(ProductionAuthorityError):
                self.read(source_id)
        self.assertEqual(self.read(other.source_id).content, FIXTURE_ALPHA)

    def test_restart_rejects_session_a_and_preserves_stop_use(self):
        receipt = self.write()
        pending = self.root.capture_manual_event(source_id=receipt.source_id, new_snapshot=True)
        self.stop(receipt.source_id)
        self.root.close()
        second = self.start()
        write = self.context(OperationClass.SOURCE_WRITE, second)
        read = self.context(OperationClass.NORMAL_READ, second)
        stop = self.context(OperationClass.SOURCE_SUPPRESS, second)
        fresh = second.capture_manual_event()
        for action in (
            lambda: second.write_source(context=self.write_context, provenance=fresh, content=FIXTURE_ALPHA),
            lambda: second.write_source(context=write, provenance=self.provenance, content=FIXTURE_ALPHA),
            lambda: second.write_source(context=write, provenance=pending, content=FIXTURE_BETA),
            lambda: second.read_source(context=self.read_context, source_id=receipt.source_id),
            lambda: second.stop_use_source(context=self.stop_context, source_id=receipt.source_id),
            lambda: second.read_source(context=read, source_id=receipt.source_id),
            lambda: second.capture_manual_event(source_id=receipt.source_id, new_snapshot=True),
        ):
            with self.assertRaises(ProductionAuthorityError):
                action()
        self.assertTrue(second.stop_use_source(context=stop, source_id=receipt.source_id).stopped)
        new = second.write_source(context=write, provenance=fresh, content=FIXTURE_BETA)
        self.assertEqual(second.read_source(context=read, source_id=new.source_id).content, FIXTURE_BETA)

    def test_restart_can_recapture_unsuppressed_origin_with_fresh_authority(self):
        receipt = self.write()
        self.root.close()
        second = self.start()
        provenance = second.capture_manual_event(source_id=receipt.source_id)
        result = second.write_source(context=self.context(OperationClass.SOURCE_WRITE, second),
                                     provenance=provenance, content=FIXTURE_ALPHA)
        self.assertEqual(result.source_id, receipt.source_id)
        self.assertTrue(result.exact_replay)
        self.assertNotEqual(provenance.session_id, self.provenance.session_id)

    def test_missing_or_damaged_stop_use_schema_and_state_fail_before_payload(self):
        receipt = self.write()
        self.execute_fixture_sql("DROP TRIGGER production_stop_use_no_delete",
                                 "DELETE FROM production_stop_use",
                                 schema._TRIGGERS["production_stop_use_no_delete"])
        self._assert_all_payload_denied(receipt.source_id)

    def test_missing_or_damaged_origin_state_fails_before_payload(self):
        receipt = self.write()
        self.execute_fixture_sql("DROP TRIGGER production_origins_no_delete", "DELETE FROM production_origins",
                                 schema._TRIGGERS["production_origins_no_delete"])
        self._assert_all_payload_denied(receipt.source_id)

    def test_missing_authority_table_or_trigger_prevents_first_payload_commit(self):
        for table in ("production_stop_use", "production_origins", "production_captures", "production_profile"):
            with self.subTest(table=table):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "fixture.sqlite3"
                    root = start_synthetic_production_memory(runtime_root=directory, db_path=path, scope=self.scope)
                    try:
                        context = root.issue_operation(principal=root.issue_owner(), operation_class=OperationClass.SOURCE_WRITE,
                                                       request_id=RequestId("fixture"))
                        provenance = root.capture_manual_event()
                        connection = sqlite3.connect(path)
                        try:
                            connection.execute(f"DROP TABLE {table}")
                            connection.commit()
                        finally:
                            connection.close()
                        with self.assertRaises(ProductionAuthorityError):
                            root.write_source(context=context, provenance=provenance, content=FIXTURE_ALPHA)
                    finally:
                        root.close()
        self.execute_fixture_sql("DROP TRIGGER production_stop_use_one_way")
        with self.assertRaises(ProductionAuthorityError):
            self.write()

    def test_damaged_origin_namespace_fails_before_payload(self):
        receipt = self.write()
        self.execute_fixture_sql("DROP TRIGGER production_origins_no_update",
                                 "UPDATE production_origins SET namespace = 'fixture-wrong'",
                                 schema._TRIGGERS["production_origins_no_update"])
        self._assert_all_payload_denied(receipt.source_id)

    def test_damaged_source_scope_fails_before_payload(self):
        receipt = self.write()
        self.execute_fixture_sql("DROP TRIGGER production_sources_no_update",
                                 "UPDATE production_sources SET scope = 'synthetic fixture: wrong scope'",
                                 schema._TRIGGERS["production_sources_no_update"])
        self._assert_all_payload_denied(receipt.source_id)

    def test_same_path_incarnation_replacement_fails_before_payload(self):
        receipt = self.write()
        self.execute_fixture_sql("UPDATE home_store_domain SET incarnation = 'fixture-wrong-incarnation'")
        self._assert_all_payload_denied(receipt.source_id)

    def test_changed_same_process_generation_fails_before_payload(self):
        receipt = self.write()
        self.root._coordinator.generation += 1
        self._assert_all_payload_denied(receipt.source_id)

    def test_payload_hash_corruption_is_rejected(self):
        receipt = self.write()
        self.execute_fixture_sql("DROP TRIGGER production_sources_no_update",
                                 "UPDATE production_sources SET content = 'synthetic fixture: corrupt'",
                                 schema._TRIGGERS["production_sources_no_update"])
        with self.assertRaises(ProductionAuthorityError):
            self.read(receipt.source_id)
        with self.assertRaises(ProductionAuthorityError):
            self.write()

    def _assert_all_payload_denied(self, source_id):
        statements = []
        with traced_connections(statements):
            for action in (self.write, lambda: self.read(source_id), lambda: self.stop(source_id)):
                with self.assertRaises(ProductionAuthorityError):
                    action()
        assert_no_payload_access(self, statements)

    def test_exercise_ingress_read_stop_use_and_maintenance_reject_payload_store(self):
        receipt = self.write()
        before = self.path.read_bytes()
        principal = exercise.trusted_test_principal_issuer().issue(
            principal_id=self.scope.owner_principal_id, principal_kind="local_owner")
        common = dict(policy_id="fixture-policy", owner_principal_id=self.scope.owner_principal_id,
                      access_domain_id=self.scope.access_domain_id)
        writer = ClosedRealIngressWriter(
            db_path=self.path, capability=exercise.trusted_test_closed_real_ingress_capability(),
            policy=exercise.trusted_test_single_owner_real_ingress_policy(
                **common, origin_namespace_id=self.scope.origin_namespace_id), ingress_channel="fixture-channel")
        reader = ClosedRealNormalReader(
            db_path=self.path, capability=exercise.trusted_test_closed_real_normal_read_capability(),
            policy=exercise.trusted_test_single_owner_real_normal_read_policy(**common))
        stopper = ClosedRealStopUseWriter(
            db_path=self.path, capability=exercise.trusted_test_closed_real_stop_use_capability(),
            policy=exercise.trusted_test_single_owner_real_stop_use_policy(**common))
        def context(kind):
            return create_operation_context(principal=principal, operation_class=kind)
        with self.assertRaises(StoreDomainError):
            writer.write_source(context=context(OperationClass.SOURCE_WRITE), source_id=receipt.source_id,
                                content=FIXTURE_BETA, metadata=IngressIdentityMetadata(access_domain_id=self.scope.access_domain_id),
                                provenance=exercise.trusted_test_source_origin_provenance(
                                    external_object_key=self.provenance.external_object_key,
                                    origin_namespace_id=self.scope.origin_namespace_id))
        with self.assertRaises(StoreDomainError):
            reader.read_source(context=context(OperationClass.NORMAL_READ), source_id=receipt.source_id)
        with self.assertRaises(StoreDomainError):
            stopper.suppress_source(context=context(OperationClass.SOURCE_SUPPRESS), source_id=receipt.source_id,
                                    reason_code=StopUseReasonCode.USER_STOP_USE)
        for action in (create_empty_real_store, destroy_real_store):
            with self.assertRaises(StoreDomainError):
                action(db_path=self.path, capability=exercise.trusted_test_real_store_bootstrap_capability())
        with self.assertRaises(StoreDomainError):
            MemoryStore(self.path).initialize()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.read(receipt.source_id).content, FIXTURE_ALPHA)

    def test_replacing_store_with_exercise_or_synthetic_denies_all_production_fronts(self):
        receipt = self.write()
        for kind in ("exercise", "synthetic"):
            with self.subTest(kind=kind):
                replacement = self.directory / f"fixture-{kind}.sqlite3"
                if kind == "exercise":
                    create_empty_real_store(db_path=replacement,
                                            capability=exercise.trusted_test_real_store_bootstrap_capability())
                else:
                    MemoryStore(replacement).initialize()
                os.replace(replacement, self.path)
                self._assert_all_payload_denied(receipt.source_id)

    def test_payload_profile_reset_is_unavailable_and_does_not_close_session(self):
        receipt = self.write()
        before = self.path.read_bytes()
        with self.assertRaises(ProductionAuthorityError):
            self.root.reset_empty_store()
        self.assertEqual(self.root.state, ProductionLifecycle.ACTIVE)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(self.read(receipt.source_id).content, FIXTURE_ALPHA)

    def _thread(self, action, errors):
        def run():
            try:
                action()
            except BaseException as exc:
                errors.append(exc)
        thread = Thread(target=run, daemon=True)
        thread.start()
        return thread

    def test_shutdown_cutoff_rechecks_queued_payload_context_before_access(self):
        attempted, errors = Event(), []
        original_guard = self.root._lease.live_guard
        def guard():
            attempted.set()
            return original_guard()
        with self.root._lease._liveness_lock, patch.object(self.root._lease, "live_guard", guard):
            writer = self._thread(self.write, errors)
            self.assertTrue(attempted.wait(5))
            closer = self._thread(self.root.close, errors)
            with self.root._condition:
                self.assertTrue(self.root._condition.wait_for(
                    lambda: self.root._state is ProductionLifecycle.CLOSING, timeout=5))
        writer.join(5)
        closer.join(5)
        self.assertFalse(writer.is_alive() or closer.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ProductionAuthorityError)
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM production_sources").fetchone(), (0,))
        finally:
            connection.close()

    def test_stop_use_serializes_with_admitted_read_then_blocks_next_read(self):
        receipt = self.write()
        entered, finish, stopping = Event(), Event(), Event()
        errors, reads = [], []
        original = schema.require_usable
        def held_usable(connection, origin_id):
            original(connection, origin_id)
            entered.set()
            if not finish.wait(5):
                raise AssertionError("fixture read drain timed out")
        with patch.object(schema, "require_usable", held_usable):
            reader = self._thread(lambda: reads.append(self.read(receipt.source_id)), errors)
            self.assertTrue(entered.wait(5))
            def stop():
                stopping.set()
                self.stop(receipt.source_id)
            stopper = self._thread(stop, errors)
            try:
                self.assertTrue(stopping.wait(5))
                self.assertTrue(stopper.is_alive())
            finally:
                finish.set()
                reader.join(5)
                stopper.join(5)
        self.assertEqual(errors, [])
        self.assertEqual([read.content for read in reads], [FIXTURE_ALPHA])
        with self.assertRaises(ProductionAuthorityError):
            self.read(receipt.source_id)

    @unittest.skipUnless(hasattr(os, "fork"), "fork isolation is POSIX-only")
    def test_forked_child_cannot_mint_capture_read_write_or_stop(self):
        receipt = self.write()
        pid = os.fork()
        if pid == 0:
            try:
                for action in (self.root.issue_owner, self.root.capture_manual_event, self.write,
                               lambda: self.read(receipt.source_id), lambda: self.stop(receipt.source_id)):
                    try:
                        action()
                    except HomeProcessIsolationError:
                        continue
                    os._exit(2)
                os._exit(0)
            except BaseException:
                os._exit(3)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        self.assertEqual(self.read(receipt.source_id).content, FIXTURE_ALPHA)

    def test_released_lease_denies_payload_and_provenance_minting(self):
        receipt = self.write()
        self.root._lease.release()
        from home_memory_core.host_runtime import HostRuntimeLeaseError
        for action in (self.root.capture_manual_event, self.write, lambda: self.read(receipt.source_id),
                       lambda: self.stop(receipt.source_id)):
            with self.assertRaises(HostRuntimeLeaseError):
                action()


class ProductionMemoryBootstrapTests(unittest.TestCase):
    def test_marker_only_1a_store_transitions_explicitly_preserving_scope_and_incarnation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.sqlite3"
            old = start_production_authority_contract(runtime_root=directory, db_path=path, scope=fixture_scope())
            incarnation = old._incarnation
            old_owner = old.issue_owner()
            old.close()
            root = start_synthetic_production_memory(runtime_root=directory, db_path=path, scope=fixture_scope())
            try:
                self.assertEqual(root._incarnation, incarnation)
                self.assertTrue(root._barrier_complete)
                self.assertEqual(root.state, ProductionLifecycle.ACTIVE)
                with self.assertRaises(ProductionAuthorityError):
                    root.issue_operation(principal=old_owner, request_id=RequestId("fixture"),
                                         operation_class=OperationClass.SOURCE_WRITE)
            finally:
                root.close()
            with self.assertRaises(ProductionAuthorityError):
                start_production_authority_contract(runtime_root=directory, db_path=path, scope=fixture_scope())

    def test_failure_at_each_new_schema_stage_publishes_no_payload_authority(self):
        for stage in ("_initialize_origin_schema", "_initialize_stop_use_schema", "_initialize_source_schema",
                      "_seal_profile", "assert_ready"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "fixture.sqlite3"
                old = start_production_authority_contract(runtime_root=directory, db_path=path, scope=fixture_scope())
                old.close()
                before = path.read_bytes()
                roots = []
                original_init = ProductionMemorySession.__init__
                original_stage = getattr(schema, stage)
                def capture(root, **kwargs):
                    original_init(root, **kwargs)
                    roots.append(root)
                def fail(*args, **kwargs):
                    root = roots[0]
                    self.assertEqual(root.state, ProductionLifecycle.BOOTSTRAPPING)
                    for action in (
                        root.issue_owner, root.capture_manual_event,
                        lambda: root.issue_operation(principal=None, request_id=RequestId("fixture"),
                                                     operation_class=OperationClass.SOURCE_WRITE),
                        lambda: root.write_source(context=None, provenance=None, content=FIXTURE_ALPHA),
                        lambda: root.read_source(context=None, source_id="fixture-source"),
                        lambda: root.stop_use_source(context=None, source_id="fixture-source"),
                    ):
                        with self.assertRaises(ProductionAuthorityError):
                            action()
                    original_stage(*args, **kwargs)  # Also test rollback of partial DDL.
                    raise RuntimeError("synthetic fixture: schema-stage failure")
                with patch.object(ProductionMemorySession, "__init__", capture), patch.object(schema, stage, fail):
                    with self.assertRaisesRegex(RuntimeError, "schema-stage failure"):
                        start_synthetic_production_memory(runtime_root=directory, db_path=path, scope=fixture_scope())
                root = roots[0]
                self.assertEqual(root.state, ProductionLifecycle.CLOSED)
                self.assertTrue(root._lease.released)
                self.assertTrue(root._permit.consumed)
                self.assertTrue(all(not registry for registry in (
                    root._principals, root._contexts, root._provenance, root._adapters)))
                self.assertEqual(before, path.read_bytes())
                reopened = start_synthetic_production_memory(runtime_root=directory, db_path=path, scope=fixture_scope())
                reopened.close()

    def test_unknown_or_payload_bearing_partial_initialization_is_not_repaired(self):
        for damage in ("DROP TABLE production_stop_use", "DROP TABLE production_origins",
                       "DROP TABLE production_profile", "DROP TABLE production_captures",
                       "CREATE TABLE fixture_unknown (fixture_content TEXT)"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "fixture.sqlite3"
                root = start_synthetic_production_memory(runtime_root=directory, db_path=path, scope=fixture_scope())
                owner = root.issue_owner()
                context = root.issue_operation(principal=owner, request_id=RequestId("fixture"),
                                               operation_class=OperationClass.SOURCE_WRITE)
                root.write_source(context=context, provenance=root.capture_manual_event(), content=FIXTURE_ALPHA)
                root.close()
                connection = sqlite3.connect(path)
                try:
                    connection.execute(damage)
                    connection.commit()
                finally:
                    connection.close()
                before = path.read_bytes()
                with self.assertRaises(ProductionAuthorityError):
                    start_synthetic_production_memory(runtime_root=directory, db_path=path, scope=fixture_scope())
                self.assertEqual(before, path.read_bytes())

    def test_synthetic_and_exercise_stores_cannot_be_adopted(self):
        for kind in ("synthetic", "exercise"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "fixture.sqlite3"
                if kind == "synthetic":
                    MemoryStore(path).initialize()
                else:
                    create_empty_real_store(db_path=path, capability=exercise.trusted_test_real_store_bootstrap_capability())
                before = path.read_bytes()
                with self.assertRaises(ProductionAuthorityError):
                    start_synthetic_production_memory(runtime_root=directory, db_path=path, scope=fixture_scope())
                self.assertEqual(before, path.read_bytes())

    def test_real_data_enablement_is_rejected_before_filesystem_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture-new-root"
            for flag in (False, 1, "true", None):
                with self.subTest(flag=flag), self.assertRaises(ProductionAuthorityError):
                    start_synthetic_production_memory(runtime_root=path, db_path=path / "fixture.sqlite3",
                                                       scope=fixture_scope(), synthetic_only=flag)
            self.assertFalse(path.exists())

    def test_runtime_vertical_slice_without_importable_test_helpers(self):
        repo = Path(__file__).resolve().parents[1]
        code = """
import sys, tempfile
from pathlib import Path
class BlockTestImports:
    def find_spec(self, fullname, path=None, target=None):
        if 'test' in fullname:
            raise AssertionError('runtime test dependency')
sys.meta_path.insert(0, BlockTestImports())
from home_memory_core.production_memory import start_synthetic_production_memory
from home_memory_core.production_authority import ProductionScope, ProductionAuthorityError
from home_memory_core.identity_namespaces import *
from home_memory_core.operation_identity import OperationClass, PrincipalId
scope = ProductionScope(PrincipalId('fixture-owner'), AccessDomainId('fixture-domain'),
    PerspectiveOwnerId('fixture-perspective'), PerspectiveInstanceId('fixture-instance'),
    OriginNamespaceId('fixture-namespace'), DestinationId('fixture-destination'))
with tempfile.TemporaryDirectory() as d:
    root = start_synthetic_production_memory(runtime_root=d, db_path=Path(d)/'fixture.sqlite3', scope=scope)
    try:
        owner = root.issue_owner()
        def context(kind):
            return root.issue_operation(principal=owner, operation_class=kind, request_id=RequestId('fixture'))
        receipt = root.write_source(context=context(OperationClass.SOURCE_WRITE),
            provenance=root.capture_manual_event(), content='synthetic fixture: isolated process')
        assert root.read_source(context=context(OperationClass.NORMAL_READ), source_id=receipt.source_id).content == 'synthetic fixture: isolated process'
        root.stop_use_source(context=context(OperationClass.SOURCE_SUPPRESS), source_id=receipt.source_id)
        try:
            root.read_source(context=context(OperationClass.NORMAL_READ), source_id=receipt.source_id)
        except ProductionAuthorityError:
            pass
        else:
            raise AssertionError('stop-use bypassed')
    finally:
        root.close()
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-c", code], cwd=directory,
                                    env=dict(os.environ, PYTHONPATH=str(repo / "src")),
                                    text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
