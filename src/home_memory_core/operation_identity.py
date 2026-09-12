from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


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

    An OperationContext records identity and request binding. It is not an
    authorization decision and does not grant access by itself.
    """

    operation_id: str
    principal: AuthenticatedPrincipal
    operation_class: str
    request_id: str | None = None
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
        if not isinstance(self.operation_class, str) or not self.operation_class.strip():
            raise AuthenticationBoundaryError("operation_class cannot be empty")
        if self.request_id is not None:
            if not isinstance(self.request_id, str) or not self.request_id.strip():
                raise AuthenticationBoundaryError(
                    "request_id must be non-empty when present"
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
    operation_class: str,
    request_id: str | None = None,
) -> OperationContext:
    _require_authenticated_principal(principal)
    return OperationContext(
        operation_id=f"operation-{uuid4().hex}",
        principal=principal,
        operation_class=operation_class,
        request_id=request_id,
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
