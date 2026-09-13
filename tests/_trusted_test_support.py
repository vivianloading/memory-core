"""Synthetic tests may cross private trust roots deliberately.

This module is test-only and is not part of the HOME runtime package. It lets
adversarial tests construct capabilities that production request data cannot
mint through supported runtime APIs.
"""

from home_memory_core import operation_identity as identity
from home_memory_core import real_ingress
from home_memory_core import real_relationships
from home_memory_core import real_stop_use
from home_memory_core import store_domain


def trusted_test_principal_issuer(
    *,
    trust_source: str = "synthetic-test-authn",
) -> identity.TrustedPrincipalIssuer:
    return identity.TrustedPrincipalIssuer(
        trust_source=trust_source,
        _issuer_marker=identity._TRUSTED_ISSUER_MARKER,
    )


def trusted_test_real_store_bootstrap_capability(
) -> store_domain.RealStoreBootstrapCapability:
    return store_domain.RealStoreBootstrapCapability(
        _marker=store_domain._REAL_STORE_BOOTSTRAP_MARKER,
    )


def trusted_test_closed_real_ingress_capability(
) -> real_ingress.ClosedRealIngressExerciseCapability:
    return real_ingress.ClosedRealIngressExerciseCapability(
        _marker=real_ingress._CLOSED_REAL_INGRESS_CAPABILITY_MARKER,
    )


def trusted_test_single_owner_real_ingress_policy(
    *,
    policy_id: str,
    owner_principal_id: identity.PrincipalId,
    access_domain_id,
) -> real_ingress.SingleOwnerRealIngressWritePolicy:
    return real_ingress.SingleOwnerRealIngressWritePolicy(
        policy_id=policy_id,
        owner_principal_id=owner_principal_id,
        access_domain_id=access_domain_id,
        _marker=real_ingress._TRUSTED_WRITE_POLICY_MARKER,
    )


def trusted_test_closed_real_relationship_capability(
) -> real_relationships.ClosedRealRelationshipExerciseCapability:
    return real_relationships.ClosedRealRelationshipExerciseCapability(
        _marker=real_relationships._CLOSED_REAL_RELATIONSHIP_CAPABILITY_MARKER,
    )


def trusted_test_single_owner_real_relationship_policy(
    *,
    policy_id: str,
    owner_principal_id: identity.PrincipalId,
    access_domain_id,
    perspective_owner=None,
    perspective_instance=None,
) -> real_relationships.SingleOwnerRealRelationshipWritePolicy:
    from home_memory_core.identity_namespaces import (
        PerspectiveInstanceId,
        PerspectiveOwnerId,
    )

    return real_relationships.SingleOwnerRealRelationshipWritePolicy(
        policy_id=policy_id,
        owner_principal_id=owner_principal_id,
        access_domain_id=access_domain_id,
        perspective_owner=(
            perspective_owner or PerspectiveOwnerId("owner")
        ),
        perspective_instance=(
            perspective_instance or PerspectiveInstanceId("owner-instance")
        ),
        _marker=real_relationships._TRUSTED_RELATIONSHIP_WRITE_POLICY_MARKER,
    )


def trusted_test_closed_real_supersession_capability():
    from home_memory_core import real_supersession

    return real_supersession.ClosedRealSupersessionExerciseCapability(
        _marker=real_supersession._CLOSED_REAL_SUPERSESSION_CAPABILITY_MARKER,
    )


def trusted_test_closed_real_stop_use_capability(
) -> real_stop_use.ClosedRealStopUseExerciseCapability:
    return real_stop_use.ClosedRealStopUseExerciseCapability(
        _marker=real_stop_use._CLOSED_REAL_STOP_USE_CAPABILITY_MARKER,
    )


def trusted_test_single_owner_real_stop_use_policy(
    *,
    policy_id: str,
    owner_principal_id: identity.PrincipalId,
    access_domain_id,
) -> real_stop_use.SingleOwnerRealStopUsePolicy:
    return real_stop_use.SingleOwnerRealStopUsePolicy(
        policy_id=policy_id,
        owner_principal_id=owner_principal_id,
        access_domain_id=access_domain_id,
        _marker=real_stop_use._TRUSTED_STOP_USE_POLICY_MARKER,
    )
