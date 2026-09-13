from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
import sqlite3
from uuid import uuid4

from home_memory_core.identity_namespaces import AccessDomainId
from home_memory_core.operation_identity import (
    OperationClass,
    OperationContext,
    PrincipalId,
    require_operation_context,
)
from home_memory_core.real_authority_ordering import (
    capture_real_store_generation,
    real_authority_maintenance,
    real_authority_operation,
)
from home_memory_core.real_ingress import RealIngressIntegrityError
from home_memory_core.real_use_state import (
    SOURCE_DOMAIN_INDEX,
    STOP_USE_SCHEMA_MARKER_TABLE,
    STOP_USE_SCHEMA_VERSION,
    SUPPRESSION_TABLE,
    RealUseStateIntegrityError,
    assert_real_stop_use_schema,
)
from home_memory_core.store_domain import assert_real_store_domain


_CLOSED_REAL_STOP_USE_CAPABILITY_MARKER = object()
_TRUSTED_STOP_USE_POLICY_MARKER = object()


class RealStopUseDisabledError(RuntimeError):
    """Closed real stop-use is unavailable to normal runtime callers."""


class RealStopUseAuthorizationError(PermissionError):
    """A real stop-use operation was denied by trusted policy."""


class RealStopUseIntegrityError(RuntimeError):
    """A stop-use operation or persisted stop-use state failed an invariant."""


class StopUseReasonCode(StrEnum):
    USER_STOP_USE = "user_stop_use"
    USER_REQUEST = "user_request"
    TEST_FIXTURE = "test_fixture"


@dataclass(frozen=True)
class ClosedRealStopUseExerciseCapability:
    """Synthetic-fixture-only capability; there is no production minting path."""

    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _CLOSED_REAL_STOP_USE_CAPABILITY_MARKER:
            raise RealStopUseDisabledError(
                "closed real stop-use capability cannot be caller-minted"
            )


@dataclass(frozen=True)
class SingleOwnerRealStopUsePolicy:
    """One-owner, one-domain policy for first-pilot source stop-use exercises."""

    policy_id: str
    owner_principal_id: PrincipalId
    access_domain_id: AccessDomainId
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _TRUSTED_STOP_USE_POLICY_MARKER:
            raise RealStopUseAuthorizationError(
                "stop-use policy must come from trusted policy code"
            )
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise RealStopUseAuthorizationError("policy_id cannot be empty")
        if not isinstance(self.owner_principal_id, PrincipalId):
            raise RealStopUseAuthorizationError(
                "owner_principal_id must use PrincipalId"
            )
        if not isinstance(self.access_domain_id, AccessDomainId):
            raise RealStopUseAuthorizationError(
                "access_domain_id must use AccessDomainId"
            )

    def authorize_source_suppress(
        self,
        *,
        context: OperationContext,
        persisted_access_domain_id: AccessDomainId,
    ) -> None:
        require_operation_context(
            context,
            expected_operation_class=OperationClass.SOURCE_SUPPRESS,
        )
        if context.principal.principal_id != self.owner_principal_id:
            raise RealStopUseAuthorizationError("source.suppress denied")
        if persisted_access_domain_id != self.access_domain_id:
            raise RealStopUseAuthorizationError("source.suppress denied")


@dataclass(frozen=True)
class RealSourceSuppressionReceipt:
    suppression_id: str
    source_id: str
    access_domain_id: AccessDomainId
    operation_id: str
    requested_by_principal_id: PrincipalId
    reason_code: StopUseReasonCode
    recorded_at_utc: str
    policy_id: str
    status: str
    authority: str = "none"


class ClosedRealStopUseWriter:
    """Persist one-way source stop-use through the closed real authority boundary."""

    def __init__(
        self,
        *,
        db_path: str | Path,
        capability: ClosedRealStopUseExerciseCapability,
        policy: SingleOwnerRealStopUsePolicy,
    ) -> None:
        _require_stop_use_capability(capability)
        _require_stop_use_policy(policy)
        self.db_path = Path(db_path)
        self._capability = capability
        self._policy = policy
        self._authority_generation = capture_real_store_generation(self.db_path)

    def suppress_source(
        self,
        *,
        context: OperationContext,
        source_id: str,
        reason_code: StopUseReasonCode,
    ) -> RealSourceSuppressionReceipt:
        _require_stop_use_capability(self._capability)
        _require_stop_use_policy(self._policy)
        require_operation_context(
            context,
            expected_operation_class=OperationClass.SOURCE_SUPPRESS,
        )
        _validate_suppression_input(
            source_id=source_id,
            reason_code=reason_code,
        )
        recorded_at = _utc_now_text()

        with real_authority_operation(
            self.db_path,
            expected_generation=self._authority_generation,
        ):
            connection = _open_write_connection(self.db_path)
            try:
                connection.execute("BEGIN IMMEDIATE")
                assert_real_store_domain(connection)
                try:
                    assert_real_stop_use_schema(connection)
                except RealUseStateIntegrityError as error:
                    raise RealStopUseIntegrityError(
                        "real stop-use schema is unavailable"
                    ) from error

                row = connection.execute(
                    "SELECT access_domain_id FROM real_sources WHERE source_id = ?",
                    (source_id,),
                ).fetchone()
                if row is None:
                    raise RealStopUseIntegrityError("source is missing")
                persisted_domain = AccessDomainId(row[0])
                self._policy.authorize_source_suppress(
                    context=context,
                    persisted_access_domain_id=persisted_domain,
                )

                operation_row = connection.execute(
                    f"""
                    SELECT
                        suppression_id,
                        source_id,
                        access_domain_id,
                        requested_by_principal_id,
                        requested_by_principal_kind,
                        requested_by_trust_source,
                        reason_code,
                        recorded_at_utc,
                        policy_id
                    FROM {SUPPRESSION_TABLE}
                    WHERE operation_id = ?
                    """,
                    (context.operation_id,),
                ).fetchone()
                if operation_row is not None:
                    if (
                        operation_row[1] != source_id
                        or operation_row[2] != persisted_domain.value
                        or operation_row[3] != context.principal.principal_id.value
                        or operation_row[4] != context.principal.principal_kind
                        or operation_row[5] != context.principal.trust_source
                        or operation_row[6] != reason_code.value
                        or operation_row[8] != self._policy.policy_id
                    ):
                        raise RealStopUseIntegrityError(
                            "operation_id is already bound to a different suppression"
                        )
                    connection.commit()
                    return RealSourceSuppressionReceipt(
                        suppression_id=operation_row[0],
                        source_id=operation_row[1],
                        access_domain_id=AccessDomainId(operation_row[2]),
                        operation_id=context.operation_id,
                        requested_by_principal_id=PrincipalId(operation_row[3]),
                        reason_code=StopUseReasonCode(operation_row[6]),
                        recorded_at_utc=operation_row[7],
                        policy_id=operation_row[8],
                        status="already_suppressed",
                    )

                existing_row = connection.execute(
                    f"""
                    SELECT
                        suppression_id,
                        source_id,
                        access_domain_id,
                        requested_by_principal_id,
                        reason_code,
                        recorded_at_utc,
                        policy_id,
                        operation_id
                    FROM {SUPPRESSION_TABLE}
                    WHERE source_id = ?
                    """,
                    (source_id,),
                ).fetchone()
                if existing_row is not None:
                    connection.commit()
                    return RealSourceSuppressionReceipt(
                        suppression_id=existing_row[0],
                        source_id=existing_row[1],
                        access_domain_id=AccessDomainId(existing_row[2]),
                        operation_id=existing_row[7],
                        requested_by_principal_id=PrincipalId(existing_row[3]),
                        reason_code=StopUseReasonCode(existing_row[4]),
                        recorded_at_utc=existing_row[5],
                        policy_id=existing_row[6],
                        status="already_suppressed",
                    )

                suppression_id = f"real-suppression-{uuid4().hex}"
                try:
                    connection.execute(
                        f"""
                        INSERT INTO {SUPPRESSION_TABLE} (
                            suppression_id,
                            source_id,
                            access_domain_id,
                            requested_by_principal_id,
                            requested_by_principal_kind,
                            requested_by_trust_source,
                            operation_id,
                            reason_code,
                            recorded_at_utc,
                            policy_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            suppression_id,
                            source_id,
                            persisted_domain.value,
                            context.principal.principal_id.value,
                            context.principal.principal_kind,
                            context.principal.trust_source,
                            context.operation_id,
                            reason_code.value,
                            recorded_at,
                            self._policy.policy_id,
                        ),
                    )
                except sqlite3.IntegrityError as error:
                    raise RealStopUseIntegrityError(
                        "source suppression could not be stored"
                    ) from error
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

        return RealSourceSuppressionReceipt(
            suppression_id=suppression_id,
            source_id=source_id,
            access_domain_id=persisted_domain,
            operation_id=context.operation_id,
            requested_by_principal_id=context.principal.principal_id,
            reason_code=reason_code,
            recorded_at_utc=recorded_at,
            policy_id=self._policy.policy_id,
            status="suppressed",
        )


def initialize_closed_real_stop_use_schema(
    *,
    db_path: str | Path,
    capability: ClosedRealStopUseExerciseCapability,
) -> None:
    """Install/validate stop-use state in an initialized closed real source store.

    After the feature marker exists, missing tables/indexes/triggers fail closed;
    this function never silently recreates an empty suppression state.
    """

    _require_stop_use_capability(capability)
    path = Path(db_path)
    with real_authority_maintenance(path):
        connection = _open_write_connection(path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            assert_real_store_domain(connection)
            _assert_real_source_schema(connection)

            marker_exists = _object_exists(
                connection, "table", STOP_USE_SCHEMA_MARKER_TABLE
            )
            stop_use_artifacts = _existing_stop_use_artifacts(connection)
            if marker_exists:
                try:
                    assert_real_stop_use_schema(connection)
                except RealUseStateIntegrityError as error:
                    raise RealStopUseIntegrityError(
                        "existing stop-use feature is damaged; refusing repair-as-empty"
                    ) from error
                connection.commit()
                return
            if stop_use_artifacts:
                raise RealStopUseIntegrityError(
                    "partial stop-use schema exists without its feature marker"
                )

            _create_stop_use_schema(connection)
            try:
                assert_real_stop_use_schema(connection)
            except RealUseStateIntegrityError as error:
                raise RealStopUseIntegrityError(
                    "stop-use schema initialization failed validation"
                ) from error
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _create_stop_use_schema(connection: sqlite3.Connection) -> None:
    reason_codes = ", ".join(f"'{code.value}'" for code in StopUseReasonCode)
    connection.executescript(
        f"""
        CREATE UNIQUE INDEX {SOURCE_DOMAIN_INDEX}
            ON real_sources(source_id, access_domain_id);

        CREATE TABLE {STOP_USE_SCHEMA_MARKER_TABLE} (
            marker_key TEXT NOT NULL PRIMARY KEY
                CHECK (marker_key = 'stop_use_schema'),
            schema_version TEXT NOT NULL
                CHECK (schema_version = '{STOP_USE_SCHEMA_VERSION}')
        );

        INSERT INTO {STOP_USE_SCHEMA_MARKER_TABLE} (marker_key, schema_version)
        VALUES ('stop_use_schema', '{STOP_USE_SCHEMA_VERSION}');

        CREATE TABLE {SUPPRESSION_TABLE} (
            suppression_id TEXT NOT NULL PRIMARY KEY
                CHECK (length(trim(suppression_id)) > 0),
            source_id TEXT NOT NULL UNIQUE
                CHECK (length(trim(source_id)) > 0),
            access_domain_id TEXT NOT NULL
                CHECK (length(trim(access_domain_id)) > 0),
            requested_by_principal_id TEXT NOT NULL
                CHECK (length(trim(requested_by_principal_id)) > 0),
            requested_by_principal_kind TEXT NOT NULL
                CHECK (length(trim(requested_by_principal_kind)) > 0),
            requested_by_trust_source TEXT NOT NULL
                CHECK (length(trim(requested_by_trust_source)) > 0),
            operation_id TEXT NOT NULL UNIQUE
                CHECK (length(trim(operation_id)) > 0),
            reason_code TEXT NOT NULL
                CHECK (reason_code IN ({reason_codes})),
            recorded_at_utc TEXT NOT NULL
                CHECK (length(trim(recorded_at_utc)) > 0),
            policy_id TEXT NOT NULL
                CHECK (length(trim(policy_id)) > 0),
            FOREIGN KEY (source_id, access_domain_id)
                REFERENCES real_sources(source_id, access_domain_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT
        );

        CREATE TRIGGER real_stop_use_schema_marker_no_update
        BEFORE UPDATE ON {STOP_USE_SCHEMA_MARKER_TABLE}
        BEGIN
            SELECT RAISE(ABORT, 'real stop-use schema marker is immutable');
        END;

        CREATE TRIGGER real_stop_use_schema_marker_no_delete
        BEFORE DELETE ON {STOP_USE_SCHEMA_MARKER_TABLE}
        BEGIN
            SELECT RAISE(ABORT, 'real stop-use schema marker is immutable');
        END;

        CREATE TRIGGER real_source_suppressions_no_update
        BEFORE UPDATE ON {SUPPRESSION_TABLE}
        BEGIN
            SELECT RAISE(ABORT, 'real source suppression is immutable');
        END;

        CREATE TRIGGER real_source_suppressions_no_delete
        BEFORE DELETE ON {SUPPRESSION_TABLE}
        BEGIN
            SELECT RAISE(ABORT, 'real source suppression is immutable');
        END;

        CREATE TRIGGER real_source_suppressions_block_replace
        BEFORE INSERT ON {SUPPRESSION_TABLE}
        WHEN EXISTS (
            SELECT 1 FROM {SUPPRESSION_TABLE}
            WHERE suppression_id = NEW.suppression_id
               OR source_id = NEW.source_id
               OR operation_id = NEW.operation_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'real source suppression cannot replace history');
        END;

        CREATE TRIGGER real_sources_block_reinsert_suppressed
        BEFORE INSERT ON real_sources
        WHEN EXISTS (
            SELECT 1 FROM {SUPPRESSION_TABLE}
            WHERE source_id = NEW.source_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'suppressed source identity cannot be reintroduced');
        END;
        """
    )


def _validate_suppression_input(
    *,
    source_id: str,
    reason_code: StopUseReasonCode,
) -> None:
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id cannot be empty")
    if not isinstance(reason_code, StopUseReasonCode):
        raise TypeError("reason_code must use StopUseReasonCode")


def _require_stop_use_capability(
    capability: ClosedRealStopUseExerciseCapability,
) -> None:
    if not isinstance(capability, ClosedRealStopUseExerciseCapability):
        raise RealStopUseDisabledError(
            "closed real stop-use requires a trusted exercise capability"
        )
    if capability._marker is not _CLOSED_REAL_STOP_USE_CAPABILITY_MARKER:
        raise RealStopUseDisabledError("closed real stop-use capability is invalid")


def _require_stop_use_policy(policy: SingleOwnerRealStopUsePolicy) -> None:
    if not isinstance(policy, SingleOwnerRealStopUsePolicy):
        raise RealStopUseAuthorizationError(
            "closed real stop-use requires trusted policy"
        )
    if policy._marker is not _TRUSTED_STOP_USE_POLICY_MARKER:
        raise RealStopUseAuthorizationError("stop-use policy is invalid")


def _assert_real_source_schema(connection: sqlite3.Connection) -> None:
    required = {"real_sources", "real_source_subjects"}
    existing = {
        row[0]
        for row in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name IN ('real_sources', 'real_source_subjects')
            """
        ).fetchall()
    }
    if existing != required:
        raise RealIngressIntegrityError(
            "closed real source-ingress schema has not been initialized"
        )


def _existing_stop_use_artifacts(connection: sqlite3.Connection) -> set[str]:
    known = {
        STOP_USE_SCHEMA_MARKER_TABLE,
        SUPPRESSION_TABLE,
        SOURCE_DOMAIN_INDEX,
        "real_stop_use_schema_marker_no_update",
        "real_stop_use_schema_marker_no_delete",
        "real_source_suppressions_no_update",
        "real_source_suppressions_no_delete",
        "real_source_suppressions_block_replace",
        "real_sources_block_reinsert_suppressed",
    }
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE name IN (%s)"
            % ",".join("?" for _ in known),
            tuple(sorted(known)),
        ).fetchall()
    }


def _object_exists(
    connection: sqlite3.Connection,
    object_type: str,
    name: str,
) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type=? AND name=?",
        (object_type, name),
    ).fetchone() is not None


def _open_write_connection(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    if foreign_keys != 1:
        connection.close()
        raise RealStopUseIntegrityError("SQLite foreign keys are not enabled")
    return connection


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00",
        "Z",
    )
