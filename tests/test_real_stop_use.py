from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch

from _trusted_test_support import (
    trusted_test_closed_real_ingress_capability,
    trusted_test_closed_real_source_origin_capability,
    trusted_test_source_origin_provenance,
    trusted_test_closed_real_relationship_capability,
    trusted_test_closed_real_stop_use_capability,
    trusted_test_closed_real_supersession_capability,
    trusted_test_principal_issuer,
    trusted_test_real_store_bootstrap_capability,
    trusted_test_single_owner_real_ingress_policy,
    trusted_test_single_owner_real_relationship_policy,
    trusted_test_single_owner_real_stop_use_policy,
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
    RealRelationshipIdentity,
    initialize_closed_real_relationship_schema,
)
from home_memory_core.real_source_origin import initialize_closed_real_source_origin_schema
from home_memory_core.real_stop_use import (
    ClosedRealStopUseExerciseCapability,
    ClosedRealStopUseWriter,
    RealStopUseAuthorizationError,
    RealStopUseDisabledError,
    RealStopUseIntegrityError,
    SingleOwnerRealStopUsePolicy,
    StopUseReasonCode,
    initialize_closed_real_stop_use_schema,
)
from home_memory_core.real_supersession import (
    ClosedRealSupersessionWriter,
    initialize_closed_real_supersession_schema,
)
from home_memory_core.real_use_state import (
    RealSourceSuppressedError,
    RealUseStateIntegrityError,
    assert_interpretation_usable,
    assert_source_ids_usable,
)
from home_memory_core.store_domain import create_empty_real_store


class ClosedRealStopUseTests(unittest.TestCase):
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
        self.supersession_writer = ClosedRealSupersessionWriter(
            db_path=self.db_path,
            capability=self.supersession_capability,
            relationship_capability=self.relationship_capability,
            policy=relationship_policy,
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

        self.contents = {
            "source-a": "alpha evidence span omega",
            "source-b": "beta evidence span omega",
            "source-reason": "synthetic reason evidence",
        }
        for source_id, content in self.contents.items():
            self._write_source(source_id, content)

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
        *,
        domain: AccessDomainId | None = None,
    ):
        domain = domain or self.domain
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

    def _evidence(self, source_id: str) -> EvidenceRef:
        content = self.contents[source_id]
        return EvidenceRef(
            source_id=source_id,
            source_sha256=sha256(content.encode("utf-8")).hexdigest(),
            start_char=0,
            end_char=len(content),
        )

    def _interpretation(self, interpretation_id: str, source_id: str):
        return self.relationship_writer.write_interpretation(
            context=self._context(OperationClass.INTERPRETATION_WRITE),
            interpretation_id=interpretation_id,
            text=f"synthetic interpretation {interpretation_id}",
            identity=self.identity,
            evidence=(self._evidence(source_id),),
        )

    def _thread(self, thread_id: str):
        return self.relationship_writer.create_thread(
            context=self._context(OperationClass.THREAD_CREATE),
            thread_id=thread_id,
            question=f"synthetic question {thread_id}?",
            identity=self.identity,
        )

    def _admit(self, thread_id: str, interpretation_id: str):
        return self.relationship_writer.admit_interpretation(
            context=self._context(OperationClass.THREAD_ADMIT),
            admission_id=f"admit-{thread_id}-{interpretation_id}",
            thread_id=thread_id,
            interpretation_id=interpretation_id,
        )

    def _suppress(
        self,
        source_id: str,
        *,
        context=None,
        reason=StopUseReasonCode.TEST_FIXTURE,
    ):
        return self.stop_writer.suppress_source(
            context=context or self._context(OperationClass.SOURCE_SUPPRESS),
            source_id=source_id,
            reason_code=reason,
        )

    def _row_count(self, table: str) -> int:
        connection = sqlite3.connect(self.db_path)
        try:
            return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            connection.close()

    def test_stop_use_capability_cannot_be_caller_minted(self) -> None:
        with self.assertRaises(RealStopUseDisabledError):
            ClosedRealStopUseExerciseCapability(_marker=object())

    def test_stop_use_policy_cannot_be_caller_minted(self) -> None:
        with self.assertRaises(RealStopUseAuthorizationError):
            SingleOwnerRealStopUsePolicy(
                policy_id="fake",
                owner_principal_id=self.owner_id,
                access_domain_id=self.domain,
                _marker=object(),
            )

    def test_authorized_suppression_persists_trusted_provenance_and_no_payload_copy(self) -> None:
        context = self._context(OperationClass.SOURCE_SUPPRESS)
        receipt = self._suppress(
            "source-a",
            context=context,
            reason=StopUseReasonCode.USER_STOP_USE,
        )

        self.assertEqual(receipt.authority, "none")
        self.assertEqual(receipt.operation_id, context.operation_id)
        self.assertEqual(receipt.requested_by_principal_id, self.owner_id)
        self.assertEqual(receipt.status, "suppressed")

        connection = sqlite3.connect(self.db_path)
        try:
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(real_source_suppressions)"
                ).fetchall()
            }
            self.assertNotIn("reason_note", columns)
            row = connection.execute(
                """
                SELECT source_id, access_domain_id, requested_by_principal_id,
                       requested_by_principal_kind, requested_by_trust_source,
                       operation_id, reason_code, policy_id
                FROM real_source_suppressions
                """
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(
            row,
            (
                "source-a",
                self.domain.value,
                self.owner_id.value,
                "local_owner",
                "synthetic-test-authn",
                context.operation_id,
                StopUseReasonCode.USER_STOP_USE.value,
                "single-owner-stop-use-v0.1",
            ),
        )

    def test_wrong_principal_or_domain_cannot_suppress(self) -> None:
        with self.assertRaises(RealStopUseAuthorizationError):
            self._suppress(
                "source-a",
                context=self._context(
                    OperationClass.SOURCE_SUPPRESS,
                    principal=self.other,
                ),
            )
        self.assertEqual(self._row_count("real_source_suppressions"), 0)

        other_content = "other domain synthetic fixture"
        self.contents["source-other"] = other_content
        self._write_source(
            "source-other",
            other_content,
            domain=self.other_domain,
        )
        with self.assertRaises(RealStopUseAuthorizationError):
            self._suppress("source-other")
        self.assertEqual(self._row_count("real_source_suppressions"), 0)

    def test_repeated_suppression_is_idempotent_and_operation_id_is_bound(self) -> None:
        same_context = self._context(OperationClass.SOURCE_SUPPRESS)
        first = self._suppress("source-a", context=same_context)
        retry = self._suppress("source-a", context=same_context)
        self.assertEqual(retry.status, "already_suppressed")
        self.assertEqual(retry.suppression_id, first.suppression_id)
        self.assertEqual(retry.operation_id, first.operation_id)

        later = self._suppress("source-a")
        self.assertEqual(later.status, "already_suppressed")
        self.assertEqual(later.suppression_id, first.suppression_id)
        self.assertEqual(later.operation_id, first.operation_id)
        self.assertEqual(self._row_count("real_source_suppressions"), 1)

        with self.assertRaises(RealStopUseIntegrityError):
            self._suppress("source-b", context=same_context)
        self.assertEqual(self._row_count("real_source_suppressions"), 1)

    def test_suppression_receipt_is_never_an_operation_context(self) -> None:
        receipt = self._suppress("source-a")
        with self.assertRaises(AuthenticationBoundaryError):
            self.stop_writer.suppress_source(
                context=receipt,  # type: ignore[arg-type]
                source_id="source-b",
                reason_code=StopUseReasonCode.TEST_FIXTURE,
            )

    def test_storage_rejects_update_delete_replace_and_null_identity_fields(self) -> None:
        receipt = self._suppress("source-a")
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE real_source_suppressions SET policy_id='changed' "
                    "WHERE suppression_id=?",
                    (receipt.suppression_id,),
                )
            connection.rollback()

            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM real_source_suppressions WHERE suppression_id=?",
                    (receipt.suppression_id,),
                )
            connection.rollback()

            row = connection.execute(
                """
                SELECT source_id, access_domain_id, requested_by_principal_id,
                       requested_by_principal_kind, requested_by_trust_source,
                       operation_id, reason_code, recorded_at_utc, policy_id
                FROM real_source_suppressions
                WHERE suppression_id=?
                """,
                (receipt.suppression_id,),
            ).fetchone()
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT OR REPLACE INTO real_source_suppressions (
                        suppression_id, source_id, access_domain_id,
                        requested_by_principal_id, requested_by_principal_kind,
                        requested_by_trust_source, operation_id, reason_code,
                        recorded_at_utc, policy_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "replacement-id",
                        "source-b",
                        self.domain.value,
                        row[2],
                        row[3],
                        row[4],
                        row[5],
                        row[6],
                        row[7],
                        row[8],
                    ),
                )
            connection.rollback()

            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO real_source_suppressions (
                        suppression_id, source_id, access_domain_id,
                        requested_by_principal_id, requested_by_principal_kind,
                        requested_by_trust_source, operation_id, reason_code,
                        recorded_at_utc, policy_id
                    ) VALUES (NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                    """
                )
            connection.rollback()
        finally:
            connection.close()

        self.assertEqual(self._row_count("real_source_suppressions"), 1)

    def test_damaged_stop_use_schema_fails_closed_instead_of_repairing_empty(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("DROP TRIGGER real_source_suppressions_no_update")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(RealStopUseIntegrityError):
            initialize_closed_real_stop_use_schema(
                db_path=self.db_path,
                capability=self.stop_use_capability,
            )

        with self.assertRaises(RealStopUseIntegrityError):
            self._suppress("source-a")

    def test_interpretation_write_rejects_suppressed_evidence(self) -> None:
        self._suppress("source-a")
        with self.assertRaises(RealSourceSuppressedError):
            self._interpretation("i-blocked", "source-a")
        self.assertEqual(self._row_count("real_interpretations"), 0)

    def test_historical_interpretation_cannot_be_newly_admitted_after_suppression(self) -> None:
        self._interpretation("i-old", "source-a")
        self._thread("thread-new")
        self._suppress("source-a")

        with self.assertRaises(RealSourceSuppressedError):
            self._admit("thread-new", "i-old")
        self.assertEqual(self._row_count("real_thread_memberships"), 0)

    def test_thread_creation_remains_allowed_without_source_dependency(self) -> None:
        self._suppress("source-a")
        receipt = self._thread("empty-thread")
        self.assertEqual(receipt.relationship_kind, "thread.create")

    def test_supersession_rejects_suppressed_previous_endpoint_support(self) -> None:
        self._interpretation("old", "source-a")
        self._interpretation("new", "source-b")
        self._thread("thread-a")
        self._admit("thread-a", "old")
        self._admit("thread-a", "new")
        self._suppress("source-a")

        with self.assertRaises(RealSourceSuppressedError):
            self.supersession_writer.write_supersession(
                context=self._context(OperationClass.SUPERSESSION_WRITE),
                supersession_id="sup-old-new",
                previous_interpretation_id="old",
                new_interpretation_id="new",
                reason_evidence=(self._evidence("source-reason"),),
            )
        self.assertEqual(self._row_count("real_supersessions"), 0)

    def test_supersession_rejects_suppressed_new_endpoint_support(self) -> None:
        self._interpretation("old", "source-a")
        self._interpretation("new", "source-b")
        self._thread("thread-a")
        self._admit("thread-a", "old")
        self._admit("thread-a", "new")
        self._suppress("source-b")

        with self.assertRaises(RealSourceSuppressedError):
            self.supersession_writer.write_supersession(
                context=self._context(OperationClass.SUPERSESSION_WRITE),
                supersession_id="sup-old-new",
                previous_interpretation_id="old",
                new_interpretation_id="new",
                reason_evidence=(self._evidence("source-reason"),),
            )
        self.assertEqual(self._row_count("real_supersessions"), 0)

    def test_supersession_rejects_suppressed_reason_support(self) -> None:
        self._interpretation("old", "source-a")
        self._interpretation("new", "source-b")
        self._thread("thread-a")
        self._admit("thread-a", "old")
        self._admit("thread-a", "new")
        self._suppress("source-reason")

        with self.assertRaises(RealSourceSuppressedError):
            self.supersession_writer.write_supersession(
                context=self._context(OperationClass.SUPERSESSION_WRITE),
                supersession_id="sup-old-new",
                previous_interpretation_id="old",
                new_interpretation_id="new",
                reason_evidence=(self._evidence("source-reason"),),
            )
        self.assertEqual(self._row_count("real_supersessions"), 0)

    def test_unaffected_independent_lineage_remains_usable(self) -> None:
        self._interpretation("i-a", "source-a")
        self._suppress("source-a")

        receipt = self._interpretation("i-b", "source-b")
        self.assertEqual(receipt.resource_id, "i-b")

        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with self.assertRaises(RealSourceSuppressedError):
                assert_interpretation_usable(connection, "i-a")
            assert_interpretation_usable(connection, "i-b")
        finally:
            connection.close()

    def test_current_use_state_is_persisted_not_carried_by_old_objects(self) -> None:
        self._interpretation("i-old", "source-a")
        self._suppress("source-a")

        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with self.assertRaises(RealSourceSuppressedError):
                assert_source_ids_usable(connection, ("source-a",))
            with self.assertRaises(RealSourceSuppressedError):
                assert_interpretation_usable(connection, "i-old")
        finally:
            connection.close()

    def test_write_and_suppression_share_one_deterministic_ordering_boundary(self) -> None:
        import home_memory_core.real_relationships as relationship_module

        reached_validation = Event()
        release_writer = Event()
        writer_done = Event()
        suppression_done = Event()
        writer_error: list[BaseException] = []
        suppression_error: list[BaseException] = []
        original = relationship_module._validate_evidence_dependencies

        def blocking_validate(*args, **kwargs):
            result = original(*args, **kwargs)
            reached_validation.set()
            if not release_writer.wait(2):
                raise AssertionError("test did not release writer")
            return result

        def run_writer():
            try:
                self._interpretation("race-i", "source-a")
            except BaseException as error:  # pragma: no cover - diagnostic capture
                writer_error.append(error)
            finally:
                writer_done.set()

        def run_suppression():
            try:
                self._suppress("source-a")
            except BaseException as error:  # pragma: no cover - diagnostic capture
                suppression_error.append(error)
            finally:
                suppression_done.set()

        with patch.object(
            relationship_module,
            "_validate_evidence_dependencies",
            side_effect=blocking_validate,
        ):
            writer_thread = Thread(target=run_writer)
            writer_thread.start()
            self.assertTrue(reached_validation.wait(1))

            suppression_thread = Thread(target=run_suppression)
            suppression_thread.start()
            self.assertFalse(
                suppression_done.wait(0.05),
                "suppression must wait while writer owns authority ordering",
            )

            release_writer.set()
            self.assertTrue(writer_done.wait(1))
            self.assertTrue(suppression_done.wait(1))
            writer_thread.join()
            suppression_thread.join()

        self.assertEqual(writer_error, [])
        self.assertEqual(suppression_error, [])
        self.assertEqual(self._row_count("real_interpretations"), 1)
        self.assertEqual(self._row_count("real_source_suppressions"), 1)

        with self.assertRaises(RealSourceSuppressedError):
            self._interpretation("race-i-after", "source-a")


if __name__ == "__main__":
    unittest.main()
