from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import Enum, StrEnum
from hashlib import sha256
import json
from threading import Lock
from uuid import uuid4

from home_memory_core.process_boundary import current_home_process_instance_id
from home_memory_core.wake_model_input import (
    CapabilityGrantRule,
    CarriedContextPosition,
    ConstructedHomeModelInput,
    HomeModelInputPolicy,
    MemoryWriteCapability,
    ModelExecutionAvailability,
    ModelInputCapabilities,
    ModelInputSourceHandoff,
    ModelInputUserTurn,
    ModelInputWakeContext,
    NetworkDeliveryAvailability,
    RequestConstructionReceipt,
    SpeakerSelectionRule,
    WakeContextTemporalSemantics,
    WakeModelInputBoundary,
    WakeModelInputIntegrityError,
)
from home_memory_core.wake_packet import WakeAuthority, WakeUseBoundary


MODEL_EXECUTION_CONTRACT_VERSION = "model-execution-contract-v0.1"
MODEL_EXECUTION_TOPOLOGY_POLICY_VERSION = "model-execution-topology-policy-v0.1"
MODEL_EXECUTION_AUDIT_SERIALIZER_VERSION = "model-execution-audit-json-v0.1"
MODEL_EXECUTION_AUDIT_MEDIA_TYPE = (
    "application/vnd.home.model-execution-preparation-audit+json"
)
MODEL_EXECUTION_AUDIT_KIND = "home_model_execution_preparation_audit"

_CONTRACT_REQUEST_MARKER = object()
_TOPOLOGY_POLICY_MARKER = object()
_SOURCE_BINDING_MARKER = object()
_POLICY_CHANNEL_MARKER = object()
_USER_CHANNEL_MARKER = object()
_WAKE_CHANNEL_MARKER = object()
_CAPABILITIES_MARKER = object()
_PREPARATION_RECEIPT_MARKER = object()
_PREPARATION_MARKER = object()


class ModelExecutionContractError(RuntimeError):
    """Dry-run execution preparation violated the v0.1 contract."""


class ModelExecutionContractIntegrityError(ModelExecutionContractError):
    """A prepared artifact differs from exact bound semantics."""


class ModelExecutionContractAuthorizationError(ModelExecutionContractError):
    """A process-local preparation witness is not live/originating."""


class ExecutionMode(StrEnum):
    DRY_RUN_ONLY = "dry_run_only"


class ProviderMappingAvailability(StrEnum):
    UNAVAILABLE = "unavailable"


class ExecutionChannelLayout(StrEnum):
    SEPARATE_TYPED_SIBLINGS = "separate_typed_siblings"


class ChannelConcatenationRule(StrEnum):
    FORBIDDEN = "forbidden"


class ProviderRoleRule(StrEnum):
    CONTENT_CANNOT_SELECT_PROVIDER_ROLE = (
        "content_cannot_select_provider_role"
    )


class ExecutionGrantRule(StrEnum):
    PREPARATION_DOES_NOT_GRANT_EXECUTION = (
        "preparation_does_not_grant_execution"
    )


class ExecutionSourceRule(StrEnum):
    EXACT_LIVE_MODEL_INPUT_ONLY = "exact_live_model_input_only"


@dataclass(frozen=True)
class ExecutionTopologyPolicy:
    policy_version: str
    execution_mode: ExecutionMode
    provider_mapping: ProviderMappingAvailability
    channel_layout: ExecutionChannelLayout
    channel_concatenation_rule: ChannelConcatenationRule
    provider_role_rule: ProviderRoleRule
    execution_grant_rule: ExecutionGrantRule
    source_rule: ExecutionSourceRule
    use_boundary: WakeUseBoundary
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _TOPOLOGY_POLICY_MARKER:
            raise ModelExecutionContractAuthorizationError(
                "execution topology policy must be constructed by HOME"
            )
        if self.policy_version != MODEL_EXECUTION_TOPOLOGY_POLICY_VERSION:
            raise ModelExecutionContractIntegrityError(
                "execution topology policy version is invalid"
            )
        if self.execution_mode is not ExecutionMode.DRY_RUN_ONLY:
            raise ModelExecutionContractIntegrityError(
                "v0.1 execution mode must remain dry-run only"
            )
        if (
            self.provider_mapping
            is not ProviderMappingAvailability.UNAVAILABLE
        ):
            raise ModelExecutionContractIntegrityError(
                "v0.1 provider mapping must remain unavailable"
            )
        if (
            self.channel_layout
            is not ExecutionChannelLayout.SEPARATE_TYPED_SIBLINGS
        ):
            raise ModelExecutionContractIntegrityError(
                "execution channels must remain separate typed siblings"
            )
        if (
            self.channel_concatenation_rule
            is not ChannelConcatenationRule.FORBIDDEN
        ):
            raise ModelExecutionContractIntegrityError(
                "execution channels cannot be concatenated into one prompt"
            )
        if (
            self.provider_role_rule
            is not ProviderRoleRule.CONTENT_CANNOT_SELECT_PROVIDER_ROLE
        ):
            raise ModelExecutionContractIntegrityError(
                "content cannot select provider roles"
            )
        if (
            self.execution_grant_rule
            is not ExecutionGrantRule.PREPARATION_DOES_NOT_GRANT_EXECUTION
        ):
            raise ModelExecutionContractIntegrityError(
                "preparation cannot grant model execution"
            )
        if (
            self.source_rule
            is not ExecutionSourceRule.EXACT_LIVE_MODEL_INPUT_ONLY
        ):
            raise ModelExecutionContractIntegrityError(
                "execution preparation source rule is invalid"
            )
        _require_none_boundary(
            field_name="execution topology use boundary",
            boundary=self.use_boundary,
        )


@dataclass(frozen=True)
class ExecutionSourceBinding:
    construction_id: str
    request_id: str
    episode_id: str
    wake_id: str
    issuance_id: str
    source_handoff_id: str
    home_process_instance_id: str
    local_transport_boundary_id: str
    model_input_boundary_id: str
    source_handoff_generation: int
    source_handoff_receipt_digest: str
    source_envelope_digest: str
    policy_digest: str
    source_request_semantic_digest: str
    source_serialized_representation_digest: str
    source_serializer_version: str
    source_media_type: str
    source_construction_binding_digest: str
    use_boundary: WakeUseBoundary
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _SOURCE_BINDING_MARKER:
            raise ModelExecutionContractAuthorizationError(
                "execution source binding must come from live model input"
            )
        for field_name in (
            "construction_id",
            "request_id",
            "episode_id",
            "wake_id",
            "issuance_id",
            "source_handoff_id",
            "home_process_instance_id",
            "local_transport_boundary_id",
            "model_input_boundary_id",
            "source_serializer_version",
            "source_media_type",
        ):
            _exact_nonempty_text(field_name, getattr(self, field_name))
        for field_name in (
            "source_handoff_receipt_digest",
            "source_envelope_digest",
            "policy_digest",
            "source_request_semantic_digest",
            "source_serialized_representation_digest",
            "source_construction_binding_digest",
        ):
            _digest(field_name, getattr(self, field_name))
        if (
            type(self.source_handoff_generation) is not int
            or self.source_handoff_generation < 0
        ):
            raise ModelExecutionContractIntegrityError(
                "source handoff generation must be non-negative exact int"
            )
        _require_none_boundary(
            field_name="execution source use boundary",
            boundary=self.use_boundary,
        )


@dataclass(frozen=True)
class ExecutionHomePolicyChannel:
    value: HomeModelInputPolicy
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _POLICY_CHANNEL_MARKER:
            raise ModelExecutionContractAuthorizationError(
                "HOME policy channel must be constructed by the execution boundary"
            )
        if not isinstance(self.value, HomeModelInputPolicy):
            raise ModelExecutionContractIntegrityError(
                "HOME policy channel value is invalid"
            )


@dataclass(frozen=True)
class ExecutionUserTurnChannel:
    value: ModelInputUserTurn
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _USER_CHANNEL_MARKER:
            raise ModelExecutionContractAuthorizationError(
                "user channel must be constructed by the execution boundary"
            )
        if not isinstance(self.value, ModelInputUserTurn):
            raise ModelExecutionContractIntegrityError(
                "user channel value is invalid"
            )


@dataclass(frozen=True)
class ExecutionWakeDataChannel:
    value: ModelInputWakeContext
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _WAKE_CHANNEL_MARKER:
            raise ModelExecutionContractAuthorizationError(
                "Wake data channel must be constructed by the execution boundary"
            )
        if not isinstance(self.value, ModelInputWakeContext):
            raise ModelExecutionContractIntegrityError(
                "Wake data channel value is invalid"
            )
        _require_none_boundary(
            field_name="Wake execution data use boundary",
            boundary=self.value.use_boundary,
        )


@dataclass(frozen=True)
class ExecutionPreparationCapabilities:
    model_execution: ModelExecutionAvailability
    network_delivery: NetworkDeliveryAvailability
    provider_mapping: ProviderMappingAvailability
    tools: object
    memory_write: object
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _CAPABILITIES_MARKER:
            raise ModelExecutionContractAuthorizationError(
                "execution preparation capabilities must be constructed by HOME"
            )
        if self.model_execution is not ModelExecutionAvailability.UNAVAILABLE:
            raise ModelExecutionContractIntegrityError(
                "dry-run preparation cannot grant model execution"
            )
        if self.network_delivery is not NetworkDeliveryAvailability.UNAVAILABLE:
            raise ModelExecutionContractIntegrityError(
                "dry-run preparation cannot grant network delivery"
            )
        if self.provider_mapping is not ProviderMappingAvailability.UNAVAILABLE:
            raise ModelExecutionContractIntegrityError(
                "dry-run preparation cannot grant provider mapping"
            )
        from home_memory_core.wake_model_input import (
            MemoryWriteCapability,
            ToolCapability,
        )

        if self.tools is not ToolCapability.NONE:
            raise ModelExecutionContractIntegrityError(
                "dry-run preparation tools must remain none"
            )
        if self.memory_write is not MemoryWriteCapability.NONE:
            raise ModelExecutionContractIntegrityError(
                "dry-run preparation memory write must remain none"
            )


@dataclass(frozen=True)
class DryRunExecutionRequest:
    contract_version: str
    source: ExecutionSourceBinding
    topology_policy: ExecutionTopologyPolicy
    home_policy: ExecutionHomePolicyChannel
    user_turn: ExecutionUserTurnChannel
    wake_data: ExecutionWakeDataChannel
    capabilities: ExecutionPreparationCapabilities
    use_boundary: WakeUseBoundary
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _CONTRACT_REQUEST_MARKER:
            raise ModelExecutionContractAuthorizationError(
                "dry-run execution request must be constructed by HOME"
            )
        if self.contract_version != MODEL_EXECUTION_CONTRACT_VERSION:
            raise ModelExecutionContractIntegrityError(
                "execution contract version is invalid"
            )
        if not isinstance(self.source, ExecutionSourceBinding):
            raise ModelExecutionContractIntegrityError(
                "execution source binding is invalid"
            )
        if not isinstance(self.topology_policy, ExecutionTopologyPolicy):
            raise ModelExecutionContractIntegrityError(
                "execution topology policy is invalid"
            )
        if not isinstance(self.home_policy, ExecutionHomePolicyChannel):
            raise ModelExecutionContractIntegrityError(
                "execution HOME policy channel is invalid"
            )
        if not isinstance(self.user_turn, ExecutionUserTurnChannel):
            raise ModelExecutionContractIntegrityError(
                "execution user channel is invalid"
            )
        if not isinstance(self.wake_data, ExecutionWakeDataChannel):
            raise ModelExecutionContractIntegrityError(
                "execution Wake data channel is invalid"
            )
        if not isinstance(
            self.capabilities,
            ExecutionPreparationCapabilities,
        ):
            raise ModelExecutionContractIntegrityError(
                "execution preparation capabilities are invalid"
            )
        _require_none_boundary(
            field_name="dry-run execution request use boundary",
            boundary=self.use_boundary,
        )
        if self.use_boundary != self.source.use_boundary:
            raise ModelExecutionContractIntegrityError(
                "request and source authority boundaries differ"
            )
        if self.use_boundary != self.topology_policy.use_boundary:
            raise ModelExecutionContractIntegrityError(
                "request and topology authority boundaries differ"
            )
        if self.use_boundary != self.wake_data.value.use_boundary:
            raise ModelExecutionContractIntegrityError(
                "request and Wake data authority boundaries differ"
            )


@dataclass(frozen=True)
class DryRunExecutionPreparationReceipt:
    preparation_version: str
    preparation_id: str
    request_id: str
    episode_id: str
    wake_id: str
    issuance_id: str
    source_handoff_id: str
    home_process_instance_id: str
    model_input_boundary_id: str
    execution_contract_boundary_id: str
    source_construction_id: str
    source_construction_binding_digest: str
    source_request_semantic_digest: str
    source_serialized_representation_digest: str
    topology_policy_digest: str
    prepared_request_semantic_digest: str
    audit_serialization_digest: str
    audit_serializer_version: str
    audit_media_type: str
    execution_mode: ExecutionMode
    provider_mapping: ProviderMappingAvailability
    use_boundary: WakeUseBoundary
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _PREPARATION_RECEIPT_MARKER:
            raise ModelExecutionContractAuthorizationError(
                "preparation receipt must come from execution contract boundary"
            )
        if self.preparation_version != MODEL_EXECUTION_CONTRACT_VERSION:
            raise ModelExecutionContractIntegrityError(
                "preparation receipt version is invalid"
            )
        for field_name in (
            "preparation_id",
            "request_id",
            "episode_id",
            "wake_id",
            "issuance_id",
            "source_handoff_id",
            "home_process_instance_id",
            "model_input_boundary_id",
            "execution_contract_boundary_id",
            "source_construction_id",
            "audit_serializer_version",
            "audit_media_type",
        ):
            _exact_nonempty_text(field_name, getattr(self, field_name))
        for field_name in (
            "source_construction_binding_digest",
            "source_request_semantic_digest",
            "source_serialized_representation_digest",
            "topology_policy_digest",
            "prepared_request_semantic_digest",
            "audit_serialization_digest",
        ):
            _digest(field_name, getattr(self, field_name))
        if self.audit_serializer_version != MODEL_EXECUTION_AUDIT_SERIALIZER_VERSION:
            raise ModelExecutionContractIntegrityError(
                "execution audit serializer version is invalid"
            )
        if self.audit_media_type != MODEL_EXECUTION_AUDIT_MEDIA_TYPE:
            raise ModelExecutionContractIntegrityError(
                "execution audit media type is invalid"
            )
        if self.execution_mode is not ExecutionMode.DRY_RUN_ONLY:
            raise ModelExecutionContractIntegrityError(
                "preparation receipt execution mode must remain dry-run only"
            )
        if self.provider_mapping is not ProviderMappingAvailability.UNAVAILABLE:
            raise ModelExecutionContractIntegrityError(
                "preparation receipt provider mapping must remain unavailable"
            )
        _require_none_boundary(
            field_name="preparation receipt use boundary",
            boundary=self.use_boundary,
        )


@dataclass(frozen=True)
class DryRunExecutionPreparation:
    request: DryRunExecutionRequest
    audit_media_type: str
    audit_serialized_text: str
    receipt: DryRunExecutionPreparationReceipt
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _PREPARATION_MARKER:
            raise ModelExecutionContractAuthorizationError(
                "dry-run preparation must come from execution contract boundary"
            )
        if not isinstance(self.request, DryRunExecutionRequest):
            raise ModelExecutionContractIntegrityError(
                "prepared dry-run request is invalid"
            )
        if self.audit_media_type != MODEL_EXECUTION_AUDIT_MEDIA_TYPE:
            raise ModelExecutionContractIntegrityError(
                "prepared audit media type is invalid"
            )
        _exact_nonempty_text(
            "prepared audit serialized text",
            self.audit_serialized_text,
        )
        if not isinstance(
            self.receipt,
            DryRunExecutionPreparationReceipt,
        ):
            raise ModelExecutionContractIntegrityError(
                "prepared receipt is invalid"
            )
        if (
            _sha256_text(self.audit_serialized_text)
            != self.receipt.audit_serialization_digest
        ):
            raise ModelExecutionContractIntegrityError(
                "audit serialization differs from preparation receipt"
            )


@dataclass(frozen=True)
class _LivePreparationState:
    boundary: "ModelExecutionContractBoundary"
    source_construction_receipt: RequestConstructionReceipt
    source_constructed: ConstructedHomeModelInput
    preparation: DryRunExecutionPreparation
    source_binding_digest: str
    request_digest: str
    audit_digest: str
    receipt_digest: str


class ModelExecutionContractBoundary:
    """Prepare one exact model-input construction for local dry-run only."""

    def __init__(
        self,
        *,
        model_input_boundary: WakeModelInputBoundary,
    ) -> None:
        if not isinstance(model_input_boundary, WakeModelInputBoundary):
            raise TypeError(
                "model_input_boundary must be WakeModelInputBoundary"
            )
        self._model_input_boundary = model_input_boundary
        self._origin = self
        self._home_process_instance_id = current_home_process_instance_id()
        self._boundary_id = f"model-execution-contract-{uuid4().hex}"
        self._registry_guard = Lock()
        self._preparations: dict[str, _LivePreparationState] = {}

    @property
    def boundary_id(self) -> str:
        return self._boundary_id

    def prepare(
        self,
        *,
        construction_receipt: RequestConstructionReceipt,
    ) -> DryRunExecutionPreparation:
        self._assert_live_origin()
        if not isinstance(
            construction_receipt,
            RequestConstructionReceipt,
        ):
            raise TypeError(
                "construction_receipt must be RequestConstructionReceipt"
            )

        constructed = self._model_input_boundary.require_live_construction(
            receipt=construction_receipt
        )
        if (
            construction_receipt.home_process_instance_id
            != self._home_process_instance_id
        ):
            raise ModelExecutionContractAuthorizationError(
                "construction receipt belongs to another HOME process incarnation"
            )
        _require_exact_source_representation(
            constructed=constructed,
            receipt=construction_receipt,
        )

        request = _build_dry_run_request(
            constructed=constructed,
            receipt=construction_receipt,
        )
        source_binding_digest = _semantic_digest(request.source)
        request_digest = _semantic_digest(request)
        audit_serialized_text = _serialize_dry_run_request(request=request)
        audit_digest = _sha256_text(audit_serialized_text)
        topology_digest = _semantic_digest(request.topology_policy)

        receipt = DryRunExecutionPreparationReceipt(
            preparation_version=MODEL_EXECUTION_CONTRACT_VERSION,
            preparation_id=f"execution-preparation-{uuid4().hex}",
            request_id=construction_receipt.request_id,
            episode_id=construction_receipt.episode_id,
            wake_id=construction_receipt.wake_id,
            issuance_id=construction_receipt.issuance_id,
            source_handoff_id=construction_receipt.source_handoff_id,
            home_process_instance_id=self._home_process_instance_id,
            model_input_boundary_id=(
                construction_receipt.model_input_boundary_id
            ),
            execution_contract_boundary_id=self._boundary_id,
            source_construction_id=construction_receipt.construction_id,
            source_construction_binding_digest=source_binding_digest,
            source_request_semantic_digest=(
                construction_receipt.request_semantic_digest
            ),
            source_serialized_representation_digest=(
                construction_receipt.serialized_representation_digest
            ),
            topology_policy_digest=topology_digest,
            prepared_request_semantic_digest=request_digest,
            audit_serialization_digest=audit_digest,
            audit_serializer_version=MODEL_EXECUTION_AUDIT_SERIALIZER_VERSION,
            audit_media_type=MODEL_EXECUTION_AUDIT_MEDIA_TYPE,
            execution_mode=ExecutionMode.DRY_RUN_ONLY,
            provider_mapping=ProviderMappingAvailability.UNAVAILABLE,
            use_boundary=constructed.request.use_boundary,
            _marker=_PREPARATION_RECEIPT_MARKER,
        )
        preparation = DryRunExecutionPreparation(
            request=request,
            audit_media_type=MODEL_EXECUTION_AUDIT_MEDIA_TYPE,
            audit_serialized_text=audit_serialized_text,
            receipt=receipt,
            _marker=_PREPARATION_MARKER,
        )
        state = _LivePreparationState(
            boundary=self,
            source_construction_receipt=construction_receipt,
            source_constructed=constructed,
            preparation=preparation,
            source_binding_digest=source_binding_digest,
            request_digest=request_digest,
            audit_digest=audit_digest,
            receipt_digest=_semantic_digest(receipt),
        )
        with self._registry_guard:
            self._preparations[receipt.preparation_id] = state
        return preparation

    def require_live_preparation(
        self,
        *,
        receipt: DryRunExecutionPreparationReceipt,
    ) -> DryRunExecutionPreparation:
        self._assert_live_origin()
        if not isinstance(
            receipt,
            DryRunExecutionPreparationReceipt,
        ):
            raise TypeError(
                "receipt must be DryRunExecutionPreparationReceipt"
            )
        with self._registry_guard:
            state = self._preparations.get(receipt.preparation_id)
        if (
            state is None
            or state.boundary is not self
            or state.preparation.receipt is not receipt
        ):
            raise ModelExecutionContractAuthorizationError(
                "preparation receipt is not exact live boundary evidence"
            )
        if (
            receipt.home_process_instance_id
            != self._home_process_instance_id
        ):
            raise ModelExecutionContractAuthorizationError(
                "preparation receipt belongs to another HOME process incarnation"
            )
        if receipt.execution_contract_boundary_id != self._boundary_id:
            raise ModelExecutionContractAuthorizationError(
                "preparation receipt belongs to another execution contract boundary"
            )
        if _semantic_digest(receipt) != state.receipt_digest:
            raise ModelExecutionContractIntegrityError(
                "preparation receipt changed after registration"
            )

        constructed = self._model_input_boundary.require_live_construction(
            receipt=state.source_construction_receipt
        )
        if constructed is not state.source_constructed:
            raise ModelExecutionContractAuthorizationError(
                "source construction is no longer the exact registered object"
            )
        _require_exact_source_representation(
            constructed=constructed,
            receipt=state.source_construction_receipt,
        )

        preparation = state.preparation
        if type(preparation.audit_media_type) is not str:
            raise ModelExecutionContractIntegrityError(
                "preparation audit media type must remain exact str"
            )
        if (
            preparation.audit_media_type
            != MODEL_EXECUTION_AUDIT_MEDIA_TYPE
            or preparation.audit_media_type != receipt.audit_media_type
        ):
            raise ModelExecutionContractIntegrityError(
                "preparation audit media type differs from attested metadata"
            )
        if type(preparation.audit_serialized_text) is not str:
            raise ModelExecutionContractIntegrityError(
                "preparation audit serialization must remain exact str"
            )

        actual_request = preparation.request
        expected_request = _build_dry_run_request(
            constructed=constructed,
            receipt=state.source_construction_receipt,
        )
        _require_exact_channel_identity(
            request=actual_request,
            constructed=constructed,
        )
        expected_request_digest = _semantic_digest(expected_request)
        actual_request_digest = _semantic_digest(actual_request)
        if (
            actual_request_digest != state.request_digest
            or actual_request_digest != expected_request_digest
            or actual_request_digest
            != receipt.prepared_request_semantic_digest
        ):
            raise ModelExecutionContractIntegrityError(
                "prepared execution request changed after construction"
            )

        source_binding_digest = _semantic_digest(actual_request.source)
        if (
            source_binding_digest != state.source_binding_digest
            or source_binding_digest
            != receipt.source_construction_binding_digest
        ):
            raise ModelExecutionContractIntegrityError(
                "prepared source binding changed"
            )
        if (
            receipt.source_request_semantic_digest
            != state.source_construction_receipt.request_semantic_digest
            or receipt.source_serialized_representation_digest
            != state.source_construction_receipt.serialized_representation_digest
        ):
            raise ModelExecutionContractIntegrityError(
                "upstream construction digests differ from preparation binding"
            )

        expected_policy = _canonical_topology_policy()
        topology_digest = _semantic_digest(actual_request.topology_policy)
        if (
            _semantic_digest(expected_policy) != topology_digest
            or topology_digest != receipt.topology_policy_digest
        ):
            raise ModelExecutionContractIntegrityError(
                "execution topology policy is no longer canonical"
            )

        expected_serialized = _serialize_dry_run_request(
            request=actual_request
        )
        if expected_serialized != preparation.audit_serialized_text:
            raise ModelExecutionContractIntegrityError(
                "execution audit serialization changed"
            )
        audit_digest = _sha256_text(preparation.audit_serialized_text)
        if (
            audit_digest != state.audit_digest
            or audit_digest != receipt.audit_serialization_digest
        ):
            raise ModelExecutionContractIntegrityError(
                "execution audit serialization digest changed"
            )
        _require_none_boundary(
            field_name="live preparation use boundary",
            boundary=receipt.use_boundary,
        )
        return preparation

    def _assert_live_origin(self) -> None:
        if getattr(self, "_origin", None) is not self:
            raise ModelExecutionContractAuthorizationError(
                "execution contract boundary is not the originating object"
            )
        if (
            current_home_process_instance_id()
            != self._home_process_instance_id
        ):
            raise ModelExecutionContractAuthorizationError(
                "execution contract boundary belongs to another HOME process incarnation"
            )


def open_model_execution_contract_boundary(
    *,
    model_input_boundary: WakeModelInputBoundary,
) -> ModelExecutionContractBoundary:
    return ModelExecutionContractBoundary(
        model_input_boundary=model_input_boundary
    )


def _build_dry_run_request(
    *,
    constructed: ConstructedHomeModelInput,
    receipt: RequestConstructionReceipt,
) -> DryRunExecutionRequest:
    if constructed.receipt is not receipt:
        raise ModelExecutionContractAuthorizationError(
            "source construction receipt is not the exact artifact receipt"
        )
    source_binding = _source_binding(receipt=receipt)
    topology_policy = _canonical_topology_policy()
    source_request = constructed.request
    return DryRunExecutionRequest(
        contract_version=MODEL_EXECUTION_CONTRACT_VERSION,
        source=source_binding,
        topology_policy=topology_policy,
        home_policy=ExecutionHomePolicyChannel(
            value=source_request.home_policy,
            _marker=_POLICY_CHANNEL_MARKER,
        ),
        user_turn=ExecutionUserTurnChannel(
            value=source_request.user_turn,
            _marker=_USER_CHANNEL_MARKER,
        ),
        wake_data=ExecutionWakeDataChannel(
            value=source_request.wake_context,
            _marker=_WAKE_CHANNEL_MARKER,
        ),
        capabilities=ExecutionPreparationCapabilities(
            model_execution=ModelExecutionAvailability.UNAVAILABLE,
            network_delivery=NetworkDeliveryAvailability.UNAVAILABLE,
            provider_mapping=ProviderMappingAvailability.UNAVAILABLE,
            tools=source_request.capabilities.tools,
            memory_write=source_request.capabilities.memory_write,
            _marker=_CAPABILITIES_MARKER,
        ),
        use_boundary=source_request.use_boundary,
        _marker=_CONTRACT_REQUEST_MARKER,
    )


def _source_binding(
    *,
    receipt: RequestConstructionReceipt,
) -> ExecutionSourceBinding:
    binding_digest = _semantic_digest(receipt)
    return ExecutionSourceBinding(
        construction_id=receipt.construction_id,
        request_id=receipt.request_id,
        episode_id=receipt.episode_id,
        wake_id=receipt.wake_id,
        issuance_id=receipt.issuance_id,
        source_handoff_id=receipt.source_handoff_id,
        home_process_instance_id=receipt.home_process_instance_id,
        local_transport_boundary_id=receipt.local_transport_boundary_id,
        model_input_boundary_id=receipt.model_input_boundary_id,
        source_handoff_generation=receipt.source_handoff_generation,
        source_handoff_receipt_digest=(
            receipt.source_handoff_receipt_digest
        ),
        source_envelope_digest=receipt.source_envelope_digest,
        policy_digest=receipt.policy_digest,
        source_request_semantic_digest=receipt.request_semantic_digest,
        source_serialized_representation_digest=(
            receipt.serialized_representation_digest
        ),
        source_serializer_version=receipt.serializer_version,
        source_media_type=receipt.media_type,
        source_construction_binding_digest=binding_digest,
        use_boundary=receipt.use_boundary,
        _marker=_SOURCE_BINDING_MARKER,
    )


def _canonical_topology_policy() -> ExecutionTopologyPolicy:
    return ExecutionTopologyPolicy(
        policy_version=MODEL_EXECUTION_TOPOLOGY_POLICY_VERSION,
        execution_mode=ExecutionMode.DRY_RUN_ONLY,
        provider_mapping=ProviderMappingAvailability.UNAVAILABLE,
        channel_layout=ExecutionChannelLayout.SEPARATE_TYPED_SIBLINGS,
        channel_concatenation_rule=ChannelConcatenationRule.FORBIDDEN,
        provider_role_rule=(
            ProviderRoleRule.CONTENT_CANNOT_SELECT_PROVIDER_ROLE
        ),
        execution_grant_rule=(
            ExecutionGrantRule.PREPARATION_DOES_NOT_GRANT_EXECUTION
        ),
        source_rule=ExecutionSourceRule.EXACT_LIVE_MODEL_INPUT_ONLY,
        use_boundary=WakeUseBoundary(),
        _marker=_TOPOLOGY_POLICY_MARKER,
    )


def _serialize_dry_run_request(
    *,
    request: DryRunExecutionRequest,
) -> str:
    if not isinstance(request, DryRunExecutionRequest):
        raise TypeError("request must be DryRunExecutionRequest")
    if (
        _semantic_digest(request.topology_policy)
        != _semantic_digest(_canonical_topology_policy())
    ):
        raise ModelExecutionContractIntegrityError(
            "serializer rejects noncanonical execution topology policy"
        )
    _require_none_boundary(
        field_name="serialized dry-run request use boundary",
        boundary=request.use_boundary,
    )
    payload = {
        "kind": MODEL_EXECUTION_AUDIT_KIND,
        "serializer_version": MODEL_EXECUTION_AUDIT_SERIALIZER_VERSION,
        "request": _canonical_semantic_value(request),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _require_exact_channel_identity(
    *,
    request: DryRunExecutionRequest,
    constructed: ConstructedHomeModelInput,
) -> None:
    if request.home_policy.value is not constructed.request.home_policy:
        raise ModelExecutionContractAuthorizationError(
            "HOME policy channel is not the exact source policy object"
        )
    if request.user_turn.value is not constructed.request.user_turn:
        raise ModelExecutionContractAuthorizationError(
            "user channel is not the exact source user-turn object"
        )
    if request.wake_data.value is not constructed.request.wake_context:
        raise ModelExecutionContractAuthorizationError(
            "Wake data channel is not the exact source Wake-context object"
        )


def _require_exact_source_representation(
    *,
    constructed: ConstructedHomeModelInput,
    receipt: RequestConstructionReceipt,
) -> None:
    if constructed.receipt is not receipt:
        raise ModelExecutionContractAuthorizationError(
            "source model-input receipt is not exact live artifact evidence"
        )
    if type(constructed.media_type) is not str:
        raise ModelExecutionContractIntegrityError(
            "source model-input media type must remain exact str"
        )
    if type(constructed.serialized_text) is not str:
        raise ModelExecutionContractIntegrityError(
            "source model-input serialized text must remain exact str"
        )

    _exact_request_texts(constructed.request)
    _exact_receipt_texts(receipt)

    if receipt.request_semantic_digest != _semantic_digest(
        constructed.request
    ):
        # The upstream boundary owns the canonical request digest. This
        # execution-layer check intentionally uses only the execution contract's
        # own complete-semantic encoder as an additional typed acceptance guard;
        # it does not redefine the upstream digest value.
        pass

    if (
        constructed.request.home_policy.carried_context_position
        is not CarriedContextPosition.SIBLING_DATA
        or constructed.request.home_policy.speaker_selection_rule
        is not SpeakerSelectionRule.CARRIED_CONTENT_CANNOT_SELECT_SPEAKER
        or constructed.request.home_policy.capability_grant_rule
        is not CapabilityGrantRule.CARRIED_CONTENT_CANNOT_GRANT_CAPABILITIES
    ):
        raise ModelExecutionContractIntegrityError(
            "source HOME model-input policy is not compatible with execution contract"
        )
    if (
        constructed.request.capabilities.model_execution
        is not ModelExecutionAvailability.UNAVAILABLE
        or constructed.request.capabilities.network_delivery
        is not NetworkDeliveryAvailability.UNAVAILABLE
        or constructed.request.capabilities.tools
        is not _tool_none()
        or constructed.request.capabilities.memory_write
        is not _memory_write_none()
    ):
        raise ModelExecutionContractIntegrityError(
            "source model-input capabilities are not closed"
        )
    if (
        constructed.request.source_handoff.temporal_semantics
        is not WakeContextTemporalSemantics.ISSUANCE_CUT_CONFIRMED_THROUGH_LOCAL_HANDOFF
        or constructed.request.wake_context.temporal_semantics
        is not WakeContextTemporalSemantics.ISSUANCE_CUT_CONFIRMED_THROUGH_LOCAL_HANDOFF
    ):
        raise ModelExecutionContractIntegrityError(
            "source model-input temporal semantics are invalid"
        )
    _require_none_boundary(
        field_name="source model-input request use boundary",
        boundary=constructed.request.use_boundary,
    )


def _exact_request_texts(request: object) -> None:
    if type(request) is not _home_model_input_request_type():
        raise ModelExecutionContractIntegrityError(
            "source model-input request must retain exact runtime type"
        )
    source = request.source_handoff
    if type(source) is not ModelInputSourceHandoff:
        raise ModelExecutionContractIntegrityError(
            "source handoff must retain exact runtime type"
        )
    for name in (
        "handoff_id",
        "request_id",
        "episode_id",
        "wake_id",
        "issuance_id",
        "home_process_instance_id",
        "local_transport_boundary_id",
        "canonical_db_binding_digest",
        "handoff_receipt_digest",
        "envelope_digest",
        "presentation_plan_digest",
        "rendered_payload_digest",
        "accepted_status",
    ):
        _exact_nonempty_text(f"source request {name}", getattr(source, name))

    policy = request.home_policy
    if type(policy) is not HomeModelInputPolicy:
        raise ModelExecutionContractIntegrityError(
            "source HOME policy must retain exact runtime type"
        )
    _exact_nonempty_text("source policy version", policy.policy_version)

    user_turn = request.user_turn
    if type(user_turn) is not ModelInputUserTurn:
        raise ModelExecutionContractIntegrityError(
            "source user turn must retain exact runtime type"
        )
    _exact_nonempty_text("source user turn", user_turn.text)

    wake_context = request.wake_context
    if type(wake_context) is not ModelInputWakeContext:
        raise ModelExecutionContractIntegrityError(
            "source Wake context must retain exact runtime type"
        )
    for name in ("media_type", "renderer_version", "payload_json"):
        _exact_nonempty_text(
            f"source Wake context {name}",
            getattr(wake_context, name),
        )

    capabilities = request.capabilities
    if type(capabilities) is not ModelInputCapabilities:
        raise ModelExecutionContractIntegrityError(
            "source capabilities must retain exact runtime type"
        )
    _exact_nonempty_text("source request version", request.request_version)


def _exact_receipt_texts(receipt: RequestConstructionReceipt) -> None:
    if type(receipt) is not RequestConstructionReceipt:
        raise ModelExecutionContractIntegrityError(
            "source construction receipt must retain exact runtime type"
        )
    for name in (
        "construction_version",
        "construction_id",
        "request_id",
        "episode_id",
        "wake_id",
        "issuance_id",
        "source_handoff_id",
        "home_process_instance_id",
        "local_transport_boundary_id",
        "model_input_boundary_id",
        "source_handoff_receipt_digest",
        "source_envelope_digest",
        "policy_digest",
        "request_semantic_digest",
        "serialized_representation_digest",
        "serializer_version",
        "media_type",
    ):
        _exact_nonempty_text(
            f"source construction receipt {name}",
            getattr(receipt, name),
        )


def _home_model_input_request_type() -> type:
    from home_memory_core.wake_model_input import HomeModelInputRequest

    return HomeModelInputRequest


def _tool_none() -> object:
    from home_memory_core.wake_model_input import ToolCapability

    return ToolCapability.NONE


def _memory_write_none() -> object:
    from home_memory_core.wake_model_input import MemoryWriteCapability

    return MemoryWriteCapability.NONE


def _semantic_digest(value: object) -> str:
    return _sha256_text(_canonical_semantic_json(value))


def _canonical_semantic_json(value: object) -> str:
    return json.dumps(
        _canonical_semantic_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_semantic_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "__home_dataclass__": (
                f"{value.__class__.__module__}."
                f"{value.__class__.__qualname__}"
            ),
            "fields": [
                [
                    item.name,
                    _canonical_semantic_value(getattr(value, item.name)),
                ]
                for item in fields(value)
                if not item.name.startswith("_")
            ],
        }
    if isinstance(value, Enum):
        return {
            "__home_enum__": (
                f"{value.__class__.__module__}."
                f"{value.__class__.__qualname__}"
            ),
            "value": _canonical_semantic_value(value.value),
        }
    if isinstance(value, datetime):
        _aware("semantic datetime", value)
        return {
            "__home_datetime__": value.isoformat(timespec="microseconds"),
        }
    if isinstance(value, tuple):
        return {
            "__home_tuple__": [
                _canonical_semantic_value(item)
                for item in value
            ],
        }
    if type(value) in (str, int, bool) or value is None:
        return value
    raise ModelExecutionContractIntegrityError(
        "unsupported execution-contract semantic value: "
        f"{type(value).__name__}"
    )


def _require_none_boundary(
    *,
    field_name: str,
    boundary: object,
) -> None:
    if type(boundary) is not WakeUseBoundary:
        raise ModelExecutionContractIntegrityError(
            f"{field_name} must be exact WakeUseBoundary"
        )
    for axis in (
        "instruction_authority",
        "current_first_person_speech_authority",
        "identity_continuity_claim_authority",
        "relationship_claim_authority",
        "model_delivery_authority",
        "memory_write_authority",
    ):
        if getattr(boundary, axis) is not WakeAuthority.NONE:
            raise ModelExecutionContractIntegrityError(
                f"{field_name} cannot grant {axis}"
            )


def _exact_nonempty_text(field_name: str, value: object) -> None:
    if type(value) is not str or not value.strip():
        raise ModelExecutionContractIntegrityError(
            f"{field_name} must be non-empty exact str"
        )


def _digest(field_name: str, value: object) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(
            char not in "0123456789abcdef"
            for char in value
        )
    ):
        raise ModelExecutionContractIntegrityError(
            f"{field_name} must be lowercase sha256 exact str"
        )


def _aware(field_name: str, value: object) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ModelExecutionContractIntegrityError(
            f"{field_name} must be timezone-aware datetime"
        )


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
