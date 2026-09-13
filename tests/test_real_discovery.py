from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from _trusted_test_support import (
    trusted_test_closed_real_discovery_capability,
    trusted_test_closed_real_ingress_capability,
    trusted_test_closed_real_relationship_capability,
    trusted_test_closed_real_stop_use_capability,
    trusted_test_closed_real_supersession_capability,
    trusted_test_principal_issuer,
    trusted_test_real_store_bootstrap_capability,
    trusted_test_single_owner_real_discovery_policy,
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
from home_memory_core.real_authority_ordering import RealStoreLifecycleError
from home_memory_core.real_discovery import (
    ClosedRealAuthorizedDiscovery,
    ClosedRealDiscoveryExerciseCapability,
    RealDiscoveryAuthorizationError,
    RealDiscoveryDisabledError,
    RealDiscoveryIntegrityError,
    RealDiscoveryQueryError,
    RealDiscoveryReceipt,
    SingleOwnerRealDiscoveryPolicy,
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
from home_memory_core.real_stop_use import (
    ClosedRealStopUseWriter,
    StopUseReasonCode,
    initialize_closed_real_stop_use_schema,
)
from home_memory_core.real_supersession import (
    ClosedRealSupersessionWriter,
    initialize_closed_real_supersession_schema,
)
from home_memory_core.store_domain import create_empty_real_store, destroy_real_store


class ClosedRealAuthorizedDiscoveryTests(unittest.TestCase):
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
        self.other_domain = AccessDomainId("other-private-domain")
        self.perspective_owner = PerspectiveOwnerId("owner")
        self.perspective_instance = PerspectiveInstanceId("owner-instance")
        self.subject = SubjectId("subject")

        self.discovery_capability = trusted_test_closed_real_discovery_capability()
        self.discovery_policy = trusted_test_single_owner_real_discovery_policy(
            policy_id="single-owner-discovery-v0.1",
            owner_principal_id=self.owner_id,
            access_domain_id=self.domain,
            perspective_owner=self.perspective_owner,
            perspective_instance=self.perspective_instance,
        )
        self.discovery = ClosedRealAuthorizedDiscovery(
            db_path=self.db_path,
            capability=self.discovery_capability,
            policy=self.discovery_policy,
        )

        self.stop_writer = ClosedRealStopUseWriter(
            db_path=self.db_path,
            capability=self.stop_use_capability,
            policy=trusted_test_single_owner_real_stop_use_policy(
                policy_id="single-owner-stop-use-v0.1",
                owner_principal_id=self.owner_id,
                access_domain_id=self.domain,
            ),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _context(self, operation_class: OperationClass, *, principal=None):
        return create_operation_context(
            principal=principal or self.owner,
            operation_class=operation_class,
        )

    def _identity(self, domain: AccessDomainId) -> RealRelationshipIdentity:
        return RealRelationshipIdentity(
            access_domain_id=domain,
            perspective_owner=self.perspective_owner,
            perspective_instance=self.perspective_instance,
            about_subject=self.subject,
        )

    def _writers(self, domain: AccessDomainId):
        ingress = ClosedRealIngressWriter(
            db_path=self.db_path,
            capability=self.ingress_capability,
            policy=trusted_test_single_owner_real_ingress_policy(
                policy_id=f"ingress-{domain.value}",
                owner_principal_id=self.owner_id,
                access_domain_id=domain,
            ),
            ingress_channel="synthetic-fixture-test",
        )
        relationship_policy = trusted_test_single_owner_real_relationship_policy(
            policy_id=f"relationship-{domain.value}",
            owner_principal_id=self.owner_id,
            access_domain_id=domain,
            perspective_owner=self.perspective_owner,
            perspective_instance=self.perspective_instance,
        )
        relationships = ClosedRealRelationshipWriter(
            db_path=self.db_path,
            capability=self.relationship_capability,
            policy=relationship_policy,
        )
        supersessions = ClosedRealSupersessionWriter(
            db_path=self.db_path,
            capability=self.supersession_capability,
            relationship_capability=self.relationship_capability,
            policy=relationship_policy,
        )
        return ingress, relationships, supersessions

    def _write_source(self, *, source_id: str, content: str, domain=None) -> EvidenceRef:
        domain = domain or self.domain
        ingress, _, _ = self._writers(domain)
        ingress.write_source(
            context=self._context(OperationClass.SOURCE_WRITE),
            source_id=source_id,
            content=content,
            metadata=IngressIdentityMetadata(access_domain_id=domain),
        )
        return EvidenceRef(
            source_id=source_id,
            source_sha256=sha256(content.encode("utf-8")).hexdigest(),
            start_char=0,
            end_char=len(content),
        )

    def _bundle(
        self,
        *,
        label: str,
        content: str,
        domain: AccessDomainId | None = None,
        evidence_range: tuple[int, int] | None = None,
        interpretation_text: str | None = None,
    ):
        domain = domain or self.domain
        source_id = f"source-{label}"
        interpretation_id = f"interpretation-{label}"
        thread_id = f"thread-{label}"
        full_ref = self._write_source(
            source_id=source_id,
            content=content,
            domain=domain,
        )
        if evidence_range is None:
            evidence = full_ref
        else:
            start, end = evidence_range
            evidence = EvidenceRef(
                source_id=source_id,
                source_sha256=full_ref.source_sha256,
                start_char=start,
                end_char=end,
            )
        _, relationships, _ = self._writers(domain)
        relationships.write_interpretation(
            context=self._context(OperationClass.INTERPRETATION_WRITE),
            interpretation_id=interpretation_id,
            text=interpretation_text or f"synthetic interpretation {label}",
            identity=self._identity(domain),
            evidence=(evidence,),
        )
        relationships.create_thread(
            context=self._context(OperationClass.THREAD_CREATE),
            thread_id=thread_id,
            question=f"synthetic question {label}?",
            identity=self._identity(domain),
        )
        relationships.admit_interpretation(
            context=self._context(OperationClass.THREAD_ADMIT),
            admission_id=f"admission-{label}",
            thread_id=thread_id,
            interpretation_id=interpretation_id,
        )
        return {
            "source_id": source_id,
            "interpretation_id": interpretation_id,
            "thread_id": thread_id,
            "evidence": evidence,
        }

    def _suppress(self, source_id: str) -> None:
        self.stop_writer.suppress_source(
            context=self._context(OperationClass.SOURCE_SUPPRESS),
            source_id=source_id,
            reason_code=StopUseReasonCode.TEST_FIXTURE,
        )

    def test_capability_cannot_be_caller_minted(self) -> None:
        with self.assertRaises(RealDiscoveryDisabledError):
            ClosedRealDiscoveryExerciseCapability(_marker=object())

    def test_policy_cannot_be_caller_minted(self) -> None:
        with self.assertRaises(RealDiscoveryAuthorizationError):
            SingleOwnerRealDiscoveryPolicy(
                policy_id="fake",
                owner_principal_id=self.owner_id,
                access_domain_id=self.domain,
                perspective_owner=self.perspective_owner,
                perspective_instance=self.perspective_instance,
                _marker=object(),
            )

    def test_exact_evidence_span_discovery_is_stable_and_unranked(self) -> None:
        b = self._bundle(label="b", content="prefix needle suffix")
        a = self._bundle(label="a", content="needle in earlier thread")

        result = self.discovery.search(
            context=self._context(OperationClass.DISCOVERY_READ),
            query="needle",
        )

        self.assertEqual(result.status, "ok")
        self.assertTrue(result.complete_for_rule)
        self.assertEqual(result.thread_ids, (a["thread_id"], b["thread_id"]))
        self.assertEqual(result.receipt.matched_thread_ids, result.thread_ids)
        self.assertEqual(result.receipt.authority, "none")

    def test_query_matches_exact_span_only_not_source_wide_or_derived_text(self) -> None:
        content = "needle outside | exact safe span"
        start = content.index("exact")
        bundle = self._bundle(
            label="span",
            content=content,
            evidence_range=(start, len(content)),
            interpretation_text="derived text contains needle",
        )

        result = self.discovery.search(
            context=self._context(OperationClass.DISCOVERY_READ),
            query="needle",
        )
        self.assertEqual(result.thread_ids, ())
        self.assertNotIn(bundle["thread_id"], result.receipt.matched_thread_ids)

    def test_unauthorized_domain_data_cannot_change_visible_results_or_limit(self) -> None:
        visible = self._bundle(label="visible", content="needle visible")
        self._bundle(
            label="hidden-a",
            content="needle hidden a",
            domain=self.other_domain,
        )
        self._bundle(
            label="hidden-b",
            content="needle hidden b",
            domain=self.other_domain,
        )
        discovery = ClosedRealAuthorizedDiscovery(
            db_path=self.db_path,
            capability=self.discovery_capability,
            policy=self.discovery_policy,
            max_thread_matches=1,
        )

        result = discovery.search(
            context=self._context(OperationClass.DISCOVERY_READ),
            query="needle",
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.thread_ids, (visible["thread_id"],))
        self.assertTrue(result.complete_for_rule)

    def test_corrupt_payload_in_unauthorized_domain_has_zero_discovery_influence(self) -> None:
        visible = self._bundle(label="visible-corrupt-hidden", content="needle visible")
        hidden = self._bundle(
            label="hidden-corrupt",
            content="needle hidden",
            domain=self.other_domain,
        )
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "UPDATE real_sources SET content = ? WHERE source_id = ?",
                ("tampered hidden payload", hidden["source_id"]),
            )
            connection.commit()
        finally:
            connection.close()

        result = self.discovery.search(
            context=self._context(OperationClass.DISCOVERY_READ),
            query="needle",
        )
        self.assertEqual(result.thread_ids, (visible["thread_id"],))

    def test_suppressed_history_cannot_influence_result_count_or_too_many(self) -> None:
        visible = self._bundle(label="visible-limit", content="needle visible")
        blocked = self._bundle(label="blocked-limit", content="needle blocked")
        self._suppress(blocked["source_id"])
        discovery = ClosedRealAuthorizedDiscovery(
            db_path=self.db_path,
            capability=self.discovery_capability,
            policy=self.discovery_policy,
            max_thread_matches=1,
        )

        result = discovery.search(
            context=self._context(OperationClass.DISCOVERY_READ),
            query="needle",
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.thread_ids, (visible["thread_id"],))

    def test_suppressed_payload_is_not_fetched_for_discovery_integrity(self) -> None:
        blocked = self._bundle(label="blocked-corrupt", content="needle blocked")
        self._suppress(blocked["source_id"])
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "UPDATE real_sources SET content = ? WHERE source_id = ?",
                ("tampered after suppression", blocked["source_id"]),
            )
            connection.commit()
        finally:
            connection.close()

        result = self.discovery.search(
            context=self._context(OperationClass.DISCOVERY_READ),
            query="needle",
        )
        self.assertEqual(result.thread_ids, ())

    def test_blocked_newer_interpretation_does_not_fallback_to_old_member(self) -> None:
        old_ref = self._write_source(source_id="source-old", content="needle old")
        new_ref = self._write_source(source_id="source-new", content="needle new")
        reason_ref = self._write_source(source_id="source-reason", content="reason")
        _, relationships, supersessions = self._writers(self.domain)
        identity = self._identity(self.domain)
        for interpretation_id, evidence in (
            ("interpretation-old", old_ref),
            ("interpretation-new", new_ref),
        ):
            relationships.write_interpretation(
                context=self._context(OperationClass.INTERPRETATION_WRITE),
                interpretation_id=interpretation_id,
                text=interpretation_id,
                identity=identity,
                evidence=(evidence,),
            )
        relationships.create_thread(
            context=self._context(OperationClass.THREAD_CREATE),
            thread_id="thread-revision",
            question="revision?",
            identity=identity,
        )
        for interpretation_id in ("interpretation-old", "interpretation-new"):
            relationships.admit_interpretation(
                context=self._context(OperationClass.THREAD_ADMIT),
                admission_id=f"admit-{interpretation_id}",
                thread_id="thread-revision",
                interpretation_id=interpretation_id,
            )
        supersessions.write_supersession(
            context=self._context(OperationClass.SUPERSESSION_WRITE),
            supersession_id="supersession-revision",
            previous_interpretation_id="interpretation-old",
            new_interpretation_id="interpretation-new",
            reason_evidence=(reason_ref,),
        )
        self._suppress("source-new")

        result = self.discovery.search(
            context=self._context(OperationClass.DISCOVERY_READ),
            query="needle",
        )
        self.assertEqual(result.thread_ids, ())

    def test_suppressed_supersession_reason_blocks_thread_discovery(self) -> None:
        old_ref = self._write_source(source_id="source-r-old", content="needle old")
        new_ref = self._write_source(source_id="source-r-new", content="needle new")
        reason_ref = self._write_source(source_id="source-r-reason", content="clean reason")
        _, relationships, supersessions = self._writers(self.domain)
        identity = self._identity(self.domain)
        for interpretation_id, evidence in (
            ("interpretation-r-old", old_ref),
            ("interpretation-r-new", new_ref),
        ):
            relationships.write_interpretation(
                context=self._context(OperationClass.INTERPRETATION_WRITE),
                interpretation_id=interpretation_id,
                text=interpretation_id,
                identity=identity,
                evidence=(evidence,),
            )
        relationships.create_thread(
            context=self._context(OperationClass.THREAD_CREATE),
            thread_id="thread-reason",
            question="reason?",
            identity=identity,
        )
        for interpretation_id in ("interpretation-r-old", "interpretation-r-new"):
            relationships.admit_interpretation(
                context=self._context(OperationClass.THREAD_ADMIT),
                admission_id=f"admit-{interpretation_id}",
                thread_id="thread-reason",
                interpretation_id=interpretation_id,
            )
        supersessions.write_supersession(
            context=self._context(OperationClass.SUPERSESSION_WRITE),
            supersession_id="supersession-reason",
            previous_interpretation_id="interpretation-r-old",
            new_interpretation_id="interpretation-r-new",
            reason_evidence=(reason_ref,),
        )
        self._suppress("source-r-reason")

        result = self.discovery.search(
            context=self._context(OperationClass.DISCOVERY_READ),
            query="needle",
        )
        self.assertEqual(result.thread_ids, ())

    def test_visible_matches_over_cap_return_no_partial_ids(self) -> None:
        for label in ("cap-a", "cap-b", "cap-c"):
            self._bundle(label=label, content=f"needle {label}")
        discovery = ClosedRealAuthorizedDiscovery(
            db_path=self.db_path,
            capability=self.discovery_capability,
            policy=self.discovery_policy,
            max_thread_matches=2,
        )

        result = discovery.search(
            context=self._context(OperationClass.DISCOVERY_READ),
            query="needle",
        )
        self.assertEqual(result.status, "too_many_matches")
        self.assertFalse(result.complete_for_rule)
        self.assertIsNone(result.thread_ids)
        self.assertEqual(result.receipt.matched_thread_ids, ())

    def test_wrong_principal_is_denied_before_database_open(self) -> None:
        with patch("home_memory_core.real_discovery.sqlite3.connect") as connect:
            with self.assertRaisesRegex(
                RealDiscoveryAuthorizationError,
                "^discovery unavailable$",
            ):
                self.discovery.search(
                    context=self._context(
                        OperationClass.DISCOVERY_READ,
                        principal=self.other,
                    ),
                    query="needle",
                )
        connect.assert_not_called()

    def test_non_discovery_operation_context_cannot_be_reused(self) -> None:
        for operation_class in (
            OperationClass.NORMAL_READ,
            OperationClass.MEMORY_DELIVER,
            OperationClass.AUDIT_READ,
        ):
            with self.assertRaises(AuthenticationBoundaryError):
                self.discovery.search(
                    context=self._context(operation_class),
                    query="needle",
                )

    def test_receipt_is_not_reusable_as_discovery_authority(self) -> None:
        self._bundle(label="receipt", content="needle receipt")
        result = self.discovery.search(
            context=self._context(OperationClass.DISCOVERY_READ),
            query="needle",
        )
        self.assertIsInstance(result.receipt, RealDiscoveryReceipt)
        with self.assertRaises(AuthenticationBoundaryError):
            self.discovery.search(context=result.receipt, query="needle")

    def test_invalid_literal_query_is_rejected_without_normalization(self) -> None:
        for query in ("", "\ud800"):
            with self.assertRaises(RealDiscoveryQueryError):
                self.discovery.search(
                    context=self._context(OperationClass.DISCOVERY_READ),
                    query=query,
                )
        bundle = self._bundle(label="literal", content="Needle")
        result = self.discovery.search(
            context=self._context(OperationClass.DISCOVERY_READ),
            query="needle",
        )
        self.assertNotIn(bundle["thread_id"], result.thread_ids)

    def test_authorized_payload_integrity_failure_is_fail_closed(self) -> None:
        bundle = self._bundle(label="tamper-visible", content="needle visible")
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "UPDATE real_sources SET content = ? WHERE source_id = ?",
                ("tampered visible payload", bundle["source_id"]),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(RealDiscoveryIntegrityError):
            self.discovery.search(
                context=self._context(OperationClass.DISCOVERY_READ),
                query="needle",
            )


    def test_matching_early_evidence_does_not_skip_later_integrity_validation(self) -> None:
        first = self._write_source(
            source_id="source-integrity-first",
            content="needle first support",
        )
        second = self._write_source(
            source_id="source-integrity-second",
            content="other required support",
        )
        _, relationships, _ = self._writers(self.domain)
        identity = self._identity(self.domain)
        relationships.write_interpretation(
            context=self._context(OperationClass.INTERPRETATION_WRITE),
            interpretation_id="interpretation-integrity-complete",
            text="synthetic interpretation complete validation",
            identity=identity,
            evidence=(first, second),
        )
        relationships.create_thread(
            context=self._context(OperationClass.THREAD_CREATE),
            thread_id="thread-integrity-complete",
            question="synthetic integrity question?",
            identity=identity,
        )
        relationships.admit_interpretation(
            context=self._context(OperationClass.THREAD_ADMIT),
            admission_id="admission-integrity-complete",
            thread_id="thread-integrity-complete",
            interpretation_id="interpretation-integrity-complete",
        )

        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "UPDATE real_sources SET content = ? WHERE source_id = ?",
                ("tampered later support", second.source_id),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(RealDiscoveryIntegrityError):
            self.discovery.search(
                context=self._context(OperationClass.DISCOVERY_READ),
                query="needle",
            )

    def test_damaged_stop_use_schema_fails_closed(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("DROP TRIGGER real_source_suppressions_no_update")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(RealDiscoveryIntegrityError):
            self.discovery.search(
                context=self._context(OperationClass.DISCOVERY_READ),
                query="needle",
            )

    def test_discovery_generation_becomes_stale_after_destroy_and_rebootstrap(self) -> None:
        destroy_real_store(db_path=self.db_path, capability=self.bootstrap)
        create_empty_real_store(db_path=self.db_path, capability=self.bootstrap)

        with self.assertRaises(RealStoreLifecycleError):
            self.discovery.search(
                context=self._context(OperationClass.DISCOVERY_READ),
                query="needle",
            )

    def test_discovery_connection_is_query_only(self) -> None:
        self._bundle(label="query-only", content="needle query only")
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
                    observed.append(
                        self._inner.execute("PRAGMA query_only").fetchone()[0]
                    )
                return result

            @property
            def in_transaction(self):
                return self._inner.in_transaction

            def close(self):
                return self._inner.close()

        def probed_connect(*args, **kwargs):
            return QueryOnlyProbe(original_connect(*args, **kwargs))

        with patch("home_memory_core.real_discovery.sqlite3.connect", probed_connect):
            result = self.discovery.search(
                context=self._context(OperationClass.DISCOVERY_READ),
                query="needle",
            )
        self.assertEqual(result.thread_ids, ("thread-query-only",))
        self.assertEqual(observed, [1])


if __name__ == "__main__":
    unittest.main()
