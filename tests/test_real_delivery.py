from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from _trusted_test_support import (
    trusted_test_closed_real_delivery_capability,
    trusted_test_closed_real_ingress_capability,
    trusted_test_closed_real_relationship_capability,
    trusted_test_closed_real_source_origin_capability,
    trusted_test_closed_real_stop_use_capability,
    trusted_test_closed_real_supersession_capability,
    trusted_test_principal_issuer,
    trusted_test_real_store_bootstrap_capability,
    trusted_test_single_owner_real_delivery_policy,
    trusted_test_single_owner_real_ingress_policy,
    trusted_test_single_owner_real_relationship_policy,
    trusted_test_single_owner_real_stop_use_policy,
    trusted_test_source_origin_provenance,
)
from home_memory_core.evidence import EvidenceRef
from home_memory_core.identity_namespaces import (
    AccessDomainId,
    DestinationId,
    PerspectiveInstanceId,
    PerspectiveOwnerId,
    RequestId,
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
from home_memory_core.real_delivery import (
    ClosedRealDeliveryExerciseCapability,
    ClosedRealThreadDeliveryPreparer,
    PreparedRealThreadPacket,
    RealDeliveryAuthorizationError,
    RealDeliveryDisabledError,
    RealDeliveryIntegrityError,
    RealDeliveryUnavailableError,
    SingleOwnerRealDeliveryPolicy,
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
    ClosedRealStopUseWriter,
    StopUseReasonCode,
    initialize_closed_real_stop_use_schema,
)
from home_memory_core.real_supersession import (
    ClosedRealSupersessionWriter,
    initialize_closed_real_supersession_schema,
)
from home_memory_core.store_domain import create_empty_real_store, destroy_real_store


class ClosedRealThreadDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "real.sqlite3"

        self.bootstrap = trusted_test_real_store_bootstrap_capability()
        self.ingress_capability = trusted_test_closed_real_ingress_capability()
        self.stop_use_capability = trusted_test_closed_real_stop_use_capability()
        self.origin_capability = trusted_test_closed_real_source_origin_capability()
        self.relationship_capability = trusted_test_closed_real_relationship_capability()
        self.supersession_capability = trusted_test_closed_real_supersession_capability()
        self._initialize_store()

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
        self.destination = DestinationId("approved-model-destination")
        self.other_destination = DestinationId("other-destination")

        self.delivery_capability = trusted_test_closed_real_delivery_capability()
        self.delivery_policy = trusted_test_single_owner_real_delivery_policy(
            policy_id="single-owner-delivery-v0.1",
            owner_principal_id=self.owner_id,
            access_domain_id=self.domain,
            perspective_owner=self.perspective_owner,
            perspective_instance=self.perspective_instance,
            destination_id=self.destination,
        )
        self.delivery = ClosedRealThreadDeliveryPreparer(
            db_path=self.db_path,
            capability=self.delivery_capability,
            policy=self.delivery_policy,
        )
        self.stop_writer = ClosedRealStopUseWriter(
            db_path=self.db_path,
            capability=self.stop_use_capability,
            policy=trusted_test_single_owner_real_stop_use_policy(
                policy_id="stop-use-v0.1",
                owner_principal_id=self.owner_id,
                access_domain_id=self.domain,
            ),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _initialize_store(self) -> None:
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
            capability=self.origin_capability,
        )
        initialize_closed_real_relationship_schema(
            db_path=self.db_path,
            ingress_capability=self.ingress_capability,
            relationship_capability=self.relationship_capability,
        )
        initialize_closed_real_supersession_schema(
            db_path=self.db_path,
            relationship_capability=self.relationship_capability,
            supersession_capability=self.supersession_capability,
        )

    def _context(
        self,
        operation_class: OperationClass,
        *,
        principal=None,
        request: str | None = None,
        destination: DestinationId | None = None,
    ):
        return create_operation_context(
            principal=principal or self.owner,
            operation_class=operation_class,
            request_id=(RequestId(request) if request is not None else None),
            destination_id=destination,
        )

    def _delivery_context(self, *, principal=None, destination=None, request="req-1"):
        return self._context(
            OperationClass.MEMORY_DELIVER,
            principal=principal,
            request=request,
            destination=destination or self.destination,
        )

    def _identity(self, domain=None) -> RealRelationshipIdentity:
        return RealRelationshipIdentity(
            access_domain_id=domain or self.domain,
            perspective_owner=self.perspective_owner,
            perspective_instance=self.perspective_instance,
            about_subject=self.subject,
        )

    def _writers(self, domain=None):
        domain = domain or self.domain
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
        result = ingress.write_source(
            context=self._context(OperationClass.SOURCE_WRITE),
            source_id=source_id,
            content=content,
            metadata=IngressIdentityMetadata(access_domain_id=domain),
            provenance=trusted_test_source_origin_provenance(
                external_object_key=source_id,
            ),
        )
        canonical_source_id = result.source_id
        return EvidenceRef(
            source_id=canonical_source_id,
            source_sha256=sha256(content.encode("utf-8")).hexdigest(),
            start_char=0,
            end_char=len(content),
        )

    def _single_thread(self, *, label: str, content: str, domain=None):
        domain = domain or self.domain
        evidence = self._write_source(
            source_id=f"source-{label}",
            content=content,
            domain=domain,
        )
        _, relationships, _ = self._writers(domain)
        interpretation_id = f"interpretation-{label}"
        thread_id = f"thread-{label}"
        relationships.write_interpretation(
            context=self._context(OperationClass.INTERPRETATION_WRITE),
            interpretation_id=interpretation_id,
            text=f"derived text {label} that must never be delivered",
            identity=self._identity(domain),
            evidence=(evidence,),
        )
        relationships.create_thread(
            context=self._context(OperationClass.THREAD_CREATE),
            thread_id=thread_id,
            question=f"question {label}?",
            identity=self._identity(domain),
        )
        relationships.admit_interpretation(
            context=self._context(OperationClass.THREAD_ADMIT),
            admission_id=f"admission-{label}",
            thread_id=thread_id,
            interpretation_id=interpretation_id,
        )
        return {
            "source_id": evidence.source_id,
            "evidence": evidence,
            "interpretation_id": interpretation_id,
            "thread_id": thread_id,
        }

    def _chain(self, *, label="chain"):
        a = self._write_source(source_id=f"source-{label}-a", content="old exact evidence")
        b = self._write_source(source_id=f"source-{label}-b", content="new exact evidence")
        reason = self._write_source(
            source_id=f"source-{label}-reason",
            content="revision reason evidence",
        )
        _, relationships, supersessions = self._writers()
        ia = f"interpretation-{label}-a"
        ib = f"interpretation-{label}-b"
        thread = f"thread-{label}"
        relationships.write_interpretation(
            context=self._context(OperationClass.INTERPRETATION_WRITE),
            interpretation_id=ia,
            text="old derived text",
            identity=self._identity(),
            evidence=(a,),
        )
        relationships.write_interpretation(
            context=self._context(OperationClass.INTERPRETATION_WRITE),
            interpretation_id=ib,
            text="new derived text",
            identity=self._identity(),
            evidence=(b,),
        )
        relationships.create_thread(
            context=self._context(OperationClass.THREAD_CREATE),
            thread_id=thread,
            question="which revision?",
            identity=self._identity(),
        )
        relationships.admit_interpretation(
            context=self._context(OperationClass.THREAD_ADMIT),
            admission_id=f"admission-{label}-a",
            thread_id=thread,
            interpretation_id=ia,
        )
        relationships.admit_interpretation(
            context=self._context(OperationClass.THREAD_ADMIT),
            admission_id=f"admission-{label}-b",
            thread_id=thread,
            interpretation_id=ib,
        )
        supersessions.write_supersession(
            context=self._context(OperationClass.SUPERSESSION_WRITE),
            supersession_id=f"supersession-{label}",
            previous_interpretation_id=ia,
            new_interpretation_id=ib,
            reason_evidence=(reason,),
        )
        return {
            "thread_id": thread,
            "old_interpretation_id": ia,
            "new_interpretation_id": ib,
            "old_source_id": a.source_id,
            "new_source_id": b.source_id,
            "reason_source_id": reason.source_id,
        }

    def _suppress(self, source_id: str) -> None:
        self.stop_writer.suppress_source(
            context=self._context(OperationClass.SOURCE_SUPPRESS),
            source_id=source_id,
            reason_code=StopUseReasonCode.TEST_FIXTURE,
        )

    def test_capability_and_policy_cannot_be_caller_minted(self) -> None:
        with self.assertRaises(RealDeliveryDisabledError):
            ClosedRealDeliveryExerciseCapability(_marker=object())
        with self.assertRaises(RealDeliveryAuthorizationError):
            SingleOwnerRealDeliveryPolicy(
                policy_id="fake",
                owner_principal_id=self.owner_id,
                access_domain_id=self.domain,
                perspective_owner=self.perspective_owner,
                perspective_instance=self.perspective_instance,
                destination_id=self.destination,
                _marker=object(),
            )

    def test_prepare_binds_request_destination_and_exact_candidate_source_only(self) -> None:
        item = self._single_thread(label="simple", content="prefix exact memory suffix")
        prepared = self.delivery.prepare(
            context=self._delivery_context(request="request-simple"),
            thread_id=item["thread_id"],
        )

        packet = prepared.packet
        self.assertEqual(packet.request_id, RequestId("request-simple"))
        self.assertEqual(packet.destination_id, self.destination)
        self.assertEqual(packet.candidate_interpretation_id, item["interpretation_id"])
        self.assertEqual(len(packet.evidence_spans), 1)
        self.assertEqual(packet.evidence_spans[0].exact_text, "prefix exact memory suffix")
        self.assertFalse(hasattr(packet, "interpretation_text"))
        self.assertEqual(packet.instruction_authority, "none")
        self.assertEqual(packet.authority, "none")
        self.assertEqual(prepared.receipt.authority, "none")
        self.assertEqual(prepared.receipt.delivery_stage, "prepared_not_handed_off")

    def test_prepared_packet_cannot_be_caller_minted(self) -> None:
        item = self._single_thread(label="mint", content="evidence")
        prepared = self.delivery.prepare(
            context=self._delivery_context(),
            thread_id=item["thread_id"],
        )
        p = prepared.packet
        with self.assertRaises(RealDeliveryDisabledError):
            PreparedRealThreadPacket(
                request_id=p.request_id,
                destination_id=p.destination_id,
                thread_id=p.thread_id,
                candidate_interpretation_id=p.candidate_interpretation_id,
                evidence_spans=p.evidence_spans,
                dependency_refs=p.dependency_refs,
                _marker=object(),
            )

    def test_wrong_principal_or_destination_denied_before_database_open(self) -> None:
        item = self._single_thread(label="denied", content="protected")
        with patch("home_memory_core.real_delivery.sqlite3.connect") as connect:
            with self.assertRaises(RealDeliveryAuthorizationError):
                self.delivery.prepare(
                    context=self._delivery_context(principal=self.other),
                    thread_id=item["thread_id"],
                )
            connect.assert_not_called()
        with patch("home_memory_core.real_delivery.sqlite3.connect") as connect:
            with self.assertRaises(RealDeliveryAuthorizationError):
                self.delivery.prepare(
                    context=self._delivery_context(destination=self.other_destination),
                    thread_id=item["thread_id"],
                )
            connect.assert_not_called()

    def test_delivery_requires_memory_deliver_request_and_destination_context(self) -> None:
        item = self._single_thread(label="context", content="protected")
        with self.assertRaises(AuthenticationBoundaryError):
            self.delivery.prepare(
                context=self._context(
                    OperationClass.NORMAL_READ,
                    request="req",
                    destination=self.destination,
                ),
                thread_id=item["thread_id"],
            )
        with self.assertRaises(RealDeliveryAuthorizationError):
            self.delivery.prepare(
                context=self._context(OperationClass.MEMORY_DELIVER),
                thread_id=item["thread_id"],
            )

    def test_missing_and_wrong_domain_thread_converge_on_unavailable(self) -> None:
        hidden = self._single_thread(
            label="hidden",
            content="hidden",
            domain=self.other_domain,
        )
        for thread_id in ("thread-missing", hidden["thread_id"]):
            with self.assertRaisesRegex(
                RealDeliveryUnavailableError,
                "normal delivery unavailable",
            ):
                self.delivery.prepare(
                    context=self._delivery_context(),
                    thread_id=thread_id,
                )

    def test_supersession_chain_delivers_only_head_but_receipt_binds_full_support(self) -> None:
        chain = self._chain()
        prepared = self.delivery.prepare(
            context=self._delivery_context(request="chain-request"),
            thread_id=chain["thread_id"],
        )

        self.assertEqual(
            prepared.packet.candidate_interpretation_id,
            chain["new_interpretation_id"],
        )
        self.assertEqual(
            tuple(span.source_id for span in prepared.packet.evidence_spans),
            (chain["new_source_id"],),
        )
        dependency_source_ids = {d.source_id for d in prepared.packet.dependency_refs}
        self.assertEqual(
            dependency_source_ids,
            {
                chain["old_source_id"],
                chain["new_source_id"],
                chain["reason_source_id"],
            },
        )
        for dependency in prepared.packet.dependency_refs:
            self.assertTrue(dependency.origin_id.value)
            self.assertTrue(dependency.snapshot_id.value)
            self.assertFalse(hasattr(dependency, "provider_account_id"))

    def test_multiple_heads_are_not_partially_deliverable(self) -> None:
        first = self._single_thread(label="fork-base", content="base")
        second_evidence = self._write_source(source_id="source-fork-second", content="second")
        _, relationships, _ = self._writers()
        second_id = "interpretation-fork-second"
        relationships.write_interpretation(
            context=self._context(OperationClass.INTERPRETATION_WRITE),
            interpretation_id=second_id,
            text="second derived",
            identity=self._identity(),
            evidence=(second_evidence,),
        )
        relationships.admit_interpretation(
            context=self._context(OperationClass.THREAD_ADMIT),
            admission_id="admission-fork-second",
            thread_id=first["thread_id"],
            interpretation_id=second_id,
        )
        with self.assertRaises(RealDeliveryUnavailableError):
            self.delivery.prepare(
                context=self._delivery_context(),
                thread_id=first["thread_id"],
            )

    def test_suppressed_historical_member_blocks_newer_head_no_fallback(self) -> None:
        chain = self._chain(label="blocked-old")
        self._suppress(chain["old_source_id"])
        with self.assertRaises(RealDeliveryUnavailableError):
            self.delivery.prepare(
                context=self._delivery_context(),
                thread_id=chain["thread_id"],
            )

    def test_suppressed_supersession_reason_blocks_delivery(self) -> None:
        chain = self._chain(label="blocked-reason")
        self._suppress(chain["reason_source_id"])
        with self.assertRaises(RealDeliveryUnavailableError):
            self.delivery.prepare(
                context=self._delivery_context(),
                thread_id=chain["thread_id"],
            )

    def test_historical_noncandidate_integrity_is_validated_before_packet(self) -> None:
        chain = self._chain(label="corrupt-old")
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "UPDATE real_sources SET content='tampered historical payload' WHERE source_id=?",
                (chain["old_source_id"],),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(RealDeliveryIntegrityError):
            self.delivery.prepare(
                context=self._delivery_context(),
                thread_id=chain["thread_id"],
            )

    def test_prepared_packet_and_receipt_do_not_survive_later_stop_use_as_authority(self) -> None:
        item = self._single_thread(label="stale-packet", content="current evidence")
        prepared = self.delivery.prepare(
            context=self._delivery_context(request="before-suppress"),
            thread_id=item["thread_id"],
        )
        self.assertEqual(prepared.packet.authority, "none")
        self.assertEqual(prepared.receipt.authority, "none")
        self._suppress(item["source_id"])
        with self.assertRaises(RealDeliveryUnavailableError):
            self.delivery.prepare(
                context=self._delivery_context(request="after-suppress"),
                thread_id=item["thread_id"],
            )
        with self.assertRaises(AuthenticationBoundaryError):
            self.delivery.prepare(  # type: ignore[arg-type]
                context=prepared.receipt,
                thread_id=item["thread_id"],
            )

    def test_damaged_origin_authority_fails_closed(self) -> None:
        item = self._single_thread(label="damaged-origin", content="evidence")
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("DROP TRIGGER real_source_origins_no_update")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(RealDeliveryIntegrityError):
            self.delivery.prepare(
                context=self._delivery_context(),
                thread_id=item["thread_id"],
            )

    def test_prepare_is_query_only_and_does_not_mutate_persisted_state(self) -> None:
        item = self._single_thread(label="readonly", content="evidence")
        before = self._db_state_fingerprint()
        self.delivery.prepare(
            context=self._delivery_context(),
            thread_id=item["thread_id"],
        )
        after = self._db_state_fingerprint()
        self.assertEqual(after, before)

    def test_old_delivery_object_fails_after_destroy_and_rebootstrap(self) -> None:
        item = self._single_thread(label="stale-generation", content="evidence")
        destroy_real_store(db_path=self.db_path, capability=self.bootstrap)
        self._initialize_store()
        with self.assertRaises(RealStoreLifecycleError):
            self.delivery.prepare(
                context=self._delivery_context(),
                thread_id=item["thread_id"],
            )

    def _db_state_fingerprint(self):
        connection = sqlite3.connect(self.db_path)
        try:
            names = tuple(
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            )
            return tuple(
                (name, connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
                for name in names
            )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
