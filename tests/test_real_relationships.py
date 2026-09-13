from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
import tempfile
import unittest

from _trusted_test_support import (
    trusted_test_closed_real_ingress_capability,
    trusted_test_closed_real_source_origin_capability,
    trusted_test_source_origin_provenance,
    trusted_test_closed_real_relationship_capability,
    trusted_test_principal_issuer,
    trusted_test_real_store_bootstrap_capability,
    trusted_test_single_owner_real_ingress_policy,
    trusted_test_single_owner_real_relationship_policy,
    trusted_test_closed_real_stop_use_capability,
)
from home_memory_core.evidence import EvidenceRef
from home_memory_core.identity_namespaces import (
    AccessDomainId,
    PerspectiveInstanceId,
    PerspectiveOwnerId,
    SubjectId,
)
from home_memory_core.ingress_identity import IngressIdentityMetadata
from home_memory_core.operation_identity import (
    AuthenticationBoundaryError,
    OperationClass,
    PrincipalId,
    create_operation_context,
)
from home_memory_core.real_ingress import (
    ClosedRealIngressWriter,
    initialize_closed_real_ingress_schema,
)
from home_memory_core.real_relationships import (
    ClosedRealRelationshipExerciseCapability,
    ClosedRealRelationshipWriter,
    RealRelationshipAuthorizationError,
    RealRelationshipDisabledError,
    RealRelationshipIdentity,
    RealRelationshipIntegrityError,
    SingleOwnerRealRelationshipWritePolicy,
    initialize_closed_real_relationship_schema,
)
from home_memory_core.real_source_origin import initialize_closed_real_source_origin_schema
from home_memory_core.real_stop_use import initialize_closed_real_stop_use_schema
from home_memory_core.store_domain import create_empty_real_store


class ClosedRealRelationshipWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "real.sqlite3"
        bootstrap = trusted_test_real_store_bootstrap_capability()
        create_empty_real_store(db_path=self.db_path, capability=bootstrap)

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

        self.relationship_capability = (
            trusted_test_closed_real_relationship_capability()
        )
        initialize_closed_real_relationship_schema(
            db_path=self.db_path,
            ingress_capability=self.ingress_capability,
            relationship_capability=self.relationship_capability,
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
        relationship_policy = trusted_test_single_owner_real_relationship_policy(
            policy_id="single-owner-relationship-v0.1",
            owner_principal_id=self.owner_id,
            access_domain_id=self.domain,
        )
        self.writer = ClosedRealRelationshipWriter(
            db_path=self.db_path,
            capability=self.relationship_capability,
            policy=relationship_policy,
        )
        self.identity = RealRelationshipIdentity(
            access_domain_id=self.domain,
            perspective_owner=PerspectiveOwnerId("owner"),
            perspective_instance=PerspectiveInstanceId("owner-instance"),
            about_subject=SubjectId("subject"),
        )
        self._write_source(
            source_id="source-a",
            content="alpha evidence span omega",
            domain=self.domain,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _context(self, operation_class: OperationClass, *, principal=None):
        return create_operation_context(
            principal=principal or self.owner,
            operation_class=operation_class,
        )

    def _write_source(
        self,
        *,
        source_id: str,
        content: str,
        domain: AccessDomainId,
    ) -> None:
        if domain == self.domain:
            writer = self.ingress_writer
        else:
            policy = trusted_test_single_owner_real_ingress_policy(
                policy_id="other-domain-ingress-v0.1",
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

    def _evidence(self, source_id: str, content: str, start: int, end: int):
        return EvidenceRef(
            source_id=source_id,
            source_sha256=sha256(content.encode("utf-8")).hexdigest(),
            start_char=start,
            end_char=end,
        )

    def _write_interpretation(self, interpretation_id: str = "interpretation-a"):
        content = "alpha evidence span omega"
        return self.writer.write_interpretation(
            context=self._context(OperationClass.INTERPRETATION_WRITE),
            interpretation_id=interpretation_id,
            text="synthetic interpretation",
            identity=self.identity,
            evidence=(self._evidence("source-a", content, 6, 19),),
        )

    def _create_thread(self, thread_id: str = "thread-a"):
        return self.writer.create_thread(
            context=self._context(OperationClass.THREAD_CREATE),
            thread_id=thread_id,
            question="synthetic question?",
            identity=self.identity,
        )

    def test_relationship_capability_cannot_be_caller_minted(self) -> None:
        with self.assertRaises(RealRelationshipDisabledError):
            ClosedRealRelationshipExerciseCapability(_marker=object())

    def test_relationship_policy_cannot_be_caller_minted(self) -> None:
        with self.assertRaises(RealRelationshipAuthorizationError):
            SingleOwnerRealRelationshipWritePolicy(
                policy_id="fake",
                owner_principal_id=self.owner_id,
                access_domain_id=self.domain,
                perspective_owner=PerspectiveOwnerId("owner"),
                perspective_instance=PerspectiveInstanceId("owner-instance"),
                _marker=object(),
            )

    def test_interpretation_persists_only_exact_same_domain_evidence(self) -> None:
        receipt = self._write_interpretation()
        self.assertEqual(receipt.authority, "none")
        self.assertEqual(receipt.access_domain_id, self.domain)

        connection = sqlite3.connect(self.db_path)
        try:
            row = connection.execute(
                """
                SELECT access_domain_id, created_by_principal_id
                FROM real_interpretations
                WHERE interpretation_id='interpretation-a'
                """
            ).fetchone()
            evidence = connection.execute(
                """
                SELECT source_id, source_sha256, start_char, end_char, access_domain_id
                FROM real_interpretation_evidence
                WHERE interpretation_id='interpretation-a'
                """
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row, (self.domain.value, self.owner_id.value))
        self.assertEqual(evidence[0], "source-a")
        self.assertEqual(evidence[2:5], (6, 19, self.domain.value))

    def test_private_other_domain_source_cannot_be_borrowed_as_evidence(self) -> None:
        other_content = "private other-domain evidence"
        self._write_source(
            source_id="source-other",
            content=other_content,
            domain=self.other_domain,
        )
        evidence = self._evidence(
            "source-other",
            other_content,
            0,
            len(other_content),
        )
        with self.assertRaises(RealRelationshipAuthorizationError):
            self.writer.write_interpretation(
                context=self._context(OperationClass.INTERPRETATION_WRITE),
                interpretation_id="cross-domain-interpretation",
                text="should not store",
                identity=self.identity,
                evidence=(evidence,),
            )

        connection = sqlite3.connect(self.db_path)
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM real_interpretations WHERE interpretation_id=?",
                ("cross-domain-interpretation",),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 0)

    def test_wrong_principal_cannot_write_relationship_even_with_matching_metadata(self) -> None:
        content = "alpha evidence span omega"
        with self.assertRaises(RealRelationshipAuthorizationError):
            self.writer.write_interpretation(
                context=self._context(
                    OperationClass.INTERPRETATION_WRITE,
                    principal=self.other,
                ),
                interpretation_id="impersonation-relationship",
                text="metadata does not grant authority",
                identity=self.identity,
                evidence=(self._evidence("source-a", content, 6, 19),),
            )

    def test_wrong_operation_class_cannot_be_reused_for_relationship_write(self) -> None:
        content = "alpha evidence span omega"
        with self.assertRaises(AuthenticationBoundaryError):
            self.writer.write_interpretation(
                context=self._context(OperationClass.THREAD_ADMIT),
                interpretation_id="wrong-operation",
                text="synthetic interpretation",
                identity=self.identity,
                evidence=(self._evidence("source-a", content, 6, 19),),
            )

    def test_evidence_hash_and_offsets_are_revalidated_against_persisted_source(self) -> None:
        content = "alpha evidence span omega"
        wrong_hash = EvidenceRef(
            source_id="source-a",
            source_sha256="0" * 64,
            start_char=6,
            end_char=19,
        )
        with self.assertRaises(RealRelationshipIntegrityError):
            self.writer.write_interpretation(
                context=self._context(OperationClass.INTERPRETATION_WRITE),
                interpretation_id="wrong-hash",
                text="synthetic interpretation",
                identity=self.identity,
                evidence=(wrong_hash,),
            )

        out_of_range = self._evidence("source-a", content, 6, 999)
        with self.assertRaises(RealRelationshipIntegrityError):
            self.writer.write_interpretation(
                context=self._context(OperationClass.INTERPRETATION_WRITE),
                interpretation_id="wrong-range",
                text="synthetic interpretation",
                identity=self.identity,
                evidence=(out_of_range,),
            )


    def test_tampered_source_content_cannot_become_relationship_evidence(self) -> None:
        content = "alpha evidence span omega"
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "UPDATE real_sources SET content=? WHERE source_id='source-a'",
                ("tampered source content",),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(RealRelationshipIntegrityError):
            self.writer.write_interpretation(
                context=self._context(OperationClass.INTERPRETATION_WRITE),
                interpretation_id="tampered-source-interpretation",
                text="synthetic interpretation",
                identity=self.identity,
                evidence=(self._evidence("source-a", content, 6, 19),),
            )

    def test_thread_admission_requires_both_persisted_endpoints_to_match(self) -> None:
        self._write_interpretation()
        self._create_thread()
        receipt = self.writer.admit_interpretation(
            context=self._context(OperationClass.THREAD_ADMIT),
            admission_id="admission-a",
            thread_id="thread-a",
            interpretation_id="interpretation-a",
        )
        self.assertEqual(receipt.relationship_kind, "thread.admit")

        connection = sqlite3.connect(self.db_path)
        try:
            row = connection.execute(
                """
                SELECT access_domain_id, admitted_by_principal_id
                FROM real_thread_memberships
                WHERE admission_id='admission-a'
                """
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row, (self.domain.value, self.owner_id.value))

    def test_thread_admission_rejects_identity_or_domain_mismatch(self) -> None:
        self._write_interpretation()
        mismatched_identity = RealRelationshipIdentity(
            access_domain_id=self.domain,
            perspective_owner=PerspectiveOwnerId("owner"),
            perspective_instance=PerspectiveInstanceId("different-instance"),
            about_subject=SubjectId("subject"),
        )
        mismatched_policy = trusted_test_single_owner_real_relationship_policy(
            policy_id="relationship-policy-mismatch",
            owner_principal_id=self.owner_id,
            access_domain_id=self.domain,
            perspective_owner=mismatched_identity.perspective_owner,
            perspective_instance=mismatched_identity.perspective_instance,
        )
        mismatched_writer = ClosedRealRelationshipWriter(
            db_path=self.db_path,
            capability=self.relationship_capability,
            policy=mismatched_policy,
        )
        mismatched_writer.create_thread(
            context=self._context(OperationClass.THREAD_CREATE),
            thread_id="thread-mismatch",
            question="synthetic question?",
            identity=mismatched_identity,
        )
        with self.assertRaises(RealRelationshipIntegrityError):
            self.writer.admit_interpretation(
                context=self._context(OperationClass.THREAD_ADMIT),
                admission_id="admission-mismatch",
                thread_id="thread-mismatch",
                interpretation_id="interpretation-a",
            )

    def test_storage_foreign_key_rejects_cross_domain_evidence_even_via_raw_insert(self) -> None:
        content = "alpha evidence span omega"
        self._write_interpretation()
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO real_interpretation_evidence (
                        interpretation_id,
                        position,
                        source_id,
                        source_sha256,
                        start_char,
                        end_char,
                        access_domain_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "interpretation-a",
                        99,
                        "source-a",
                        sha256(content.encode("utf-8")).hexdigest(),
                        0,
                        5,
                        self.other_domain.value,
                    ),
                )
        finally:
            connection.close()

    def test_storage_foreign_key_rejects_tampered_admission_metadata(self) -> None:
        self._write_interpretation()
        self._create_thread()
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO real_thread_memberships (
                        admission_id,
                        thread_id,
                        interpretation_id,
                        perspective_owner_id,
                        perspective_instance_id,
                        about_subject_id,
                        access_domain_id,
                        admitted_by_principal_id,
                        admitted_by_principal_kind,
                        admitted_by_trust_source,
                        operation_id,
                        recorded_at_utc,
                        write_policy_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "raw-bad-admission",
                        "thread-a",
                        "interpretation-a",
                        "owner",
                        "owner-instance",
                        "subject",
                        self.other_domain.value,
                        self.owner_id.value,
                        "local_owner",
                        "synthetic-test-authn",
                        "operation-raw-bad",
                        "2026-09-13T00:00:00Z",
                        "raw-policy",
                    ),
                )
        finally:
            connection.close()

    def test_interpretation_cannot_be_admitted_to_multiple_threads(self) -> None:
        self._write_interpretation()
        self._create_thread("thread-a")
        self._create_thread("thread-b")
        self.writer.admit_interpretation(
            context=self._context(OperationClass.THREAD_ADMIT),
            admission_id="admission-a",
            thread_id="thread-a",
            interpretation_id="interpretation-a",
        )
        with self.assertRaises(RealRelationshipIntegrityError):
            self.writer.admit_interpretation(
                context=self._context(OperationClass.THREAD_ADMIT),
                admission_id="admission-b",
                thread_id="thread-b",
                interpretation_id="interpretation-a",
            )

    def test_relationship_schema_requires_initialized_real_ingress_schema(self) -> None:
        other_path = self.root / "marker-only.sqlite3"
        create_empty_real_store(
            db_path=other_path,
            capability=trusted_test_real_store_bootstrap_capability(),
        )
        from home_memory_core.real_ingress import RealIngressIntegrityError

        with self.assertRaises(RealIngressIntegrityError):
            initialize_closed_real_relationship_schema(
                db_path=other_path,
                ingress_capability=self.ingress_capability,
                relationship_capability=self.relationship_capability,
            )

    def test_receipt_is_not_reusable_as_operation_context(self) -> None:
        receipt = self._write_interpretation()
        with self.assertRaises(AuthenticationBoundaryError):
            self.writer.create_thread(
                context=receipt,  # type: ignore[arg-type]
                thread_id="receipt-thread",
                question="should fail",
                identity=self.identity,
            )

    def test_policy_rejects_unbound_derived_perspective_owner(self) -> None:
        unbound = RealRelationshipIdentity(
            access_domain_id=self.domain,
            perspective_owner=PerspectiveOwnerId("lior"),
            perspective_instance=PerspectiveInstanceId("lior-X"),
            about_subject=SubjectId("subject"),
        )
        content = "alpha evidence span omega"
        evidence = EvidenceRef(
            source_id="source-a",
            source_sha256=sha256(content.encode("utf-8")).hexdigest(),
            start_char=0,
            end_char=5,
        )
        with self.assertRaises(RealRelationshipAuthorizationError):
            self.writer.write_interpretation(
                context=self._context(OperationClass.INTERPRETATION_WRITE),
                interpretation_id="unbound-perspective",
                text="synthetic interpretation",
                identity=unbound,
                evidence=(evidence,),
            )

    def test_policy_rejects_unbound_perspective_instance_for_same_owner(self) -> None:
        unbound = RealRelationshipIdentity(
            access_domain_id=self.domain,
            perspective_owner=PerspectiveOwnerId("owner"),
            perspective_instance=PerspectiveInstanceId("different-instance"),
            about_subject=SubjectId("subject"),
        )
        with self.assertRaises(RealRelationshipAuthorizationError):
            self.writer.create_thread(
                context=self._context(OperationClass.THREAD_CREATE),
                thread_id="unbound-thread",
                question="synthetic?",
                identity=unbound,
            )


if __name__ == "__main__":
    unittest.main()
