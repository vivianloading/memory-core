from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import sqlite3
from uuid import uuid4

from home_memory_core.evidence import EvidenceRef
from home_memory_core.identity_namespaces import (
    AccessDomainId,
    PerspectiveInstanceId,
    PerspectiveOwnerId,
    SubjectId,
)
from home_memory_core.interpretation import SYNTHETIC_UNATTRIBUTED_INSTANCE_ID
from home_memory_core.operation_identity import (
    OperationClass,
    OperationContext,
    PrincipalId,
    require_operation_context,
)
from home_memory_core.real_ingress import (
    ClosedRealIngressExerciseCapability,
    RealIngressIntegrityError,
    _require_closed_real_ingress_capability,
)
from home_memory_core.real_write_ordering import real_write_ordering_lock_for_path
from home_memory_core.store_domain import assert_real_store_domain


_CLOSED_REAL_RELATIONSHIP_CAPABILITY_MARKER = object()
_TRUSTED_RELATIONSHIP_WRITE_POLICY_MARKER = object()


class RealRelationshipDisabledError(RuntimeError):
    """Closed real relationship-writing is not available to runtime callers."""


class RealRelationshipAuthorizationError(PermissionError):
    """A real relationship write was denied by trusted policy."""


class RealRelationshipIntegrityError(RuntimeError):
    """A real relationship write violated a mechanical domain invariant."""


@dataclass(frozen=True)
class ClosedRealRelationshipExerciseCapability:
    """Synthetic-fixture-only capability for relationship-write exercises."""

    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _CLOSED_REAL_RELATIONSHIP_CAPABILITY_MARKER:
            raise RealRelationshipDisabledError(
                "closed real relationship capability cannot be caller-minted"
            )


@dataclass(frozen=True)
class RealRelationshipIdentity:
    """Semantic identity + authorization domain for one derived unit.

    `access_domain_id` is a trusted policy/resource-domain identifier. It is
    separate from any synthetic `scope` label and cannot be inferred from one.
    """

    access_domain_id: AccessDomainId
    perspective_owner: PerspectiveOwnerId
    perspective_instance: PerspectiveInstanceId
    about_subject: SubjectId

    def __post_init__(self) -> None:
        expected = {
            "access_domain_id": (self.access_domain_id, AccessDomainId),
            "perspective_owner": (self.perspective_owner, PerspectiveOwnerId),
            "perspective_instance": (
                self.perspective_instance,
                PerspectiveInstanceId,
            ),
            "about_subject": (self.about_subject, SubjectId),
        }
        for name, (value, value_type) in expected.items():
            if not isinstance(value, value_type):
                raise TypeError(f"{name} must use {value_type.__name__}")
            if value.value == SYNTHETIC_UNATTRIBUTED_INSTANCE_ID:
                raise RealRelationshipIntegrityError(
                    "synthetic compatibility sentinel cannot enter real relationships"
                )


@dataclass(frozen=True)
class SingleOwnerRealRelationshipWritePolicy:
    """Deny-by-default relationship policy for one owner + one access domain."""

    policy_id: str
    owner_principal_id: PrincipalId
    access_domain_id: AccessDomainId
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _TRUSTED_RELATIONSHIP_WRITE_POLICY_MARKER:
            raise RealRelationshipAuthorizationError(
                "relationship write policy must come from trusted policy code"
            )
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise RealRelationshipAuthorizationError("policy_id cannot be empty")
        if not isinstance(self.owner_principal_id, PrincipalId):
            raise RealRelationshipAuthorizationError(
                "owner_principal_id must use PrincipalId"
            )
        if not isinstance(self.access_domain_id, AccessDomainId):
            raise RealRelationshipAuthorizationError(
                "access_domain_id must use AccessDomainId"
            )

    def authorize(
        self,
        *,
        context: OperationContext,
        expected_operation_class: OperationClass,
        access_domain_id: AccessDomainId,
    ) -> None:
        require_operation_context(
            context,
            expected_operation_class=expected_operation_class,
        )
        if context.principal.principal_id != self.owner_principal_id:
            raise RealRelationshipAuthorizationError("relationship write denied")
        if access_domain_id != self.access_domain_id:
            raise RealRelationshipAuthorizationError("relationship write denied")


@dataclass(frozen=True)
class RealRelationshipReceipt:
    receipt_id: str
    relationship_kind: str
    resource_id: str
    operation_id: str
    principal_id: PrincipalId
    access_domain_id: AccessDomainId
    policy_id: str
    recorded_at_utc: str
    authority: str = "none"


class ClosedRealRelationshipWriter:
    """Exercise real-domain relationship writes using synthetic fixtures only.

    The first pilot intentionally permits only a single authorization domain.
    A relationship is created only after every protected endpoint/dependency has
    been resolved from persisted state and proven to live in that same domain.
    """

    def __init__(
        self,
        *,
        db_path: str | Path,
        capability: ClosedRealRelationshipExerciseCapability,
        policy: SingleOwnerRealRelationshipWritePolicy,
    ) -> None:
        _require_relationship_capability(capability)
        _require_relationship_policy(policy)
        self.db_path = Path(db_path)
        self._capability = capability
        self._policy = policy
        self._ordering_lock = real_write_ordering_lock_for_path(self.db_path)

    def write_interpretation(
        self,
        *,
        context: OperationContext,
        interpretation_id: str,
        text: str,
        identity: RealRelationshipIdentity,
        evidence: tuple[EvidenceRef, ...],
    ) -> RealRelationshipReceipt:
        _require_relationship_capability(self._capability)
        _require_relationship_policy(self._policy)
        _validate_interpretation_input(
            interpretation_id=interpretation_id,
            text=text,
            identity=identity,
            evidence=evidence,
        )
        recorded_at = _utc_now_text()

        with self._ordering_lock:
            self._policy.authorize(
                context=context,
                expected_operation_class=OperationClass.INTERPRETATION_WRITE,
                access_domain_id=identity.access_domain_id,
            )
            connection = _open_write_connection(self.db_path)
            try:
                connection.execute("BEGIN IMMEDIATE")
                assert_real_store_domain(connection)
                _assert_relationship_schema(connection)
                _validate_evidence_dependencies(
                    connection=connection,
                    identity=identity,
                    evidence=evidence,
                )
                try:
                    connection.execute(
                        """
                        INSERT INTO real_interpretations (
                            interpretation_id,
                            text,
                            perspective_owner_id,
                            perspective_instance_id,
                            about_subject_id,
                            access_domain_id,
                            created_by_principal_id,
                            created_by_principal_kind,
                            created_by_trust_source,
                            operation_id,
                            recorded_at_utc,
                            write_policy_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            interpretation_id,
                            text,
                            identity.perspective_owner.value,
                            identity.perspective_instance.value,
                            identity.about_subject.value,
                            identity.access_domain_id.value,
                            context.principal.principal_id.value,
                            context.principal.principal_kind,
                            context.principal.trust_source,
                            context.operation_id,
                            recorded_at,
                            self._policy.policy_id,
                        ),
                    )
                    for position, item in enumerate(evidence):
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
                                interpretation_id,
                                position,
                                item.source_id,
                                item.source_sha256,
                                item.start_char,
                                item.end_char,
                                identity.access_domain_id.value,
                            ),
                        )
                except sqlite3.IntegrityError as error:
                    raise RealRelationshipIntegrityError(
                        "real interpretation relationship could not be stored"
                    ) from error
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

        return _receipt(
            kind="interpretation.write",
            resource_id=interpretation_id,
            context=context,
            domain=identity.access_domain_id,
            policy_id=self._policy.policy_id,
            recorded_at=recorded_at,
        )

    def create_thread(
        self,
        *,
        context: OperationContext,
        thread_id: str,
        question: str,
        identity: RealRelationshipIdentity,
    ) -> RealRelationshipReceipt:
        _require_relationship_capability(self._capability)
        _require_relationship_policy(self._policy)
        _validate_thread_input(thread_id=thread_id, question=question, identity=identity)
        recorded_at = _utc_now_text()

        with self._ordering_lock:
            self._policy.authorize(
                context=context,
                expected_operation_class=OperationClass.THREAD_CREATE,
                access_domain_id=identity.access_domain_id,
            )
            connection = _open_write_connection(self.db_path)
            try:
                connection.execute("BEGIN IMMEDIATE")
                assert_real_store_domain(connection)
                _assert_relationship_schema(connection)
                try:
                    connection.execute(
                        """
                        INSERT INTO real_threads (
                            thread_id,
                            question,
                            perspective_owner_id,
                            perspective_instance_id,
                            about_subject_id,
                            access_domain_id,
                            created_by_principal_id,
                            created_by_principal_kind,
                            created_by_trust_source,
                            operation_id,
                            recorded_at_utc,
                            write_policy_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            thread_id,
                            question,
                            identity.perspective_owner.value,
                            identity.perspective_instance.value,
                            identity.about_subject.value,
                            identity.access_domain_id.value,
                            context.principal.principal_id.value,
                            context.principal.principal_kind,
                            context.principal.trust_source,
                            context.operation_id,
                            recorded_at,
                            self._policy.policy_id,
                        ),
                    )
                except sqlite3.IntegrityError as error:
                    raise RealRelationshipIntegrityError(
                        "real thread could not be stored"
                    ) from error
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

        return _receipt(
            kind="thread.create",
            resource_id=thread_id,
            context=context,
            domain=identity.access_domain_id,
            policy_id=self._policy.policy_id,
            recorded_at=recorded_at,
        )

    def admit_interpretation(
        self,
        *,
        context: OperationContext,
        admission_id: str,
        thread_id: str,
        interpretation_id: str,
    ) -> RealRelationshipReceipt:
        _require_relationship_capability(self._capability)
        _require_relationship_policy(self._policy)
        for field_name, value in {
            "admission_id": admission_id,
            "thread_id": thread_id,
            "interpretation_id": interpretation_id,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
        recorded_at = _utc_now_text()

        with self._ordering_lock:
            require_operation_context(
                context,
                expected_operation_class=OperationClass.THREAD_ADMIT,
            )
            connection = _open_write_connection(self.db_path)
            try:
                connection.execute("BEGIN IMMEDIATE")
                assert_real_store_domain(connection)
                _assert_relationship_schema(connection)
                interpretation = _load_relationship_identity(
                    connection=connection,
                    table="real_interpretations",
                    id_column="interpretation_id",
                    resource_id=interpretation_id,
                )
                thread = _load_relationship_identity(
                    connection=connection,
                    table="real_threads",
                    id_column="thread_id",
                    resource_id=thread_id,
                )
                if interpretation != thread:
                    raise RealRelationshipIntegrityError(
                        "thread admission cannot cross identity or access-domain boundaries"
                    )
                self._policy.authorize(
                    context=context,
                    expected_operation_class=OperationClass.THREAD_ADMIT,
                    access_domain_id=interpretation.access_domain_id,
                )
                try:
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
                            admission_id,
                            thread_id,
                            interpretation_id,
                            interpretation.perspective_owner.value,
                            interpretation.perspective_instance.value,
                            interpretation.about_subject.value,
                            interpretation.access_domain_id.value,
                            context.principal.principal_id.value,
                            context.principal.principal_kind,
                            context.principal.trust_source,
                            context.operation_id,
                            recorded_at,
                            self._policy.policy_id,
                        ),
                    )
                except sqlite3.IntegrityError as error:
                    raise RealRelationshipIntegrityError(
                        "real thread admission could not be stored"
                    ) from error
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

        return _receipt(
            kind="thread.admit",
            resource_id=admission_id,
            context=context,
            domain=interpretation.access_domain_id,
            policy_id=self._policy.policy_id,
            recorded_at=recorded_at,
        )


def initialize_closed_real_relationship_schema(
    *,
    db_path: str | Path,
    ingress_capability: ClosedRealIngressExerciseCapability,
    relationship_capability: ClosedRealRelationshipExerciseCapability,
) -> None:
    """Create relationship tables only in an already initialized real store."""

    _require_closed_real_ingress_capability(ingress_capability)
    _require_relationship_capability(relationship_capability)
    connection = sqlite3.connect(Path(db_path))
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            assert_real_store_domain(connection)
            _assert_real_source_schema(connection)
            connection.executescript(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS real_sources_evidence_domain_key
                    ON real_sources(source_id, content_sha256, access_domain_id);

                CREATE TABLE IF NOT EXISTS real_interpretations (
                    interpretation_id TEXT PRIMARY KEY
                        CHECK (length(trim(interpretation_id)) > 0),
                    text TEXT NOT NULL CHECK (length(trim(text)) > 0),
                    perspective_owner_id TEXT NOT NULL
                        CHECK (
                            length(trim(perspective_owner_id)) > 0
                            AND perspective_owner_id != '{SYNTHETIC_UNATTRIBUTED_INSTANCE_ID}'
                        ),
                    perspective_instance_id TEXT NOT NULL
                        CHECK (
                            length(trim(perspective_instance_id)) > 0
                            AND perspective_instance_id != '{SYNTHETIC_UNATTRIBUTED_INSTANCE_ID}'
                        ),
                    about_subject_id TEXT NOT NULL
                        CHECK (
                            length(trim(about_subject_id)) > 0
                            AND about_subject_id != '{SYNTHETIC_UNATTRIBUTED_INSTANCE_ID}'
                        ),
                    access_domain_id TEXT NOT NULL
                        CHECK (
                            length(trim(access_domain_id)) > 0
                            AND access_domain_id != '{SYNTHETIC_UNATTRIBUTED_INSTANCE_ID}'
                        ),
                    created_by_principal_id TEXT NOT NULL
                        CHECK (
                            length(trim(created_by_principal_id)) > 0
                            AND created_by_principal_id != '__synthetic_unattributed__'
                        ),
                    created_by_principal_kind TEXT NOT NULL
                        CHECK (length(trim(created_by_principal_kind)) > 0),
                    created_by_trust_source TEXT NOT NULL
                        CHECK (length(trim(created_by_trust_source)) > 0),
                    operation_id TEXT NOT NULL UNIQUE
                        CHECK (length(trim(operation_id)) > 0),
                    recorded_at_utc TEXT NOT NULL
                        CHECK (length(trim(recorded_at_utc)) > 0),
                    write_policy_id TEXT NOT NULL
                        CHECK (length(trim(write_policy_id)) > 0),
                    UNIQUE (
                        interpretation_id,
                        perspective_owner_id,
                        perspective_instance_id,
                        about_subject_id,
                        access_domain_id
                    )
                );

                CREATE TABLE IF NOT EXISTS real_interpretation_evidence (
                    interpretation_id TEXT NOT NULL,
                    position INTEGER NOT NULL CHECK (position >= 0),
                    source_id TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
                    start_char INTEGER NOT NULL CHECK (start_char >= 0),
                    end_char INTEGER NOT NULL CHECK (end_char > start_char),
                    access_domain_id TEXT NOT NULL,
                    PRIMARY KEY (interpretation_id, position),
                    UNIQUE (
                        interpretation_id,
                        source_id,
                        source_sha256,
                        start_char,
                        end_char
                    ),
                    FOREIGN KEY (interpretation_id)
                        REFERENCES real_interpretations(interpretation_id)
                        ON DELETE RESTRICT,
                    FOREIGN KEY (source_id, source_sha256, access_domain_id)
                        REFERENCES real_sources(
                            source_id,
                            content_sha256,
                            access_domain_id
                        )
                        ON UPDATE RESTRICT
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS real_threads (
                    thread_id TEXT PRIMARY KEY
                        CHECK (length(trim(thread_id)) > 0),
                    question TEXT NOT NULL CHECK (length(trim(question)) > 0),
                    perspective_owner_id TEXT NOT NULL
                        CHECK (
                            length(trim(perspective_owner_id)) > 0
                            AND perspective_owner_id != '{SYNTHETIC_UNATTRIBUTED_INSTANCE_ID}'
                        ),
                    perspective_instance_id TEXT NOT NULL
                        CHECK (
                            length(trim(perspective_instance_id)) > 0
                            AND perspective_instance_id != '{SYNTHETIC_UNATTRIBUTED_INSTANCE_ID}'
                        ),
                    about_subject_id TEXT NOT NULL
                        CHECK (
                            length(trim(about_subject_id)) > 0
                            AND about_subject_id != '{SYNTHETIC_UNATTRIBUTED_INSTANCE_ID}'
                        ),
                    access_domain_id TEXT NOT NULL
                        CHECK (
                            length(trim(access_domain_id)) > 0
                            AND access_domain_id != '{SYNTHETIC_UNATTRIBUTED_INSTANCE_ID}'
                        ),
                    created_by_principal_id TEXT NOT NULL
                        CHECK (
                            length(trim(created_by_principal_id)) > 0
                            AND created_by_principal_id != '__synthetic_unattributed__'
                        ),
                    created_by_principal_kind TEXT NOT NULL
                        CHECK (length(trim(created_by_principal_kind)) > 0),
                    created_by_trust_source TEXT NOT NULL
                        CHECK (length(trim(created_by_trust_source)) > 0),
                    operation_id TEXT NOT NULL UNIQUE
                        CHECK (length(trim(operation_id)) > 0),
                    recorded_at_utc TEXT NOT NULL
                        CHECK (length(trim(recorded_at_utc)) > 0),
                    write_policy_id TEXT NOT NULL
                        CHECK (length(trim(write_policy_id)) > 0),
                    UNIQUE (
                        thread_id,
                        perspective_owner_id,
                        perspective_instance_id,
                        about_subject_id,
                        access_domain_id
                    )
                );

                CREATE TABLE IF NOT EXISTS real_thread_memberships (
                    admission_id TEXT PRIMARY KEY
                        CHECK (length(trim(admission_id)) > 0),
                    thread_id TEXT NOT NULL,
                    interpretation_id TEXT NOT NULL UNIQUE,
                    perspective_owner_id TEXT NOT NULL,
                    perspective_instance_id TEXT NOT NULL,
                    about_subject_id TEXT NOT NULL,
                    access_domain_id TEXT NOT NULL,
                    admitted_by_principal_id TEXT NOT NULL
                        CHECK (
                            length(trim(admitted_by_principal_id)) > 0
                            AND admitted_by_principal_id != '__synthetic_unattributed__'
                        ),
                    admitted_by_principal_kind TEXT NOT NULL
                        CHECK (length(trim(admitted_by_principal_kind)) > 0),
                    admitted_by_trust_source TEXT NOT NULL
                        CHECK (length(trim(admitted_by_trust_source)) > 0),
                    operation_id TEXT NOT NULL UNIQUE
                        CHECK (length(trim(operation_id)) > 0),
                    recorded_at_utc TEXT NOT NULL
                        CHECK (length(trim(recorded_at_utc)) > 0),
                    write_policy_id TEXT NOT NULL
                        CHECK (length(trim(write_policy_id)) > 0),
                    FOREIGN KEY (
                        thread_id,
                        perspective_owner_id,
                        perspective_instance_id,
                        about_subject_id,
                        access_domain_id
                    ) REFERENCES real_threads(
                        thread_id,
                        perspective_owner_id,
                        perspective_instance_id,
                        about_subject_id,
                        access_domain_id
                    ) ON UPDATE RESTRICT ON DELETE RESTRICT,
                    FOREIGN KEY (
                        interpretation_id,
                        perspective_owner_id,
                        perspective_instance_id,
                        about_subject_id,
                        access_domain_id
                    ) REFERENCES real_interpretations(
                        interpretation_id,
                        perspective_owner_id,
                        perspective_instance_id,
                        about_subject_id,
                        access_domain_id
                    ) ON UPDATE RESTRICT ON DELETE RESTRICT
                );
                """
            )
    finally:
        connection.close()


def _require_relationship_capability(
    capability: ClosedRealRelationshipExerciseCapability,
) -> None:
    if not isinstance(capability, ClosedRealRelationshipExerciseCapability):
        raise RealRelationshipDisabledError(
            "closed real relationship writer requires trusted exercise capability"
        )
    if capability._marker is not _CLOSED_REAL_RELATIONSHIP_CAPABILITY_MARKER:
        raise RealRelationshipDisabledError("real relationship capability is invalid")


def _require_relationship_policy(
    policy: SingleOwnerRealRelationshipWritePolicy,
) -> None:
    if not isinstance(policy, SingleOwnerRealRelationshipWritePolicy):
        raise RealRelationshipAuthorizationError(
            "relationship writer requires a trusted relationship policy"
        )
    if policy._marker is not _TRUSTED_RELATIONSHIP_WRITE_POLICY_MARKER:
        raise RealRelationshipAuthorizationError("relationship policy is invalid")


def _validate_interpretation_input(
    *,
    interpretation_id: str,
    text: str,
    identity: RealRelationshipIdentity,
    evidence: tuple[EvidenceRef, ...],
) -> None:
    if not isinstance(interpretation_id, str) or not interpretation_id.strip():
        raise ValueError("interpretation_id cannot be empty")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("interpretation text cannot be empty")
    if not isinstance(identity, RealRelationshipIdentity):
        raise TypeError("identity must be RealRelationshipIdentity")
    if not isinstance(evidence, tuple) or not evidence:
        raise ValueError("real interpretation requires evidence")
    if any(not isinstance(item, EvidenceRef) for item in evidence):
        raise TypeError("evidence must contain EvidenceRef values")
    if len(set(evidence)) != len(evidence):
        raise ValueError("duplicate evidence references are not allowed")


def _validate_thread_input(
    *,
    thread_id: str,
    question: str,
    identity: RealRelationshipIdentity,
) -> None:
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError("thread_id cannot be empty")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("thread question cannot be empty")
    if not isinstance(identity, RealRelationshipIdentity):
        raise TypeError("identity must be RealRelationshipIdentity")


def _validate_evidence_dependencies(
    *,
    connection: sqlite3.Connection,
    identity: RealRelationshipIdentity,
    evidence: tuple[EvidenceRef, ...],
) -> None:
    for item in evidence:
        row = connection.execute(
            """
            SELECT content, content_sha256, access_domain_id
            FROM real_sources
            WHERE source_id = ?
            """,
            (item.source_id,),
        ).fetchone()
        if row is None:
            raise RealRelationshipIntegrityError("evidence source is missing")
        content, stored_hash, stored_domain = row
        if stored_domain != identity.access_domain_id.value:
            raise RealRelationshipAuthorizationError(
                "relationship cannot reference a source outside its access domain"
            )
        actual_hash = sha256(content.encode("utf-8")).hexdigest()
        if stored_hash != item.source_sha256 or actual_hash != stored_hash:
            raise RealRelationshipIntegrityError(
                "evidence hash does not match persisted source"
            )
        if item.start_char < 0 or item.end_char <= item.start_char:
            raise RealRelationshipIntegrityError("evidence offsets are invalid")
        if item.end_char > len(content):
            raise RealRelationshipIntegrityError(
                "evidence range exceeds persisted source content"
            )


def _load_relationship_identity(
    *,
    connection: sqlite3.Connection,
    table: str,
    id_column: str,
    resource_id: str,
) -> RealRelationshipIdentity:
    if table not in {"real_interpretations", "real_threads"}:
        raise ValueError("unsupported relationship table")
    if id_column not in {"interpretation_id", "thread_id"}:
        raise ValueError("unsupported relationship id column")
    row = connection.execute(
        f"""
        SELECT
            perspective_owner_id,
            perspective_instance_id,
            about_subject_id,
            access_domain_id
        FROM {table}
        WHERE {id_column} = ?
        """,
        (resource_id,),
    ).fetchone()
    if row is None:
        raise RealRelationshipIntegrityError("relationship endpoint is missing")
    return RealRelationshipIdentity(
        perspective_owner=PerspectiveOwnerId(row[0]),
        perspective_instance=PerspectiveInstanceId(row[1]),
        about_subject=SubjectId(row[2]),
        access_domain_id=AccessDomainId(row[3]),
    )


def _open_write_connection(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _assert_real_source_schema(connection: sqlite3.Connection) -> None:
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
            "closed real source-ingress schema has not been initialized"
        )


def _assert_relationship_schema(connection: sqlite3.Connection) -> None:
    required = {
        "real_interpretations",
        "real_interpretation_evidence",
        "real_threads",
        "real_thread_memberships",
    }
    existing = {
        row[0]
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN (
                    'real_interpretations',
                    'real_interpretation_evidence',
                    'real_threads',
                    'real_thread_memberships'
              )
            """
        ).fetchall()
    }
    if existing != required:
        raise RealRelationshipIntegrityError(
            "closed real relationship schema has not been initialized"
        )


def _receipt(
    *,
    kind: str,
    resource_id: str,
    context: OperationContext,
    domain: AccessDomainId,
    policy_id: str,
    recorded_at: str,
) -> RealRelationshipReceipt:
    return RealRelationshipReceipt(
        receipt_id=f"real-relationship-receipt-{uuid4().hex}",
        relationship_kind=kind,
        resource_id=resource_id,
        operation_id=context.operation_id,
        principal_id=context.principal.principal_id,
        access_domain_id=domain,
        policy_id=policy_id,
        recorded_at_utc=recorded_at,
    )


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00",
        "Z",
    )
