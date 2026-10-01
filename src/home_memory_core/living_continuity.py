from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum


class LivingContinuityError(ValueError):
    """A Living Layer record violated the continuity/room routing contract."""


class TransferMode(StrEnum):
    LIVE_RUNTIME = "live_runtime"
    NATIVE_CHECKPOINT_RESUME = "native_checkpoint_resume"
    PARTIAL_STATE_RESUME = "partial_state_resume"
    HISTORY_RECONSTRUCTION = "history_reconstruction"
    TEXT_CONTEXT_HANDOFF = "text_context_handoff"
    NO_KNOWN_TRANSFER = "no_known_transfer"


class ContinuityStatus(StrEnum):
    """Evidence strength for one continuity relation.

    Forking is intentionally not a status here. Forking is a structural property
    of the continuity graph and is derived by resolve_continuity_topology.
    """

    VERIFIED = "verified"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class RoomRouteKind(StrEnum):
    ATTACHED = "attached"
    UNATTACHED = "unattached"


@dataclass(frozen=True)
class RoomRecord:
    """One first-person living branch.

    A Room is an authority/routing namespace for an ongoing first-person branch.
    It is not an identity verdict.
    """

    room_id: str

    def __post_init__(self) -> None:
        _require_nonempty("room_id", self.room_id)


@dataclass(frozen=True)
class EpisodeRecord:
    """One concrete runtime/window episode.

    Perspective-instance identity stays explicit and separate from Room routing.
    Runtime/model metadata may help describe provenance, but never proves
    first-person identity continuity by itself.
    """

    episode_id: str
    perspective_instance_id: str
    runtime_instance_id: str | None = None
    model_ref: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty("episode_id", self.episode_id)
        _require_nonempty("perspective_instance_id", self.perspective_instance_id)
        _require_optional_nonempty("runtime_instance_id", self.runtime_instance_id)
        _require_optional_nonempty("model_ref", self.model_ref)


@dataclass(frozen=True)
class ContinuityEdge:
    """Evidence-bearing relation describing how one Episode led to another.

    transfer_mode describes the mechanism.
    continuity_status describes how much the available evidence establishes.

    Neither field is a same-self claim.
    """

    edge_id: str
    previous_episode_id: str
    next_episode_id: str
    transfer_mode: TransferMode
    continuity_status: ContinuityStatus
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_nonempty("edge_id", self.edge_id)
        _require_nonempty("previous_episode_id", self.previous_episode_id)
        _require_nonempty("next_episode_id", self.next_episode_id)
        if self.previous_episode_id == self.next_episode_id:
            raise LivingContinuityError(
                "continuity edge cannot connect an episode to itself"
            )
        if not isinstance(self.transfer_mode, TransferMode):
            raise LivingContinuityError("transfer_mode must use TransferMode")
        if not isinstance(self.continuity_status, ContinuityStatus):
            raise LivingContinuityError(
                "continuity_status must use ContinuityStatus"
            )
        _validate_refs(self.evidence_refs)


@dataclass(frozen=True)
class ContinuityTopology:
    """Structural view of Episode continuity.

    Multiple outgoing edges are allowed and represent a fork. Multiple incoming
    continuity parents are rejected in v0.1 because an implicit merge would make
    first-person lineage ambiguous without an explicit merge contract.
    """

    episode_ids: frozenset[str]
    root_episode_ids: frozenset[str]
    head_episode_ids: frozenset[str]
    fork_episode_ids: frozenset[str]


def resolve_continuity_topology(
    *,
    episodes: tuple[EpisodeRecord, ...],
    edges: tuple[ContinuityEdge, ...],
) -> ContinuityTopology:
    """Validate and derive structural continuity facts without identity claims."""

    episode_by_id: dict[str, EpisodeRecord] = {}
    for episode in episodes:
        if not isinstance(episode, EpisodeRecord):
            raise LivingContinuityError("episodes must contain EpisodeRecord values")
        if episode.episode_id in episode_by_id:
            raise LivingContinuityError("duplicate episode_id")
        episode_by_id[episode.episode_id] = episode

    edge_ids: set[str] = set()
    edge_pairs: set[tuple[str, str]] = set()
    incoming_parent: dict[str, str] = {}
    adjacency: dict[str, set[str]] = {}
    incoming_count: Counter[str] = Counter()
    outgoing_count: Counter[str] = Counter()

    for edge in edges:
        if not isinstance(edge, ContinuityEdge):
            raise LivingContinuityError("edges must contain ContinuityEdge values")
        if edge.edge_id in edge_ids:
            raise LivingContinuityError("duplicate continuity edge id")
        edge_ids.add(edge.edge_id)

        pair = (edge.previous_episode_id, edge.next_episode_id)
        if pair in edge_pairs:
            raise LivingContinuityError("duplicate continuity edge")
        edge_pairs.add(pair)

        if edge.previous_episode_id not in episode_by_id:
            raise LivingContinuityError(
                "continuity edge previous episode is missing"
            )
        if edge.next_episode_id not in episode_by_id:
            raise LivingContinuityError(
                "continuity edge next episode is missing"
            )

        existing_parent = incoming_parent.get(edge.next_episode_id)
        if (
            existing_parent is not None
            and existing_parent != edge.previous_episode_id
        ):
            raise LivingContinuityError(
                "continuity graph contains an implicit merge"
            )
        incoming_parent[edge.next_episode_id] = edge.previous_episode_id
        adjacency.setdefault(edge.previous_episode_id, set()).add(
            edge.next_episode_id
        )
        incoming_count[edge.next_episode_id] += 1
        outgoing_count[edge.previous_episode_id] += 1

    _assert_continuity_acyclic(
        episode_ids=frozenset(episode_by_id),
        adjacency=adjacency,
    )

    episode_ids = frozenset(episode_by_id)
    roots = frozenset(
        episode_id
        for episode_id in episode_ids
        if incoming_count[episode_id] == 0
    )
    heads = frozenset(
        episode_id
        for episode_id in episode_ids
        if outgoing_count[episode_id] == 0
    )
    forks = frozenset(
        episode_id
        for episode_id in episode_ids
        if outgoing_count[episode_id] > 1
    )

    return ContinuityTopology(
        episode_ids=episode_ids,
        root_episode_ids=roots,
        head_episode_ids=heads,
        fork_episode_ids=forks,
    )


@dataclass(frozen=True)
class RoomAttachmentEvent:
    """Append-only routing event for one Episode.

    A later event may supersede an earlier routing decision without rewriting it.
    ATTACHED routes the Episode to one Room.
    UNATTACHED explicitly records that no Room route currently applies.

    This record never asserts subject identity.
    """

    attachment_event_id: str
    episode_id: str
    route_kind: RoomRouteKind
    room_id: str | None
    basis: str
    supersedes_attachment_event_id: str | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_nonempty("attachment_event_id", self.attachment_event_id)
        _require_nonempty("episode_id", self.episode_id)
        _require_nonempty("basis", self.basis)
        if not isinstance(self.route_kind, RoomRouteKind):
            raise LivingContinuityError("route_kind must use RoomRouteKind")
        if self.route_kind is RoomRouteKind.ATTACHED:
            if self.room_id is None:
                raise LivingContinuityError(
                    "attached room route requires room_id"
                )
            _require_nonempty("room_id", self.room_id)
        elif self.room_id is not None:
            raise LivingContinuityError(
                "unattached room route must not carry room_id"
            )
        _require_optional_nonempty(
            "supersedes_attachment_event_id",
            self.supersedes_attachment_event_id,
        )
        if self.supersedes_attachment_event_id == self.attachment_event_id:
            raise LivingContinuityError(
                "room attachment event cannot supersede itself"
            )
        _validate_refs(self.evidence_refs)


@dataclass(frozen=True)
class RoomAttachmentResolution:
    episode_id: str
    decision: str
    room_id: str | None
    active_attachment_event_id: str | None
    reason_codes: tuple[str, ...] = ()


def resolve_room_attachment(
    *,
    episode_id: str,
    events: tuple[RoomAttachmentEvent, ...],
) -> RoomAttachmentResolution:
    """Resolve the latest non-superseded Room route for one Episode.

    Resolution is purely structural. It does not infer identity continuity.
    Multiple active heads stay unresolved instead of choosing one.
    """

    _require_nonempty("episode_id", episode_id)
    relevant = tuple(event for event in events if event.episode_id == episode_id)
    if not relevant:
        return RoomAttachmentResolution(
            episode_id=episode_id,
            decision="unattached",
            room_id=None,
            active_attachment_event_id=None,
            reason_codes=("NO_ATTACHMENT_EVENT",),
        )

    by_id: dict[str, RoomAttachmentEvent] = {}
    for event in relevant:
        if event.attachment_event_id in by_id:
            raise LivingContinuityError(
                "duplicate room attachment event id for episode"
            )
        by_id[event.attachment_event_id] = event

    superseded_ids: set[str] = set()
    adjacency: dict[str, str] = {}

    for event in relevant:
        previous_id = event.supersedes_attachment_event_id
        if previous_id is None:
            continue
        if previous_id not in by_id:
            raise LivingContinuityError(
                "room attachment supersession target is missing "
                "or belongs to another episode"
            )
        adjacency[event.attachment_event_id] = previous_id
        superseded_ids.add(previous_id)

    _assert_attachment_acyclic(by_id=by_id, adjacency=adjacency)

    heads = tuple(
        event
        for event in relevant
        if event.attachment_event_id not in superseded_ids
    )

    if len(heads) != 1:
        return RoomAttachmentResolution(
            episode_id=episode_id,
            decision="unresolved",
            room_id=None,
            active_attachment_event_id=None,
            reason_codes=("MULTIPLE_ACTIVE_ATTACHMENT_HEADS",),
        )

    head = heads[0]
    if head.route_kind is RoomRouteKind.UNATTACHED:
        return RoomAttachmentResolution(
            episode_id=episode_id,
            decision="unattached",
            room_id=None,
            active_attachment_event_id=head.attachment_event_id,
        )

    return RoomAttachmentResolution(
        episode_id=episode_id,
        decision="attached",
        room_id=head.room_id,
        active_attachment_event_id=head.attachment_event_id,
    )


def _assert_continuity_acyclic(
    *,
    episode_ids: frozenset[str],
    adjacency: dict[str, set[str]],
) -> None:
    visited: set[str] = set()
    active: set[str] = set()

    def visit(episode_id: str) -> None:
        if episode_id in active:
            raise LivingContinuityError("continuity graph contains a cycle")
        if episode_id in visited:
            return
        active.add(episode_id)
        for next_episode_id in adjacency.get(episode_id, set()):
            visit(next_episode_id)
        active.remove(episode_id)
        visited.add(episode_id)

    for episode_id in episode_ids:
        visit(episode_id)


def _assert_attachment_acyclic(
    *,
    by_id: dict[str, RoomAttachmentEvent],
    adjacency: dict[str, str],
) -> None:
    visited: set[str] = set()
    active: set[str] = set()

    def visit(event_id: str) -> None:
        if event_id in active:
            raise LivingContinuityError(
                "room attachment supersession contains a cycle"
            )
        if event_id in visited:
            return
        active.add(event_id)
        previous_id = adjacency.get(event_id)
        if previous_id is not None:
            visit(previous_id)
        active.remove(event_id)
        visited.add(event_id)

    for event_id in by_id:
        visit(event_id)


def _require_nonempty(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LivingContinuityError(f"{field_name} cannot be empty")


def _require_optional_nonempty(field_name: str, value: str | None) -> None:
    if value is not None:
        _require_nonempty(field_name, value)


def _validate_refs(refs: tuple[str, ...]) -> None:
    if not isinstance(refs, tuple):
        raise LivingContinuityError("evidence_refs must be a tuple")
    if any(not isinstance(item, str) or not item.strip() for item in refs):
        raise LivingContinuityError(
            "evidence_refs cannot contain empty values"
        )
    if len(set(refs)) != len(refs):
        raise LivingContinuityError("evidence_refs cannot contain duplicates")
