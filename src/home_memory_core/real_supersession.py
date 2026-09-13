from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

from home_memory_core.evidence import EvidenceRef
from home_memory_core.identity_namespaces import AccessDomainId
from home_memory_core.operation_identity import (
    OperationClass,
    OperationContext,
    PrincipalId,
    require_operation_context,
)
from home_memory_core.real_relationships import (
    RealRelationshipAuthorizationError,
    RealRelationshipIdentity,
    RealRelationshipIntegrityError,
    SingleOwnerRealRelationshipWritePolicy,
    _assert_relationship_schema,
    _require_relationship_capability,
    _require_relationship_policy,
    _validate_evidence_dependencies,
    ClosedRealRelationshipExerciseCapability,
)
from home_memory_core.real_authority_ordering import (
    capture_real_store_generation,
    real_authority_maintenance,
    real_authority_operation,
)
from home_memory_core.real_use_state import (
    RealUseStateIntegrityError,
    assert_interpretation_usable,
    assert_real_stop_use_schema,
    assert_source_ids_usable,
)
from home_memory_core.store_domain import assert_real_store_domain


_CLOSED_REAL_SUPERSESSION_CAPABILITY_MARKER = object()


class RealSupersessionDisabledError(RuntimeError):
    """Closed real supersession-writing is not available to runtime callers."""


class RealSupersessionIntegrityError(RuntimeError):
    """A supersession write violated topology or endpoint integrity."""


@dataclass(frozen=True)
class ClosedRealSupersessionExerciseCapability:
    """Synthetic-fixture-only capability for supersession exercises."""

    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _CLOSED_REAL_SUPERSESSION_CAPABILITY_MARKER:
            raise RealSupersessionDisabledError(
                "closed real supersession capability cannot be caller-minted"
            )


@dataclass(frozen=True)
class RealSupersessionReceipt:
    receipt_id: str
    supersession_id: str
    previous_interpretation_id: str
    new_interpretation_id: str
    thread_id: str
    operation_id: str
    principal_id: PrincipalId
    access_domain_id: AccessDomainId
    policy_id: str
    recorded_at_utc: str
    authority: str = "none"


@dataclass(frozen=True)
class _AdmittedEndpoint:
    thread_id: str
    interpretation_id: str
    identity: RealRelationshipIdentity


class ClosedRealSupersessionWriter:
    """Exercise supersession writes while the real-data gate remains closed.

    A supersession is accepted only when both persisted interpretations are
    already admitted to the same thread, share the same semantic identity and
    authorization domain, and every reason-evidence source lives in that same
    domain. The proposed edge is validated against the complete persisted
    thread topology before commit.
    """

    def __init__(
        self,
        *,
        db_path: str | Path,
        capability: ClosedRealSupersessionExerciseCapability,
        relationship_capability: ClosedRealRelationshipExerciseCapability,
        policy: SingleOwnerRealRelationshipWritePolicy,
    ) -> None:
        _require_supersession_capability(capability)
        _require_relationship_capability(relationship_capability)
        _require_relationship_policy(policy)
        self.db_path = Path(db_path)
        self._capability = capability
        self._relationship_capability = relationship_capability
        self._policy = policy
        self._authority_generation = capture_real_store_generation(self.db_path)

    def write_supersession(
        self,
        *,
        context: OperationContext,
        supersession_id: str,
        previous_interpretation_id: str,
        new_interpretation_id: str,
        reason_evidence: tuple[EvidenceRef, ...],
    ) -> RealSupersessionReceipt:
        _require_supersession_capability(self._capability)
        _require_relationship_capability(self._relationship_capability)
        _require_relationship_policy(self._policy)
        _validate_input(
            supersession_id=supersession_id,
            previous_interpretation_id=previous_interpretation_id,
            new_interpretation_id=new_interpretation_id,
            reason_evidence=reason_evidence,
        )
        recorded_at = _utc_now_text()

        with real_authority_operation(
            self.db_path, expected_generation=self._authority_generation
        ):
            require_operation_context(
                context,
                expected_operation_class=OperationClass.SUPERSESSION_WRITE,
            )
            connection = _open_write_connection(self.db_path)
            try:
                connection.execute("BEGIN IMMEDIATE")
                assert_real_store_domain(connection)
                _assert_relationship_schema(connection)
                _assert_supersession_schema(connection)
                try:
                    assert_real_stop_use_schema(connection)
                except RealUseStateIntegrityError as error:
                    raise RealSupersessionIntegrityError(
                        "closed real stop-use state has not been initialized"
                    ) from error

                previous = _load_admitted_endpoint(
                    connection=connection,
                    interpretation_id=previous_interpretation_id,
                )
                new = _load_admitted_endpoint(
                    connection=connection,
                    interpretation_id=new_interpretation_id,
                )
                if previous.thread_id != new.thread_id:
                    raise RealSupersessionIntegrityError(
                        "supersession cannot cross thread boundaries"
                    )
                if previous.identity != new.identity:
                    raise RealSupersessionIntegrityError(
                        "supersession cannot cross identity or access-domain boundaries"
                    )

                self._policy.authorize(
                    context=context,
                    expected_operation_class=OperationClass.SUPERSESSION_WRITE,
                    identity=previous.identity,
                )
                assert_interpretation_usable(connection, previous_interpretation_id)
                assert_interpretation_usable(connection, new_interpretation_id)
                try:
                    _validate_evidence_dependencies(
                        connection=connection,
                        identity=previous.identity,
                        evidence=reason_evidence,
                    )
                except RealRelationshipAuthorizationError:
                    raise
                except RealRelationshipIntegrityError as error:
                    raise RealSupersessionIntegrityError(
                        "supersession reason evidence is invalid"
                    ) from error
                assert_source_ids_usable(
                    connection,
                    (item.source_id for item in reason_evidence),
                )

                _validate_proposed_topology(
                    connection=connection,
                    thread_id=previous.thread_id,
                    previous_interpretation_id=previous_interpretation_id,
                    new_interpretation_id=new_interpretation_id,
                )

                try:
                    # Reason rows are inserted first under a deferred FK. The
                    # parent insert has an AFTER trigger requiring at least one
                    # reason row, so even raw SQL cannot create a reasonless
                    # supersession head.
                    for position, item in enumerate(reason_evidence):
                        connection.execute(
                            """
                            INSERT INTO real_supersession_reason_evidence (
                                supersession_id,
                                position,
                                source_id,
                                source_sha256,
                                start_char,
                                end_char,
                                access_domain_id
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                supersession_id,
                                position,
                                item.source_id,
                                item.source_sha256,
                                item.start_char,
                                item.end_char,
                                previous.identity.access_domain_id.value,
                            ),
                        )
                    connection.execute(
                        """
                        INSERT INTO real_supersessions (
                            supersession_id,
                            previous_interpretation_id,
                            new_interpretation_id,
                            thread_id,
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
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            supersession_id,
                            previous_interpretation_id,
                            new_interpretation_id,
                            previous.thread_id,
                            previous.identity.perspective_owner.value,
                            previous.identity.perspective_instance.value,
                            previous.identity.about_subject.value,
                            previous.identity.access_domain_id.value,
                            context.principal.principal_id.value,
                            context.principal.principal_kind,
                            context.principal.trust_source,
                            context.operation_id,
                            recorded_at,
                            self._policy.policy_id,
                        ),
                    )
                except sqlite3.IntegrityError as error:
                    raise RealSupersessionIntegrityError(
                        "real supersession could not be stored"
                    ) from error

                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

        return RealSupersessionReceipt(
            receipt_id=f"real-supersession-receipt-{uuid4().hex}",
            supersession_id=supersession_id,
            previous_interpretation_id=previous_interpretation_id,
            new_interpretation_id=new_interpretation_id,
            thread_id=previous.thread_id,
            operation_id=context.operation_id,
            principal_id=context.principal.principal_id,
            access_domain_id=previous.identity.access_domain_id,
            policy_id=self._policy.policy_id,
            recorded_at_utc=recorded_at,
        )


def initialize_closed_real_supersession_schema(
    *,
    db_path: str | Path,
    relationship_capability: ClosedRealRelationshipExerciseCapability,
    supersession_capability: ClosedRealSupersessionExerciseCapability,
) -> None:
    """Add closed supersession tables only to an initialized real relationship store."""

    _require_relationship_capability(relationship_capability)
    _require_supersession_capability(supersession_capability)
    path = Path(db_path)
    with real_authority_maintenance(path):
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                assert_real_store_domain(connection)
                _assert_relationship_schema(connection)
                connection.executescript(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS real_thread_membership_endpoint_key
                    ON real_thread_memberships (
                        thread_id,
                        interpretation_id,
                        perspective_owner_id,
                        perspective_instance_id,
                        about_subject_id,
                        access_domain_id
                    );

                CREATE TABLE IF NOT EXISTS real_supersessions (
                    supersession_id TEXT PRIMARY KEY
                        CHECK (length(trim(supersession_id)) > 0),
                    previous_interpretation_id TEXT NOT NULL,
                    new_interpretation_id TEXT NOT NULL UNIQUE,
                    thread_id TEXT NOT NULL,
                    perspective_owner_id TEXT NOT NULL,
                    perspective_instance_id TEXT NOT NULL,
                    about_subject_id TEXT NOT NULL,
                    access_domain_id TEXT NOT NULL,
                    created_by_principal_id TEXT NOT NULL
                        CHECK (length(trim(created_by_principal_id)) > 0),
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
                    CHECK (previous_interpretation_id != new_interpretation_id),
                    UNIQUE (previous_interpretation_id, new_interpretation_id),
                    UNIQUE (supersession_id, access_domain_id),
                    FOREIGN KEY (
                        thread_id,
                        previous_interpretation_id,
                        perspective_owner_id,
                        perspective_instance_id,
                        about_subject_id,
                        access_domain_id
                    ) REFERENCES real_thread_memberships (
                        thread_id,
                        interpretation_id,
                        perspective_owner_id,
                        perspective_instance_id,
                        about_subject_id,
                        access_domain_id
                    ) ON UPDATE RESTRICT ON DELETE RESTRICT,
                    FOREIGN KEY (
                        thread_id,
                        new_interpretation_id,
                        perspective_owner_id,
                        perspective_instance_id,
                        about_subject_id,
                        access_domain_id
                    ) REFERENCES real_thread_memberships (
                        thread_id,
                        interpretation_id,
                        perspective_owner_id,
                        perspective_instance_id,
                        about_subject_id,
                        access_domain_id
                    ) ON UPDATE RESTRICT ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS real_supersession_reason_evidence (
                    supersession_id TEXT NOT NULL,
                    position INTEGER NOT NULL CHECK (position >= 0),
                    source_id TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
                    start_char INTEGER NOT NULL CHECK (start_char >= 0),
                    end_char INTEGER NOT NULL CHECK (end_char > start_char),
                    access_domain_id TEXT NOT NULL,
                    PRIMARY KEY (supersession_id, position),
                    UNIQUE (
                        supersession_id,
                        source_id,
                        source_sha256,
                        start_char,
                        end_char
                    ),
                    FOREIGN KEY (supersession_id, access_domain_id)
                        REFERENCES real_supersessions(
                            supersession_id,
                            access_domain_id
                        ) ON UPDATE RESTRICT ON DELETE RESTRICT
                        DEFERRABLE INITIALLY DEFERRED,
                    FOREIGN KEY (source_id, source_sha256, access_domain_id)
                        REFERENCES real_sources(
                            source_id,
                            content_sha256,
                            access_domain_id
                        ) ON UPDATE RESTRICT ON DELETE RESTRICT
                );

                CREATE TRIGGER IF NOT EXISTS real_supersessions_require_reason_evidence
                AFTER INSERT ON real_supersessions
                WHEN NOT EXISTS (
                    SELECT 1
                    FROM real_supersession_reason_evidence
                    WHERE supersession_id = NEW.supersession_id
                )
                BEGIN
                    SELECT RAISE(ABORT, 'real supersession requires reason evidence');
                END;

                CREATE TRIGGER IF NOT EXISTS real_supersession_reason_preserve_last
                BEFORE DELETE ON real_supersession_reason_evidence
                WHEN (
                    SELECT COUNT(*)
                    FROM real_supersession_reason_evidence
                    WHERE supersession_id = OLD.supersession_id
                ) <= 1
                BEGIN
                    SELECT RAISE(ABORT, 'real supersession must retain reason evidence');
                END;

                CREATE TRIGGER IF NOT EXISTS real_supersessions_prevent_cycle
                BEFORE INSERT ON real_supersessions
                BEGIN
                    SELECT CASE WHEN EXISTS (
                        WITH RECURSIVE descendants(interpretation_id) AS (
                            SELECT new_interpretation_id
                            FROM real_supersessions
                            WHERE thread_id = NEW.thread_id
                              AND previous_interpretation_id = NEW.new_interpretation_id
                            UNION
                            SELECT s.new_interpretation_id
                            FROM real_supersessions AS s
                            JOIN descendants AS d
                              ON s.previous_interpretation_id = d.interpretation_id
                            WHERE s.thread_id = NEW.thread_id
                        )
                        SELECT 1
                        FROM descendants
                        WHERE interpretation_id = NEW.previous_interpretation_id
                    ) THEN RAISE(ABORT, 'real supersession cycle') END;
                END;
                """
                )
        finally:
            connection.close()


def _validate_input(
    *,
    supersession_id: str,
    previous_interpretation_id: str,
    new_interpretation_id: str,
    reason_evidence: tuple[EvidenceRef, ...],
) -> None:
    for field_name, value in {
        "supersession_id": supersession_id,
        "previous_interpretation_id": previous_interpretation_id,
        "new_interpretation_id": new_interpretation_id,
    }.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} cannot be empty")
    if previous_interpretation_id == new_interpretation_id:
        raise RealSupersessionIntegrityError(
            "an interpretation cannot supersede itself"
        )
    if not isinstance(reason_evidence, tuple) or not reason_evidence:
        raise ValueError("supersession requires reason evidence")
    if any(not isinstance(item, EvidenceRef) for item in reason_evidence):
        raise TypeError("reason_evidence must contain EvidenceRef values")
    if len(set(reason_evidence)) != len(reason_evidence):
        raise ValueError("duplicate reason evidence is not allowed")


def _load_admitted_endpoint(
    *,
    connection: sqlite3.Connection,
    interpretation_id: str,
) -> _AdmittedEndpoint:
    row = connection.execute(
        """
        SELECT
            thread_id,
            interpretation_id,
            perspective_owner_id,
            perspective_instance_id,
            about_subject_id,
            access_domain_id
        FROM real_thread_memberships
        WHERE interpretation_id = ?
        """,
        (interpretation_id,),
    ).fetchone()
    if row is None:
        raise RealSupersessionIntegrityError(
            "supersession endpoint must already be admitted to a thread"
        )
    from home_memory_core.identity_namespaces import (
        PerspectiveInstanceId,
        PerspectiveOwnerId,
        SubjectId,
    )

    return _AdmittedEndpoint(
        thread_id=row[0],
        interpretation_id=row[1],
        identity=RealRelationshipIdentity(
            perspective_owner=PerspectiveOwnerId(row[2]),
            perspective_instance=PerspectiveInstanceId(row[3]),
            about_subject=SubjectId(row[4]),
            access_domain_id=AccessDomainId(row[5]),
        ),
    )


def _validate_proposed_topology(
    *,
    connection: sqlite3.Connection,
    thread_id: str,
    previous_interpretation_id: str,
    new_interpretation_id: str,
) -> None:
    edges = connection.execute(
        """
        SELECT previous_interpretation_id, new_interpretation_id
        FROM real_supersessions
        WHERE thread_id = ?
        """,
        (thread_id,),
    ).fetchall()
    proposed = [*edges, (previous_interpretation_id, new_interpretation_id)]

    seen: set[tuple[str, str]] = set()
    incoming_parent: dict[str, str] = {}
    adjacency: dict[str, set[str]] = {}
    all_ids: set[str] = set()

    for previous_id, new_id in proposed:
        edge = (previous_id, new_id)
        if previous_id == new_id:
            raise RealSupersessionIntegrityError("supersession graph contains self-loop")
        if edge in seen:
            raise RealSupersessionIntegrityError("supersession graph contains duplicate edge")
        existing_parent = incoming_parent.get(new_id)
        if existing_parent is not None and existing_parent != previous_id:
            raise RealSupersessionIntegrityError(
                "supersession graph contains implicit reconvergence"
            )
        incoming_parent[new_id] = previous_id
        seen.add(edge)
        adjacency.setdefault(previous_id, set()).add(new_id)
        all_ids.add(previous_id)
        all_ids.add(new_id)

    visited: set[str] = set()
    active: set[str] = set()

    def visit(interpretation_id: str) -> None:
        if interpretation_id in active:
            raise RealSupersessionIntegrityError("supersession graph contains a cycle")
        if interpretation_id in visited:
            return
        active.add(interpretation_id)
        for next_id in adjacency.get(interpretation_id, set()):
            visit(next_id)
        active.remove(interpretation_id)
        visited.add(interpretation_id)

    for interpretation_id in all_ids:
        visit(interpretation_id)


def _assert_supersession_schema(connection: sqlite3.Connection) -> None:
    required = {"real_supersessions", "real_supersession_reason_evidence"}
    existing = {
        row[0]
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN ('real_supersessions', 'real_supersession_reason_evidence')
            """
        ).fetchall()
    }
    if existing != required:
        raise RealSupersessionIntegrityError(
            "closed real supersession schema has not been initialized"
        )


def _require_supersession_capability(
    capability: ClosedRealSupersessionExerciseCapability,
) -> None:
    if not isinstance(capability, ClosedRealSupersessionExerciseCapability):
        raise RealSupersessionDisabledError(
            "closed real supersession writer requires trusted exercise capability"
        )
    if capability._marker is not _CLOSED_REAL_SUPERSESSION_CAPABILITY_MARKER:
        raise RealSupersessionDisabledError("real supersession capability is invalid")


def _open_write_connection(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00",
        "Z",
    )
