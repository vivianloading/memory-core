from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from home_memory_core.current_resolver import (
    CurrentResolvedView,
    CurrentResolverDecision,
    CurrentResolverStatus,
)
from home_memory_core.current_view import (
    CurrentCandidate,
    CurrentNamespace,
    CurrentStanding,
)
from home_memory_core.living_continuity import (
    ContinuityEdge,
    EpisodeRecord,
    RoomAttachmentResolution,
)


WAKE_PACKET_VERSION = "wake-packet-v0.1"
WAKE_SELECTION_POLICY_VERSION = "wake-selection-v0.1"


class WakePacketError(ValueError):
    """Typed Wake assembly violated the v0.1 carriage contract."""


class WakeLayer(StrEnum):
    MAP = "map"
    SHARED_NOW = "shared_now"
    ROOM_NOW = "room_now"
    RECENT_LIFE = "recent_life"
    NEARBY_DOORS = "nearby_doors"


class WakeLayerAvailability(StrEnum):
    READY = "ready"
    PARTIAL = "partial"
    CLOSED = "closed"
    UNAVAILABLE = "unavailable"


class WakePrivacyScopeKind(StrEnum):
    EPISODE = "episode"
    ROOM = "room"
    SHARED = "shared"


class WakeAuthority(StrEnum):
    NONE = "none"


@dataclass(frozen=True)
class WakeUseBoundary:
    """Authority that carriage itself does not grant.

    v0.1 intentionally has no non-NONE values and rejects caller-supplied
    lookalike strings. Carriage cannot mint any of these authorities.
    """

    instruction_authority: WakeAuthority = WakeAuthority.NONE
    current_first_person_speech_authority: WakeAuthority = WakeAuthority.NONE
    identity_continuity_claim_authority: WakeAuthority = WakeAuthority.NONE
    relationship_claim_authority: WakeAuthority = WakeAuthority.NONE
    model_delivery_authority: WakeAuthority = WakeAuthority.NONE
    memory_write_authority: WakeAuthority = WakeAuthority.NONE

    def __post_init__(self) -> None:
        for field_name in (
            "instruction_authority",
            "current_first_person_speech_authority",
            "identity_continuity_claim_authority",
            "relationship_claim_authority",
            "model_delivery_authority",
            "memory_write_authority",
        ):
            if getattr(self, field_name) is not WakeAuthority.NONE:
                raise WakePacketError(
                    f"{field_name} cannot be granted by Wake v0.1"
                )


@dataclass(frozen=True)
class WakePrivacyScope:
    kind: WakePrivacyScopeKind
    scope_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, WakePrivacyScopeKind):
            raise WakePacketError("privacy scope kind is invalid")
        _text("scope_id", self.scope_id)


@dataclass(frozen=True)
class WakeContinuityEvidence:
    edge_id: str
    previous_episode_id: str
    next_episode_id: str
    transfer_mode: str
    continuity_status: str
    support_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "edge_id",
            "previous_episode_id",
            "next_episode_id",
            "transfer_mode",
            "continuity_status",
        ):
            _text(field_name, getattr(self, field_name))
        _refs("support_refs", self.support_refs)


@dataclass(frozen=True)
class WakeMapItem:
    item_id: str
    episode_id: str
    perspective_instance_id: str
    route_decision: str
    room_id: str | None
    active_attachment_event_id: str | None
    incoming_continuity: WakeContinuityEvidence | None
    privacy_scope: WakePrivacyScope
    inclusion_reason: str = "ORIENT_CONCRETE_EPISODE"
    use_boundary: WakeUseBoundary = field(default_factory=WakeUseBoundary)

    def __post_init__(self) -> None:
        for field_name in (
            "item_id",
            "episode_id",
            "perspective_instance_id",
            "route_decision",
            "inclusion_reason",
        ):
            _text(field_name, getattr(self, field_name))
        if self.room_id is not None:
            _text("room_id", self.room_id)
        if self.active_attachment_event_id is not None:
            _text(
                "active_attachment_event_id",
                self.active_attachment_event_id,
            )
        if not isinstance(self.privacy_scope, WakePrivacyScope):
            raise WakePacketError("map privacy_scope is invalid")
        if not isinstance(self.use_boundary, WakeUseBoundary):
            raise WakePacketError("map use boundary is invalid")


@dataclass(frozen=True)
class WakeEndEvidence:
    end_event_id: str
    end_kind: str
    episode_id: str | None
    perspective_instance_id: str | None
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _text("end_event_id", self.end_event_id)
        _text("end_kind", self.end_kind)
        if self.episode_id is not None:
            _text("episode_id", self.episode_id)
        if self.perspective_instance_id is not None:
            _text(
                "perspective_instance_id",
                self.perspective_instance_id,
            )
        _refs("source_refs", self.source_refs)


@dataclass(frozen=True)
class WakeCurrentCandidate:
    state_id: str
    value: str
    state_kind: str
    standing: CurrentStanding
    semantic_change_authority: str
    event_time: datetime
    recorded_at: datetime
    episode_id: str | None
    perspective_instance_id: str | None
    source_refs: tuple[str, ...]
    end_evidence: tuple[WakeEndEvidence, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "state_id",
            "value",
            "state_kind",
            "semantic_change_authority",
        ):
            _text(field_name, getattr(self, field_name))
        if not isinstance(self.standing, CurrentStanding):
            raise WakePacketError("candidate standing is invalid")
        _aware("event_time", self.event_time)
        _aware("recorded_at", self.recorded_at)
        if self.episode_id is not None:
            _text("episode_id", self.episode_id)
        if self.perspective_instance_id is not None:
            _text(
                "perspective_instance_id",
                self.perspective_instance_id,
            )
        _refs("source_refs", self.source_refs)
        if not isinstance(self.end_evidence, tuple):
            raise WakePacketError("end_evidence must be a tuple")


@dataclass(frozen=True)
class WakeRoomNowItem:
    item_id: str
    room_id: str
    key: str
    state_kind: str
    standing: CurrentStanding
    candidates: tuple[WakeCurrentCandidate, ...]
    reason_codes: tuple[str, ...]
    privacy_scope: WakePrivacyScope
    inclusion_reason: str = (
        "CURRENT_RESOLVER_RESOLVED_CARRYABLE_STANDING"
    )
    use_boundary: WakeUseBoundary = field(default_factory=WakeUseBoundary)

    def __post_init__(self) -> None:
        for field_name in (
            "item_id",
            "room_id",
            "key",
            "state_kind",
            "inclusion_reason",
        ):
            _text(field_name, getattr(self, field_name))
        if not isinstance(self.standing, CurrentStanding):
            raise WakePacketError("Room Now standing is invalid")
        if self.standing not in _CARRYABLE_STANDINGS:
            raise WakePacketError(
                "Room Now item standing is not carryable in v0.1"
            )
        if not self.candidates:
            raise WakePacketError(
                "Room Now item requires attributed candidates"
            )
        if len({item.state_kind for item in self.candidates}) != 1:
            raise WakePacketError(
                "Room Now candidates cannot mix state kinds"
            )
        if self.state_kind != self.candidates[0].state_kind:
            raise WakePacketError(
                "Room Now item state_kind differs from candidates"
            )
        _refs("reason_codes", self.reason_codes)
        if (
            self.privacy_scope.kind is not WakePrivacyScopeKind.ROOM
            or self.privacy_scope.scope_id != self.room_id
        ):
            raise WakePacketError(
                "Room Now item requires matching Room privacy scope"
            )
        if not isinstance(self.use_boundary, WakeUseBoundary):
            raise WakePacketError("Room Now use boundary is invalid")


@dataclass(frozen=True)
class WakeMapSection:
    availability: WakeLayerAvailability
    item: WakeMapItem
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.availability is not WakeLayerAvailability.READY:
            raise WakePacketError("Map must be ready in v0.1 assembly")
        if not isinstance(self.item, WakeMapItem):
            raise WakePacketError("Map section item is invalid")
        _refs("reason_codes", self.reason_codes)


@dataclass(frozen=True)
class WakeRoomNowSection:
    availability: WakeLayerAvailability
    items: tuple[WakeRoomNowItem, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.availability not in {
            WakeLayerAvailability.READY,
            WakeLayerAvailability.PARTIAL,
            WakeLayerAvailability.UNAVAILABLE,
        }:
            raise WakePacketError(
                "Room Now availability is invalid"
            )
        if not isinstance(self.items, tuple):
            raise WakePacketError("Room Now items must be a tuple")
        if (
            self.availability is WakeLayerAvailability.UNAVAILABLE
            and self.items
        ):
            raise WakePacketError(
                "unavailable Room Now cannot carry items"
            )
        _refs("reason_codes", self.reason_codes)


@dataclass(frozen=True)
class WakeEmptyLayer:
    layer: WakeLayer
    availability: WakeLayerAvailability
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.layer in {WakeLayer.MAP, WakeLayer.ROOM_NOW}:
            raise WakePacketError(
                "Map/Room Now require their typed section forms"
            )
        if self.availability not in {
            WakeLayerAvailability.CLOSED,
            WakeLayerAvailability.UNAVAILABLE,
        }:
            raise WakePacketError(
                "empty Wake layer must be closed or unavailable"
            )
        _refs("reason_codes", self.reason_codes)


@dataclass(frozen=True)
class WakePacket:
    wake_id: str
    packet_version: str
    as_of: datetime
    episode_id: str
    perspective_instance_id: str
    map: WakeMapSection
    shared_now: WakeEmptyLayer
    room_now: WakeRoomNowSection
    recent_life: WakeEmptyLayer
    nearby_doors: WakeEmptyLayer
    use_boundary: WakeUseBoundary = field(default_factory=WakeUseBoundary)

    def __post_init__(self) -> None:
        _text("wake_id", self.wake_id)
        if self.packet_version != WAKE_PACKET_VERSION:
            raise WakePacketError("unexpected Wake Packet version")
        _aware("as_of", self.as_of)
        _text("episode_id", self.episode_id)
        _text("perspective_instance_id", self.perspective_instance_id)
        if self.map.item.episode_id != self.episode_id:
            raise WakePacketError(
                "Map episode differs from Wake episode"
            )
        if (
            self.map.item.perspective_instance_id
            != self.perspective_instance_id
        ):
            raise WakePacketError(
                "Map perspective differs from Wake perspective"
            )
        if (
            self.shared_now.layer is not WakeLayer.SHARED_NOW
            or self.recent_life.layer is not WakeLayer.RECENT_LIFE
            or self.nearby_doors.layer is not WakeLayer.NEARBY_DOORS
        ):
            raise WakePacketError("Wake fixed layer ordering is invalid")
        if not isinstance(self.use_boundary, WakeUseBoundary):
            raise WakePacketError("Wake packet use boundary is invalid")


@dataclass(frozen=True)
class WakeOmission:
    layer: WakeLayer
    subject_ref: str
    classification: str
    reason_codes: tuple[str, ...]
    audit_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.layer, WakeLayer):
            raise WakePacketError("omission layer is invalid")
        _text("subject_ref", self.subject_ref)
        _text("classification", self.classification)
        _refs("reason_codes", self.reason_codes)
        _refs("audit_refs", self.audit_refs)


@dataclass(frozen=True)
class WakeAssemblyReceipt:
    wake_id: str
    packet_version: str
    selection_policy_version: str
    as_of: datetime
    episode_id: str
    included_item_ids: tuple[str, ...]
    omissions: tuple[WakeOmission, ...]
    layer_availability: tuple[
        tuple[WakeLayer, WakeLayerAvailability], ...
    ]

    def __post_init__(self) -> None:
        _text("wake_id", self.wake_id)
        if self.packet_version != WAKE_PACKET_VERSION:
            raise WakePacketError("receipt packet version is invalid")
        if self.selection_policy_version != WAKE_SELECTION_POLICY_VERSION:
            raise WakePacketError(
                "receipt selection policy version is invalid"
            )
        _aware("as_of", self.as_of)
        _text("episode_id", self.episode_id)
        _refs("included_item_ids", self.included_item_ids)


_CARRYABLE_STANDINGS = frozenset(
    {
        CurrentStanding.CURRENT,
        CurrentStanding.LAST_KNOWN,
        CurrentStanding.UNRESOLVED,
        CurrentStanding.CONFLICTING,
    }
)


def assemble_wake_packet_v0_1(
    *,
    wake_id: str,
    as_of: datetime,
    episode: EpisodeRecord,
    route: RoomAttachmentResolution,
    continuity_edges: tuple[ContinuityEdge, ...] = (),
    room_current: CurrentResolvedView | None = None,
) -> tuple[WakePacket, WakeAssemblyReceipt]:
    """Pure deterministic Wake assembly from already-resolved typed inputs."""

    _text("wake_id", wake_id)
    _aware("as_of", as_of)
    if not isinstance(episode, EpisodeRecord):
        raise WakePacketError("episode must use EpisodeRecord")
    if not isinstance(route, RoomAttachmentResolution):
        raise WakePacketError(
            "route must use RoomAttachmentResolution"
        )
    if route.episode_id != episode.episode_id:
        raise WakePacketError("route belongs to a different Episode")
    if not isinstance(continuity_edges, tuple):
        raise WakePacketError("continuity_edges must be a tuple")

    incoming = tuple(
        edge
        for edge in continuity_edges
        if edge.next_episode_id == episode.episode_id
    )
    if len(incoming) > 1:
        raise WakePacketError(
            "Wake Map cannot accept implicit continuity merge"
        )
    incoming_item = (
        None
        if not incoming
        else _wake_continuity_evidence(incoming[0])
    )

    if route.decision == "attached":
        if route.room_id is None:
            raise WakePacketError(
                "attached route requires room_id"
            )
        # Map is structural orientation for this concrete Episode. The fact
        # that the Episode routes to a Room does not widen topology into Room
        # privacy authority.
        privacy = WakePrivacyScope(
            kind=WakePrivacyScopeKind.EPISODE,
            scope_id=episode.episode_id,
        )
    elif route.decision in {"unattached", "unresolved"}:
        if route.room_id is not None:
            raise WakePacketError(
                "non-attached route cannot claim room_id"
            )
        privacy = WakePrivacyScope(
            kind=WakePrivacyScopeKind.EPISODE,
            scope_id=episode.episode_id,
        )
    else:
        raise WakePacketError("unknown Room route decision")

    map_item = WakeMapItem(
        item_id=f"map:{episode.episode_id}",
        episode_id=episode.episode_id,
        perspective_instance_id=episode.perspective_instance_id,
        route_decision=route.decision,
        room_id=route.room_id,
        active_attachment_event_id=(
            route.active_attachment_event_id
        ),
        incoming_continuity=incoming_item,
        privacy_scope=privacy,
    )
    map_section = WakeMapSection(
        availability=WakeLayerAvailability.READY,
        item=map_item,
    )

    omissions: list[WakeOmission] = []
    room_section = _assemble_room_now(
        as_of=as_of,
        episode=episode,
        route=route,
        room_current=room_current,
        omissions=omissions,
    )

    shared = WakeEmptyLayer(
        layer=WakeLayer.SHARED_NOW,
        availability=WakeLayerAvailability.CLOSED,
        reason_codes=("SHARED_OPERATIONAL_CURRENT_CLOSED",),
    )
    recent = WakeEmptyLayer(
        layer=WakeLayer.RECENT_LIFE,
        availability=WakeLayerAvailability.UNAVAILABLE,
        reason_codes=("NO_TYPED_RECENT_LIFE_PRODUCER",),
    )
    doors = WakeEmptyLayer(
        layer=WakeLayer.NEARBY_DOORS,
        availability=WakeLayerAvailability.UNAVAILABLE,
        reason_codes=("NO_TYPED_NEARBY_DOORS_PRODUCER",),
    )

    packet = WakePacket(
        wake_id=wake_id,
        packet_version=WAKE_PACKET_VERSION,
        as_of=as_of,
        episode_id=episode.episode_id,
        perspective_instance_id=episode.perspective_instance_id,
        map=map_section,
        shared_now=shared,
        room_now=room_section,
        recent_life=recent,
        nearby_doors=doors,
    )
    included = [map_item.item_id]
    included.extend(item.item_id for item in room_section.items)
    receipt = WakeAssemblyReceipt(
        wake_id=wake_id,
        packet_version=WAKE_PACKET_VERSION,
        selection_policy_version=WAKE_SELECTION_POLICY_VERSION,
        as_of=as_of,
        episode_id=episode.episode_id,
        included_item_ids=tuple(included),
        omissions=tuple(omissions),
        layer_availability=(
            (WakeLayer.MAP, map_section.availability),
            (WakeLayer.SHARED_NOW, shared.availability),
            (WakeLayer.ROOM_NOW, room_section.availability),
            (WakeLayer.RECENT_LIFE, recent.availability),
            (WakeLayer.NEARBY_DOORS, doors.availability),
        ),
    )
    return packet, receipt


def _assemble_room_now(
    *,
    as_of: datetime,
    episode: EpisodeRecord,
    route: RoomAttachmentResolution,
    room_current: CurrentResolvedView | None,
    omissions: list[WakeOmission],
) -> WakeRoomNowSection:
    if route.decision == "unresolved":
        return WakeRoomNowSection(
            availability=WakeLayerAvailability.UNAVAILABLE,
            items=(),
            reason_codes=("ROOM_ROUTE_UNRESOLVED",),
        )
    if route.decision == "unattached":
        return WakeRoomNowSection(
            availability=WakeLayerAvailability.UNAVAILABLE,
            items=(),
            reason_codes=("EPISODE_NOT_ATTACHED_TO_ROOM",),
        )

    assert route.room_id is not None
    if room_current is None:
        return WakeRoomNowSection(
            availability=WakeLayerAvailability.UNAVAILABLE,
            items=(),
            reason_codes=("ROOM_CURRENT_VIEW_NOT_PROVIDED",),
        )
    if not isinstance(room_current, CurrentResolvedView):
        raise WakePacketError(
            "room_current must use CurrentResolvedView"
        )
    if room_current.namespace is not CurrentNamespace.ROOM:
        raise WakePacketError(
            "Wake Room Now requires Room Current namespace"
        )
    if room_current.owner_id != route.room_id:
        raise WakePacketError(
            "Current owner differs from routed Room"
        )
    if not _same_instant(room_current.as_of, as_of):
        raise WakePacketError(
            "Current view as_of differs from Wake as_of"
        )

    items: list[WakeRoomNowItem] = []
    held_back = False
    keys = tuple(decision.key for decision in room_current.items)
    if len(set(keys)) != len(keys):
        raise WakePacketError(
            "Room Current view contains duplicate operational keys"
        )

    for decision in room_current.items:
        if (
            decision.namespace is not CurrentNamespace.ROOM
            or decision.owner_id != route.room_id
            or not _same_instant(decision.as_of, as_of)
        ):
            raise WakePacketError(
                "Current decision does not match Wake Room/as_of"
            )

        if decision.status is CurrentResolverStatus.BLOCKED_UNKNOWN:
            held_back = True
            omissions.append(
                WakeOmission(
                    layer=WakeLayer.ROOM_NOW,
                    subject_ref=decision.key,
                    classification="operationally_withheld",
                    reason_codes=decision.reason_codes,
                    audit_refs=tuple(
                        f"suppression:{block.suppression_id}"
                        for block in decision.blocks
                    ),
                )
            )
            # Deliberately do not inspect decision.semantic_resolution.
            continue

        if (
            decision.status
            is CurrentResolverStatus.ADMISSION_PROOF_UNAVAILABLE
        ):
            held_back = True
            omissions.append(
                WakeOmission(
                    layer=WakeLayer.ROOM_NOW,
                    subject_ref=decision.key,
                    classification="operationally_withheld",
                    reason_codes=decision.reason_codes,
                    audit_refs=tuple(
                        (
                            f"effect:{effect.effect_kind.value}:"
                            f"{effect.effect_id}"
                        )
                        for effect
                        in decision.missing_live_admission_effects
                    ),
                )
            )
            continue

        if decision.status is not CurrentResolverStatus.RESOLVED:
            raise WakePacketError("unknown Current Resolver status")

        semantic = decision.semantic_resolution
        if semantic is None:
            raise WakePacketError(
                "resolved Current decision lacks semantic resolution"
            )
        if semantic.standing not in _CARRYABLE_STANDINGS:
            omissions.append(
                WakeOmission(
                    layer=WakeLayer.ROOM_NOW,
                    subject_ref=decision.key,
                    classification="not_carried_semantic_standing",
                    reason_codes=(
                        f"STANDING_{semantic.standing.value.upper()}",
                    ),
                )
            )
            continue

        items.append(
            _wake_room_item(
                room_id=route.room_id,
                decision=decision,
            )
        )

    availability = (
        WakeLayerAvailability.PARTIAL
        if held_back
        else WakeLayerAvailability.READY
    )
    reason_codes = (
        ("ROOM_CURRENT_ITEMS_WITHHELD",)
        if held_back
        else ()
    )
    return WakeRoomNowSection(
        availability=availability,
        items=tuple(items),
        reason_codes=reason_codes,
    )


def _wake_room_item(
    *,
    room_id: str,
    decision: CurrentResolverDecision,
) -> WakeRoomNowItem:
    semantic = decision.semantic_resolution
    if semantic is None:
        raise WakePacketError(
            "Room Now conversion requires semantic resolution"
        )
    selected_ids = semantic.current_state_ids
    if not selected_ids or len(set(selected_ids)) != len(selected_ids):
        raise WakePacketError(
            "carryable semantic standing requires exact current_state_ids"
        )
    candidate_by_id = {
        candidate.state_id: candidate
        for candidate in semantic.candidates
    }
    if len(candidate_by_id) != len(semantic.candidates):
        raise WakePacketError(
            "Current semantic candidates contain duplicate ids"
        )
    if any(state_id not in candidate_by_id for state_id in selected_ids):
        raise WakePacketError(
            "Current semantic current_state_ids lack candidate provenance"
        )
    selected = tuple(
        candidate_by_id[state_id]
        for state_id in selected_ids
    )
    for candidate in selected:
        record = candidate.record
        if (
            record.namespace is not CurrentNamespace.ROOM
            or record.owner_id != room_id
            or record.key != decision.key
        ):
            raise WakePacketError(
                "selected Current candidate crosses Wake Room/key boundary"
            )
    candidates = tuple(
        _wake_current_candidate(candidate)
        for candidate in selected
    )
    state_kinds = {item.state_kind for item in candidates}
    if len(state_kinds) != 1:
        raise WakePacketError(
            "one Current key cannot carry mixed state kinds"
        )
    return WakeRoomNowItem(
        item_id=f"room-now:{room_id}:{decision.key}",
        room_id=room_id,
        key=decision.key,
        state_kind=candidates[0].state_kind,
        standing=semantic.standing,
        candidates=candidates,
        reason_codes=semantic.reason_codes,
        privacy_scope=WakePrivacyScope(
            kind=WakePrivacyScopeKind.ROOM,
            scope_id=room_id,
        ),
    )


def _wake_current_candidate(
    candidate: CurrentCandidate,
) -> WakeCurrentCandidate:
    record = candidate.record
    if record.namespace is not CurrentNamespace.ROOM:
        raise WakePacketError(
            "Room Now candidate is not Room Current"
        )
    if record.episode_id is None or record.perspective_instance_id is None:
        raise WakePacketError(
            "Room Now candidate lacks Episode/Perspective provenance"
        )
    return WakeCurrentCandidate(
        state_id=record.state_id,
        value=record.value,
        state_kind=record.state_kind.value,
        standing=candidate.standing,
        semantic_change_authority=(
            record.semantic_change_authority.value
        ),
        event_time=record.event_time,
        recorded_at=record.recorded_at,
        episode_id=record.episode_id,
        perspective_instance_id=record.perspective_instance_id,
        source_refs=record.source_refs,
        end_evidence=tuple(
            WakeEndEvidence(
                end_event_id=event.end_event_id,
                end_kind=event.end_kind.value,
                episode_id=event.episode_id,
                perspective_instance_id=event.perspective_instance_id,
                source_refs=event.source_refs,
            )
            for event in candidate.end_events
        ),
    )


def _wake_continuity_evidence(
    edge: ContinuityEdge,
) -> WakeContinuityEvidence:
    return WakeContinuityEvidence(
        edge_id=edge.edge_id,
        previous_episode_id=edge.previous_episode_id,
        next_episode_id=edge.next_episode_id,
        transfer_mode=edge.transfer_mode.value,
        continuity_status=edge.continuity_status.value,
        support_refs=edge.support_refs,
    )


def _same_instant(left: datetime, right: datetime) -> bool:
    _aware("left timestamp", left)
    _aware("right timestamp", right)
    return left == right


def _text(field_name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise WakePacketError(
            f"{field_name} must be non-empty text"
        )


def _aware(field_name: str, value: object) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise WakePacketError(
            f"{field_name} must be timezone-aware"
        )


def _refs(field_name: str, values: object) -> None:
    if not isinstance(values, tuple):
        raise WakePacketError(f"{field_name} must be a tuple")
    if any(
        not isinstance(value, str) or not value.strip()
        for value in values
    ):
        raise WakePacketError(
            f"{field_name} contains invalid text"
        )
    if len(set(values)) != len(values):
        raise WakePacketError(
            f"{field_name} contains duplicates"
        )