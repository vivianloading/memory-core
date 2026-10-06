from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import Enum, StrEnum
from hashlib import sha256
import json
from threading import Lock
from uuid import uuid4

from home_memory_core.process_boundary import current_home_process_instance_id
from home_memory_core.wake_local_handoff import (
    LocalWakeTransportBoundary,
    WakeHandoffReceipt,
)
from home_memory_core.wake_packet import (
    WakeAuthority,
    WakeUseBoundary,
)


WAKE_MODEL_INPUT_VERSION = "wake-model-input-v0.1"
WAKE_MODEL_POLICY_VERSION = "home-model-policy-v0.1"
WAKE_MODEL_SERIALIZER_VERSION = "wake-model-input-json-v0.1"
WAKE_MODEL_INPUT_MEDIA_TYPE = "application/vnd.home.model-input+json"
WAKE_MODEL_INPUT_KIND = "home_model_input_data"

_MODEL_INPUT_MARKER = object()
_MODEL_POLICY_MARKER = object()
_SOURCE_HANDOFF_MARKER = object()
_USER_TURN_MARKER = object()
_WAKE_CONTEXT_MARKER = object()
_CAPABILITIES_MARKER = object()
_CONSTRUCTION_RECEIPT_MARKER = object()
_CONSTRUCTED_INPUT_MARKER = object()


class WakeModelInputError(RuntimeError):
    """Wake model-input construction violated the v0.1 contract."""


class WakeModelInputIntegrityError(WakeModelInputError):
    """A model-input artifact differs from exact bound semantics."""


class WakeModelInputAuthorizationError(WakeModelInputError):
    """A process-local construction witness is not live/originating."""


class CarriedContextPosition(StrEnum):
    SIBLING_DATA = "sibling_data"


class SpeakerSelectionRule(StrEnum):
    CARRIED_CONTENT_CANNOT_SELECT_SPEAKER = (
        "carried_content_cannot_select_speaker"
    )


class CapabilityGrantRule(StrEnum):
    CARRIED_CONTENT_CANNOT_GRANT_CAPABILITIES = (
        "carried_content_cannot_grant_capabilities"
    )


class ModelExecutionAvailability(StrEnum):
    UNAVAILABLE = "unavailable"


class NetworkDeliveryAvailability(StrEnum):
    UNAVAILABLE = "unavailable"


class ToolCapability(StrEnum):
    NONE = "none"


class MemoryWriteCapability(StrEnum):
    NONE = "none"


class WakeContextTemporalSemantics(StrEnum):
    AT_COMPLETED_LOCAL_HANDOFF_CUT = "at_completed_local_handoff_cut"


@dataclass(frozen=True)
class HomeModelInputPolicy:
    policy_version: str
    carried_context_position: CarriedContextPosition
    speaker_selection_rule: SpeakerSelectionRule
    capability_grant_rule: CapabilityGrantRule
    use_boundary: WakeUseBoundary
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _MODEL_POLICY_MARKER:
            raise WakeModelInputAuthorizationError(
                "HOME model-input policy must be constructed by HOME"
            )
        if self.policy_version != WAKE_MODEL_POLICY_VERSION:
            raise WakeModelInputIntegrityError(
                "HOME model-input policy version is invalid"
            )
        if (
            self.carried_context_position
            is not CarriedContextPosition.SIBLING_DATA
        ):
            raise WakeModelInputIntegrityError(
                "carried Wake context must remain sibling data"
            )
        if (
            self.speaker_selection_rule
            is not SpeakerSelectionRule.CARRIED_CONTENT_CANNOT_SELECT_SPEAKER
        ):
            raise WakeModelInputIntegrityError(
                "carried content cannot select the request speaker"
            )
        if (
            self.capability_grant_rule
            is not CapabilityGrantRule.CARRIED_CONTENT_CANNOT_GRANT_CAPABILITIES
        ):
            raise WakeModelInputIntegrityError(
                "carried content cannot grant request capabilities"
            )
        _require_none_boundary(
            field_name="policy use boundary",
            boundary=self.use_boundary,
        )


@dataclass(frozen=True)
class ModelInputCapabilities:
    model_execution: ModelExecutionAvailability
    network_delivery: NetworkDeliveryAvailability
    tools: ToolCapability
    memory_write: MemoryWriteCapability
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _CAPABILITIES_MARKER:
            raise WakeModelInputAuthorizationError(
                "model-input capabilities must be constructed by HOME"
            )
        if self.model_execution is not ModelExecutionAvailability.UNAVAILABLE:
            raise WakeModelInputIntegrityError(
                "v0.1 model execution must remain unavailable"
            )
        if self.network_delivery is not NetworkDeliveryAvailability.UNAVAILABLE:
            raise WakeModelInputIntegrityError(
                "v0.1 network delivery must remain unavailable"
            )
        if self.tools is not ToolCapability.NONE:
            raise WakeModelInputIntegrityError(
                "v0.1 tool capability must remain none"
            )
        if self.memory_write is not MemoryWriteCapability.NONE:
            raise WakeModelInputIntegrityError(
                "v0.1 memory-write capability must remain none"
            )


@dataclass(frozen=True)
class ModelInputSourceHandoff:
    handoff_id: str
    request_id: str
    episode_id: str
    wake_id: str
    issuance_id: str
    home_process_instance_id: str
    local_transport_boundary_id: str
    canonical_db_binding_digest: str
    generation: int
    handoff_receipt_digest: str
    envelope_digest: str
    presentation_plan_digest: str
    rendered_payload_digest: str
    accepted_status: str
    as_of: datetime
    temporal_semantics: WakeContextTemporalSemantics
    use_boundary: WakeUseBoundary
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _SOURCE_HANDOFF_MARKER:
            raise WakeModelInputAuthorizationError(
                "model-input source handoff must come from live local acceptance"
            )
        for field_name in (
            "handoff_id",
            "request_id",
            "episode_id",
            "wake_id",
            "issuance_id",
            "home_process_instance_id",
            "local_transport_boundary_id",
            "accepted_status",
        ):
            _text(field_name, getattr(self, field_name))
        for field_name in (
            "canonical_db_binding_digest",
            "handoff_receipt_digest",
            "envelope_digest",
            "presentation_plan_digest",
            "rendered_payload_digest",
        ):
            _digest(field_name, getattr(self, field_name))
        if (
            not isinstance(self.generation, int)
            or isinstance(self.generation, bool)
            or self.generation < 0
        ):
            raise WakeModelInputIntegrityError(
                "source handoff generation must be non-negative integer"
            )
        _aware("as_of", self.as_of)
        if (
            self.temporal_semantics
            is not WakeContextTemporalSemantics.AT_COMPLETED_LOCAL_HANDOFF_CUT
        ):
            raise WakeModelInputIntegrityError(
                "Wake context must remain bound to completed local handoff cut"
            )
        _require_none_boundary(
            field_name="source handoff use boundary",
            boundary=self.use_boundary,
        )


@dataclass(frozen=True)
class ModelInputUserTurn:
    text: str
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _USER_TURN_MARKER:
            raise WakeModelInputAuthorizationError(
                "model-input user turn must come from accepted handoff"
            )
        _text("user turn text", self.text)


@dataclass(frozen=True)
class ModelInputWakeContext:
    media_type: str
    renderer_version: str
    payload_json: str
    temporal_semantics: WakeContextTemporalSemantics
    use_boundary: WakeUseBoundary
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _WAKE_CONTEXT_MARKER:
            raise WakeModelInputAuthorizationError(
                "model-input Wake context must come from accepted handoff"
            )
        for field_name in (
            "media_type",
            "renderer_version",
            "payload_json",
        ):
            _text(field_name, getattr(self, field_name))
        if (
            self.temporal_semantics
            is not WakeContextTemporalSemantics.AT_COMPLETED_LOCAL_HANDOFF_CUT
        ):
            raise WakeModelInputIntegrityError(
                "Wake context temporal semantics are invalid"
            )
        _require_none_boundary(
            field_name="Wake context use boundary",
            boundary=self.use_boundary,
        )


@dataclass(frozen=True)
class HomeModelInputRequest:
    request_version: str
    source_handoff: ModelInputSourceHandoff
    home_policy: HomeModelInputPolicy
    user_turn: ModelInputUserTurn
    wake_context: ModelInputWakeContext
    capabilities: ModelInputCapabilities
    use_boundary: WakeUseBoundary
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _MODEL_INPUT_MARKER:
            raise WakeModelInputAuthorizationError(
                "HOME model-input request must be constructed by the boundary"
            )
        if self.request_version != WAKE_MODEL_INPUT_VERSION:
            raise WakeModelInputIntegrityError(
                "HOME model-input request version is invalid"
            )
        if not isinstance(
            self.source_handoff,
            ModelInputSourceHandoff,
        ):
            raise WakeModelInputIntegrityError(
                "model-input source handoff is invalid"
            )
        if not isinstance(self.home_policy, HomeModelInputPolicy):
            raise WakeModelInputIntegrityError(
                "model-input HOME policy is invalid"
            )
        if not isinstance(self.user_turn, ModelInputUserTurn):
            raise WakeModelInputIntegrityError(
                "model-input user turn is invalid"
            )
        if not isinstance(
            self.wake_context,
            ModelInputWakeContext,
        ):
            raise WakeModelInputIntegrityError(
                "model-input Wake context is invalid"
            )
        if not isinstance(
            self.capabilities,
            ModelInputCapabilities,
        ):
            raise WakeModelInputIntegrityError(
                "model-input capabilities are invalid"
            )
        _require_none_boundary(
            field_name="request use boundary",
            boundary=self.use_boundary,
        )
        if self.use_boundary != self.home_policy.use_boundary:
            raise WakeModelInputIntegrityError(
                "request and HOME policy authority boundaries differ"
            )
        if self.use_boundary != self.wake_context.use_boundary:
            raise WakeModelInputIntegrityError(
                "request and Wake context authority boundaries differ"
            )
        if self.use_boundary != self.source_handoff.use_boundary:
            raise WakeModelInputIntegrityError(
                "request and source handoff authority boundaries differ"
            )
        if (
            self.source_handoff.temporal_semantics
            is not self.wake_context.temporal_semantics
        ):
            raise WakeModelInputIntegrityError(
                "source and Wake context temporal semantics differ"
            )
        if (
            _sha256_text(self.wake_context.payload_json)
            != self.source_handoff.rendered_payload_digest
        ):
            raise WakeModelInputIntegrityError(
                "Wake context payload differs from accepted handoff digest"
            )
        expected_policy = _canonical_home_policy()
        if (
            _canonical_semantic_json(self.home_policy)
            != _canonical_semantic_json(expected_policy)
        ):
            raise WakeModelInputIntegrityError(
                "HOME model-input policy differs from canonical fixed policy"
            )


@dataclass(frozen=True)
class RequestConstructionReceipt:
    construction_version: str
    construction_id: str
    request_id: str
    episode_id: str
    wake_id: str
    issuance_id: str
    source_handoff_id: str
    home_process_instance_id: str
    local_transport_boundary_id: str
    source_handoff_generation: int
    source_handoff_receipt_digest: str
    source_envelope_digest: str
    policy_digest: str
    request_semantic_digest: str
    serialized_representation_digest: str
    serializer_version: str
    media_type: str
    use_boundary: WakeUseBoundary
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _CONSTRUCTION_RECEIPT_MARKER:
            raise WakeModelInputAuthorizationError(
                "request construction receipt must come from model-input boundary"
            )
        if self.construction_version != WAKE_MODEL_INPUT_VERSION:
            raise WakeModelInputIntegrityError(
                "construction receipt version is invalid"
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
            "serializer_version",
            "media_type",
        ):
            _text(field_name, getattr(self, field_name))
        for field_name in (
            "source_handoff_receipt_digest",
            "source_envelope_digest",
            "policy_digest",
            "request_semantic_digest",
            "serialized_representation_digest",
        ):
            _digest(field_name, getattr(self, field_name))
        if (
            not isinstance(self.source_handoff_generation, int)
            or isinstance(self.source_handoff_generation, bool)
            or self.source_handoff_generation < 0
        ):
            raise WakeModelInputIntegrityError(
                "construction source generation must be non-negative integer"
            )
        if self.serializer_version != WAKE_MODEL_SERIALIZER_VERSION:
            raise WakeModelInputIntegrityError(
                "construction serializer version is invalid"
            )
        if self.media_type != WAKE_MODEL_INPUT_MEDIA_TYPE:
            raise WakeModelInputIntegrityError(
                "construction media type is invalid"
            )
        _require_none_boundary(
            field_name="construction receipt use boundary",
            boundary=self.use_boundary,
        )


@dataclass(frozen=True)
class ConstructedHomeModelInput:
    request: HomeModelInputRequest
    media_type: str
    serialized_text: str
    receipt: RequestConstructionReceipt
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _CONSTRUCTED_INPUT_MARKER:
            raise WakeModelInputAuthorizationError(
                "constructed model input must come from model-input boundary"
            )
        if not isinstance(self.request, HomeModelInputRequest):
            raise WakeModelInputIntegrityError(
                "constructed model input request is invalid"
            )
        if self.media_type != WAKE_MODEL_INPUT_MEDIA_TYPE:
            raise WakeModelInputIntegrityError(
                "constructed model input media type is invalid"
            )
        _text("serialized_text", self.serialized_text)
        if not isinstance(
            self.receipt,
            RequestConstructionReceipt,
        ):
            raise WakeModelInputIntegrityError(
                "constructed model input receipt is invalid"
            )
        if (
            _sha256_text(self.serialized_text)
            != self.receipt.serialized_representation_digest
        ):
            raise WakeModelInputIntegrityError(
                "serialized model input differs from construction receipt"
            )


@dataclass(frozen=True)
class _LiveConstructionState:
    boundary: "WakeModelInputBoundary"
    source_handoff_receipt: WakeHandoffReceipt
    constructed: ConstructedHomeModelInput
    request_digest: str
    serialized_digest: str
    construction_receipt_digest: str


class WakeModelInputBoundary:
    """Construct exact typed model input from completed local Wake handoff."""

    def __init__(
        self,
        *,
        local_transport_boundary: LocalWakeTransportBoundary,
    ) -> None:
        if not isinstance(
            local_transport_boundary,
            LocalWakeTransportBoundary,
        ):
            raise TypeError(
                "local_transport_boundary must be LocalWakeTransportBoundary"
            )
        self._local_transport_boundary = local_transport_boundary
        self._origin = self
        self._home_process_instance_id = current_home_process_instance_id()
        self._boundary_id = f"wake-model-input-{uuid4().hex}"
        self._registry_guard = Lock()
        self._constructions: dict[str, _LiveConstructionState] = {}

    @property
    def boundary_id(self) -> str:
        return self._boundary_id

    def construct(
        self,
        *,
        handoff_receipt: WakeHandoffReceipt,
    ) -> ConstructedHomeModelInput:
        self._assert_live_origin()
        if not isinstance(handoff_receipt, WakeHandoffReceipt):
            raise TypeError(
                "handoff_receipt must be WakeHandoffReceipt"
            )

        envelope = self._local_transport_boundary.require_live_acceptance(
            receipt=handoff_receipt
        )
        if (
            handoff_receipt.home_process_instance_id
            != self._home_process_instance_id
        ):
            raise WakeModelInputAuthorizationError(
                "handoff receipt belongs to another HOME process incarnation"
            )

        source_receipt_digest = _semantic_digest(handoff_receipt)
        rendered = envelope.rendered
        rendered_receipt = rendered.receipt
        use_boundary = envelope.use_boundary
        _require_none_boundary(
            field_name="accepted envelope use boundary",
            boundary=use_boundary,
        )

        source_handoff = ModelInputSourceHandoff(
            handoff_id=handoff_receipt.handoff_id,
            request_id=handoff_receipt.request_id,
            episode_id=handoff_receipt.episode_id,
            wake_id=handoff_receipt.wake_id,
            issuance_id=handoff_receipt.issuance_id,
            home_process_instance_id=(
                handoff_receipt.home_process_instance_id
            ),
            local_transport_boundary_id=(
                handoff_receipt.local_transport_boundary_id
            ),
            canonical_db_binding_digest=(
                handoff_receipt.canonical_db_binding_digest
            ),
            generation=handoff_receipt.generation,
            handoff_receipt_digest=source_receipt_digest,
            envelope_digest=handoff_receipt.envelope_digest,
            presentation_plan_digest=(
                handoff_receipt.presentation_plan_digest
            ),
            rendered_payload_digest=(
                handoff_receipt.rendered_payload_digest
            ),
            accepted_status=handoff_receipt.acceptance_status,
            as_of=rendered_receipt.as_of,
            temporal_semantics=(
                WakeContextTemporalSemantics.AT_COMPLETED_LOCAL_HANDOFF_CUT
            ),
            use_boundary=use_boundary,
            _marker=_SOURCE_HANDOFF_MARKER,
        )
        policy = _canonical_home_policy()
        user_turn = ModelInputUserTurn(
            text=envelope.user_input,
            _marker=_USER_TURN_MARKER,
        )
        wake_context = ModelInputWakeContext(
            media_type=rendered.media_type,
            renderer_version=rendered.renderer_version,
            payload_json=rendered.payload_json,
            temporal_semantics=(
                WakeContextTemporalSemantics.AT_COMPLETED_LOCAL_HANDOFF_CUT
            ),
            use_boundary=use_boundary,
            _marker=_WAKE_CONTEXT_MARKER,
        )
        capabilities = ModelInputCapabilities(
            model_execution=ModelExecutionAvailability.UNAVAILABLE,
            network_delivery=NetworkDeliveryAvailability.UNAVAILABLE,
            tools=ToolCapability.NONE,
            memory_write=MemoryWriteCapability.NONE,
            _marker=_CAPABILITIES_MARKER,
        )
        request = HomeModelInputRequest(
            request_version=WAKE_MODEL_INPUT_VERSION,
            source_handoff=source_handoff,
            home_policy=policy,
            user_turn=user_turn,
            wake_context=wake_context,
            capabilities=capabilities,
            use_boundary=use_boundary,
            _marker=_MODEL_INPUT_MARKER,
        )

        request_digest = _semantic_digest(request)
        serialized_text = serialize_home_model_input_request(
            request=request
        )
        serialized_digest = _sha256_text(serialized_text)
        policy_digest = _semantic_digest(policy)

        receipt = RequestConstructionReceipt(
            construction_version=WAKE_MODEL_INPUT_VERSION,
            construction_id=f"model-input-construction-{uuid4().hex}",
            request_id=handoff_receipt.request_id,
            episode_id=handoff_receipt.episode_id,
            wake_id=handoff_receipt.wake_id,
            issuance_id=handoff_receipt.issuance_id,
            source_handoff_id=handoff_receipt.handoff_id,
            home_process_instance_id=self._home_process_instance_id,
            local_transport_boundary_id=(
                handoff_receipt.local_transport_boundary_id
            ),
            source_handoff_generation=handoff_receipt.generation,
            source_handoff_receipt_digest=source_receipt_digest,
            source_envelope_digest=handoff_receipt.envelope_digest,
            policy_digest=policy_digest,
            request_semantic_digest=request_digest,
            serialized_representation_digest=serialized_digest,
            serializer_version=WAKE_MODEL_SERIALIZER_VERSION,
            media_type=WAKE_MODEL_INPUT_MEDIA_TYPE,
            use_boundary=use_boundary,
            _marker=_CONSTRUCTION_RECEIPT_MARKER,
        )
        constructed = ConstructedHomeModelInput(
            request=request,
            media_type=WAKE_MODEL_INPUT_MEDIA_TYPE,
            serialized_text=serialized_text,
            receipt=receipt,
            _marker=_CONSTRUCTED_INPUT_MARKER,
        )
        state = _LiveConstructionState(
            boundary=self,
            source_handoff_receipt=handoff_receipt,
            constructed=constructed,
            request_digest=request_digest,
            serialized_digest=serialized_digest,
            construction_receipt_digest=_semantic_digest(receipt),
        )
        with self._registry_guard:
            self._constructions[receipt.construction_id] = state
        return constructed

    def require_live_construction(
        self,
        *,
        receipt: RequestConstructionReceipt,
    ) -> ConstructedHomeModelInput:
        self._assert_live_origin()
        if not isinstance(receipt, RequestConstructionReceipt):
            raise TypeError(
                "receipt must be RequestConstructionReceipt"
            )
        with self._registry_guard:
            state = self._constructions.get(receipt.construction_id)
        if (
            state is None
            or state.boundary is not self
            or state.constructed.receipt is not receipt
        ):
            raise WakeModelInputAuthorizationError(
                "construction receipt is not exact live boundary evidence"
            )
        if (
            receipt.home_process_instance_id
            != self._home_process_instance_id
        ):
            raise WakeModelInputAuthorizationError(
                "construction receipt belongs to another HOME process incarnation"
            )
        if (
            _semantic_digest(receipt)
            != state.construction_receipt_digest
        ):
            raise WakeModelInputIntegrityError(
                "construction receipt changed after registration"
            )

        envelope = self._local_transport_boundary.require_live_acceptance(
            receipt=state.source_handoff_receipt
        )
        source_receipt_digest = _semantic_digest(
            state.source_handoff_receipt
        )
        if (
            source_receipt_digest
            != receipt.source_handoff_receipt_digest
        ):
            raise WakeModelInputIntegrityError(
                "source handoff receipt differs from construction binding"
            )
        if (
            state.source_handoff_receipt.envelope_digest
            != receipt.source_envelope_digest
            or _semantic_digest(envelope)
            != receipt.source_envelope_digest
        ):
            raise WakeModelInputIntegrityError(
                "source accepted envelope differs from construction binding"
            )

        constructed = state.constructed
        request_digest = _semantic_digest(constructed.request)
        if (
            request_digest != state.request_digest
            or request_digest != receipt.request_semantic_digest
        ):
            raise WakeModelInputIntegrityError(
                "typed model-input request changed after construction"
            )

        expected_policy = _canonical_home_policy()
        if (
            _semantic_digest(constructed.request.home_policy)
            != _semantic_digest(expected_policy)
            or receipt.policy_digest
            != _semantic_digest(expected_policy)
        ):
            raise WakeModelInputIntegrityError(
                "constructed request HOME policy is no longer canonical"
            )

        expected_serialized = serialize_home_model_input_request(
            request=constructed.request
        )
        if expected_serialized != constructed.serialized_text:
            raise WakeModelInputIntegrityError(
                "serialized model-input representation changed"
            )
        serialized_digest = _sha256_text(
            constructed.serialized_text
        )
        if (
            serialized_digest != state.serialized_digest
            or serialized_digest
            != receipt.serialized_representation_digest
        ):
            raise WakeModelInputIntegrityError(
                "serialized model-input digest changed"
            )
        _require_none_boundary(
            field_name="live construction use boundary",
            boundary=receipt.use_boundary,
        )
        return constructed

    def _assert_live_origin(self) -> None:
        if getattr(self, "_origin", None) is not self:
            raise WakeModelInputAuthorizationError(
                "model-input boundary is not the originating object"
            )
        if (
            current_home_process_instance_id()
            != self._home_process_instance_id
        ):
            raise WakeModelInputAuthorizationError(
                "model-input boundary belongs to another HOME process incarnation"
            )


def open_wake_model_input_boundary(
    *,
    local_transport_boundary: LocalWakeTransportBoundary,
) -> WakeModelInputBoundary:
    return WakeModelInputBoundary(
        local_transport_boundary=local_transport_boundary
    )


def serialize_home_model_input_request(
    *,
    request: HomeModelInputRequest,
) -> str:
    if not isinstance(request, HomeModelInputRequest):
        raise TypeError(
            "request must be HomeModelInputRequest"
        )
    expected_policy = _canonical_home_policy()
    if (
        _canonical_semantic_json(request.home_policy)
        != _canonical_semantic_json(expected_policy)
    ):
        raise WakeModelInputIntegrityError(
            "serializer rejects noncanonical HOME policy"
        )
    _require_none_boundary(
        field_name="serialized request use boundary",
        boundary=request.use_boundary,
    )

    payload = {
        "kind": WAKE_MODEL_INPUT_KIND,
        "serializer_version": WAKE_MODEL_SERIALIZER_VERSION,
        "request": _canonical_semantic_value(request),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_home_policy() -> HomeModelInputPolicy:
    return HomeModelInputPolicy(
        policy_version=WAKE_MODEL_POLICY_VERSION,
        carried_context_position=CarriedContextPosition.SIBLING_DATA,
        speaker_selection_rule=(
            SpeakerSelectionRule.CARRIED_CONTENT_CANNOT_SELECT_SPEAKER
        ),
        capability_grant_rule=(
            CapabilityGrantRule.CARRIED_CONTENT_CANNOT_GRANT_CAPABILITIES
        ),
        use_boundary=WakeUseBoundary(),
        _marker=_MODEL_POLICY_MARKER,
    )


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
                    _canonical_semantic_value(
                        getattr(value, item.name)
                    ),
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
            "__home_datetime__": value.isoformat(
                timespec="microseconds"
            ),
        }
    if isinstance(value, tuple):
        return {
            "__home_tuple__": [
                _canonical_semantic_value(item)
                for item in value
            ],
        }
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise WakeModelInputIntegrityError(
        "unsupported model-input semantic value: "
        f"{type(value).__name__}"
    )


def _require_none_boundary(
    *,
    field_name: str,
    boundary: object,
) -> None:
    if not isinstance(boundary, WakeUseBoundary):
        raise WakeModelInputIntegrityError(
            f"{field_name} must be WakeUseBoundary"
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
            raise WakeModelInputIntegrityError(
                f"{field_name} cannot grant {axis}"
            )


def _text(field_name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise WakeModelInputIntegrityError(
            f"{field_name} must be non-empty text"
        )


def _digest(field_name: str, value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(
            char not in "0123456789abcdef"
            for char in value
        )
    ):
        raise WakeModelInputIntegrityError(
            f"{field_name} must be lowercase sha256"
        )


def _aware(field_name: str, value: object) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise WakeModelInputIntegrityError(
            f"{field_name} must be timezone-aware datetime"
        )


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
