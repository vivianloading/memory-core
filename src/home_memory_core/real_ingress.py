from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import sqlite3
from uuid import uuid4

from home_memory_core.identity_namespaces import (
    AccessDomainId,
    CaptureEventId,
    OriginId,
    OriginNamespaceId,
    SnapshotId,
)
from home_memory_core.ingress_identity import IngressIdentityMetadata
from home_memory_core.interpretation import SYNTHETIC_UNATTRIBUTED_INSTANCE_ID
from home_memory_core.operation_identity import (
    OperationClass,
    OperationContext,
    PrincipalId,
    require_operation_context,
)
from home_memory_core.real_use_state import (
    RealUseStateIntegrityError,
    assert_real_stop_use_schema,
)
from home_memory_core.real_source_origin import (
    CAPTURE_EVENT_TABLE,
    ORIGIN_TABLE,
    SNAPSHOT_SUPPRESSION_TABLE,
    SNAPSHOT_TABLE,
    SOURCE_BINDING_TABLE,
    RealSourceOriginIntegrityError,
    assert_real_source_origin_schema,
)
from home_memory_core.source_origin import (
    ReplayDisposition,
    TrustedSourceOriginProvenance,
)
from home_memory_core.store_domain import assert_real_store_domain
from home_memory_core.real_authority_ordering import (
    capture_real_store_generation,
    real_authority_maintenance,
    real_authority_operation,
)


_CLOSED_REAL_INGRESS_CAPABILITY_MARKER = object()
_TRUSTED_WRITE_POLICY_MARKER = object()
class RealIngressDisabledError(RuntimeError):
    """The closed real-ingress exercise boundary is not available."""


class RealIngressAuthorizationError(PermissionError):
    """A trusted operation context was denied by real-ingress write policy."""


class RealIngressIntegrityError(RuntimeError):
    """The real-ingress store or payload failed a mechanical invariant."""


class RealIngressProvenanceConflictError(RealIngressIntegrityError):
    """Trusted provenance resolved to an immutable identity conflict."""


class RealIngressReplayBlockedError(RealIngressIntegrityError):
    """A replay/new snapshot is not eligible for normal ingress."""

    def __init__(self, disposition: ReplayDisposition, message: str) -> None:
        self.disposition = disposition
        super().__init__(message)


@dataclass(frozen=True)
class ClosedRealIngressExerciseCapability:
    """Synthetic-fixture-only capability for exercising the closed real path.

    There is intentionally no production/runtime minting function in HOME.
    Tests may cross the private marker boundary from test-only support code.
    Possessing this capability is *not* a final real-data enablement decision.
    """

    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _CLOSED_REAL_INGRESS_CAPABILITY_MARKER:
            raise RealIngressDisabledError(
                "closed real-ingress capability cannot be caller-minted"
            )


@dataclass(frozen=True)
class SingleOwnerRealIngressWritePolicy:
    """Narrow deny-by-default policy for the first closed ingress exercise.

    This policy intentionally supports one authenticated owner and one access
    domain. It does not use `scope`, asserted author, subject, or perspective
    metadata as proof of authority.
    """

    policy_id: str
    owner_principal_id: PrincipalId
    access_domain_id: AccessDomainId
    origin_namespace_id: OriginNamespaceId
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _TRUSTED_WRITE_POLICY_MARKER:
            raise RealIngressAuthorizationError(
                "real-ingress write policy must come from trusted policy code"
            )
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise RealIngressAuthorizationError("policy_id cannot be empty")
        if not isinstance(self.owner_principal_id, PrincipalId):
            raise RealIngressAuthorizationError(
                "owner_principal_id must use PrincipalId"
            )
        if not isinstance(self.access_domain_id, AccessDomainId):
            raise RealIngressAuthorizationError(
                "access_domain_id must use AccessDomainId"
            )
        if not isinstance(self.origin_namespace_id, OriginNamespaceId):
            raise RealIngressAuthorizationError(
                "origin_namespace_id must use OriginNamespaceId"
            )

    def authorize_source_write(
        self,
        *,
        context: OperationContext,
        metadata: IngressIdentityMetadata,
        provenance: TrustedSourceOriginProvenance,
    ) -> None:
        require_operation_context(
            context,
            expected_operation_class=OperationClass.SOURCE_WRITE,
        )
        if not isinstance(metadata, IngressIdentityMetadata):
            raise RealIngressAuthorizationError(
                "real source write requires IngressIdentityMetadata"
            )

        if context.principal.principal_id != self.owner_principal_id:
            raise RealIngressAuthorizationError("source.write denied")
        if metadata.access_domain_id != self.access_domain_id:
            raise RealIngressAuthorizationError("source.write denied")
        if not isinstance(provenance, TrustedSourceOriginProvenance):
            raise RealIngressAuthorizationError(
                "source.write requires trusted source-origin provenance"
            )
        if provenance.origin_namespace_id != self.origin_namespace_id:
            raise RealIngressAuthorizationError("source.write denied")


@dataclass(frozen=True)
class RealIngressReceipt:
    """Frozen audit receipt for a closed-ingress synthetic exercise.

    This receipt records what was committed. It is never an authorization
    token and cannot be replayed to authorize another write.
    """

    receipt_id: str
    source_id: str
    operation_id: str
    ingested_by_principal_id: PrincipalId
    access_domain_id: AccessDomainId
    policy_id: str
    recorded_at_utc: str
    content_sha256: str
    origin_id: OriginId
    snapshot_id: SnapshotId
    capture_event_id: CaptureEventId
    replay_disposition: ReplayDisposition
    authority: str = "none"


class ClosedRealIngressWriter:
    """Write synthetic fixtures through the future real-ingress boundary.

    The writer requires a private exercise capability with no runtime minting
    path. It is therefore useful for adversarial tests without opening HOME to
    real personal data.
    """

    def __init__(
        self,
        *,
        db_path: str | Path,
        capability: ClosedRealIngressExerciseCapability,
        policy: SingleOwnerRealIngressWritePolicy,
        ingress_channel: str,
    ) -> None:
        _require_closed_real_ingress_capability(capability)
        _require_trusted_write_policy(policy)
        if not isinstance(ingress_channel, str) or not ingress_channel.strip():
            raise ValueError("ingress_channel cannot be empty")

        self.db_path = Path(db_path)
        self._capability = capability
        self._policy = policy
        self._ingress_channel = ingress_channel
        self._authority_generation = capture_real_store_generation(self.db_path)

    def write_source(
        self,
        *,
        context: OperationContext,
        source_id: str,
        content: str,
        metadata: IngressIdentityMetadata,
        provenance: TrustedSourceOriginProvenance,
    ) -> RealIngressReceipt:
        _require_closed_real_ingress_capability(self._capability)
        _require_trusted_write_policy(self._policy)
        require_operation_context(
            context,
            expected_operation_class=OperationClass.SOURCE_WRITE,
        )
        _validate_source_input(
            source_id=source_id,
            content=content,
            metadata=metadata,
        )
        if not isinstance(provenance, TrustedSourceOriginProvenance):
            raise RealIngressIntegrityError(
                "real source write requires trusted source-origin provenance"
            )

        digest = sha256(content.encode("utf-8")).hexdigest()
        recorded_at_utc = _utc_now_text()

        with real_authority_operation(
            self.db_path, expected_generation=self._authority_generation
        ):
            self._policy.authorize_source_write(
                context=context,
                metadata=metadata,
                provenance=provenance,
            )

            connection = sqlite3.connect(self.db_path)
            try:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")
                assert_real_store_domain(connection)
                _assert_real_ingress_schema(connection)
                try:
                    assert_real_stop_use_schema(connection)
                    assert_real_source_origin_schema(connection)
                except (RealUseStateIntegrityError, RealSourceOriginIntegrityError) as error:
                    raise RealIngressIntegrityError(
                        "closed real source authority has not been initialized"
                    ) from error

                origin_id, origin_was_new = _resolve_or_create_origin(
                    connection=connection,
                    domain=metadata.access_domain_id,
                    provenance=provenance,
                    recorded_at_utc=recorded_at_utc,
                )

                snapshot_row = connection.execute(
                    f"""
                    SELECT snapshot_id, content_sha256
                    FROM {SNAPSHOT_TABLE}
                    WHERE origin_id = ?
                      AND snapshot_kind = ?
                      AND external_snapshot_key = ?
                    """,
                    (
                        origin_id.value,
                        provenance.snapshot_kind.value,
                        provenance.external_snapshot_key,
                    ),
                ).fetchone()

                if snapshot_row is not None:
                    snapshot_id = SnapshotId(snapshot_row[0])
                    if snapshot_row[1] != digest:
                        raise RealIngressProvenanceConflictError(
                            "same canonical snapshot identity has conflicting content"
                        )
                    suppressed = connection.execute(
                        f"SELECT 1 FROM {SNAPSHOT_SUPPRESSION_TABLE} WHERE snapshot_id = ?",
                        (snapshot_id.value,),
                    ).fetchone()
                    if suppressed is not None:
                        raise RealIngressReplayBlockedError(
                            ReplayDisposition.BLOCKED_SUPPRESSED_SNAPSHOT_REPLAY,
                            "suppressed canonical snapshot replay is blocked",
                        )

                    binding = connection.execute(
                        f"""
                        SELECT source_id
                        FROM {SOURCE_BINDING_TABLE}
                        WHERE snapshot_id = ?
                        """,
                        (snapshot_id.value,),
                    ).fetchone()
                    if binding is None:
                        raise RealIngressIntegrityError(
                            "canonical snapshot is missing its source materialization"
                        )
                    canonical_source_id = binding[0]
                    existing_source = connection.execute(
                        "SELECT content, content_sha256, access_domain_id "
                        "FROM real_sources WHERE source_id = ?",
                        (canonical_source_id,),
                    ).fetchone()
                    if existing_source is None:
                        raise RealIngressIntegrityError(
                            "canonical source materialization is missing"
                        )
                    if (
                        existing_source[0] != content
                        or existing_source[1] != digest
                        or existing_source[2] != metadata.access_domain_id.value
                    ):
                        raise RealIngressProvenanceConflictError(
                            "canonical snapshot materialization conflicts with replay"
                        )
                    requested_existing = connection.execute(
                        f"SELECT snapshot_id FROM {SOURCE_BINDING_TABLE} WHERE source_id = ?",
                        (source_id,),
                    ).fetchone()
                    if (
                        requested_existing is not None
                        and requested_existing[0] != snapshot_id.value
                    ):
                        raise RealIngressProvenanceConflictError(
                            "requested local source_id is already bound to another snapshot"
                        )
                    disposition = ReplayDisposition.EXACT_REPLAY_EXISTING_SNAPSHOT
                else:
                    suppressed_history = connection.execute(
                        f"""
                        SELECT 1
                        FROM {SNAPSHOT_SUPPRESSION_TABLE} AS ss
                        JOIN {SNAPSHOT_TABLE} AS old_snap
                          ON old_snap.snapshot_id = ss.snapshot_id
                        WHERE old_snap.origin_id = ?
                        LIMIT 1
                        """,
                        (origin_id.value,),
                    ).fetchone()
                    if suppressed_history is not None:
                        raise RealIngressReplayBlockedError(
                            ReplayDisposition.BLOCKED_POST_SUPPRESSION_NEW_SNAPSHOT,
                            "new snapshot after suppressed origin history is not normal-use eligible",
                        )

                    snapshot_id = SnapshotId(f"real-snapshot-{uuid4().hex}")
                    connection.execute(
                        f"""
                        INSERT INTO {SNAPSHOT_TABLE} (
                            snapshot_id, access_domain_id, origin_id, snapshot_kind,
                            external_snapshot_key, content_sha256, created_at_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            snapshot_id.value,
                            metadata.access_domain_id.value,
                            origin_id.value,
                            provenance.snapshot_kind.value,
                            provenance.external_snapshot_key,
                            digest,
                            recorded_at_utc,
                        ),
                    )

                    try:
                        connection.execute(
                            """
                            INSERT INTO real_sources (
                                source_id, content, content_sha256, asserted_author_ref,
                                access_domain_id, perspective_owner_id, perspective_instance_id,
                                ingested_by_principal_id, ingested_by_principal_kind,
                                ingested_by_trust_source, ingress_operation_id, ingress_channel,
                                recorded_at_utc, write_policy_id
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                source_id,
                                content,
                                digest,
                                metadata.asserted_author.value if metadata.asserted_author is not None else None,
                                metadata.access_domain_id.value,
                                metadata.perspective_owner.value if metadata.perspective_owner is not None else None,
                                metadata.perspective_instance.value if metadata.perspective_instance is not None else None,
                                context.principal.principal_id.value,
                                context.principal.principal_kind,
                                context.principal.trust_source,
                                context.operation_id,
                                self._ingress_channel,
                                recorded_at_utc,
                                self._policy.policy_id,
                            ),
                        )
                        for position, subject in enumerate(metadata.subjects):
                            connection.execute(
                                """
                                INSERT INTO real_source_subjects (source_id, position, subject_id)
                                VALUES (?, ?, ?)
                                """,
                                (source_id, position, subject.value),
                            )
                        connection.execute(
                            f"""
                            INSERT INTO {SOURCE_BINDING_TABLE} (
                                source_id, access_domain_id, snapshot_id
                            ) VALUES (?, ?, ?)
                            """,
                            (source_id, metadata.access_domain_id.value, snapshot_id.value),
                        )
                    except sqlite3.IntegrityError as error:
                        raise RealIngressIntegrityError(
                            "real source could not be stored under canonical snapshot identity"
                        ) from error
                    canonical_source_id = source_id
                    disposition = (
                        ReplayDisposition.NEW_ORIGIN
                        if origin_was_new
                        else ReplayDisposition.NEW_SNAPSHOT_EXISTING_ORIGIN
                    )

                capture_event_id = CaptureEventId(f"real-capture-{uuid4().hex}")
                try:
                    connection.execute(
                        f"""
                        INSERT INTO {CAPTURE_EVENT_TABLE} (
                            capture_event_id, operation_id, requested_source_id,
                            canonical_source_id, access_domain_id, origin_id, snapshot_id,
                            replay_disposition, ingress_adapter_id, adapter_version,
                            capture_locator, recorded_at_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            capture_event_id.value,
                            context.operation_id,
                            source_id,
                            canonical_source_id,
                            metadata.access_domain_id.value,
                            origin_id.value,
                            snapshot_id.value,
                            disposition.value,
                            provenance.ingress_adapter_id,
                            provenance.adapter_version,
                            provenance.capture_locator,
                            recorded_at_utc,
                        ),
                    )
                except sqlite3.IntegrityError as error:
                    raise RealIngressIntegrityError(
                        "capture event could not be stored without replacing history"
                    ) from error

                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

        return RealIngressReceipt(
            receipt_id=f"real-ingress-receipt-{uuid4().hex}",
            source_id=canonical_source_id,
            operation_id=context.operation_id,
            ingested_by_principal_id=context.principal.principal_id,
            access_domain_id=metadata.access_domain_id,
            policy_id=self._policy.policy_id,
            recorded_at_utc=recorded_at_utc,
            content_sha256=digest,
            origin_id=origin_id,
            snapshot_id=snapshot_id,
            capture_event_id=capture_event_id,
            replay_disposition=disposition,
        )


def _resolve_or_create_origin(
    *,
    connection: sqlite3.Connection,
    domain: AccessDomainId,
    provenance: TrustedSourceOriginProvenance,
    recorded_at_utc: str,
) -> tuple[OriginId, bool]:
    row = connection.execute(
        f"""
        SELECT origin_id, object_kind, origin_key_version
        FROM {ORIGIN_TABLE}
        WHERE access_domain_id = ?
          AND origin_namespace_id = ?
          AND external_object_key = ?
        """,
        (
            domain.value,
            provenance.origin_namespace_id.value,
            provenance.external_object_key,
        ),
    ).fetchone()
    if row is not None:
        if row[1] != provenance.object_kind or row[2] != provenance.origin_key_version:
            raise RealIngressProvenanceConflictError(
                "canonical origin identity contract conflicts with persisted origin"
            )
        return OriginId(row[0]), False

    origin_id = OriginId(f"real-origin-{uuid4().hex}")
    try:
        connection.execute(
            f"""
            INSERT INTO {ORIGIN_TABLE} (
                origin_id, access_domain_id, origin_namespace_id, external_object_key,
                object_kind, origin_key_version, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                origin_id.value,
                domain.value,
                provenance.origin_namespace_id.value,
                provenance.external_object_key,
                provenance.object_kind,
                provenance.origin_key_version,
                recorded_at_utc,
            ),
        )
    except sqlite3.IntegrityError as error:
        raise RealIngressProvenanceConflictError(
            "canonical origin could not be created without replacing history"
        ) from error
    return origin_id, True


def initialize_closed_real_ingress_schema(
    *,
    db_path: str | Path,
    capability: ClosedRealIngressExerciseCapability,
) -> None:
    """Create the future real source-ingress schema while the gate stays closed."""

    _require_closed_real_ingress_capability(capability)
    path = Path(db_path)
    with real_authority_maintenance(path):
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                assert_real_store_domain(connection)
                connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS real_sources (
                    source_id TEXT PRIMARY KEY
                        CHECK (length(trim(source_id)) > 0),
                    content TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL
                        CHECK (length(content_sha256) = 64),
                    asserted_author_ref TEXT NULL
                        CHECK (
                            asserted_author_ref IS NULL OR (
                                length(trim(asserted_author_ref)) > 0
                                AND asserted_author_ref != '{SYNTHETIC_UNATTRIBUTED_INSTANCE_ID}'
                            )
                        ),
                    access_domain_id TEXT NOT NULL
                        CHECK (
                            length(trim(access_domain_id)) > 0
                            AND access_domain_id != '{SYNTHETIC_UNATTRIBUTED_INSTANCE_ID}'
                        ),
                    perspective_owner_id TEXT NULL
                        CHECK (
                            perspective_owner_id IS NULL OR (
                                length(trim(perspective_owner_id)) > 0
                                AND perspective_owner_id != '{SYNTHETIC_UNATTRIBUTED_INSTANCE_ID}'
                            )
                        ),
                    perspective_instance_id TEXT NULL
                        CHECK (
                            perspective_instance_id IS NULL OR (
                                length(trim(perspective_instance_id)) > 0
                                AND perspective_instance_id != '{SYNTHETIC_UNATTRIBUTED_INSTANCE_ID}'
                            )
                        ),
                    ingested_by_principal_id TEXT NOT NULL
                        CHECK (
                            length(trim(ingested_by_principal_id)) > 0
                            AND ingested_by_principal_id != '{SYNTHETIC_UNATTRIBUTED_INSTANCE_ID}'
                        ),
                    ingested_by_principal_kind TEXT NOT NULL
                        CHECK (length(trim(ingested_by_principal_kind)) > 0),
                    ingested_by_trust_source TEXT NOT NULL
                        CHECK (length(trim(ingested_by_trust_source)) > 0),
                    ingress_operation_id TEXT NOT NULL UNIQUE
                        CHECK (length(trim(ingress_operation_id)) > 0),
                    ingress_channel TEXT NOT NULL
                        CHECK (length(trim(ingress_channel)) > 0),
                    recorded_at_utc TEXT NOT NULL
                        CHECK (length(trim(recorded_at_utc)) > 0),
                    write_policy_id TEXT NOT NULL
                        CHECK (length(trim(write_policy_id)) > 0),
                    CHECK (
                        (perspective_owner_id IS NULL AND perspective_instance_id IS NULL)
                        OR
                        (perspective_owner_id IS NOT NULL AND perspective_instance_id IS NOT NULL)
                    )
                );

                CREATE TABLE IF NOT EXISTS real_source_subjects (
                    source_id TEXT NOT NULL,
                    position INTEGER NOT NULL CHECK (position >= 0),
                    subject_id TEXT NOT NULL
                        CHECK (
                            length(trim(subject_id)) > 0
                            AND subject_id != '{SYNTHETIC_UNATTRIBUTED_INSTANCE_ID}'
                        ),
                    PRIMARY KEY (source_id, position),
                    UNIQUE (source_id, subject_id),
                    FOREIGN KEY (source_id)
                        REFERENCES real_sources(source_id)
                        ON DELETE RESTRICT
                );
                """
                )
        finally:
            connection.close()


def _require_closed_real_ingress_capability(
    capability: ClosedRealIngressExerciseCapability,
) -> None:
    if not isinstance(capability, ClosedRealIngressExerciseCapability):
        raise RealIngressDisabledError(
            "closed real-ingress requires a trusted exercise capability"
        )
    if capability._marker is not _CLOSED_REAL_INGRESS_CAPABILITY_MARKER:
        raise RealIngressDisabledError("closed real-ingress capability is invalid")


def _require_trusted_write_policy(
    policy: SingleOwnerRealIngressWritePolicy,
) -> None:
    if not isinstance(policy, SingleOwnerRealIngressWritePolicy):
        raise RealIngressAuthorizationError(
            "real-ingress writer requires a trusted write policy"
        )
    if policy._marker is not _TRUSTED_WRITE_POLICY_MARKER:
        raise RealIngressAuthorizationError("real-ingress write policy is invalid")


def _validate_source_input(
    *,
    source_id: str,
    content: str,
    metadata: IngressIdentityMetadata,
) -> None:
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id cannot be empty")
    if not isinstance(content, str):
        raise TypeError("content must be str")
    if not isinstance(metadata, IngressIdentityMetadata):
        raise TypeError("metadata must be IngressIdentityMetadata")

    identity_values: list[str] = [metadata.access_domain_id.value]
    if metadata.asserted_author is not None:
        identity_values.append(metadata.asserted_author.value)
    identity_values.extend(subject.value for subject in metadata.subjects)
    if metadata.perspective_owner is not None:
        identity_values.append(metadata.perspective_owner.value)
    if metadata.perspective_instance is not None:
        identity_values.append(metadata.perspective_instance.value)

    if SYNTHETIC_UNATTRIBUTED_INSTANCE_ID in identity_values:
        raise RealIngressIntegrityError(
            "synthetic compatibility sentinel cannot enter real ingress"
        )


def _assert_real_ingress_schema(connection: sqlite3.Connection) -> None:
    required = {"real_sources", "real_source_subjects"}
    existing = {
        row[0]
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN ('real_sources', 'real_source_subjects')
            """
        ).fetchall()
    }
    if existing != required:
        raise RealIngressIntegrityError(
            "closed real-ingress schema has not been initialized"
        )


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00",
        "Z",
    )
