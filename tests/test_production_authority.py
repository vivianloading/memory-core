"""#08a.1a adversarial contracts. All identifiers and data are synthetic fixtures."""
from dataclasses import replace
import importlib
import gc
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from threading import Event, Thread
import unittest
import weakref
from unittest.mock import patch

import _trusted_test_support as exercise
from home_memory_core import production_authority as production
from home_memory_core.host_runtime import HostRuntimeLeaseError, acquire_home_single_instance
from home_memory_core.identity_namespaces import (
    AccessDomainId, DestinationId, OriginNamespaceId, PerspectiveInstanceId,
    PerspectiveOwnerId, RequestId,
)
from home_memory_core.ingress_identity import IngressIdentityMetadata
from home_memory_core.operation_identity import (
    AuthenticationBoundaryError, OperationClass, PrincipalId,
    create_operation_context, require_operation_context,
)
from home_memory_core.process_boundary import HomeProcessIsolationError
from home_memory_core.production_authority import (
    ProductionAuthorityError, ProductionAuthorityRoot, ProductionLifecycle,
    ProductionScope, ShutdownDisposition, start_production_authority_contract,
)
from home_memory_core.real_ingress import ClosedRealIngressWriter
from home_memory_core.real_normal_read import ClosedRealNormalReader
from home_memory_core.storage import MemoryStore
from home_memory_core.store_domain import (
    StoreDomainError, create_empty_real_store, destroy_real_store,
)


def fixture_scope():
    return ProductionScope(
        PrincipalId("fixture-owner"), AccessDomainId("fixture-domain"),
        PerspectiveOwnerId("fixture-perspective"), PerspectiveInstanceId("fixture-instance"),
        OriginNamespaceId("fixture-provider/account"), DestinationId("fixture-destination"),
    )


class ProductionAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / "contract.sqlite3"
        self.scope = fixture_scope()
        self.root = self.start()
        self.principal, self.context, self.adapter, self.provenance = self.issue(self.root)

    def start(self):
        root = start_production_authority_contract(
            runtime_root=self.directory, db_path=self.path, scope=self.scope,
        )
        self.addCleanup(root.close)
        return root

    def issue(self, root):
        principal = root.issue_owner()
        context = root.issue_operation(principal=principal, request_id=RequestId("fixture-request"))
        adapter = root.register_adapter(
            adapter_id="fixture-adapter", origin_namespace_id=self.scope.origin_namespace_id,
        )
        provenance = root.issue_provenance(adapter=adapter, external_object_key="fixture-object")
        return principal, context, adapter, provenance

    def check(self, root=None, **overrides):
        values = dict(context=self.context, provenance=self.provenance, scope=self.scope)
        values.update(overrides)
        return (root or self.root).check_contract(**values)

    def legacy_principal(self):
        return exercise.trusted_test_principal_issuer(
            trust_source=self.principal.trust_source,
        ).issue(principal_id=self.scope.owner_principal_id, principal_kind=self.principal.principal_kind)

    def test_current_registered_adapter_succeeds_with_no_payload_schema(self):
        receipt = self.check()
        self.assertEqual(receipt.session_id, self.root.session_id)
        self.assertEqual(receipt.store_incarnation, self.context.store_incarnation)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(production._user_tables(connection), {"home_store_domain"})
        connection.close()
        for name in ("read_source", "write_source", "deliver", "sink", "principal", "provenance_issuer"):
            self.assertFalse(hasattr(self.root, name))

    def test_test_minted_exact_owner_and_global_context_are_rejected(self):
        principal = self.legacy_principal()
        self.assertEqual(principal.principal_id, self.principal.principal_id)
        self.assertEqual(principal.trust_source, self.principal.trust_source)
        with self.assertRaises(ProductionAuthorityError):
            self.root.issue_operation(principal=principal, request_id=RequestId("fixture-request"))
        legacy = create_operation_context(
            principal=principal, operation_class=OperationClass.AUDIT_READ,
            request_id=self.context.request_id, destination_id=self.scope.destination_id,
        )
        with self.assertRaises(ProductionAuthorityError):
            self.check(context=legacy)
        with self.assertRaises(AuthenticationBoundaryError):
            require_operation_context(self.context)

    def test_same_fields_do_not_substitute_for_current_root_issuance(self):
        for field, value in (("context", self.context), ("provenance", self.provenance)):
            with self.subTest(field=field), self.assertRaises(ProductionAuthorityError):
                self.check(**{field: replace(value)})
        with self.assertRaises(ProductionAuthorityError):
            self.root.issue_operation(principal=replace(self.principal), request_id=RequestId("fixture"))
        with self.assertRaises(ProductionAuthorityError):
            self.root.issue_provenance(adapter=replace(self.adapter), external_object_key="fixture-object")

    def test_legacy_provenance_exact_namespace_and_adapter_are_rejected(self):
        provenance = exercise.trusted_test_source_origin_provenance(
            external_object_key=self.provenance.external_object_key,
            origin_namespace_id=self.scope.origin_namespace_id,
            ingress_adapter_id=self.provenance.ingress_adapter_id,
        )
        with self.assertRaises(ProductionAuthorityError):
            self.check(provenance=provenance)

    def test_exercise_capability_and_matching_policy_never_authorize_production(self):
        policy = exercise.trusted_test_single_owner_real_ingress_policy(
            policy_id="fixture-policy", owner_principal_id=self.scope.owner_principal_id,
            access_domain_id=self.scope.access_domain_id,
            origin_namespace_id=self.scope.origin_namespace_id,
        )
        for value in (policy, exercise.trusted_test_closed_real_ingress_capability()):
            with self.subTest(value=type(value).__name__), self.assertRaises(ProductionAuthorityError):
                self.check(context=value)

    def test_all_exact_constraints_and_operation_classes_fail_closed(self):
        for name, value in vars(self.scope).items():
            with self.subTest(constraint=name), self.assertRaises(ProductionAuthorityError):
                self.check(scope=replace(self.scope, **{name: type(value)("fixture-other")}))
        for operation_class in OperationClass:
            if operation_class is OperationClass.AUDIT_READ:
                continue
            with self.subTest(operation=operation_class), self.assertRaises(ProductionAuthorityError):
                self.root.issue_operation(
                    principal=self.principal, request_id=RequestId("fixture"),
                    operation_class=operation_class,
                )
        with self.assertRaises(ProductionAuthorityError):
            self.root.register_adapter(adapter_id="fixture", origin_namespace_id=OriginNamespaceId("other"))

    def test_session_a_objects_and_adapter_fail_after_restart_into_b(self):
        self.root.close()
        second = self.start()
        self.assertNotEqual(second.session_id, self.root.session_id)
        with self.assertRaises(ProductionAuthorityError):
            self.check(root=second)
        with self.assertRaises(ProductionAuthorityError):
            second.issue_operation(principal=self.principal, request_id=RequestId("fixture"))
        with self.assertRaises(ProductionAuthorityError):
            second.issue_provenance(adapter=self.adapter, external_object_key="fixture-object")
        _, context, _, provenance = self.issue(second)
        self.check(root=second, context=context, provenance=provenance)

    def test_closed_is_terminal_and_bootstrap_permit_is_revoked(self):
        self.assertTrue(self.root._permit.consumed)
        with self.assertRaises(ProductionAuthorityError):
            self.root._bootstrap_store()
        self.root.close()
        self.assertEqual(self.root.state, ProductionLifecycle.CLOSED)
        for action in (self.root.issue_owner, self.root._activate, self.check):
            with self.assertRaises((ProductionAuthorityError, HostRuntimeLeaseError)):
                action()
        self.assertEqual(self.root.close(), ShutdownDisposition.CLOSE)

    def test_legal_exercise_cannot_read_write_bootstrap_reset_or_initialize(self):
        before = self.path.read_bytes()
        capability = exercise.trusted_test_real_store_bootstrap_capability()
        for action in (create_empty_real_store, destroy_real_store):
            with self.subTest(action=action.__name__), self.assertRaises(StoreDomainError):
                action(db_path=self.path, capability=capability)
        for suffix in ("ingress", "source_origin", "relationships", "supersession", "stop_use", "delivery"):
            module = importlib.import_module(f"home_memory_core.real_{suffix}")
            factory_suffix = "relationship" if suffix == "relationships" else suffix
            capability = getattr(exercise, f"trusted_test_closed_real_{factory_suffix}_capability")()
            schema_suffix = "handoff" if suffix == "delivery" else factory_suffix
            initializer = getattr(module, f"initialize_closed_real_{schema_suffix}_schema")
            kwargs = {"capability": capability}
            if suffix == "relationships":
                kwargs = dict(relationship_capability=capability,
                              ingress_capability=exercise.trusted_test_closed_real_ingress_capability())
            elif suffix == "supersession":
                kwargs = dict(supersession_capability=capability,
                              relationship_capability=exercise.trusted_test_closed_real_relationship_capability())
            with self.subTest(schema=suffix), self.assertRaises(StoreDomainError):
                initializer(db_path=self.path, **kwargs)
        with self.assertRaises(StoreDomainError):
            MemoryStore(self.path).initialize()
        self._exercise_read_write_denied()
        self.assertEqual(before, self.path.read_bytes())
        self.check()

    def _exercise_read_write_denied(self):
        principal = self.legacy_principal()
        reader = ClosedRealNormalReader(
            db_path=self.path,
            capability=exercise.trusted_test_closed_real_normal_read_capability(),
            policy=exercise.trusted_test_single_owner_real_normal_read_policy(
                policy_id="fixture-policy", owner_principal_id=self.scope.owner_principal_id,
                access_domain_id=self.scope.access_domain_id,
                perspective_owner=self.scope.perspective_owner,
                perspective_instance=self.scope.perspective_instance,
            ),
        )
        writer = ClosedRealIngressWriter(
            db_path=self.path, capability=exercise.trusted_test_closed_real_ingress_capability(),
            policy=exercise.trusted_test_single_owner_real_ingress_policy(
                policy_id="fixture-policy", owner_principal_id=self.scope.owner_principal_id,
                access_domain_id=self.scope.access_domain_id,
                origin_namespace_id=self.scope.origin_namespace_id,
            ), ingress_channel="fixture-channel",
        )
        with self.assertRaises(StoreDomainError):
            reader.read_source(context=create_operation_context(
                principal=principal, operation_class=OperationClass.NORMAL_READ,
            ), source_id="fixture-source")
        with self.assertRaises(StoreDomainError):
            writer.write_source(
                context=create_operation_context(principal=principal, operation_class=OperationClass.SOURCE_WRITE),
                source_id="fixture-source", content="synthetic fixture only",
                metadata=IngressIdentityMetadata(access_domain_id=self.scope.access_domain_id),
                provenance=exercise.trusted_test_source_origin_provenance(
                    external_object_key="fixture-object", origin_namespace_id=self.scope.origin_namespace_id,
                ),
            )

    def test_test_helpers_visible_in_fresh_process_do_not_open_production_store(self):
        self.root.close()
        repo = Path(__file__).resolve().parents[1]
        code = """
import sys
from pathlib import Path
from test_production_authority import ProductionAuthorityTests, fixture_scope
from _trusted_test_support import trusted_test_real_store_bootstrap_capability
from home_memory_core.store_domain import create_empty_real_store, destroy_real_store, StoreDomainError
case = ProductionAuthorityTests()
case.path = Path(sys.argv[1])
case.scope = fixture_scope()
from types import SimpleNamespace
case.principal = SimpleNamespace(trust_source='production-contract-root', principal_kind='local_owner')
case._exercise_read_write_denied()
for fn in (create_empty_real_store, destroy_real_store):
    try:
        fn(db_path=case.path, capability=trusted_test_real_store_bootstrap_capability())
    except StoreDomainError:
        continue
    raise AssertionError('exercise crossed production ownership')
"""
        env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(repo / "src"), str(repo / "tests"))))
        result = subprocess.run([sys.executable, "-c", code, str(self.path)], cwd=repo / "tests",
                                env=env, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_released_or_lost_lease_revokes_minting_and_operations(self):
        self.root._lease.release()  # Deliberately simulate a lost host-owned lease.
        for action in (self.root.issue_owner, self.check):
            with self.assertRaises(HostRuntimeLeaseError):
                action()
        self.root.close()
        second = self.start()
        _, context, _, provenance = self.issue(second)
        second._lease._handle.close()  # OS releases the lock, even without release().
        with self.assertRaises(HostRuntimeLeaseError):
            second.issue_owner()
        with self.assertRaises(HostRuntimeLeaseError):
            self.check(root=second, context=context, provenance=provenance)

    def test_missing_replaced_lock_file_fails_closed(self):
        if sys.platform == "win32":
            self.skipTest("open lock-file replacement is platform-specific")
        lock_path = self.root._lease.identity.lock_path
        moved = lock_path.with_name("old-lock")
        lock_path.rename(moved)
        lock_path.touch()
        with self.assertRaises(HostRuntimeLeaseError):
            self.check()

    def test_lease_release_is_serialized_with_admitted_operations(self):
        entered, finish, release_attempted, released = Event(), Event(), Event(), Event()
        errors = []
        def admitted():
            with self.root._operation_admission(
                context=self.context, provenance=self.provenance, scope=self.scope,
            ):
                entered.set()
                if not finish.wait(5):
                    raise AssertionError("lease fixture timed out")
        def lose_lease():
            release_attempted.set()
            self.root._lease.release()
            released.set()
        worker = self._thread(admitted, errors)
        self.assertTrue(entered.wait(5))
        releaser = self._thread(lose_lease, errors)
        try:
            self.assertTrue(release_attempted.wait(5))
            self.assertFalse(released.is_set())
        finally:
            finish.set()
            worker.join(5)
            releaser.join(5)
        self.assertEqual(errors, [])
        self.assertTrue(released.is_set())
        with self.assertRaises(HostRuntimeLeaseError):
            self.check()

    def test_same_thread_shutdown_and_nested_admission_are_rejected(self):
        with self.root._operation_admission(
            context=self.context, provenance=self.provenance, scope=self.scope,
        ):
            for action in (self.root.close, self.root.reset_empty_store, self.check):
                with self.assertRaises(ProductionAuthorityError):
                    action()
        self.check()

    def test_generation_and_persistent_incarnation_are_both_required(self):
        self.root._coordinator.generation += 1
        with self.assertRaises(ProductionAuthorityError):
            self.check()
        self.root._coordinator.generation -= 1
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("UPDATE home_store_domain SET incarnation = 'fixture-replaced'")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(ProductionAuthorityError):
            self.check()

    def test_missing_incarnation_never_matches_as_wildcard(self):
        self.root.close()
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("ALTER TABLE home_store_domain RENAME COLUMN incarnation TO absent")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(ProductionAuthorityError):
            self.start()

    def _thread(self, action, errors):
        def run():
            try:
                action()
            except BaseException as error:
                errors.append(error)
        thread = Thread(target=run, daemon=True)
        thread.start()
        return thread

    def _wait_cutoff(self):
        with self.root._condition:
            self.assertTrue(self.root._condition.wait_for(
                lambda: self.root._state is ProductionLifecycle.CLOSING, timeout=5,
            ))

    def test_shutdown_cutoff_drains_admitted_work_and_rejects_held_old_context(self):
        entered, finish = Event(), Event()
        errors, results = [], []
        def admitted():
            with self.root._operation_admission(
                context=self.context, provenance=self.provenance, scope=self.scope,
            ):
                entered.set()
                if not finish.wait(5):
                    raise AssertionError("drain fixture timed out")
        worker = self._thread(admitted, errors)
        self.assertTrue(entered.wait(5))
        closer = self._thread(lambda: results.append(self.root.close()), errors)
        try:
            self._wait_cutoff()
            self.assertFalse(self.root._lease.released)
            self.assertTrue(closer.is_alive())
            with self.assertRaises(ProductionAuthorityError):
                self.check()
            with self.assertRaises(ProductionAuthorityError):
                self.root.issue_owner()
        finally:
            finish.set()
            worker.join(5)
            closer.join(5)
        self.assertFalse(worker.is_alive() or closer.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results, [ShutdownDisposition.CLOSE])
        self.assertTrue(self.root._lease.released)
        self.assertFalse(self.root._contexts)

    def test_context_queued_before_cutoff_is_rechecked_inside_admission(self):
        attempted, errors = Event(), []
        original_guard = self.root._lease.live_guard
        def observed_guard():
            attempted.set()
            return original_guard()
        # Queue an operation after its early state check, before the real
        # admission point. The lifecycle cutoff must still win.
        with self.root._lease._liveness_lock, patch.object(self.root._lease, "live_guard", observed_guard):
            worker = self._thread(self.check, errors)
            self.assertTrue(attempted.wait(5))
            closer = self._thread(self.root.close, errors)
            self._wait_cutoff()
        worker.join(5)
        closer.join(5)
        self.assertFalse(worker.is_alive() or closer.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ProductionAuthorityError)

    def test_close_reset_first_cutoff_has_one_deterministic_result(self):
        for reset_first in (False, True):
            with self.subTest(reset_first=reset_first):
                if self.root.state is ProductionLifecycle.CLOSED:
                    self.root = self.start()
                before = self.root._incarnation
                errors, results = [], []
                first = self.root.reset_empty_store if reset_first else self.root.close
                second = self.root.close if reset_first else self.root.reset_empty_store
                # Prevent drain while allowing the first caller to close admission.
                with self.root._coordinator.lock:
                    a = self._thread(lambda: results.append(first()), errors)
                    self._wait_cutoff()
                    b = self._thread(lambda: results.append(second()), errors)
                a.join(5)
                b.join(5)
                expected = ShutdownDisposition.RESET_EMPTY_METADATA if reset_first else ShutdownDisposition.CLOSE
                self.assertFalse(a.is_alive() or b.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(results, [expected, expected])
                reopened = self.start()
                self.assertEqual(reopened._incarnation == before, not reset_first)
                reopened.close()

    def test_release_occurs_after_closed_and_issuance_invalidation(self):
        original = self.root._lease.release
        def observe_release():
            self.assertEqual(self.root.state, ProductionLifecycle.CLOSED)
            self.assertTrue(all(not x for x in (self.root._principals, self.root._contexts,
                                                self.root._adapters, self.root._provenance)))
            original()
        with patch.object(self.root._lease, "release", observe_release):
            self.root.close()

    def test_cleanup_failure_never_reactivates_or_releases_lease(self):
        with patch.object(self.root, "_close_runtime_resources", side_effect=RuntimeError("fixture-failure")):
            with self.assertRaises(RuntimeError):
                self.root.close()
        self.assertEqual(self.root.state, ProductionLifecycle.CLOSING)
        self.assertFalse(self.root._lease.released)
        for action in (self.check, self.root.issue_owner, self.root.close, self.root._activate):
            with self.assertRaises(ProductionAuthorityError):
                action()
        with self.assertRaises(HostRuntimeLeaseError):
            acquire_home_single_instance(runtime_root=self.directory, db_path=self.path)
        # Test harness disposal only: production provides no unsafe recovery API.
        self.root._lease.release()
        production._FAILED_ROOTS.pop(self.root.session_id)
        self._cleanups = [(fn, args, kw) for fn, args, kw in self._cleanups if fn != self.root.close]

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork")
    def test_forked_child_cannot_mint_use_close_or_bootstrap(self):
        pid = os.fork()
        if pid == 0:
            try:
                for action in (self.root.issue_owner, self.check, self.root.close,
                               lambda: start_production_authority_contract(
                                   runtime_root=self.directory, db_path=self.path, scope=self.scope)):
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
        self.check()


class ProductionBootstrapTests(unittest.TestCase):
    def test_each_sql_bootstrap_stage_closes_handles_and_rolls_back(self):
        original_connect = sqlite3.connect
        stages = ("BEGIN IMMEDIATE", "CREATE TABLE", "INSERT INTO", "CREATE TRIGGER",
                  "SELECT marker_key", "commit")
        for stage in stages:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                handles, roots = [], []
                original_init = ProductionAuthorityRoot.__init__
                def capture(root, **kwargs):
                    original_init(root, **kwargs)
                    roots.append(root)
                class FailingConnection:
                    def __init__(self, *args, **kwargs):
                        self.connection = original_connect(*args, **kwargs)
                        self.closed = False
                        handles.append(self)
                    def execute(self, sql, *args):
                        if sql.startswith(stage):
                            raise sqlite3.OperationalError("fixture-sql-failure")
                        return self.connection.execute(sql, *args)
                    def __enter__(self):
                        self.connection.__enter__()
                        return self
                    def __exit__(self, kind, value, tb):
                        if stage == "commit" and kind is None:
                            self.connection.rollback()
                            raise sqlite3.OperationalError("fixture-commit-failure")
                        return self.connection.__exit__(kind, value, tb)
                    def close(self):
                        self.connection.close()
                        self.closed = True
                path = Path(directory) / "contract.sqlite3"
                with patch.object(ProductionAuthorityRoot, "__init__", capture), \
                        patch.object(production.sqlite3, "connect", FailingConnection):
                    with self.assertRaises((sqlite3.OperationalError, ProductionAuthorityError)):
                        start_production_authority_contract(runtime_root=directory, db_path=path, scope=fixture_scope())
                self.assertTrue(handles and all(handle.closed for handle in handles))
                self.assertEqual(roots[0].state, ProductionLifecycle.CLOSED)
                self.assertTrue(roots[0]._lease.released)
                connection = original_connect(path)
                try:
                    self.assertEqual(production._user_tables(connection), set())
                finally:
                    connection.close()

    def test_bootstrap_cleanup_failure_retains_lease_and_closed_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            roots = []
            original_init = ProductionAuthorityRoot.__init__
            def capture(root, **kwargs):
                original_init(root, **kwargs)
                roots.append(weakref.ref(root))
            path = Path(directory) / "contract.sqlite3"
            with patch.object(ProductionAuthorityRoot, "__init__", capture), \
                    patch.object(ProductionAuthorityRoot, "_activate", side_effect=RuntimeError("fixture-init")), \
                    patch.object(ProductionAuthorityRoot, "_close_runtime_resources", side_effect=RuntimeError("fixture-cleanup")):
                with self.assertRaisesRegex(RuntimeError, "fixture-cleanup"):
                    start_production_authority_contract(runtime_root=directory, db_path=path, scope=fixture_scope())
            gc.collect()
            root = roots[0]()
            self.assertIsNotNone(root, "failed bootstrap must retain its lease despite GC")
            self.assertEqual(root.state, ProductionLifecycle.CLOSING)
            self.assertFalse(root._lease.released)
            with self.assertRaises(ProductionAuthorityError):
                root.issue_owner()
            with self.assertRaises(ProductionAuthorityError):
                root.close()
            with self.assertRaises(HostRuntimeLeaseError):
                acquire_home_single_instance(runtime_root=directory, db_path=path)
            root._lease.release()  # Test harness disposal only.
            production._FAILED_ROOTS.pop(root.session_id)

    def test_every_initialization_stage_failure_publishes_no_authority(self):
        stages = ("_acquire_lease", "_bootstrap_store", "consume", "_activate")
        for stage in stages:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                captured = []
                original_init = ProductionAuthorityRoot.__init__
                def capture(root, **kwargs):
                    original_init(root, **kwargs)
                    captured.append(root)
                target = production._BootstrapPermit if stage == "consume" else ProductionAuthorityRoot
                def fail(*args, **kwargs):
                    root = captured[0]
                    self.assertEqual(root.state, ProductionLifecycle.BOOTSTRAPPING)
                    for action in (
                        root.issue_owner,
                        lambda: root.issue_operation(principal=None, request_id=RequestId("fixture")),
                        lambda: root.register_adapter(adapter_id="fixture", origin_namespace_id=fixture_scope().origin_namespace_id),
                        lambda: root.issue_provenance(adapter=None, external_object_key="fixture"),
                        lambda: root.check_contract(context=None, provenance=None, scope=fixture_scope()),
                    ):
                        with self.assertRaises(ProductionAuthorityError):
                            action()
                    raise RuntimeError("fixture-bootstrap-failure")
                path = Path(directory) / "contract.sqlite3"
                with patch.object(ProductionAuthorityRoot, "__init__", capture), patch.object(target, stage, fail):
                    with self.assertRaisesRegex(RuntimeError, "fixture-bootstrap-failure"):
                        start_production_authority_contract(runtime_root=directory, db_path=path, scope=fixture_scope())
                root = captured[0]
                self.assertEqual(root.state, ProductionLifecycle.CLOSED)
                self.assertTrue(root._permit.consumed)
                self.assertTrue(all(not x for x in (root._principals, root._contexts, root._adapters, root._provenance)))
                with acquire_home_single_instance(runtime_root=directory, db_path=path):
                    pass
                if path.exists():
                    connection = sqlite3.connect(path)
                    try:
                        self.assertLessEqual(production._user_tables(connection), {"home_store_domain"})
                    finally:
                        connection.close()

    def test_production_rejects_exercise_store_without_relabeling(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "exercise.sqlite3"
            create_empty_real_store(db_path=path, capability=exercise.trusted_test_real_store_bootstrap_capability())
            before = path.read_bytes()
            with self.assertRaises(ProductionAuthorityError):
                start_production_authority_contract(runtime_root=directory, db_path=path, scope=fixture_scope())
            self.assertEqual(path.read_bytes(), before)

    def test_runtime_works_when_test_helper_import_is_forbidden(self):
        repo = Path(__file__).resolve().parents[1]
        code = """
import sys, tempfile
from pathlib import Path
class BlockTestImports:
    def find_spec(self, fullname, path=None, target=None):
        if 'test' in fullname:
            raise AssertionError('production attempted test import: ' + fullname)
sys.meta_path.insert(0, BlockTestImports())
from home_memory_core.production_authority import *
from home_memory_core.identity_namespaces import *
from home_memory_core.operation_identity import PrincipalId
with tempfile.TemporaryDirectory() as d:
    scope = ProductionScope(PrincipalId('fixture'), AccessDomainId('fixture'),
        PerspectiveOwnerId('fixture'), PerspectiveInstanceId('fixture'),
        OriginNamespaceId('fixture'), DestinationId('fixture'))
    root = start_production_authority_contract(runtime_root=d, db_path=Path(d)/'contract.db', scope=scope)
    try:
        owner = root.issue_owner()
        context = root.issue_operation(principal=owner, request_id=RequestId('fixture'))
        adapter = root.register_adapter(adapter_id='fixture', origin_namespace_id=scope.origin_namespace_id)
        provenance = root.issue_provenance(adapter=adapter, external_object_key='fixture')
        root.check_contract(context=context, provenance=provenance, scope=scope)
    finally:
        root.close()
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-c", code], cwd=directory,
                                    env=dict(os.environ, PYTHONPATH=str(repo / "src")),
                                    text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
