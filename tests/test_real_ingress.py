import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from home_memory_core.identity_namespaces import (
    AccessDomainId,
    PerspectiveInstanceId,
    PerspectiveOwnerId,
    SourceAuthorRef,
    SubjectId,
)
from home_memory_core.ingress_identity import IngressIdentityMetadata
from home_memory_core.interpretation import SYNTHETIC_UNATTRIBUTED_INSTANCE_ID
from home_memory_core.operation_identity import (
    AuthenticationBoundaryError,
    OperationClass,
    PrincipalId,
    create_operation_context,
)
from home_memory_core.real_ingress import (
    ClosedRealIngressExerciseCapability,
    ClosedRealIngressWriter,
    RealIngressAuthorizationError,
    RealIngressDisabledError,
    RealIngressIntegrityError,
    SingleOwnerRealIngressWritePolicy,
    initialize_closed_real_ingress_schema,
)
from home_memory_core.store_domain import create_empty_real_store
from _trusted_test_support import (
    trusted_test_closed_real_ingress_capability,
    trusted_test_principal_issuer,
    trusted_test_real_store_bootstrap_capability,
    trusted_test_single_owner_real_ingress_policy,
)


class ClosedRealIngressTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_directory.name)
        self.db_path = self.root / "real.sqlite3"

        bootstrap = trusted_test_real_store_bootstrap_capability()
        create_empty_real_store(db_path=self.db_path, capability=bootstrap)

        self.exercise_capability = trusted_test_closed_real_ingress_capability()
        initialize_closed_real_ingress_schema(
            db_path=self.db_path,
            capability=self.exercise_capability,
        )

        issuer = trusted_test_principal_issuer()
        self.owner_id = PrincipalId("owner-vivi")
        self.other_id = PrincipalId("other-principal")
        self.owner = issuer.issue(
            principal_id=self.owner_id,
            principal_kind="local_owner",
        )
        self.other = issuer.issue(
            principal_id=self.other_id,
            principal_kind="local_owner",
        )
        self.domain = AccessDomainId("owner-private-domain")
        self.policy = trusted_test_single_owner_real_ingress_policy(
            policy_id="single-owner-write-v0.1",
            owner_principal_id=self.owner_id,
            access_domain_id=self.domain,
        )
        self.writer = ClosedRealIngressWriter(
            db_path=self.db_path,
            capability=self.exercise_capability,
            policy=self.policy,
            ingress_channel="synthetic-fixture-test",
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def _context(self, *, principal=None, operation_class=OperationClass.SOURCE_WRITE):
        return create_operation_context(
            principal=principal or self.owner,
            operation_class=operation_class,
        )

    def _metadata(self, *, domain=None) -> IngressIdentityMetadata:
        return IngressIdentityMetadata(
            access_domain_id=domain or self.domain,
            asserted_author=SourceAuthorRef("asserted-author"),
            subjects=(SubjectId("subject-1"), SubjectId("subject-2")),
            perspective_owner=PerspectiveOwnerId("perspective-owner"),
            perspective_instance=PerspectiveInstanceId("perspective-instance"),
        )

    def test_caller_cannot_mint_closed_real_ingress_capability(self) -> None:
        with self.assertRaises(RealIngressDisabledError):
            ClosedRealIngressExerciseCapability(_marker=object())

    def test_caller_cannot_mint_allowing_write_policy(self) -> None:
        with self.assertRaises(RealIngressAuthorizationError):
            SingleOwnerRealIngressWritePolicy(
                policy_id="caller-policy",
                owner_principal_id=self.owner_id,
                access_domain_id=self.domain,
                _marker=object(),
            )

    def test_schema_initialization_refuses_synthetic_store(self) -> None:
        synthetic_path = self.root / "synthetic.sqlite3"
        from home_memory_core.storage import MemoryStore

        MemoryStore(synthetic_path).initialize()
        with self.assertRaises(Exception):
            initialize_closed_real_ingress_schema(
                db_path=synthetic_path,
                capability=self.exercise_capability,
            )

    def test_authorized_source_write_persists_operator_provenance(self) -> None:
        context = self._context()
        receipt = self.writer.write_source(
            context=context,
            source_id="real-fixture-source-1",
            content="synthetic fixture content only",
            metadata=self._metadata(),
        )

        self.assertEqual(receipt.authority, "none")
        self.assertEqual(receipt.operation_id, context.operation_id)
        self.assertEqual(receipt.ingested_by_principal_id, self.owner_id)
        self.assertEqual(receipt.access_domain_id, self.domain)
        self.assertEqual(receipt.policy_id, self.policy.policy_id)
        self.assertTrue(receipt.recorded_at_utc.endswith("Z"))

        connection = sqlite3.connect(self.db_path)
        try:
            row = connection.execute(
                """
                SELECT
                    content,
                    asserted_author_ref,
                    access_domain_id,
                    ingested_by_principal_id,
                    ingested_by_principal_kind,
                    ingested_by_trust_source,
                    ingress_operation_id,
                    ingress_channel,
                    write_policy_id
                FROM real_sources
                WHERE source_id = ?
                """,
                ("real-fixture-source-1",),
            ).fetchone()
            subjects = connection.execute(
                """
                SELECT position, subject_id
                FROM real_source_subjects
                WHERE source_id = ?
                ORDER BY position
                """,
                ("real-fixture-source-1",),
            ).fetchall()
        finally:
            connection.close()

        self.assertEqual(
            row,
            (
                "synthetic fixture content only",
                "asserted-author",
                "owner-private-domain",
                "owner-vivi",
                "local_owner",
                "synthetic-test-authn",
                context.operation_id,
                "synthetic-fixture-test",
                "single-owner-write-v0.1",
            ),
        )
        self.assertEqual(subjects, [(0, "subject-1"), (1, "subject-2")])

    def test_asserted_author_does_not_authorize_another_principal(self) -> None:
        context = self._context(principal=self.other)
        metadata = IngressIdentityMetadata(
            access_domain_id=self.domain,
            asserted_author=SourceAuthorRef(self.owner_id.value),
        )

        with self.assertRaises(RealIngressAuthorizationError):
            self.writer.write_source(
                context=context,
                source_id="impersonation-attempt",
                content="synthetic fixture",
                metadata=metadata,
            )

        self._assert_source_absent("impersonation-attempt")

    def test_wrong_access_domain_denies_without_partial_write(self) -> None:
        with self.assertRaises(RealIngressAuthorizationError):
            self.writer.write_source(
                context=self._context(),
                source_id="wrong-domain",
                content="synthetic fixture",
                metadata=self._metadata(domain=AccessDomainId("other-domain")),
            )

        self._assert_source_absent("wrong-domain")

    def test_wrong_operation_class_cannot_reuse_trusted_context(self) -> None:
        with self.assertRaises(AuthenticationBoundaryError):
            self.writer.write_source(
                context=self._context(operation_class=OperationClass.DISCOVERY_READ),
                source_id="wrong-operation",
                content="synthetic fixture",
                metadata=self._metadata(),
            )

        self._assert_source_absent("wrong-operation")

    def test_synthetic_sentinel_is_rejected_at_api_boundary(self) -> None:
        metadata = IngressIdentityMetadata(
            access_domain_id=self.domain,
            perspective_owner=PerspectiveOwnerId("owner"),
            perspective_instance=PerspectiveInstanceId(
                SYNTHETIC_UNATTRIBUTED_INSTANCE_ID
            ),
        )
        with self.assertRaises(RealIngressIntegrityError):
            self.writer.write_source(
                context=self._context(),
                source_id="sentinel-api",
                content="synthetic fixture",
                metadata=metadata,
            )

        self._assert_source_absent("sentinel-api")

    def test_storage_rejects_sentinel_even_via_raw_insert(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO real_sources (
                        source_id,
                        content,
                        content_sha256,
                        asserted_author_ref,
                        access_domain_id,
                        perspective_owner_id,
                        perspective_instance_id,
                        ingested_by_principal_id,
                        ingested_by_principal_kind,
                        ingested_by_trust_source,
                        ingress_operation_id,
                        ingress_channel,
                        recorded_at_utc,
                        write_policy_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "sentinel-storage",
                        "fixture",
                        "0" * 64,
                        None,
                        "owner-private-domain",
                        None,
                        None,
                        SYNTHETIC_UNATTRIBUTED_INSTANCE_ID,
                        "local_owner",
                        "synthetic-test-authn",
                        "operation-raw",
                        "raw-test",
                        "2026-09-13T00:00:00Z",
                        "policy",
                    ),
                )
        finally:
            connection.close()

    def test_missing_schema_fails_closed_without_creating_payload_table(self) -> None:
        other_path = self.root / "real-marker-only.sqlite3"
        bootstrap = trusted_test_real_store_bootstrap_capability()
        create_empty_real_store(db_path=other_path, capability=bootstrap)
        writer = ClosedRealIngressWriter(
            db_path=other_path,
            capability=self.exercise_capability,
            policy=self.policy,
            ingress_channel="synthetic-fixture-test",
        )

        with self.assertRaises(RealIngressIntegrityError):
            writer.write_source(
                context=self._context(),
                source_id="no-schema",
                content="synthetic fixture",
                metadata=self._metadata(),
            )

        connection = sqlite3.connect(other_path)
        try:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='real_sources'"
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNone(table)

    def test_receipt_is_not_reusable_as_an_authorization_context(self) -> None:
        receipt = self.writer.write_source(
            context=self._context(),
            source_id="receipt-source",
            content="synthetic fixture",
            metadata=self._metadata(),
        )

        with self.assertRaises(AuthenticationBoundaryError):
            self.writer.write_source(
                context=receipt,  # type: ignore[arg-type]
                source_id="receipt-replay",
                content="synthetic fixture",
                metadata=self._metadata(),
            )

        self._assert_source_absent("receipt-replay")

    def test_duplicate_source_or_operation_fails_without_partial_subject_rows(self) -> None:
        context = self._context()
        self.writer.write_source(
            context=context,
            source_id="duplicate-source",
            content="synthetic fixture",
            metadata=self._metadata(),
        )

        with self.assertRaises(RealIngressIntegrityError):
            self.writer.write_source(
                context=self._context(),
                source_id="duplicate-source",
                content="different fixture",
                metadata=self._metadata(),
            )

        connection = sqlite3.connect(self.db_path)
        try:
            source_count = connection.execute(
                "SELECT COUNT(*) FROM real_sources WHERE source_id='duplicate-source'"
            ).fetchone()[0]
            subject_count = connection.execute(
                "SELECT COUNT(*) FROM real_source_subjects WHERE source_id='duplicate-source'"
            ).fetchone()[0]
        finally:
            connection.close()

        self.assertEqual(source_count, 1)
        self.assertEqual(subject_count, 2)

    def test_policy_ignores_asserted_author_subject_and_perspective_for_authority(self) -> None:
        metadata = IngressIdentityMetadata(
            access_domain_id=self.domain,
            asserted_author=SourceAuthorRef("someone-else"),
            subjects=(SubjectId("third-party"),),
            perspective_owner=PerspectiveOwnerId("other-perspective-owner"),
            perspective_instance=PerspectiveInstanceId("other-perspective-instance"),
        )
        receipt = self.writer.write_source(
            context=self._context(),
            source_id="metadata-not-authority",
            content="synthetic fixture",
            metadata=metadata,
        )
        self.assertEqual(receipt.ingested_by_principal_id, self.owner_id)

    def _assert_source_absent(self, source_id: str) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM real_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
