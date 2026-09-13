from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from _trusted_test_support import (
    trusted_test_closed_real_ingress_capability,
    trusted_test_closed_real_source_origin_capability,
    trusted_test_source_origin_provenance,
    trusted_test_closed_real_normal_read_capability,
    trusted_test_closed_real_stop_use_capability,
    trusted_test_principal_issuer,
    trusted_test_real_store_bootstrap_capability,
    trusted_test_single_owner_real_ingress_policy,
    trusted_test_single_owner_real_normal_read_policy,
    trusted_test_single_owner_real_stop_use_policy,
)
from home_memory_core.identity_namespaces import AccessDomainId
from home_memory_core.ingress_identity import IngressIdentityMetadata
from home_memory_core.operation_identity import (
    AuthenticationBoundaryError,
    OperationClass,
    PrincipalId,
    create_operation_context,
)
from home_memory_core.real_authority_ordering import RealStoreLifecycleError
from home_memory_core.real_ingress import (
    ClosedRealIngressWriter,
    initialize_closed_real_ingress_schema,
)
from home_memory_core.real_normal_read import (
    ClosedRealNormalReadExerciseCapability,
    ClosedRealNormalReader,
    RealNormalReadAuthorizationError,
    RealNormalReadDisabledError,
    RealNormalReadIntegrityError,
    RealNormalReadReceipt,
    RealNormalReadUnavailableError,
    SingleOwnerRealNormalReadPolicy,
)
from home_memory_core.real_source_origin import initialize_closed_real_source_origin_schema
from home_memory_core.real_stop_use import (
    ClosedRealStopUseWriter,
    StopUseReasonCode,
    initialize_closed_real_stop_use_schema,
)
from home_memory_core.store_domain import (
    create_empty_real_store,
    destroy_real_store,
)


class ClosedRealNormalReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "real.sqlite3"
        self.bootstrap = trusted_test_real_store_bootstrap_capability()
        create_empty_real_store(db_path=self.db_path, capability=self.bootstrap)

        self.ingress_capability = trusted_test_closed_real_ingress_capability()
        initialize_closed_real_ingress_schema(
            db_path=self.db_path,
            capability=self.ingress_capability,
        )
        self.stop_use_capability = trusted_test_closed_real_stop_use_capability()
        initialize_closed_real_stop_use_schema(
            db_path=self.db_path,
            capability=self.stop_use_capability,
        )
        initialize_closed_real_source_origin_schema(
            db_path=self.db_path,
            capability=trusted_test_closed_real_source_origin_capability(),
        )

        self.owner_id = PrincipalId("owner-vivi")
        self.other_id = PrincipalId("other-principal")
        issuer = trusted_test_principal_issuer()
        self.owner = issuer.issue(
            principal_id=self.owner_id,
            principal_kind="local_owner",
        )
        self.other = issuer.issue(
            principal_id=self.other_id,
            principal_kind="local_owner",
        )
        self.domain = AccessDomainId("owner-private-domain")
        self.other_domain = AccessDomainId("other-domain")

        ingress_policy = trusted_test_single_owner_real_ingress_policy(
            policy_id="single-owner-ingress-v0.1",
            owner_principal_id=self.owner_id,
            access_domain_id=self.domain,
        )
        self.ingress_writer = ClosedRealIngressWriter(
            db_path=self.db_path,
            capability=self.ingress_capability,
            policy=ingress_policy,
            ingress_channel="synthetic-fixture-test",
        )

        stop_policy = trusted_test_single_owner_real_stop_use_policy(
            policy_id="single-owner-stop-use-v0.1",
            owner_principal_id=self.owner_id,
            access_domain_id=self.domain,
        )
        self.stop_writer = ClosedRealStopUseWriter(
            db_path=self.db_path,
            capability=self.stop_use_capability,
            policy=stop_policy,
        )

        self.read_capability = trusted_test_closed_real_normal_read_capability()
        read_policy = trusted_test_single_owner_real_normal_read_policy(
            policy_id="single-owner-normal-read-v0.1",
            owner_principal_id=self.owner_id,
            access_domain_id=self.domain,
        )
        self.reader = ClosedRealNormalReader(
            db_path=self.db_path,
            capability=self.read_capability,
            policy=read_policy,
        )
        self.content = "synthetic private memory payload"
        self._write_source("source-a", self.content, self.domain)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _context(self, operation_class: OperationClass, *, principal=None):
        return create_operation_context(
            principal=principal or self.owner,
            operation_class=operation_class,
        )

    def _write_source(
        self,
        source_id: str,
        content: str,
        domain: AccessDomainId,
    ) -> None:
        if domain == self.domain:
            writer = self.ingress_writer
        else:
            policy = trusted_test_single_owner_real_ingress_policy(
                policy_id=f"ingress-{domain.value}",
                owner_principal_id=self.owner_id,
                access_domain_id=domain,
            )
            writer = ClosedRealIngressWriter(
                db_path=self.db_path,
                capability=self.ingress_capability,
                policy=policy,
                ingress_channel="synthetic-fixture-test",
            )
        writer.write_source(
            context=self._context(OperationClass.SOURCE_WRITE),
            source_id=source_id,
            content=content,
            metadata=IngressIdentityMetadata(access_domain_id=domain),
            provenance=trusted_test_source_origin_provenance(
                external_object_key=source_id,
            ),
        )

    def _suppress(self, source_id: str) -> None:
        self.stop_writer.suppress_source(
            context=self._context(OperationClass.SOURCE_SUPPRESS),
            source_id=source_id,
            reason_code=StopUseReasonCode.TEST_FIXTURE,
        )

    def test_capability_cannot_be_caller_minted(self) -> None:
        with self.assertRaises(RealNormalReadDisabledError):
            ClosedRealNormalReadExerciseCapability(_marker=object())

    def test_policy_cannot_be_caller_minted(self) -> None:
        from home_memory_core.identity_namespaces import (
            PerspectiveInstanceId,
            PerspectiveOwnerId,
        )

        with self.assertRaises(RealNormalReadAuthorizationError):
            SingleOwnerRealNormalReadPolicy(
                policy_id="fake",
                owner_principal_id=self.owner_id,
                access_domain_id=self.domain,
                perspective_owner=PerspectiveOwnerId("owner"),
                perspective_instance=PerspectiveInstanceId("owner-instance"),
                _marker=object(),
            )

    def test_authorized_owner_reads_current_unsuppressed_source(self) -> None:
        result = self.reader.read_source(
            context=self._context(OperationClass.NORMAL_READ),
            source_id="source-a",
        )
        self.assertEqual(result.source_id, "source-a")
        self.assertEqual(result.content, self.content)
        self.assertEqual(len(result.content_sha256), 64)
        self.assertEqual(result.receipt.access_domain_id, self.domain)
        self.assertEqual(result.receipt.authority, "none")

    def test_wrong_principal_and_missing_source_have_same_external_denial(self) -> None:
        failures = []
        for context, source_id in (
            (self._context(OperationClass.NORMAL_READ, principal=self.other), "source-a"),
            (self._context(OperationClass.NORMAL_READ), "missing-source"),
        ):
            with self.assertRaises(RealNormalReadUnavailableError) as captured:
                self.reader.read_source(context=context, source_id=source_id)
            failures.append(str(captured.exception))
        self.assertEqual(failures, ["normal read unavailable"] * 2)

    def test_source_in_other_domain_is_unavailable(self) -> None:
        self._write_source("source-other", "other domain payload", self.other_domain)
        with self.assertRaisesRegex(
            RealNormalReadUnavailableError,
            "^normal read unavailable$",
        ):
            self.reader.read_source(
                context=self._context(OperationClass.NORMAL_READ),
                source_id="source-other",
            )

    def test_suppressed_source_is_unavailable_without_payload_in_error(self) -> None:
        self._suppress("source-a")
        with self.assertRaises(RealNormalReadUnavailableError) as captured:
            self.reader.read_source(
                context=self._context(OperationClass.NORMAL_READ),
                source_id="source-a",
            )
        self.assertEqual(str(captured.exception), "normal read unavailable")
        self.assertNotIn(self.content, str(captured.exception))

    def test_same_reader_rechecks_persisted_stop_use_after_prior_success(self) -> None:
        first = self.reader.read_source(
            context=self._context(OperationClass.NORMAL_READ),
            source_id="source-a",
        )
        self.assertEqual(first.content, self.content)
        self._suppress("source-a")
        with self.assertRaises(RealNormalReadUnavailableError):
            self.reader.read_source(
                context=self._context(OperationClass.NORMAL_READ),
                source_id="source-a",
            )

    def test_audit_or_delivery_context_cannot_be_reused_for_normal_read(self) -> None:
        for operation_class in (
            OperationClass.AUDIT_READ,
            OperationClass.MEMORY_DELIVER,
        ):
            with self.assertRaises(AuthenticationBoundaryError):
                self.reader.read_source(
                    context=self._context(operation_class),
                    source_id="source-a",
                )

    def test_receipt_is_not_reusable_as_operation_authority(self) -> None:
        result = self.reader.read_source(
            context=self._context(OperationClass.NORMAL_READ),
            source_id="source-a",
        )
        self.assertIsInstance(result.receipt, RealNormalReadReceipt)
        with self.assertRaises(AuthenticationBoundaryError):
            self.reader.read_source(
                context=result.receipt,
                source_id="source-a",
            )

    def test_payload_hash_tampering_fails_closed(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "UPDATE real_sources SET content = ? WHERE source_id = ?",
                ("tampered payload", "source-a"),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(RealNormalReadIntegrityError):
            self.reader.read_source(
                context=self._context(OperationClass.NORMAL_READ),
                source_id="source-a",
            )

    def test_missing_stop_use_schema_fails_closed(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("DROP TRIGGER real_source_suppressions_no_update")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(RealNormalReadIntegrityError):
            self.reader.read_source(
                context=self._context(OperationClass.NORMAL_READ),
                source_id="source-a",
            )

    def test_reader_generation_becomes_stale_after_destroy_and_rebootstrap(self) -> None:
        destroy_real_store(
            db_path=self.db_path,
            capability=self.bootstrap,
        )
        create_empty_real_store(db_path=self.db_path, capability=self.bootstrap)
        initialize_closed_real_ingress_schema(
            db_path=self.db_path,
            capability=self.ingress_capability,
        )
        initialize_closed_real_stop_use_schema(
            db_path=self.db_path,
            capability=self.stop_use_capability,
        )
        initialize_closed_real_source_origin_schema(
            db_path=self.db_path,
            capability=trusted_test_closed_real_source_origin_capability(),
        )

        with self.assertRaises(RealStoreLifecycleError):
            self.reader.read_source(
                context=self._context(OperationClass.NORMAL_READ),
                source_id="source-a",
            )

    def test_normal_reader_uses_query_only_sqlite_connection(self) -> None:
        # This asserts the implementation's physical read-only intent at the
        # SQLite-connection level rather than relying only on code convention.
        original_connect = sqlite3.connect
        observed = []

        class QueryOnlyProbe:
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def execute(self, sql, parameters=()):
                result = self._inner.execute(sql, parameters)
                if sql.strip().upper() == "BEGIN":
                    value = self._inner.execute("PRAGMA query_only").fetchone()[0]
                    observed.append(value)
                return result

            @property
            def in_transaction(self):
                return self._inner.in_transaction

            def close(self):
                return self._inner.close()

        def probed_connect(*args, **kwargs):
            return QueryOnlyProbe(original_connect(*args, **kwargs))

        from unittest.mock import patch

        with patch("home_memory_core.real_normal_read.sqlite3.connect", probed_connect):
            result = self.reader.read_source(
                context=self._context(OperationClass.NORMAL_READ),
                source_id="source-a",
            )
        self.assertEqual(result.content, self.content)
        self.assertEqual(observed, [1])

    def test_normal_read_does_not_add_or_mutate_persisted_rows(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            before = {
                "sources": connection.execute(
                    "SELECT COUNT(*) FROM real_sources"
                ).fetchone()[0],
                "suppressions": connection.execute(
                    "SELECT COUNT(*) FROM real_source_suppressions"
                ).fetchone()[0],
            }
        finally:
            connection.close()

        self.reader.read_source(
            context=self._context(OperationClass.NORMAL_READ),
            source_id="source-a",
        )

        connection = sqlite3.connect(self.db_path)
        try:
            after = {
                "sources": connection.execute(
                    "SELECT COUNT(*) FROM real_sources"
                ).fetchone()[0],
                "suppressions": connection.execute(
                    "SELECT COUNT(*) FROM real_source_suppressions"
                ).fetchone()[0],
            }
        finally:
            connection.close()
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
