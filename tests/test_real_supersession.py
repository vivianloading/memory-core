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
    trusted_test_closed_real_supersession_capability,
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
    ClosedRealRelationshipWriter,
    RealRelationshipAuthorizationError,
    RealRelationshipIdentity,
    RealRelationshipIntegrityError,
    initialize_closed_real_relationship_schema,
)
from home_memory_core.real_supersession import (
    ClosedRealSupersessionExerciseCapability,
    ClosedRealSupersessionWriter,
    RealSupersessionDisabledError,
    RealSupersessionIntegrityError,
    initialize_closed_real_supersession_schema,
)
from home_memory_core.real_source_origin import initialize_closed_real_source_origin_schema
from home_memory_core.real_stop_use import initialize_closed_real_stop_use_schema
from home_memory_core.store_domain import create_empty_real_store


class ClosedRealSupersessionWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "real.sqlite3"

        create_empty_real_store(
            db_path=self.db_path,
            capability=trusted_test_real_store_bootstrap_capability(),
        )
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
        self.relationship_capability = trusted_test_closed_real_relationship_capability()
        initialize_closed_real_relationship_schema(
            db_path=self.db_path,
            ingress_capability=self.ingress_capability,
            relationship_capability=self.relationship_capability,
        )
        self.supersession_capability = trusted_test_closed_real_supersession_capability()
        initialize_closed_real_supersession_schema(
            db_path=self.db_path,
            relationship_capability=self.relationship_capability,
            supersession_capability=self.supersession_capability,
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
        self.identity = RealRelationshipIdentity(
            access_domain_id=self.domain,
            perspective_owner=PerspectiveOwnerId("owner"),
            perspective_instance=PerspectiveInstanceId("owner-instance"),
            about_subject=SubjectId("subject"),
        )

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
        self.relationship_writer = ClosedRealRelationshipWriter(
            db_path=self.db_path,
            capability=self.relationship_capability,
            policy=relationship_policy,
        )
        self.writer = ClosedRealSupersessionWriter(
            db_path=self.db_path,
            capability=self.supersession_capability,
            relationship_capability=self.relationship_capability,
            policy=relationship_policy,
        )

        self.source_content = "alpha evidence span omega"
        self.reason_content = "new synthetic evidence changed the interpretation"
        self._write_source("source-a", self.source_content, self.domain)
        self._write_source("source-reason", self.reason_content, self.domain)
        for interpretation_id in ("a", "b", "c", "d"):
            self._write_interpretation(interpretation_id)
        self._create_thread("thread-a")
        for interpretation_id in ("a", "b", "c", "d"):
            self._admit("thread-a", interpretation_id)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _context(self, operation_class: OperationClass, *, principal=None):
        return create_operation_context(
            principal=principal or self.owner,
            operation_class=operation_class,
        )

    def _evidence(self, source_id: str, content: str, start=0, end=None):
        end = len(content) if end is None else end
        return EvidenceRef(
            source_id=source_id,
            source_sha256=sha256(content.encode("utf-8")).hexdigest(),
            start_char=start,
            end_char=end,
        )

    def _write_source(self, source_id: str, content: str, domain: AccessDomainId):
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
        return writer.write_source(
            context=self._context(OperationClass.SOURCE_WRITE),
            source_id=source_id,
            content=content,
            metadata=IngressIdentityMetadata(access_domain_id=domain),
            provenance=trusted_test_source_origin_provenance(
                external_object_key=source_id,
            ),
        )

    def _write_interpretation(self, interpretation_id: str):
        return self.relationship_writer.write_interpretation(
            context=self._context(OperationClass.INTERPRETATION_WRITE),
            interpretation_id=interpretation_id,
            text=f"synthetic interpretation {interpretation_id}",
            identity=self.identity,
            evidence=(self._evidence("source-a", self.source_content, 6, 19),),
        )

    def _create_thread(self, thread_id: str):
        return self.relationship_writer.create_thread(
            context=self._context(OperationClass.THREAD_CREATE),
            thread_id=thread_id,
            question=f"synthetic question for {thread_id}?",
            identity=self.identity,
        )

    def _admit(self, thread_id: str, interpretation_id: str):
        return self.relationship_writer.admit_interpretation(
            context=self._context(OperationClass.THREAD_ADMIT),
            admission_id=f"admit-{thread_id}-{interpretation_id}",
            thread_id=thread_id,
            interpretation_id=interpretation_id,
        )

    def _reason(self):
        return (self._evidence("source-reason", self.reason_content),)

    def _write_sup(self, previous: str, new: str, *, sid=None, reason=None, principal=None):
        return self.writer.write_supersession(
            context=self._context(
                OperationClass.SUPERSESSION_WRITE,
                principal=principal,
            ),
            supersession_id=sid or f"sup-{previous}-{new}",
            previous_interpretation_id=previous,
            new_interpretation_id=new,
            reason_evidence=reason or self._reason(),
        )

    def _raw_parent_values(self, sid: str, previous: str, new: str, thread_id="thread-a"):
        return (
            sid,
            previous,
            new,
            thread_id,
            self.identity.perspective_owner.value,
            self.identity.perspective_instance.value,
            self.identity.about_subject.value,
            self.domain.value,
            self.owner_id.value,
            "local_owner",
            "synthetic-test-authn",
            f"raw-operation-{sid}",
            "2026-09-13T00:00:00Z",
            "single-owner-relationship-v0.1",
        )

    def _raw_insert_reason(self, connection, sid: str, *, source_id="source-reason", content=None, domain=None):
        content = self.reason_content if content is None else content
        domain = self.domain if domain is None else domain
        connection.execute(
            """
            INSERT INTO real_supersession_reason_evidence (
                supersession_id, position, source_id, source_sha256,
                start_char, end_char, access_domain_id
            ) VALUES (?, 0, ?, ?, 0, ?, ?)
            """,
            (
                sid,
                source_id,
                sha256(content.encode("utf-8")).hexdigest(),
                len(content),
                domain.value,
            ),
        )

    def _raw_insert_parent(self, connection, values):
        connection.execute(
            """
            INSERT INTO real_supersessions (
                supersession_id, previous_interpretation_id,
                new_interpretation_id, thread_id,
                perspective_owner_id, perspective_instance_id,
                about_subject_id, access_domain_id,
                created_by_principal_id, created_by_principal_kind,
                created_by_trust_source, operation_id,
                recorded_at_utc, write_policy_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )

    def test_supersession_capability_cannot_be_caller_minted(self) -> None:
        with self.assertRaises(RealSupersessionDisabledError):
            ClosedRealSupersessionExerciseCapability(_marker=object())

    def test_supersession_schema_requires_relationship_schema(self) -> None:
        other_db = self.root / "not-ready.sqlite3"
        create_empty_real_store(
            db_path=other_db,
            capability=trusted_test_real_store_bootstrap_capability(),
        )
        with self.assertRaises(RealRelationshipIntegrityError):
            initialize_closed_real_supersession_schema(
                db_path=other_db,
                relationship_capability=self.relationship_capability,
                supersession_capability=self.supersession_capability,
            )

    def test_valid_supersession_persists_same_thread_domain_and_reason(self) -> None:
        receipt = self._write_sup("a", "b")
        self.assertEqual(receipt.authority, "none")
        self.assertEqual(receipt.thread_id, "thread-a")
        self.assertEqual(receipt.access_domain_id, self.domain)
        connection = sqlite3.connect(self.db_path)
        try:
            parent = connection.execute(
                "SELECT previous_interpretation_id, new_interpretation_id, access_domain_id FROM real_supersessions"
            ).fetchone()
            reason = connection.execute(
                "SELECT source_id, access_domain_id FROM real_supersession_reason_evidence"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(parent, ("a", "b", self.domain.value))
        self.assertEqual(reason, ("source-reason", self.domain.value))

    def test_wrong_principal_cannot_supersede_matching_endpoints(self) -> None:
        with self.assertRaises(RealRelationshipAuthorizationError):
            self._write_sup("a", "b", principal=self.other)

    def test_wrong_operation_class_cannot_be_reused(self) -> None:
        with self.assertRaises(AuthenticationBoundaryError):
            self.writer.write_supersession(
                context=self._context(OperationClass.THREAD_ADMIT),
                supersession_id="wrong-op",
                previous_interpretation_id="a",
                new_interpretation_id="b",
                reason_evidence=self._reason(),
            )

    def test_endpoint_must_already_be_admitted(self) -> None:
        self._write_interpretation("unadmitted")
        with self.assertRaises(RealSupersessionIntegrityError):
            self._write_sup("a", "unadmitted")

    def test_supersession_cannot_cross_threads(self) -> None:
        self._write_interpretation("other-thread")
        self._create_thread("thread-b")
        self._admit("thread-b", "other-thread")
        with self.assertRaises(RealSupersessionIntegrityError):
            self._write_sup("a", "other-thread")

    def test_reason_evidence_cannot_borrow_other_domain_source(self) -> None:
        content = "private reason from other domain"
        self._write_source("other-reason", content, self.other_domain)
        with self.assertRaises(RealRelationshipAuthorizationError):
            self._write_sup(
                "a",
                "b",
                sid="cross-domain-reason",
                reason=(self._evidence("other-reason", content),),
            )

    def test_reason_evidence_hash_range_and_persisted_content_are_revalidated(self) -> None:
        wrong_hash = EvidenceRef(
            source_id="source-reason",
            source_sha256="0" * 64,
            start_char=0,
            end_char=len(self.reason_content),
        )
        with self.assertRaises(RealSupersessionIntegrityError):
            self._write_sup("a", "b", sid="wrong-hash", reason=(wrong_hash,))

        out_of_range = self._evidence(
            "source-reason",
            self.reason_content,
            0,
            len(self.reason_content) + 5,
        )
        with self.assertRaises(RealSupersessionIntegrityError):
            self._write_sup("a", "b", sid="wrong-range", reason=(out_of_range,))

        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "UPDATE real_sources SET content='tampered' WHERE source_id='source-reason'"
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(RealSupersessionIntegrityError):
            self._write_sup("a", "b", sid="tampered-reason")

    def test_direct_fork_is_allowed(self) -> None:
        self._write_sup("a", "b")
        self._write_sup("a", "c")
        connection = sqlite3.connect(self.db_path)
        try:
            edges = set(
                connection.execute(
                    "SELECT previous_interpretation_id, new_interpretation_id FROM real_supersessions"
                ).fetchall()
            )
        finally:
            connection.close()
        self.assertEqual(edges, {("a", "b"), ("a", "c")})

    def test_application_rejects_implicit_reconvergence(self) -> None:
        self._write_sup("a", "b")
        self._write_sup("a", "c")
        self._write_sup("b", "d")
        with self.assertRaises(RealSupersessionIntegrityError):
            self._write_sup("c", "d")

    def test_application_rejects_cycle(self) -> None:
        self._write_sup("a", "b")
        self._write_sup("b", "c")
        with self.assertRaises(RealSupersessionIntegrityError):
            self._write_sup("c", "a")

    def test_raw_sql_cannot_create_second_parent_for_target(self) -> None:
        self._write_sup("a", "b")
        self._write_sup("b", "d")
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute("BEGIN")
            self._raw_insert_reason(connection, "raw-second-parent")
            with self.assertRaises(sqlite3.IntegrityError):
                self._raw_insert_parent(
                    connection,
                    self._raw_parent_values("raw-second-parent", "c", "d"),
                )
            connection.rollback()
        finally:
            connection.close()

    def test_raw_sql_cycle_is_blocked_by_storage_trigger(self) -> None:
        self._write_sup("a", "b")
        self._write_sup("b", "c")
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute("BEGIN")
            self._raw_insert_reason(connection, "raw-cycle")
            with self.assertRaises(sqlite3.IntegrityError):
                self._raw_insert_parent(
                    connection,
                    self._raw_parent_values("raw-cycle", "c", "a"),
                )
            connection.rollback()
        finally:
            connection.close()

    def test_raw_sql_cannot_cross_thread_membership_boundary(self) -> None:
        self._write_interpretation("other-thread")
        self._create_thread("thread-b")
        self._admit("thread-b", "other-thread")
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute("BEGIN")
            self._raw_insert_reason(connection, "raw-cross-thread")
            with self.assertRaises(sqlite3.IntegrityError):
                self._raw_insert_parent(
                    connection,
                    self._raw_parent_values(
                        "raw-cross-thread",
                        "a",
                        "other-thread",
                        thread_id="thread-a",
                    ),
                )
            connection.rollback()
        finally:
            connection.close()

    def test_raw_sql_cannot_impersonate_endpoint_identity_metadata(self) -> None:
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute("BEGIN")
            self._raw_insert_reason(connection, "raw-fake-identity")
            values = list(self._raw_parent_values("raw-fake-identity", "a", "b"))
            values[4] = "fake-owner"
            with self.assertRaises(sqlite3.IntegrityError):
                self._raw_insert_parent(connection, tuple(values))
            connection.rollback()
        finally:
            connection.close()

    def test_raw_sql_cross_domain_reason_evidence_is_blocked(self) -> None:
        content = "other-domain reason"
        self._write_source("other-reason", content, self.other_domain)
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute("BEGIN")
            with self.assertRaises(sqlite3.IntegrityError):
                self._raw_insert_reason(
                    connection,
                    "raw-cross-domain-reason",
                    source_id="other-reason",
                    content=content,
                    domain=self.domain,
                )
            connection.rollback()
        finally:
            connection.close()

    def test_raw_sql_reasonless_supersession_is_blocked(self) -> None:
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                self._raw_insert_parent(
                    connection,
                    self._raw_parent_values("raw-no-reason", "a", "b"),
                )
        finally:
            connection.close()

    def test_raw_sql_cannot_delete_last_reason_evidence(self) -> None:
        self._write_sup("a", "b")
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM real_supersession_reason_evidence WHERE supersession_id='sup-a-b'"
                )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
