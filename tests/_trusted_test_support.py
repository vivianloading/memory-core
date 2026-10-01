"""Synthetic tests may cross private trust roots deliberately.

This module is test-only and is not part of the HOME runtime package. It lets
adversarial tests construct capabilities that production request data cannot
mint through supported runtime APIs.
"""

from home_memory_core import operation_identity as identity
from home_memory_core import real_ingress
from home_memory_core import real_discovery
from home_memory_core import real_delivery
from home_memory_core import real_normal_read
from home_memory_core import real_relationships
from home_memory_core import real_stop_use
from home_memory_core import real_source_origin
from home_memory_core import living_authority
from home_memory_core import source_origin
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
    origin_namespace_id=None,
) -> real_ingress.SingleOwnerRealIngressWritePolicy:
    from home_memory_core.identity_namespaces import OriginNamespaceId

    return real_ingress.SingleOwnerRealIngressWritePolicy(
        policy_id=policy_id,
        owner_principal_id=owner_principal_id,
        access_domain_id=access_domain_id,
        origin_namespace_id=(
            origin_namespace_id or OriginNamespaceId("synthetic-test-provider/account")
        ),
        _marker=real_ingress._TRUSTED_WRITE_POLICY_MARKER,
    )


def trusted_test_closed_real_source_origin_capability(
) -> real_source_origin.ClosedRealSourceOriginExerciseCapability:
    return real_source_origin.ClosedRealSourceOriginExerciseCapability(
        _marker=real_source_origin._CLOSED_REAL_SOURCE_ORIGIN_CAPABILITY_MARKER,
    )


def trusted_test_source_origin_provenance(
    *,
    external_object_key: str,
    external_snapshot_key: str = "immutable",
    snapshot_kind=None,
    origin_namespace_id=None,
    object_kind: str = "synthetic_message",
    origin_key_version: str = "synthetic-v1",
    ingress_adapter_id: str = "synthetic-adapter",
    adapter_version: str = "1",
    capture_locator: str | None = None,
) -> source_origin.TrustedSourceOriginProvenance:
    from home_memory_core.identity_namespaces import OriginNamespaceId

    return source_origin.TrustedSourceOriginProvenance(
        origin_namespace_id=(
            origin_namespace_id or OriginNamespaceId("synthetic-test-provider/account")
        ),
        external_object_key=external_object_key,
        object_kind=object_kind,
        origin_key_version=origin_key_version,
        snapshot_kind=(snapshot_kind or source_origin.SnapshotKind.IMMUTABLE_ORIGIN),
        external_snapshot_key=external_snapshot_key,
        ingress_adapter_id=ingress_adapter_id,
        adapter_version=adapter_version,
        capture_locator=capture_locator,
        _marker=source_origin._TRUSTED_SOURCE_ORIGIN_PROVENANCE_MARKER,
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


def trusted_test_closed_real_normal_read_capability(
) -> real_normal_read.ClosedRealNormalReadExerciseCapability:
    return real_normal_read.ClosedRealNormalReadExerciseCapability(
        _marker=real_normal_read._CLOSED_REAL_NORMAL_READ_CAPABILITY_MARKER,
    )


def trusted_test_single_owner_real_normal_read_policy(
    *,
    policy_id: str,
    owner_principal_id: identity.PrincipalId,
    access_domain_id,
    perspective_owner=None,
    perspective_instance=None,
) -> real_normal_read.SingleOwnerRealNormalReadPolicy:
    from home_memory_core.identity_namespaces import (
        PerspectiveInstanceId,
        PerspectiveOwnerId,
    )

    return real_normal_read.SingleOwnerRealNormalReadPolicy(
        policy_id=policy_id,
        owner_principal_id=owner_principal_id,
        access_domain_id=access_domain_id,
        perspective_owner=(perspective_owner or PerspectiveOwnerId("owner")),
        perspective_instance=(
            perspective_instance or PerspectiveInstanceId("owner-instance")
        ),
        _marker=real_normal_read._TRUSTED_NORMAL_READ_POLICY_MARKER,
    )


def trusted_test_closed_real_discovery_capability(
) -> real_discovery.ClosedRealDiscoveryExerciseCapability:
    return real_discovery.ClosedRealDiscoveryExerciseCapability(
        _marker=real_discovery._CLOSED_REAL_DISCOVERY_CAPABILITY_MARKER,
    )


def trusted_test_single_owner_real_discovery_policy(
    *,
    policy_id: str,
    owner_principal_id: identity.PrincipalId,
    access_domain_id,
    perspective_owner=None,
    perspective_instance=None,
) -> real_discovery.SingleOwnerRealDiscoveryPolicy:
    from home_memory_core.identity_namespaces import (
        PerspectiveInstanceId,
        PerspectiveOwnerId,
    )

    return real_discovery.SingleOwnerRealDiscoveryPolicy(
        policy_id=policy_id,
        owner_principal_id=owner_principal_id,
        access_domain_id=access_domain_id,
        perspective_owner=(perspective_owner or PerspectiveOwnerId("owner")),
        perspective_instance=(
            perspective_instance or PerspectiveInstanceId("owner-instance")
        ),
        _marker=real_discovery._TRUSTED_REAL_DISCOVERY_POLICY_MARKER,
    )


def trusted_test_closed_real_delivery_capability(
) -> real_delivery.ClosedRealDeliveryExerciseCapability:
    return real_delivery.ClosedRealDeliveryExerciseCapability(
        _marker=real_delivery._CLOSED_REAL_DELIVERY_CAPABILITY_MARKER,
    )


def trusted_test_single_owner_real_delivery_policy(
    *,
    policy_id: str,
    owner_principal_id: identity.PrincipalId,
    access_domain_id,
    destination_id,
    perspective_owner=None,
    perspective_instance=None,
) -> real_delivery.SingleOwnerRealDeliveryPolicy:
    from home_memory_core.identity_namespaces import (
        PerspectiveInstanceId,
        PerspectiveOwnerId,
    )

    return real_delivery.SingleOwnerRealDeliveryPolicy(
        policy_id=policy_id,
        owner_principal_id=owner_principal_id,
        access_domain_id=access_domain_id,
        perspective_owner=(perspective_owner or PerspectiveOwnerId("owner")),
        perspective_instance=(
            perspective_instance or PerspectiveInstanceId("owner-instance")
        ),
        destination_id=destination_id,
        _marker=real_delivery._TRUSTED_REAL_DELIVERY_POLICY_MARKER,
    )


def trusted_test_synchronous_handoff_sink(
    *,
    destination_id,
    handler,
    destination_class: str = "synthetic-model-consumer",
) -> real_delivery.TrustedSynchronousHandoffSink:
    return real_delivery.TrustedSynchronousHandoffSink(
        destination_id=destination_id,
        destination_class=destination_class,
        _handler=handler,
        _marker=real_delivery._TRUSTED_SYNC_HANDOFF_SINK_MARKER,
    )


def trusted_test_room_continuation_policy(
    *,
    policy_id: str,
    room_id: str,
    allowed_scopes,
    established_episode_id: str = "episode-a",
    established_attachment_event_id: str = "route-a",
    source_event_ref: str = "synthetic-inhabitant-policy-event",
) -> living_authority.TrustedRoomContinuationPolicy:
    return living_authority._issue_trusted_room_continuation_policy_for_test(
        policy_id=policy_id,
        room_id=room_id,
        established_episode_id=established_episode_id,
        established_attachment_event_id=(
            established_attachment_event_id
        ),
        allowed_scopes=frozenset(allowed_scopes),
        source_event_ref=source_event_ref,
        _issuer_marker=(
            living_authority._CONTINUATION_POLICY_ISSUER_MARKER
        ),
    )


def trusted_test_runtime_launch_issuer(
    *,
    lease,
    store,
) -> living_authority.TrustedRuntimeLaunchIssuer:
    return living_authority.TrustedRuntimeLaunchIssuer(
        lease=lease,
        store=store,
        _marker=living_authority._RUNTIME_LAUNCH_ISSUER_MARKER,
    )
