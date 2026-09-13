from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from _trusted_test_support import (
    trusted_test_closed_real_ingress_capability,
    trusted_test_closed_real_source_origin_capability,
    trusted_test_closed_real_stop_use_capability,
    trusted_test_principal_issuer,
    trusted_test_real_store_bootstrap_capability,
    trusted_test_single_owner_real_ingress_policy,
    trusted_test_single_owner_real_stop_use_policy,
    trusted_test_source_origin_provenance,
)
from home_memory_core.identity_namespaces import AccessDomainId, OriginNamespaceId
from home_memory_core.ingress_identity import IngressIdentityMetadata
from home_memory_core.operation_identity import (
    OperationClass,
    PrincipalId,
    create_operation_context,
)
from home_memory_core.real_ingress import (
    ClosedRealIngressWriter,
    RealIngressAuthorizationError,
    RealIngressIntegrityError,
    RealIngressProvenanceConflictError,
    RealIngressReplayBlockedError,
    initialize_closed_real_ingress_schema,
)
from home_memory_core.real_source_origin import (
    CAPTURE_EVENT_TABLE,
    ORIGIN_TABLE,
    SNAPSHOT_SUPPRESSION_TABLE,
    SNAPSHOT_TABLE,
    SOURCE_BINDING_TABLE,
    ClosedRealSourceOriginExerciseCapability,
    RealSourceOriginDisabledError,
    RealSourceOriginIntegrityError,
    assert_real_source_origin_schema,
    initialize_closed_real_source_origin_schema,
)
from home_memory_core.real_stop_use import (
    ClosedRealStopUseWriter,
    StopUseReasonCode,
    initialize_closed_real_stop_use_schema,
)
from home_memory_core.real_use_state import (
    RealSourceSuppressedError,
    assert_source_ids_usable,
)
from home_memory_core.source_origin import (
    ReplayDisposition,
    SnapshotKind,
    SourceOriginBoundaryError,
    TrustedSourceOriginProvenance,
)
from home_memory_core.store_domain import create_empty_real_store


class ClosedRealSourceOriginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "real.sqlite3"
        create_empty_real_store(
            db_path=self.db_path,
            capability=trusted_test_real_store_bootstrap_capability(),
        )
        self.ingress_capability = trusted_test_closed_real_ingress_capability()
        initialize_closed_real_ingress_schema(
            db_path=self.db_path,
            capability=self.ingress_capability,
        )
        self.stop_capability = trusted_test_closed_real_stop_use_capability()
        initialize_closed_real_stop_use_schema(
            db_path=self.db_path,
            capability=self.stop_capability,
        )
        self.origin_capability = trusted_test_closed_real_source_origin_capability()
        initialize_closed_real_source_origin_schema(
            db_path=self.db_path,
            capability=self.origin_capability,
        )

        self.owner_id = PrincipalId("owner-vivi")
        self.owner = trusted_test_principal_issuer().issue(
            principal_id=self.owner_id,
            principal_kind="local_owner",
        )
        self.domain = AccessDomainId("owner-private-domain")
        self.namespace = OriginNamespaceId("provider/account-A")
        self.writer = self._writer(self.namespace)
        self.stop_writer = ClosedRealStopUseWriter(
            db_path=self.db_path,
            capability=self.stop_capability,
            policy=trusted_test_single_owner_real_stop_use_policy(
                policy_id="stop-v0.1",
                owner_principal_id=self.owner_id,
                access_domain_id=self.domain,
            ),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _context(self, operation: OperationClass):
        return create_operation_context(
            principal=self.owner,
            operation_class=operation,
        )

    def _writer(self, namespace: OriginNamespaceId):
        return ClosedRealIngressWriter(
            db_path=self.db_path,
            capability=self.ingress_capability,
            policy=trusted_test_single_owner_real_ingress_policy(
                policy_id=f"ingress-{namespace.value}",
                owner_principal_id=self.owner_id,
                access_domain_id=self.domain,
                origin_namespace_id=namespace,
            ),
            ingress_channel="synthetic-fixture-test",
        )

    def _provenance(
        self,
        object_key: str,
        *,
        snapshot_key: str = "immutable",
        snapshot_kind: SnapshotKind = SnapshotKind.IMMUTABLE_ORIGIN,
        namespace: OriginNamespaceId | None = None,
        adapter_id: str = "adapter-A",
        adapter_version: str = "1",
        key_version: str = "canonical-v1",
    ):
        return trusted_test_source_origin_provenance(
            origin_namespace_id=namespace or self.namespace,
            external_object_key=object_key,
            external_snapshot_key=snapshot_key,
            snapshot_kind=snapshot_kind,
            origin_key_version=key_version,
            ingress_adapter_id=adapter_id,
            adapter_version=adapter_version,
        )

    def _write(
        self,
        source_id: str,
        content: str,
        provenance,
        *,
        writer=None,
    ):
        return (writer or self.writer).write_source(
            context=self._context(OperationClass.SOURCE_WRITE),
            source_id=source_id,
            content=content,
            metadata=IngressIdentityMetadata(access_domain_id=self.domain),
            provenance=provenance,
        )

    def _suppress(self, source_id: str):
        return self.stop_writer.suppress_source(
            context=self._context(OperationClass.SOURCE_SUPPRESS),
            source_id=source_id,
            reason_code=StopUseReasonCode.TEST_FIXTURE,
        )

    def test_caller_cannot_mint_source_origin_capability_or_provenance(self) -> None:
        with self.assertRaises(RealSourceOriginDisabledError):
            ClosedRealSourceOriginExerciseCapability(_marker=object())
        with self.assertRaises(SourceOriginBoundaryError):
            TrustedSourceOriginProvenance(
                origin_namespace_id=self.namespace,
                external_object_key="message-1",
                object_kind="message",
                origin_key_version="v1",
                snapshot_kind=SnapshotKind.IMMUTABLE_ORIGIN,
                external_snapshot_key="immutable",
                ingress_adapter_id="adapter",
                adapter_version="1",
                _marker=object(),
            )

    def test_missing_trusted_provenance_is_rejected_before_normal_ingress(self) -> None:
        with self.assertRaises(RealIngressIntegrityError):
            self.writer.write_source(
                context=self._context(OperationClass.SOURCE_WRITE),
                source_id="source-missing-provenance",
                content="synthetic",
                metadata=IngressIdentityMetadata(access_domain_id=self.domain),
                provenance=None,  # type: ignore[arg-type]
            )

    def test_exact_replay_reuses_one_origin_snapshot_and_source(self) -> None:
        provenance = self._provenance("message-1")
        first = self._write("source-1", "hello", provenance)
        second = self._write("source-2", "hello", provenance)

        self.assertEqual(first.replay_disposition, ReplayDisposition.NEW_ORIGIN)
        self.assertEqual(
            second.replay_disposition,
            ReplayDisposition.EXACT_REPLAY_EXISTING_SNAPSHOT,
        )
        self.assertEqual(second.source_id, "source-1")
        self.assertEqual(second.origin_id, first.origin_id)
        self.assertEqual(second.snapshot_id, first.snapshot_id)
        self.assertNotEqual(second.capture_event_id, first.capture_event_id)

        connection = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM real_sources").fetchone()[0], 1)
            self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {ORIGIN_TABLE}").fetchone()[0], 1)
            self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {SNAPSHOT_TABLE}").fetchone()[0], 1)
            self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {CAPTURE_EVENT_TABLE}").fetchone()[0], 2)
        finally:
            connection.close()

    def test_suppressed_exact_replay_cannot_escape_with_new_local_source_id(self) -> None:
        provenance = self._provenance("message-suppressed")
        first = self._write("source-1", "hello", provenance)
        suppression = self._suppress("source-1")
        self.assertEqual(suppression.snapshot_id, first.snapshot_id)
        self.assertEqual(suppression.origin_id, first.origin_id)

        with self.assertRaises(RealIngressReplayBlockedError) as raised:
            self._write("source-2", "hello", provenance)
        self.assertEqual(
            raised.exception.disposition,
            ReplayDisposition.BLOCKED_SUPPRESSED_SNAPSHOT_REPLAY,
        )

        connection = sqlite3.connect(self.db_path)
        try:
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM real_sources WHERE source_id='source-2'"
                ).fetchone()
            )
        finally:
            connection.close()

    def test_identical_bytes_on_distinct_trusted_origins_remain_independent(self) -> None:
        first = self._write("source-1", "hello", self._provenance("message-1"))
        self._suppress("source-1")
        second = self._write("source-2", "hello", self._provenance("message-2"))
        self.assertNotEqual(first.origin_id, second.origin_id)
        self.assertEqual(second.replay_disposition, ReplayDisposition.NEW_ORIGIN)

        connection = sqlite3.connect(self.db_path)
        try:
            assert_source_ids_usable(connection, ("source-2",))
        finally:
            connection.close()

    def test_new_revision_after_suppressed_snapshot_is_restricted_not_auto_admitted(self) -> None:
        rev7 = self._provenance(
            "document-D",
            snapshot_key="rev7",
            snapshot_kind=SnapshotKind.EXTERNAL_REVISION,
        )
        rev8 = self._provenance(
            "document-D",
            snapshot_key="rev8",
            snapshot_kind=SnapshotKind.EXTERNAL_REVISION,
        )
        first = self._write("source-rev7", "document v7", rev7)
        self._suppress("source-rev7")

        with self.assertRaises(RealIngressReplayBlockedError) as raised:
            self._write("source-rev8", "document v8", rev8)
        self.assertEqual(
            raised.exception.disposition,
            ReplayDisposition.BLOCKED_POST_SUPPRESSION_NEW_SNAPSHOT,
        )

        connection = sqlite3.connect(self.db_path)
        try:
            rows = connection.execute(
                f"SELECT snapshot_id FROM {SNAPSHOT_TABLE} WHERE origin_id=?",
                (first.origin_id.value,),
            ).fetchall()
            self.assertEqual(rows, [(first.snapshot_id.value,)])
        finally:
            connection.close()

    def test_new_revision_before_any_suppression_is_a_new_snapshot_same_origin(self) -> None:
        rev7 = self._write(
            "source-rev7",
            "document v7",
            self._provenance(
                "document-D",
                snapshot_key="rev7",
                snapshot_kind=SnapshotKind.EXTERNAL_REVISION,
            ),
        )
        rev8 = self._write(
            "source-rev8",
            "document v8",
            self._provenance(
                "document-D",
                snapshot_key="rev8",
                snapshot_kind=SnapshotKind.EXTERNAL_REVISION,
            ),
        )
        self.assertEqual(rev8.origin_id, rev7.origin_id)
        self.assertNotEqual(rev8.snapshot_id, rev7.snapshot_id)
        self.assertEqual(
            rev8.replay_disposition,
            ReplayDisposition.NEW_SNAPSHOT_EXISTING_ORIGIN,
        )

    def test_same_snapshot_identity_with_different_bytes_fails_closed(self) -> None:
        provenance = self._provenance("message-conflict")
        self._write("source-1", "first bytes", provenance)
        with self.assertRaises(RealIngressProvenanceConflictError):
            self._write("source-2", "different bytes", provenance)

    def test_wrong_account_namespace_cannot_be_self_asserted(self) -> None:
        other_namespace = OriginNamespaceId("provider/account-B")
        with self.assertRaises(RealIngressAuthorizationError):
            self._write(
                "source-B",
                "payload",
                self._provenance("message-42", namespace=other_namespace),
            )

    def test_same_external_id_in_distinct_authorized_namespaces_does_not_collide(self) -> None:
        other_namespace = OriginNamespaceId("provider/account-B")
        other_writer = self._writer(other_namespace)
        a = self._write("source-A", "same", self._provenance("42"))
        b = self._write(
            "source-B",
            "same",
            self._provenance("42", namespace=other_namespace),
            writer=other_writer,
        )
        self.assertNotEqual(a.origin_id, b.origin_id)

    def test_cross_adapter_capture_maps_to_same_origin_when_namespace_contract_matches(self) -> None:
        a = self._write(
            "source-A",
            "payload",
            self._provenance("message-99", adapter_id="api", adapter_version="1"),
        )
        b = self._write(
            "source-B",
            "payload",
            self._provenance("message-99", adapter_id="export", adapter_version="7"),
        )
        self.assertEqual(a.origin_id, b.origin_id)
        self.assertEqual(a.snapshot_id, b.snapshot_id)
        self.assertEqual(b.source_id, "source-A")

    def test_canonicalizer_version_conflict_fails_closed_instead_of_minting_new_origin(self) -> None:
        self._write(
            "source-A",
            "payload",
            self._provenance("message-99", key_version="canonical-v1"),
        )
        with self.assertRaises(RealIngressProvenanceConflictError):
            self._write(
                "source-B",
                "payload",
                self._provenance("message-99", key_version="canonical-v2"),
            )

    def test_stop_use_persists_snapshot_tombstone_and_current_use_fails(self) -> None:
        receipt = self._write("source-A", "payload", self._provenance("message-A"))
        suppression = self._suppress("source-A")
        self.assertEqual(suppression.snapshot_id, receipt.snapshot_id)

        connection = sqlite3.connect(self.db_path)
        try:
            row = connection.execute(
                f"SELECT source_id, source_suppression_id FROM {SNAPSHOT_SUPPRESSION_TABLE} "
                "WHERE snapshot_id=?",
                (receipt.snapshot_id.value,),
            ).fetchone()
            self.assertEqual(row, ("source-A", suppression.suppression_id))
            with self.assertRaises(RealSourceSuppressedError):
                assert_source_ids_usable(connection, ("source-A",))
        finally:
            connection.close()

    def test_origin_schema_damage_fails_closed(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("DROP TRIGGER real_source_origin_bindings_block_replace")
            connection.commit()
            with self.assertRaises(RealSourceOriginIntegrityError):
                assert_real_source_origin_schema(connection)
        finally:
            connection.close()

        with self.assertRaises(RealIngressIntegrityError):
            self._write("source-A", "payload", self._provenance("message-A"))

    def test_insert_or_replace_cannot_replace_origin_or_snapshot_authority(self) -> None:
        receipt = self._write("source-A", "payload", self._provenance("message-A"))
        connection = sqlite3.connect(self.db_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    f"INSERT OR REPLACE INTO {ORIGIN_TABLE} "
                    "(origin_id, access_domain_id, origin_namespace_id, external_object_key, "
                    "object_kind, origin_key_version, created_at_utc) "
                    "SELECT origin_id, access_domain_id, origin_namespace_id, external_object_key, "
                    "object_kind, origin_key_version, created_at_utc FROM real_source_origins "
                    "WHERE origin_id=?",
                    (receipt.origin_id.value,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    f"INSERT OR REPLACE INTO {SNAPSHOT_TABLE} "
                    "(snapshot_id, access_domain_id, origin_id, snapshot_kind, "
                    "external_snapshot_key, content_sha256, created_at_utc) "
                    f"SELECT snapshot_id, access_domain_id, origin_id, snapshot_kind, "
                    f"external_snapshot_key, content_sha256, created_at_utc FROM {SNAPSHOT_TABLE} "
                    "WHERE snapshot_id=?",
                    (receipt.snapshot_id.value,),
                )
        finally:
            connection.close()

    def test_restart_writer_replay_still_resolves_existing_snapshot(self) -> None:
        provenance = self._provenance("message-restart")
        first = self._write("source-A", "payload", provenance)
        restarted = self._writer(self.namespace)
        second = self._write("source-B", "payload", provenance, writer=restarted)
        self.assertEqual(second.origin_id, first.origin_id)
        self.assertEqual(second.snapshot_id, first.snapshot_id)
        self.assertEqual(second.source_id, "source-A")

    def test_existing_unbound_source_history_is_not_auto_certified(self) -> None:
        other = Path(self.tempdir.name) / "legacy-real.sqlite3"
        create_empty_real_store(
            db_path=other,
            capability=trusted_test_real_store_bootstrap_capability(),
        )
        initialize_closed_real_ingress_schema(
            db_path=other,
            capability=self.ingress_capability,
        )
        initialize_closed_real_stop_use_schema(
            db_path=other,
            capability=self.stop_capability,
        )
        connection = sqlite3.connect(other)
        try:
            connection.execute(
                "INSERT INTO real_sources (source_id, content, content_sha256, access_domain_id, "
                "ingested_by_principal_id, ingested_by_principal_kind, ingested_by_trust_source, "
                "ingress_operation_id, ingress_channel, recorded_at_utc, write_policy_id) "
                "VALUES ('legacy', 'x', ?, 'owner-private-domain', 'owner-vivi', 'local_owner', "
                "'test', 'op-legacy', 'legacy', '2026-01-01T00:00:00Z', 'legacy')",
                ("2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881",),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(RealSourceOriginIntegrityError):
            initialize_closed_real_source_origin_schema(
                db_path=other,
                capability=self.origin_capability,
            )


if __name__ == "__main__":
    unittest.main()
