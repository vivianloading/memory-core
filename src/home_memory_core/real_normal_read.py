from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import sqlite3
from uuid import uuid4

from home_memory_core.identity_namespaces import (
    AccessDomainId,
    IdentityNamespaceError,
    PerspectiveInstanceId,
    PerspectiveOwnerId,
)
from home_memory_core.operation_identity import (
    OperationClass,
    OperationContext,
    PrincipalId,
    require_operation_context,
)
from home_memory_core.real_authority_ordering import (
    capture_real_store_generation,
    real_authority_operation,
)
from home_memory_core.real_ingress import _assert_real_ingress_schema
from home_memory_core.real_use_state import (
    RealSourceSuppressedError,
    RealUseStateIntegrityError,
    assert_real_stop_use_schema,
    assert_source_ids_usable,
)
from home_memory_core.store_domain import assert_real_store_domain


_CLOSED_REAL_NORMAL_READ_CAPABILITY_MARKER = object()
_TRUSTED_NORMAL_READ_POLICY_MARKER = object()


class RealNormalReadDisabledError(RuntimeError):
    """The synthetic-fixture-only normal-read boundary is unavailable."""


class RealNormalReadAuthorizationError(PermissionError):
    """A normal read was denied without exposing protected resource state."""


class RealNormalReadUnavailableError(PermissionError):
    """The requested normal-use resource is not available to this operation."""


class RealNormalReadIntegrityError(RuntimeError):
    """Persisted real normal-read state failed a mechanical invariant."""


@dataclass(frozen=True)
class ClosedRealNormalReadExerciseCapability:
    """Private capability for synthetic-fixture-only real normal-read tests."""

    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _CLOSED_REAL_NORMAL_READ_CAPABILITY_MARKER:
            raise RealNormalReadDisabledError(
                "closed real normal-read capability cannot be caller-minted"
            )


@dataclass(frozen=True)
class SingleOwnerRealNormalReadPolicy:
    """Closed first-pilot normal-read policy.

    The first pilot deliberately fixes one authenticated owner, one access
    domain, and one trusted derived-perspective binding.  Source reads authorize
    against the persisted source domain.  The perspective binding is retained
    as part of the mechanically closed deployment policy for later derived
    normal-read/delivery steps; raw source metadata never grants authority.
    """

    policy_id: str
    owner_principal_id: PrincipalId
    access_domain_id: AccessDomainId
    perspective_owner: PerspectiveOwnerId
    perspective_instance: PerspectiveInstanceId
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _TRUSTED_NORMAL_READ_POLICY_MARKER:
            raise RealNormalReadAuthorizationError(
                "normal-read policy must come from trusted policy code"
            )
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise RealNormalReadAuthorizationError("policy_id cannot be empty")
        if not isinstance(self.owner_principal_id, PrincipalId):
            raise RealNormalReadAuthorizationError(
                "owner_principal_id must use PrincipalId"
            )
        if not isinstance(self.access_domain_id, AccessDomainId):
            raise RealNormalReadAuthorizationError(
                "access_domain_id must use AccessDomainId"
            )
        if not isinstance(self.perspective_owner, PerspectiveOwnerId):
            raise RealNormalReadAuthorizationError(
                "perspective_owner must use PerspectiveOwnerId"
            )
        if not isinstance(self.perspective_instance, PerspectiveInstanceId):
            raise RealNormalReadAuthorizationError(
                "perspective_instance must use PerspectiveInstanceId"
            )

    def authorize_source_read(
        self,
        *,
        context: OperationContext,
        persisted_access_domain_id: AccessDomainId,
    ) -> None:
        require_operation_context(
            context,
            expected_operation_class=OperationClass.NORMAL_READ,
        )
        if not isinstance(persisted_access_domain_id, AccessDomainId):
            raise RealNormalReadAuthorizationError(
                "normal read requires persisted AccessDomainId"
            )
        if context.principal.principal_id != self.owner_principal_id:
            raise RealNormalReadAuthorizationError("normal read unavailable")
        if persisted_access_domain_id != self.access_domain_id:
            raise RealNormalReadAuthorizationError("normal read unavailable")


@dataclass(frozen=True)
class RealNormalReadReceipt:
    receipt_id: str
    resource_kind: str
    resource_id: str
    operation_id: str
    principal_id: PrincipalId
    access_domain_id: AccessDomainId
    policy_id: str
    authority: str = "none"


@dataclass(frozen=True)
class RealNormalSourceRead:
    """One authorized exact-source normal read from current persisted state."""

    source_id: str
    content: str
    content_sha256: str
    receipt: RealNormalReadReceipt


class ClosedRealNormalReader:
    """Read exact known source IDs through the closed normal-use boundary.

    This is not discovery, ranking, model delivery, or audit access.  Every
    operation opens a fresh query-only SQLite transaction while holding the same
    local real-authority coordinator used by stop-use and lifecycle changes.
    """

    def __init__(
        self,
        *,
        db_path: str | Path,
        capability: ClosedRealNormalReadExerciseCapability,
        policy: SingleOwnerRealNormalReadPolicy,
    ) -> None:
        _require_normal_read_capability(capability)
        _require_normal_read_policy(policy)
        self.db_path = Path(db_path)
        self._capability = capability
        self._policy = policy
        self._authority_generation = capture_real_store_generation(self.db_path)

    def read_source(
        self,
        *,
        context: OperationContext,
        source_id: str,
    ) -> RealNormalSourceRead:
        _require_normal_read_capability(self._capability)
        _require_normal_read_policy(self._policy)
        require_operation_context(
            context,
            expected_operation_class=OperationClass.NORMAL_READ,
        )
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("source_id cannot be empty")

        with real_authority_operation(
            self.db_path,
            expected_generation=self._authority_generation,
        ):
            connection = sqlite3.connect(self.db_path)
            try:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("PRAGMA query_only = ON")
                connection.execute("BEGIN")
                assert_real_store_domain(connection)
                _assert_real_ingress_schema(connection)
                try:
                    assert_real_stop_use_schema(connection)
                except RealUseStateIntegrityError as error:
                    raise RealNormalReadIntegrityError(
                        "closed real stop-use state is unavailable"
                    ) from error

                # Authorize from persisted minimal metadata before fetching the
                # source payload. Missing, wrong-domain, and wrong-principal
                # paths intentionally converge on the same external denial.
                domain_row = connection.execute(
                    """
                    SELECT access_domain_id
                    FROM real_sources
                    WHERE source_id = ?
                    """,
                    (source_id,),
                ).fetchone()
                if domain_row is None:
                    raise RealNormalReadUnavailableError("normal read unavailable")

                try:
                    persisted_domain = AccessDomainId(domain_row[0])
                except IdentityNamespaceError as error:
                    raise RealNormalReadIntegrityError(
                        "persisted source domain identity is invalid"
                    ) from error
                try:
                    self._policy.authorize_source_read(
                        context=context,
                        persisted_access_domain_id=persisted_domain,
                    )
                except RealNormalReadAuthorizationError as error:
                    raise RealNormalReadUnavailableError(
                        "normal read unavailable"
                    ) from error

                try:
                    assert_source_ids_usable(connection, (source_id,))
                except RealSourceSuppressedError as error:
                    raise RealNormalReadUnavailableError(
                        "normal read unavailable"
                    ) from error
                except RealUseStateIntegrityError as error:
                    raise RealNormalReadIntegrityError(
                        "normal read dependency state is invalid"
                    ) from error

                row = connection.execute(
                    """
                    SELECT content, content_sha256, access_domain_id
                    FROM real_sources
                    WHERE source_id = ?
                    """,
                    (source_id,),
                ).fetchone()
                if row is None:
                    raise RealNormalReadIntegrityError(
                        "source disappeared inside one normal-read transaction"
                    )
                content, stored_hash, final_domain = row
                if final_domain != persisted_domain.value:
                    raise RealNormalReadIntegrityError(
                        "source domain changed inside one normal-read transaction"
                    )
                actual_hash = sha256(content.encode("utf-8")).hexdigest()
                if actual_hash != stored_hash:
                    raise RealNormalReadIntegrityError(
                        "source payload hash does not match persisted integrity metadata"
                    )
                connection.commit()
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
            finally:
                connection.close()

        receipt = RealNormalReadReceipt(
            receipt_id=f"real-normal-read-receipt-{uuid4().hex}",
            resource_kind="source",
            resource_id=source_id,
            operation_id=context.operation_id,
            principal_id=context.principal.principal_id,
            access_domain_id=persisted_domain,
            policy_id=self._policy.policy_id,
        )
        return RealNormalSourceRead(
            source_id=source_id,
            content=content,
            content_sha256=stored_hash,
            receipt=receipt,
        )


def _require_normal_read_capability(
    capability: ClosedRealNormalReadExerciseCapability,
) -> None:
    if not isinstance(capability, ClosedRealNormalReadExerciseCapability):
        raise RealNormalReadDisabledError(
            "closed real normal read requires trusted exercise capability"
        )
    if capability._marker is not _CLOSED_REAL_NORMAL_READ_CAPABILITY_MARKER:
        raise RealNormalReadDisabledError("closed real normal-read capability is invalid")


def _require_normal_read_policy(policy: SingleOwnerRealNormalReadPolicy) -> None:
    if not isinstance(policy, SingleOwnerRealNormalReadPolicy):
        raise RealNormalReadAuthorizationError(
            "closed real normal reader requires trusted policy"
        )
    if policy._marker is not _TRUSTED_NORMAL_READ_POLICY_MARKER:
        raise RealNormalReadAuthorizationError("normal-read policy is invalid")
