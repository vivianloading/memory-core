from __future__ import annotations

from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest

from _trusted_test_support import (
    trusted_test_closed_real_ingress_capability,
    trusted_test_closed_real_stop_use_capability,
    trusted_test_principal_issuer,
    trusted_test_real_store_bootstrap_capability,
    trusted_test_single_owner_real_ingress_policy,
)
from home_memory_core.identity_namespaces import AccessDomainId
from home_memory_core.ingress_identity import IngressIdentityMetadata
from home_memory_core.operation_identity import (
    OperationClass,
    PrincipalId,
    create_operation_context,
)
from home_memory_core.real_authority_ordering import (
    RealStoreLifecycleError,
    real_authority_operation,
)
from home_memory_core.real_ingress import (
    ClosedRealIngressWriter,
    initialize_closed_real_ingress_schema,
)
from home_memory_core.real_stop_use import initialize_closed_real_stop_use_schema
from home_memory_core.store_domain import (
    create_empty_real_store,
    destroy_real_store,
)


class RealAuthorityLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "real.sqlite3"
        self.bootstrap = trusted_test_real_store_bootstrap_capability()
        create_empty_real_store(
            db_path=self.db_path,
            capability=self.bootstrap,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _initialize_source_path(self):
        ingress_capability = trusted_test_closed_real_ingress_capability()
        initialize_closed_real_ingress_schema(
            db_path=self.db_path,
            capability=ingress_capability,
        )
        initialize_closed_real_stop_use_schema(
            db_path=self.db_path,
            capability=trusted_test_closed_real_stop_use_capability(),
        )
        owner_id = PrincipalId("owner-vivi")
        principal = trusted_test_principal_issuer().issue(
            principal_id=owner_id,
            principal_kind="local_owner",
        )
        domain = AccessDomainId("owner-private-domain")
        policy = trusted_test_single_owner_real_ingress_policy(
            policy_id="single-owner-ingress-v0.1",
            owner_principal_id=owner_id,
            access_domain_id=domain,
        )
        writer = ClosedRealIngressWriter(
            db_path=self.db_path,
            capability=ingress_capability,
            policy=policy,
            ingress_channel="synthetic-fixture-test",
        )
        return ingress_capability, principal, domain, writer

    def test_destroy_waits_for_inflight_authority_operation(self) -> None:
        operation_entered = Event()
        release_operation = Event()
        destroy_started = Event()
        destroy_done = Event()
        errors: list[BaseException] = []

        def hold_operation():
            try:
                with real_authority_operation(self.db_path):
                    operation_entered.set()
                    if not release_operation.wait(2):
                        raise AssertionError("test did not release authority operation")
            except BaseException as error:  # pragma: no cover - diagnostics
                errors.append(error)

        def destroy():
            try:
                destroy_started.set()
                destroy_real_store(
                    db_path=self.db_path,
                    capability=self.bootstrap,
                )
            except BaseException as error:  # pragma: no cover - diagnostics
                errors.append(error)
            finally:
                destroy_done.set()

        holder = Thread(target=hold_operation)
        holder.start()
        self.assertTrue(operation_entered.wait(1))

        destroyer = Thread(target=destroy)
        destroyer.start()
        self.assertTrue(destroy_started.wait(1))
        self.assertFalse(
            destroy_done.wait(0.05),
            "reset must not pass an in-flight authority operation",
        )

        release_operation.set()
        self.assertTrue(destroy_done.wait(1))
        holder.join()
        destroyer.join()

        self.assertEqual(errors, [])
        self.assertFalse(self.db_path.exists())

    def test_destroy_recreate_invalidates_stale_writer_generation(self) -> None:
        _, principal, domain, old_writer = self._initialize_source_path()

        destroy_real_store(
            db_path=self.db_path,
            capability=self.bootstrap,
        )
        create_empty_real_store(
            db_path=self.db_path,
            capability=self.bootstrap,
        )
        ingress_capability = trusted_test_closed_real_ingress_capability()
        initialize_closed_real_ingress_schema(
            db_path=self.db_path,
            capability=ingress_capability,
        )
        initialize_closed_real_stop_use_schema(
            db_path=self.db_path,
            capability=trusted_test_closed_real_stop_use_capability(),
        )

        with self.assertRaises(RealStoreLifecycleError):
            old_writer.write_source(
                context=create_operation_context(
                    principal=principal,
                    operation_class=OperationClass.SOURCE_WRITE,
                ),
                source_id="stale-source",
                content="synthetic stale writer fixture",
                metadata=IngressIdentityMetadata(access_domain_id=domain),
            )

        owner_id = principal.principal_id
        new_policy = trusted_test_single_owner_real_ingress_policy(
            policy_id="single-owner-ingress-v0.1",
            owner_principal_id=owner_id,
            access_domain_id=domain,
        )
        new_writer = ClosedRealIngressWriter(
            db_path=self.db_path,
            capability=ingress_capability,
            policy=new_policy,
            ingress_channel="synthetic-fixture-test",
        )
        receipt = new_writer.write_source(
            context=create_operation_context(
                principal=principal,
                operation_class=OperationClass.SOURCE_WRITE,
            ),
            source_id="fresh-source",
            content="synthetic fresh writer fixture",
            metadata=IngressIdentityMetadata(access_domain_id=domain),
        )
        self.assertEqual(receipt.source_id, "fresh-source")


if __name__ == "__main__":
    unittest.main()
