from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import sqlite3
from threading import Lock, RLock
from uuid import uuid4

from home_memory_core.identity_namespaces import AccessDomainId
from home_memory_core.ingress_identity import IngressIdentityMetadata
from home_memory_core.interpretation import SYNTHETIC_UNATTRIBUTED_INSTANCE_ID
from home_memory_core.operation_identity import (
    OperationClass,
    OperationContext,
    PrincipalId,
    require_operation_context,
)
from home_memory_core.store_domain import assert_real_store_domain


_CLOSED_REAL_INGRESS_CAPABILITY_MARKER = object()
_TRUSTED_WRITE_POLICY_MARKER = object()
_REAL_INGRESS_LOCK_REGISTRY_GUARD = Lock()
_REAL_INGRESS_LOCKS: dict[str, RLock] = {}


class RealIngressDisabledError(RuntimeError):
    """The closed real-ingress exercise boundary is not available."""


class RealIngressAuthorizationError(PermissionError):
    """A trusted operation context was denied by real-ingress write policy."""


class RealIngressIntegrityError(RuntimeError):
    """The real-ingress store or payload failed a mechanical invariant."""


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

    def authorize_source_write(
        self,
        *,
        context: OperationContext,
        metadata: IngressIdentityMetadata,
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
        self._ordering_lock = _real_ingress_lock_for_path(self.db_path)

    def write_source(
        self,
        *,
        context: OperationContext,
        source_id: str,
        content: str,
        metadata: IngressIdentityMetadata,
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

        digest = sha256(content.encode("utf-8")).hexdigest()
        recorded_at_utc = _utc_now_text()

        # Authorization and commit share one same-process ordering boundary.
        # Any future mutable policy/revocation path must use this same lock (or
        # replace it with a stronger primitive before multi-process support).
        with self._ordering_lock:
            self._policy.authorize_source_write(
                context=context,
                metadata=metadata,
            )

            connection = sqlite3.connect(self.db_path)
            try:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")
                assert_real_store_domain(connection)
                _assert_real_ingress_schema(connection)

                try:
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
                            source_id,
                            content,
                            digest,
                            (
                                metadata.asserted_author.value
                                if metadata.asserted_author is not None
                                else None
                            ),
                            metadata.access_domain_id.value,
                            (
                                metadata.perspective_owner.value
                                if metadata.perspective_owner is not None
                                else None
                            ),
                            (
                                metadata.perspective_instance.value
                                if metadata.perspective_instance is not None
                                else None
                            ),
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
                            INSERT INTO real_source_subjects (
                                source_id,
                                position,
                                subject_id
                            ) VALUES (?, ?, ?)
                            """,
                            (source_id, position, subject.value),
                        )
                except sqlite3.IntegrityError as error:
                    raise RealIngressIntegrityError(
                        "real source could not be stored"
                    ) from error

                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

        return RealIngressReceipt(
            receipt_id=f"real-ingress-receipt-{uuid4().hex}",
            source_id=source_id,
            operation_id=context.operation_id,
            ingested_by_principal_id=context.principal.principal_id,
            access_domain_id=metadata.access_domain_id,
            policy_id=self._policy.policy_id,
            recorded_at_utc=recorded_at_utc,
            content_sha256=digest,
        )


def initialize_closed_real_ingress_schema(
    *,
    db_path: str | Path,
    capability: ClosedRealIngressExerciseCapability,
) -> None:
    """Create the future real source-ingress schema while the gate stays closed."""

    _require_closed_real_ingress_capability(capability)
    path = Path(db_path)
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


def _real_ingress_lock_for_path(db_path: Path) -> RLock:
    key = str(db_path.expanduser().resolve())
    with _REAL_INGRESS_LOCK_REGISTRY_GUARD:
        lock = _REAL_INGRESS_LOCKS.get(key)
        if lock is None:
            lock = RLock()
            _REAL_INGRESS_LOCKS[key] = lock
        return lock


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
