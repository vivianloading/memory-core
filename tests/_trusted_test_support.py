"""Synthetic tests may cross private trust roots deliberately.

This module is test-only and is not part of the HOME runtime package. It lets
adversarial tests construct capabilities that production request data cannot
mint through supported runtime APIs.
"""

from home_memory_core import operation_identity as identity
from home_memory_core import real_ingress
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
