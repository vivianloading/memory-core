from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum, StrEnum
from hashlib import sha256
import json

from home_memory_core.current_view import (
    CurrentStanding,
    CurrentStateKind,
)
from home_memory_core.wake_issuance import (
    IssuedWakePacket,
    WakeIssuanceAuthority,
)
from home_memory_core.wake_packet import (
    WakeAuthority,
    WakeLayer,
    WakeLayerAvailability,
    WakePrivacyScope,
    WakePrivacyScopeKind,
    WakeRouteDecision,
    WakeUseBoundary,
)


WAKE_PRESENTATION_VERSION = "wake-presentation-v0.1"
WAKE_PRESENTATION_RENDERER_VERSION = (
    "wake-presentation-json-v0.1"
)
WAKE_PRESENTATION_MEDIA_TYPE = (
    "application/vnd.home.wake-presentation+json"
)

_WAKE_PRESENTATION_PLAN_MARKER = object()


class WakePresentationError(ValueError):
    """Wake presentation violated the v0.1 carry-without-speaking contract."""


class WakePresentationBlockKind(StrEnum):
    MAP_ORIENTATION = "map_orientation"
    ROOM_STANDING = "room_standing"


class WakePresentationTemporalPolicy(StrEnum):
    AT_ISSUANCE_CUT = "at_issuance_cut"


class WakePresentationAttributionPolicy(StrEnum):
    EXPLICIT_EPISODE_PERSPECTIVE = (
        "explicit_episode_perspective"
    )
    EXPLICIT_CANDIDATE_EPISODE_PERSPECTIVE = (
        "explicit_candidate_episode_perspective"
    )


class WakePresentationPronounPolicy(StrEnum):
    NO_CURRENT_FIRST_PERSON = "no_current_first_person"


class WakePresentationAuthorityCeiling(StrEnum):
    DESCRIBE_ONLY = "describe_only"


@dataclass(frozen=True)
class WakePresentationPolicy:
    privacy_scope: WakePrivacyScope
    temporal_policy: WakePresentationTemporalPolicy
    attribution_policy: WakePresentationAttributionPolicy
    pronoun_policy: WakePresentationPronounPolicy
    authority_ceiling: WakePresentationAuthorityCeiling
    inclusion_basis: str
    use_boundary: WakeUseBoundary = field(
        default_factory=WakeUseBoundary
    )

    def __post_init__(self) -> None:
        if not isinstance(self.privacy_scope, WakePrivacyScope):
            raise WakePresentationError(
                "presentation privacy_scope is invalid"
            )
        if (
            self.temporal_policy
            is not WakePresentationTemporalPolicy.AT_ISSUANCE_CUT
        ):
            raise WakePresentationError(
                "presentation temporal policy must stay at issuance cut"
            )
        if not isinstance(
            self.attribution_policy,
            WakePresentationAttributionPolicy,
        ):
            raise WakePresentationError(
                "presentation attribution policy is invalid"
            )
        if (
            self.pronoun_policy
            is not WakePresentationPronounPolicy.NO_CURRENT_FIRST_PERSON
        ):
            raise WakePresentationError(
                "Wake Presentation v0.1 cannot grant current first-person grammar"
            )
        if (
            self.authority_ceiling
            is not WakePresentationAuthorityCeiling.DESCRIBE_ONLY
        ):
            raise WakePresentationError(
                "Wake Presentation v0.1 is describe-only"
            )
        _text("inclusion_basis", self.inclusion_basis)
        if not isinstance(self.use_boundary, WakeUseBoundary):
            raise WakePresentationError(
                "presentation use boundary is invalid"
            )


@dataclass(frozen=True)
class WakePresentationContinuity:
    edge_id: str
    previous_episode_id: str
    next_episode_id: str
    transfer_mode: str
    continuity_status: str

    def __post_init__(self) -> None:
        for field_name in (
            "edge_id",
            "previous_episode_id",
            "next_episode_id",
            "transfer_mode",
            "continuity_status",
        ):
            _text(field_name, getattr(self, field_name))


@dataclass(frozen=True)
class WakeMapPresentationBlock:
    block_id: str
    layer: WakeLayer
    block_kind: WakePresentationBlockKind
    policy: WakePresentationPolicy
    episode_id: str
    perspective_instance_id: str
    route_decision: WakeRouteDecision
    room_id: str | None
    active_attachment_event_id: str | None
    incoming_continuity: WakePresentationContinuity | None

    def __post_init__(self) -> None:
        _text("block_id", self.block_id)
        if self.layer is not WakeLayer.MAP:
            raise WakePresentationError(
                "Map presentation block must remain in Map layer"
            )
        if (
            self.block_kind
            is not WakePresentationBlockKind.MAP_ORIENTATION
        ):
            raise WakePresentationError(
                "Map presentation block kind is invalid"
            )
        if not isinstance(self.policy, WakePresentationPolicy):
            raise WakePresentationError(
                "Map presentation policy is invalid"
            )
        if (
            self.policy.privacy_scope.kind
            is not WakePrivacyScopeKind.EPISODE
        ):
            raise WakePresentationError(
                "Map presentation must remain Episode-scoped"
            )
        if (
            self.policy.attribution_policy
            is not WakePresentationAttributionPolicy.EXPLICIT_EPISODE_PERSPECTIVE
        ):
            raise WakePresentationError(
                "Map presentation requires explicit Episode/Perspective attribution"
            )
        for field_name in (
            "episode_id",
            "perspective_instance_id",
        ):
            _text(field_name, getattr(self, field_name))
        if self.policy.privacy_scope.scope_id != self.episode_id:
            raise WakePresentationError(
                "Map presentation privacy scope differs from Episode"
            )
        if not isinstance(self.route_decision, WakeRouteDecision):
            raise WakePresentationError(
                "Map presentation route decision is invalid"
            )
        if self.room_id is not None:
            _text("room_id", self.room_id)
        if self.active_attachment_event_id is not None:
            _text(
                "active_attachment_event_id",
                self.active_attachment_event_id,
            )
        if self.incoming_continuity is not None:
            if not isinstance(
                self.incoming_continuity,
                WakePresentationContinuity,
            ):
                raise WakePresentationError(
                    "Map presentation continuity is invalid"
                )
            if (
                self.incoming_continuity.next_episode_id
                != self.episode_id
            ):
                raise WakePresentationError(
                    "presentation continuity does not target Map Episode"
                )


@dataclass(frozen=True)
class WakePresentationCandidate:
    state_id: str
    value: str
    standing: CurrentStanding
    episode_id: str
    perspective_instance_id: str
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "state_id",
            "value",
            "episode_id",
            "perspective_instance_id",
        ):
            _text(field_name, getattr(self, field_name))
        if not isinstance(self.standing, CurrentStanding):
            raise WakePresentationError(
                "presentation candidate standing is invalid"
            )
        _refs("source_refs", self.source_refs)
        if not self.source_refs:
            raise WakePresentationError(
                "presentation candidate requires provenance refs"
            )


@dataclass(frozen=True)
class WakeRoomPresentationBlock:
    block_id: str
    layer: WakeLayer
    block_kind: WakePresentationBlockKind
    policy: WakePresentationPolicy
    room_id: str
    key: str
    state_kind: CurrentStateKind
    standing: CurrentStanding
    candidates: tuple[WakePresentationCandidate, ...]

    def __post_init__(self) -> None:
        _text("block_id", self.block_id)
        if self.layer is not WakeLayer.ROOM_NOW:
            raise WakePresentationError(
                "Room presentation block must remain in Room Now"
            )
        if (
            self.block_kind
            is not WakePresentationBlockKind.ROOM_STANDING
        ):
            raise WakePresentationError(
                "Room presentation block kind is invalid"
            )
        if not isinstance(self.policy, WakePresentationPolicy):
            raise WakePresentationError(
                "Room presentation policy is invalid"
            )
        if (
            self.policy.privacy_scope.kind
            is not WakePrivacyScopeKind.ROOM
        ):
            raise WakePresentationError(
                "Room presentation must remain Room-scoped"
            )
        if (
            self.policy.attribution_policy
            is not WakePresentationAttributionPolicy.EXPLICIT_CANDIDATE_EPISODE_PERSPECTIVE
        ):
            raise WakePresentationError(
                "Room presentation requires explicit candidate attribution"
            )
        for field_name in ("room_id", "key"):
            _text(field_name, getattr(self, field_name))
        if self.policy.privacy_scope.scope_id != self.room_id:
            raise WakePresentationError(
                "Room presentation privacy scope differs from Room"
            )
        if not isinstance(self.state_kind, CurrentStateKind):
            raise WakePresentationError(
                "Room presentation state kind is invalid"
            )
        if not isinstance(self.standing, CurrentStanding):
            raise WakePresentationError(
                "Room presentation standing is invalid"
            )
        if (
            not isinstance(self.candidates, tuple)
            or not self.candidates
            or any(
                not isinstance(item, WakePresentationCandidate)
                for item in self.candidates
            )
        ):
            raise WakePresentationError(
                "Room presentation requires candidate tuple"
            )
        state_ids = tuple(
            candidate.state_id
            for candidate in self.candidates
        )
        if len(set(state_ids)) != len(state_ids):
            raise WakePresentationError(
                "Room presentation cannot duplicate candidate state"
            )
        if len(self.candidates) == 1:
            if self.standing is not self.candidates[0].standing:
                raise WakePresentationError(
                    "single-candidate presentation standing must match candidate"
                )
        elif self.standing is not CurrentStanding.CONFLICTING:
            raise WakePresentationError(
                "multi-candidate presentation must remain conflicting"
            )


WakePresentationBlock = (
    WakeMapPresentationBlock
    | WakeRoomPresentationBlock
)


@dataclass(frozen=True)
class WakePresentationLayerPlan:
    layer: WakeLayer
    availability: WakeLayerAvailability
    reason_codes: tuple[str, ...]
    blocks: tuple[WakePresentationBlock, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.layer, WakeLayer):
            raise WakePresentationError(
                "presentation layer is invalid"
            )
        if not isinstance(
            self.availability,
            WakeLayerAvailability,
        ):
            raise WakePresentationError(
                "presentation layer availability is invalid"
            )
        _refs("reason_codes", self.reason_codes)
        if (
            not isinstance(self.blocks, tuple)
            or any(
                not isinstance(
                    item,
                    (
                        WakeMapPresentationBlock,
                        WakeRoomPresentationBlock,
                    ),
                )
                for item in self.blocks
            )
        ):
            raise WakePresentationError(
                "presentation layer blocks are invalid"
            )
        if any(item.layer is not self.layer for item in self.blocks):
            raise WakePresentationError(
                "presentation block crosses layer boundary"
            )
        if self.layer is WakeLayer.MAP:
            if (
                self.availability is not WakeLayerAvailability.READY
                or len(self.blocks) != 1
                or not isinstance(
                    self.blocks[0],
                    WakeMapPresentationBlock,
                )
            ):
                raise WakePresentationError(
                    "Map presentation requires one ready orientation block"
                )
        elif self.layer is WakeLayer.ROOM_NOW:
            if self.availability not in {
                WakeLayerAvailability.READY,
                WakeLayerAvailability.PARTIAL,
                WakeLayerAvailability.UNAVAILABLE,
            }:
                raise WakePresentationError(
                    "Room presentation availability is invalid"
                )
            if self.availability is WakeLayerAvailability.UNAVAILABLE:
                if self.blocks:
                    raise WakePresentationError(
                        "unavailable Room presentation cannot carry blocks"
                    )
            elif any(
                not isinstance(
                    item,
                    WakeRoomPresentationBlock,
                )
                for item in self.blocks
            ):
                raise WakePresentationError(
                    "Room layer can contain only Room standing blocks"
                )
        else:
            if self.blocks:
                raise WakePresentationError(
                    "closed/unavailable non-Map layers cannot carry blocks in v0.1"
                )
            if self.layer is WakeLayer.SHARED_NOW:
                if (
                    self.availability
                    is not WakeLayerAvailability.CLOSED
                ):
                    raise WakePresentationError(
                        "Shared Now must remain CLOSED"
                    )
            elif self.layer in {
                WakeLayer.RECENT_LIFE,
                WakeLayer.NEARBY_DOORS,
            }:
                if (
                    self.availability
                    is not WakeLayerAvailability.UNAVAILABLE
                ):
                    raise WakePresentationError(
                        "Recent Life/Nearby Doors must remain UNAVAILABLE"
                    )


@dataclass(frozen=True)
class WakePresentationPlan:
    presentation_version: str
    wake_id: str
    issuance_id: str
    as_of: datetime
    episode_id: str
    perspective_instance_id: str
    layers: tuple[WakePresentationLayerPlan, ...]
    use_boundary: WakeUseBoundary
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _WAKE_PRESENTATION_PLAN_MARKER:
            raise WakePresentationError(
                "operational Wake presentation plan must come from verified builder"
            )
        if self.presentation_version != WAKE_PRESENTATION_VERSION:
            raise WakePresentationError(
                "unexpected Wake presentation version"
            )
        for field_name in (
            "wake_id",
            "issuance_id",
            "episode_id",
            "perspective_instance_id",
        ):
            _text(field_name, getattr(self, field_name))
        _aware("as_of", self.as_of)
        if not isinstance(self.use_boundary, WakeUseBoundary):
            raise WakePresentationError(
                "presentation plan use boundary is invalid"
            )
        expected = (
            WakeLayer.MAP,
            WakeLayer.SHARED_NOW,
            WakeLayer.ROOM_NOW,
            WakeLayer.RECENT_LIFE,
            WakeLayer.NEARBY_DOORS,
        )
        if (
            not isinstance(self.layers, tuple)
            or len(self.layers) != len(expected)
            or tuple(item.layer for item in self.layers) != expected
        ):
            raise WakePresentationError(
                "presentation plan must preserve exact five-layer order"
            )

        map_block = self.layers[0].blocks[0]
        assert isinstance(map_block, WakeMapPresentationBlock)
        if (
            map_block.episode_id != self.episode_id
            or map_block.perspective_instance_id
            != self.perspective_instance_id
        ):
            raise WakePresentationError(
                "Map presentation identity differs from plan identity"
            )
        if map_block.route_decision is WakeRouteDecision.ATTACHED:
            if map_block.room_id is None:
                raise WakePresentationError(
                    "attached presentation Map requires Room"
                )
            for block in self.layers[2].blocks:
                assert isinstance(
                    block,
                    WakeRoomPresentationBlock,
                )
                if block.room_id != map_block.room_id:
                    raise WakePresentationError(
                        "Room presentation crosses attached Map Room"
                    )
        elif self.layers[2].blocks:
            raise WakePresentationError(
                "unattached/unresolved Map cannot carry Room presentation blocks"
            )


@dataclass(frozen=True)
class WakePresentationRenderReceipt:
    presentation_version: str
    renderer_version: str
    wake_id: str
    issuance_id: str
    as_of: datetime
    plan_digest: str
    payload_digest: str
    use_boundary: WakeUseBoundary = field(
        default_factory=WakeUseBoundary
    )

    def __post_init__(self) -> None:
        if self.presentation_version != WAKE_PRESENTATION_VERSION:
            raise WakePresentationError(
                "render receipt presentation version is invalid"
            )
        if (
            self.renderer_version
            != WAKE_PRESENTATION_RENDERER_VERSION
        ):
            raise WakePresentationError(
                "render receipt renderer version is invalid"
            )
        for field_name in ("wake_id", "issuance_id"):
            _text(field_name, getattr(self, field_name))
        _aware("as_of", self.as_of)
        _digest("plan_digest", self.plan_digest)
        _digest("payload_digest", self.payload_digest)
        if not isinstance(self.use_boundary, WakeUseBoundary):
            raise WakePresentationError(
                "render receipt use boundary is invalid"
            )


@dataclass(frozen=True)
class RenderedWakePresentation:
    media_type: str
    payload_json: str
    instruction_authority: WakeAuthority
    renderer_version: str
    receipt: WakePresentationRenderReceipt
    use_boundary: WakeUseBoundary = field(
        default_factory=WakeUseBoundary
    )

    def __post_init__(self) -> None:
        if self.media_type != WAKE_PRESENTATION_MEDIA_TYPE:
            raise WakePresentationError(
                "Wake presentation media type is invalid"
            )
        _text("payload_json", self.payload_json)
        if self.instruction_authority is not WakeAuthority.NONE:
            raise WakePresentationError(
                "rendered Wake presentation cannot grant instruction authority"
            )
        if (
            self.renderer_version
            != WAKE_PRESENTATION_RENDERER_VERSION
        ):
            raise WakePresentationError(
                "rendered Wake renderer version is invalid"
            )
        if not isinstance(
            self.receipt,
            WakePresentationRenderReceipt,
        ):
            raise WakePresentationError(
                "rendered Wake receipt is invalid"
            )
        if not isinstance(self.use_boundary, WakeUseBoundary):
            raise WakePresentationError(
                "rendered Wake use boundary is invalid"
            )
        if _sha256_text(self.payload_json) != self.receipt.payload_digest:
            raise WakePresentationError(
                "rendered Wake payload differs from receipt digest"
            )


def build_wake_presentation_plan(
    *,
    authority: WakeIssuanceAuthority,
    issued: IssuedWakePacket,
) -> WakePresentationPlan:
    """Build a typed presentation plan from exact live-issued Wake provenance."""

    if not isinstance(authority, WakeIssuanceAuthority):
        raise TypeError(
            "authority must be WakeIssuanceAuthority"
        )
    if not isinstance(issued, IssuedWakePacket):
        raise TypeError(
            "issued must be IssuedWakePacket"
        )

    packet = WakeIssuanceAuthority.require_live_issuance(
        authority,
        issued=issued,
    )

    map_item = packet.map.item
    continuity = None
    if map_item.incoming_continuity is not None:
        continuity = WakePresentationContinuity(
            edge_id=map_item.incoming_continuity.edge_id,
            previous_episode_id=(
                map_item.incoming_continuity.previous_episode_id
            ),
            next_episode_id=(
                map_item.incoming_continuity.next_episode_id
            ),
            transfer_mode=(
                map_item.incoming_continuity.transfer_mode.value
            ),
            continuity_status=(
                map_item.incoming_continuity.continuity_status.value
            ),
        )

    map_block = WakeMapPresentationBlock(
        block_id=f"presentation:{map_item.item_id}",
        layer=WakeLayer.MAP,
        block_kind=WakePresentationBlockKind.MAP_ORIENTATION,
        policy=WakePresentationPolicy(
            privacy_scope=map_item.privacy_scope,
            temporal_policy=(
                WakePresentationTemporalPolicy.AT_ISSUANCE_CUT
            ),
            attribution_policy=(
                WakePresentationAttributionPolicy.EXPLICIT_EPISODE_PERSPECTIVE
            ),
            pronoun_policy=(
                WakePresentationPronounPolicy.NO_CURRENT_FIRST_PERSON
            ),
            authority_ceiling=(
                WakePresentationAuthorityCeiling.DESCRIBE_ONLY
            ),
            inclusion_basis="verified_map_orientation",
            use_boundary=map_item.use_boundary,
        ),
        episode_id=map_item.episode_id,
        perspective_instance_id=(
            map_item.perspective_instance_id
        ),
        route_decision=map_item.route_decision,
        room_id=map_item.room_id,
        active_attachment_event_id=(
            map_item.active_attachment_event_id
        ),
        incoming_continuity=continuity,
    )

    room_blocks = tuple(
        _room_block_from_item(item)
        for item in packet.room_now.items
    )

    layers = (
        WakePresentationLayerPlan(
            layer=WakeLayer.MAP,
            availability=packet.map.availability,
            reason_codes=packet.map.reason_codes,
            blocks=(map_block,),
        ),
        WakePresentationLayerPlan(
            layer=WakeLayer.SHARED_NOW,
            availability=packet.shared_now.availability,
            reason_codes=packet.shared_now.reason_codes,
            blocks=(),
        ),
        WakePresentationLayerPlan(
            layer=WakeLayer.ROOM_NOW,
            availability=packet.room_now.availability,
            reason_codes=packet.room_now.reason_codes,
            blocks=room_blocks,
        ),
        WakePresentationLayerPlan(
            layer=WakeLayer.RECENT_LIFE,
            availability=packet.recent_life.availability,
            reason_codes=packet.recent_life.reason_codes,
            blocks=(),
        ),
        WakePresentationLayerPlan(
            layer=WakeLayer.NEARBY_DOORS,
            availability=packet.nearby_doors.availability,
            reason_codes=packet.nearby_doors.reason_codes,
            blocks=(),
        ),
    )

    return WakePresentationPlan(
        presentation_version=WAKE_PRESENTATION_VERSION,
        wake_id=packet.wake_id,
        issuance_id=issued.issuance_receipt.issuance_id,
        as_of=packet.as_of,
        episode_id=packet.episode_id,
        perspective_instance_id=(
            packet.perspective_instance_id
        ),
        layers=layers,
        use_boundary=packet.use_boundary,
        _marker=_WAKE_PRESENTATION_PLAN_MARKER,
    )


def render_wake_presentation(
    *,
    authority: WakeIssuanceAuthority,
    issued: IssuedWakePacket,
    plan: WakePresentationPlan,
) -> RenderedWakePresentation:
    """Render one exact live-issued presentation plan as structured data."""

    _validate_operational_plan(plan)
    expected = build_wake_presentation_plan(
        authority=authority,
        issued=issued,
    )
    plan_semantics = _canonical_semantic_value(plan)
    expected_semantics = _canonical_semantic_value(expected)
    if _canonical_json(plan_semantics) != _canonical_json(
        expected_semantics
    ):
        raise WakePresentationError(
            "presentation plan differs from the exact live-issued semantic projection"
        )

    plan_payload = _plan_payload(plan)
    plan_json = _canonical_json(plan_semantics)
    payload = {
        "kind": "home_wake_presentation_data",
        "presentation_version": (
            WAKE_PRESENTATION_VERSION
        ),
        "renderer_version": (
            WAKE_PRESENTATION_RENDERER_VERSION
        ),
        "instruction_authority": WakeAuthority.NONE.value,
        "current_first_person_speech_authority": (
            WakeAuthority.NONE.value
        ),
        "identity_continuity_claim_authority": (
            WakeAuthority.NONE.value
        ),
        "relationship_claim_authority": (
            WakeAuthority.NONE.value
        ),
        "model_delivery_authority": (
            WakeAuthority.NONE.value
        ),
        "memory_write_authority": (
            WakeAuthority.NONE.value
        ),
        "presentation": plan_payload,
    }
    payload_json = _canonical_json(payload)

    receipt = WakePresentationRenderReceipt(
        presentation_version=WAKE_PRESENTATION_VERSION,
        renderer_version=WAKE_PRESENTATION_RENDERER_VERSION,
        wake_id=plan.wake_id,
        issuance_id=plan.issuance_id,
        as_of=plan.as_of,
        plan_digest=_sha256_text(plan_json),
        payload_digest=_sha256_text(payload_json),
        use_boundary=plan.use_boundary,
    )

    return RenderedWakePresentation(
        media_type=WAKE_PRESENTATION_MEDIA_TYPE,
        payload_json=payload_json,
        instruction_authority=WakeAuthority.NONE,
        renderer_version=WAKE_PRESENTATION_RENDERER_VERSION,
        receipt=receipt,
        use_boundary=plan.use_boundary,
    )


def _room_block_from_item(item) -> WakeRoomPresentationBlock:
    candidates = tuple(
        WakePresentationCandidate(
            state_id=candidate.state_id,
            value=candidate.value,
            standing=candidate.standing,
            episode_id=candidate.episode_id,
            perspective_instance_id=(
                candidate.perspective_instance_id
            ),
            source_refs=candidate.source_refs,
        )
        for candidate in item.candidates
    )
    return WakeRoomPresentationBlock(
        block_id=f"presentation:{item.item_id}",
        layer=WakeLayer.ROOM_NOW,
        block_kind=WakePresentationBlockKind.ROOM_STANDING,
        policy=WakePresentationPolicy(
            privacy_scope=item.privacy_scope,
            temporal_policy=(
                WakePresentationTemporalPolicy.AT_ISSUANCE_CUT
            ),
            attribution_policy=(
                WakePresentationAttributionPolicy.EXPLICIT_CANDIDATE_EPISODE_PERSPECTIVE
            ),
            pronoun_policy=(
                WakePresentationPronounPolicy.NO_CURRENT_FIRST_PERSON
            ),
            authority_ceiling=(
                WakePresentationAuthorityCeiling.DESCRIBE_ONLY
            ),
            inclusion_basis=(
                "verified_room_standing_at_issuance_cut"
            ),
            use_boundary=item.use_boundary,
        ),
        room_id=item.room_id,
        key=item.key,
        state_kind=item.state_kind,
        standing=item.standing,
        candidates=candidates,
    )


def _validate_operational_plan(
    plan: WakePresentationPlan,
) -> None:
    if not isinstance(plan, WakePresentationPlan):
        raise TypeError(
            "plan must be WakePresentationPlan"
        )
    if plan._marker is not _WAKE_PRESENTATION_PLAN_MARKER:
        raise WakePresentationError(
            "Wake renderer requires verified presentation plan"
        )


def _plan_payload(plan: WakePresentationPlan) -> dict[str, object]:
    return {
        "presentation_version": plan.presentation_version,
        "wake_id": plan.wake_id,
        "issuance_id": plan.issuance_id,
        "as_of": _datetime_text(plan.as_of),
        "episode_id": plan.episode_id,
        "perspective_instance_id": (
            plan.perspective_instance_id
        ),
        "temporal_claim": "standing_at_issuance_cut",
        "use_boundary": _use_boundary_payload(
            plan.use_boundary
        ),
        "layers": [
            _layer_payload(layer)
            for layer in plan.layers
        ],
    }


def _layer_payload(
    layer: WakePresentationLayerPlan,
) -> dict[str, object]:
    return {
        "layer": layer.layer.value,
        "availability": layer.availability.value,
        "reason_codes": list(layer.reason_codes),
        "blocks": [
            _block_payload(block)
            for block in layer.blocks
        ],
    }


def _block_payload(
    block: WakePresentationBlock,
) -> dict[str, object]:
    common = {
        "block_id": block.block_id,
        "layer": block.layer.value,
        "block_kind": block.block_kind.value,
        "policy": _policy_payload(block.policy),
    }
    if isinstance(block, WakeMapPresentationBlock):
        common.update(
            {
                "episode_id": block.episode_id,
                "perspective_instance_id": (
                    block.perspective_instance_id
                ),
                "route_decision": (
                    block.route_decision.value
                ),
                "room_id": block.room_id,
                "active_attachment_event_id": (
                    block.active_attachment_event_id
                ),
                "incoming_continuity": (
                    None
                    if block.incoming_continuity is None
                    else {
                        "edge_id": (
                            block.incoming_continuity.edge_id
                        ),
                        "previous_episode_id": (
                            block.incoming_continuity.previous_episode_id
                        ),
                        "next_episode_id": (
                            block.incoming_continuity.next_episode_id
                        ),
                        "transfer_mode": (
                            block.incoming_continuity.transfer_mode
                        ),
                        "continuity_status": (
                            block.incoming_continuity.continuity_status
                        ),
                    }
                ),
            }
        )
        return common
    if isinstance(block, WakeRoomPresentationBlock):
        common.update(
            {
                "room_id": block.room_id,
                "key": block.key,
                "state_kind": block.state_kind.value,
                "standing": block.standing.value,
                "candidates": [
                    {
                        "state_id": candidate.state_id,
                        "value": candidate.value,
                        "standing": candidate.standing.value,
                        "episode_id": candidate.episode_id,
                        "perspective_instance_id": (
                            candidate.perspective_instance_id
                        ),
                        "source_refs": list(
                            candidate.source_refs
                        ),
                    }
                    for candidate in block.candidates
                ],
            }
        )
        return common
    raise WakePresentationError(
        "unsupported Wake presentation block"
    )


def _policy_payload(
    policy: WakePresentationPolicy,
) -> dict[str, object]:
    return {
        "privacy_scope": {
            "kind": policy.privacy_scope.kind.value,
            "scope_id": policy.privacy_scope.scope_id,
        },
        "temporal_policy": policy.temporal_policy.value,
        "attribution_policy": (
            policy.attribution_policy.value
        ),
        "pronoun_policy": policy.pronoun_policy.value,
        "authority_ceiling": (
            policy.authority_ceiling.value
        ),
        "inclusion_basis": policy.inclusion_basis,
        **_use_boundary_payload(policy.use_boundary),
    }


def _use_boundary_payload(
    boundary: WakeUseBoundary,
) -> dict[str, str]:
    if not isinstance(boundary, WakeUseBoundary):
        raise WakePresentationError(
            "Wake presentation use boundary is invalid"
        )
    return {
        "instruction_authority": (
            boundary.instruction_authority.value
        ),
        "current_first_person_speech_authority": (
            boundary.current_first_person_speech_authority.value
        ),
        "identity_continuity_claim_authority": (
            boundary.identity_continuity_claim_authority.value
        ),
        "relationship_claim_authority": (
            boundary.relationship_claim_authority.value
        ),
        "model_delivery_authority": (
            boundary.model_delivery_authority.value
        ),
        "memory_write_authority": (
            boundary.memory_write_authority.value
        ),
    }


def _canonical_semantic_value(value: object) -> object:
    """Canonicalize every public semantic field of a typed presentation object.

    Renderer payload projection is intentionally a separate concern. This
    function exists so operational exact-plan comparison and plan digests cannot
    silently omit a newly added public dataclass field.

    Private construction markers are excluded because they are misuse guards,
    not presentation semantics or authority credentials.
    """

    if is_dataclass(value) and not isinstance(value, type):
        return {
            "__dataclass__": (
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
            "__enum__": (
                f"{value.__class__.__module__}."
                f"{value.__class__.__qualname__}"
            ),
            "value": _canonical_semantic_value(value.value),
        }
    if isinstance(value, datetime):
        _aware("semantic datetime", value)
        return {
            "__datetime__": value.isoformat(
                timespec="microseconds"
            ),
        }
    if isinstance(value, tuple):
        return {
            "__tuple__": [
                _canonical_semantic_value(item)
                for item in value
            ],
        }
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise WakePresentationError(
        "unsupported presentation semantic value: "
        f"{type(value).__name__}"
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _datetime_text(value: datetime) -> str:
    _aware("datetime", value)
    return value.isoformat(timespec="microseconds")


def _aware(field_name: str, value: datetime) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise WakePresentationError(
            f"{field_name} must be timezone-aware datetime"
        )
    value.astimezone(timezone.utc)


def _text(field_name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise WakePresentationError(
            f"{field_name} must be non-empty text"
        )


def _refs(field_name: str, value: object) -> None:
    if (
        not isinstance(value, tuple)
        or any(
            not isinstance(item, str)
            or not item.strip()
            for item in value
        )
    ):
        raise WakePresentationError(
            f"{field_name} must be tuple[str, ...]"
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
        raise WakePresentationError(
            f"{field_name} must be lowercase sha256"
        )