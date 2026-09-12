from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from home_memory_core.identity_namespaces import DestinationId, RequestId


_AUTHENTICATED_PRINCIPAL_MARKER = object()
_TRUSTED_ISSUER_MARKER = object()
_OPERATION_CONTEXT_MARKER = object()


class AuthenticationBoundaryError(ValueError):
    """Untrusted data attempted to cross the operation-identity boundary."""


@dataclass(frozen=True)
class PrincipalId:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise AuthenticationBoundaryError("principal_id cannot be empty")


class OperationClass(StrEnum):
    SOURCE_WRITE = "source.write"
    INTERPRETATION_WRITE = "interpretation.write"
    THREAD_ADMIT = "thread.admit"
    SUPERSESSION_WRITE = "supersession.write"
    SOURCE_SUPPRESS = "source.suppress"
    DISCOVERY_READ = "discovery.read"
    MEMORY_DELIVER = "memory.deliver"
    AUDIT_READ = "audit.read"


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """A principal assertion minted by a trusted authentication boundary.

    This object is intentionally not constructible from ordinary caller data:
    its internal marker is checked by identity. The current local-only HOME
    milestone treats arbitrary code execution inside the trusted Python process
    as out of scope; future plugin/process boundaries must not receive issuer
    capabilities.
    """

    principal_id: PrincipalId
    principal_kind: str
    trust_source: str
    _authn_marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authn_marker is not _AUTHENTICATED_PRINCIPAL_MARKER:
            raise AuthenticationBoundaryError(
                "AuthenticatedPrincipal must be minted by a trusted issuer"
            )
        if not isinstance(self.principal_id, PrincipalId):
            raise AuthenticationBoundaryError(
                "principal_id must use the PrincipalId namespace"
            )
        for field_name, value in {
            "principal_kind": self.principal_kind,
            "trust_source": self.trust_source,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise AuthenticationBoundaryError(
                    f"{field_name} cannot be empty"
                )


@dataclass(frozen=True)
class OperationContext:
    """One operation attempt bound to an already-authenticated principal.

    An OperationContext records identity/request/destination binding. It is not
    an authorization decision and does not grant access by itself.
    """

    operation_id: str
    principal: AuthenticatedPrincipal
    operation_class: OperationClass
    request_id: RequestId | None = None
    destination_id: DestinationId | None = None
    _context_marker: object | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self._context_marker is not _OPERATION_CONTEXT_MARKER:
            raise AuthenticationBoundaryError(
                "OperationContext must be minted by the trusted context factory"
            )
        if not isinstance(self.operation_id, str) or not self.operation_id.strip():
            raise AuthenticationBoundaryError("operation_id cannot be empty")
        _require_authenticated_principal(self.principal)
        if not isinstance(self.operation_class, OperationClass):
            raise AuthenticationBoundaryError(
                "operation_class must use the closed OperationClass namespace"
            )
        if self.request_id is not None and not isinstance(self.request_id, RequestId):
            raise AuthenticationBoundaryError(
                "request_id must use the RequestId namespace"
            )
        if self.destination_id is not None and not isinstance(
            self.destination_id,
            DestinationId,
        ):
            raise AuthenticationBoundaryError(
                "destination_id must use the DestinationId namespace"
            )


@dataclass(frozen=True)
class TrustedPrincipalIssuer:
    """Capability held only by trusted authentication/bootstrap code."""

    trust_source: str
    _issuer_marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._issuer_marker is not _TRUSTED_ISSUER_MARKER:
            raise AuthenticationBoundaryError(
                "TrustedPrincipalIssuer cannot be caller-minted"
            )
        if not isinstance(self.trust_source, str) or not self.trust_source.strip():
            raise AuthenticationBoundaryError("trust_source cannot be empty")

    def issue(
        self,
        *,
        principal_id: PrincipalId,
        principal_kind: str,
    ) -> AuthenticatedPrincipal:
        if not isinstance(principal_id, PrincipalId):
            raise AuthenticationBoundaryError(
                "principal_id must use the PrincipalId namespace"
            )
        return AuthenticatedPrincipal(
            principal_id=principal_id,
            principal_kind=principal_kind,
            trust_source=self.trust_source,
            _authn_marker=_AUTHENTICATED_PRINCIPAL_MARKER,
        )


def create_operation_context(
    *,
    principal: AuthenticatedPrincipal,
    operation_class: OperationClass,
    request_id: RequestId | None = None,
    destination_id: DestinationId | None = None,
) -> OperationContext:
    _require_authenticated_principal(principal)
    if not isinstance(operation_class, OperationClass):
        raise AuthenticationBoundaryError(
            "operation_class must use the closed OperationClass namespace"
        )
    if request_id is not None and not isinstance(request_id, RequestId):
        raise AuthenticationBoundaryError(
            "request_id must use the RequestId namespace"
        )
    if destination_id is not None and not isinstance(destination_id, DestinationId):
        raise AuthenticationBoundaryError(
            "destination_id must use the DestinationId namespace"
        )
    return OperationContext(
        operation_id=f"operation-{uuid4().hex}",
        principal=principal,
        operation_class=operation_class,
        request_id=request_id,
        destination_id=destination_id,
        _context_marker=_OPERATION_CONTEXT_MARKER,
    )


def _require_authenticated_principal(
    principal: AuthenticatedPrincipal,
) -> None:
    if not isinstance(principal, AuthenticatedPrincipal):
        raise AuthenticationBoundaryError(
            "operation requires an AuthenticatedPrincipal"
        )
    if principal._authn_marker is not _AUTHENTICATED_PRINCIPAL_MARKER:
        raise AuthenticationBoundaryError(
            "operation principal was not minted by a trusted issuer"
        )


def require_operation_context(
    context: OperationContext,
    *,
    expected_operation_class: OperationClass | None = None,
) -> None:
    """Validate that a context was minted by HOME's trusted context factory."""

    if not isinstance(context, OperationContext):
        raise AuthenticationBoundaryError(
            "operation requires a trusted OperationContext"
        )
    if context._context_marker is not _OPERATION_CONTEXT_MARKER:
        raise AuthenticationBoundaryError(
            "operation context was not minted by the trusted context factory"
        )
    _require_authenticated_principal(context.principal)
    if expected_operation_class is not None:
        if not isinstance(expected_operation_class, OperationClass):
            raise AuthenticationBoundaryError(
                "expected operation class must use OperationClass"
            )
        if context.operation_class is not expected_operation_class:
            raise AuthenticationBoundaryError(
                "operation context class does not match requested operation"
            )
