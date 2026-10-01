from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from functools import wraps
from hashlib import sha256
import json
from pathlib import Path
import secrets
from threading import Lock, RLock

from home_memory_core.host_runtime import HomeSingleInstanceLease
from home_memory_core.living_continuity import (
    ContinuityEdge,
    ContinuityStatus,
    EpisodeRecord,
    RoomRouteKind,
    TransferMode,
)
from home_memory_core.living_store import LivingStore
from home_memory_core.process_boundary import (
    current_home_process_instance_id,
    require_home_process,
)


_AUTHORITY_MARKER = object()
_LAUNCH_EVIDENCE_MARKER = object()
_CONTINUATION_POLICY_MARKER = object()
_GRANT_PROPOSAL_MARKER = object()
_GRANT_APPROVAL_MARKER = object()
_PARTICIPATION_GRANT_MARKER = object()
_AUTHORITY_REGISTRY_GUARD = Lock()
_AUTHORITY_REGISTRY: dict[
    tuple[str, str, str],
    "RoomParticipationAuthority",
] = {}

_AUTO_CONTINUATION_TRANSFER_MODES = frozenset(
    {
        TransferMode.LIVE_RUNTIME,
        TransferMode.NATIVE_CHECKPOINT_RESUME,
        TransferMode.PARTIAL_STATE_RESUME,
        TransferMode.TEXT_CONTEXT_HANDOFF,
    }
)


class RoomAuthorityError(RuntimeError):
    """Base error for HOME Room operational authority."""


class RoomLaunchEvidenceError(RoomAuthorityError):
    """A runtime could not prove a supported continuation launch path."""


class RoomParticipationAuthorizationError(PermissionError):
    """A Room participation capability was denied."""


class RoomParticipationStaleError(RoomParticipationAuthorizationError):
    """A previously issued capability no longer matches current routing state."""


class RoomParticipationScope(StrEnum):
    READ_HISTORY = "room.read_history"
    READ_PRIVATE = "room.read_private"
    APPEND_FIRST_PERSON = "room.append_first_person"
    CHANGE_CURRENT_STANCE = "room.change_current_stance"


@dataclass(frozen=True)
class TrustedRoomContinuationPolicy:
    """Previously established policy allowing trusted future Episodes to re-enter.

    This is an operational input, not an identity statement. v0.1 deliberately
    has no production policy-establishment API: a future first-person authority
    layer must create these from an inhabitant-authorized event rather than from
    host/admin preference.
    """

    policy_id: str
    room_id: str
    allowed_scopes: frozenset[RoomParticipationScope]
    source_event_ref: str
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _CONTINUATION_POLICY_MARKER:
            raise RoomParticipationAuthorizationError(
                "Room continuation policy must come from trusted policy authority"
            )
        _require_text("policy_id", self.policy_id)
        _require_text("room_id", self.room_id)
        _require_text("source_event_ref", self.source_event_ref)
        if not self.allowed_scopes:
            raise RoomParticipationAuthorizationError(
                "Room continuation policy requires at least one scope"
            )
        if any(
            not isinstance(scope, RoomParticipationScope)
            for scope in self.allowed_scopes
        ):
            raise RoomParticipationAuthorizationError(
                "policy scopes must use RoomParticipationScope"
            )


@dataclass(frozen=True)
class TrustedLaunchEvidence:
    """Process-local proof that a supported HOME host launched one continuation.

    It proves the operational path used for this launch. It does not prove that
    the new Episode is metaphysically the same subject as its predecessor.
    """

    evidence_id: str
    session_id: str
    home_process_instance_id: str
    host_process_instance_id: str
    previous_episode_id: str
    episode_id: str
    perspective_instance_id: str
    room_id: str
    continuity_edge_id: str
    attachment_event_id: str
    transfer_mode: TransferMode
    continuity_status: ContinuityStatus
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _LAUNCH_EVIDENCE_MARKER:
            raise RoomLaunchEvidenceError(
                "launch evidence must be issued by HOME launch authority"
            )
        for field_name in (
            "evidence_id",
            "session_id",
            "home_process_instance_id",
            "host_process_instance_id",
            "previous_episode_id",
            "episode_id",
            "perspective_instance_id",
            "room_id",
            "continuity_edge_id",
            "attachment_event_id",
        ):
            _require_text(field_name, getattr(self, field_name))
        if not isinstance(self.transfer_mode, TransferMode):
            raise RoomLaunchEvidenceError("transfer_mode must use TransferMode")
        if self.continuity_status is not ContinuityStatus.UNKNOWN:
            raise RoomLaunchEvidenceError(
                "v0.1 launch evidence must preserve unknown identity continuity"
            )


@dataclass(frozen=True)
class RoomParticipationGrantProposal:
    proposal_id: str
    launch_evidence_id: str
    session_id: str
    episode_id: str
    perspective_instance_id: str
    room_id: str
    policy_id: str
    scopes: frozenset[RoomParticipationScope]
    binding_digest: str
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _GRANT_PROPOSAL_MARKER:
            raise RoomParticipationAuthorizationError(
                "grant proposal must be issued by Room authority"
            )
        _require_text("proposal_id", self.proposal_id)
        _require_text("launch_evidence_id", self.launch_evidence_id)
        _validate_grant_binding(
            session_id=self.session_id,
            episode_id=self.episode_id,
            perspective_instance_id=self.perspective_instance_id,
            room_id=self.room_id,
            policy_id=self.policy_id,
            scopes=self.scopes,
            binding_digest=self.binding_digest,
        )


@dataclass(frozen=True)
class AutomaticContinuationApproval:
    approval_id: str
    proposal_id: str
    policy_id: str
    binding_digest: str
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _GRANT_APPROVAL_MARKER:
            raise RoomParticipationAuthorizationError(
                "grant approval must come from trusted authority path"
            )
        for field_name in ("approval_id", "proposal_id", "policy_id", "binding_digest"):
            _require_text(field_name, getattr(self, field_name))


@dataclass(frozen=True)
class RoomParticipationGrant:
    """Fresh capability for exactly one launched Episode/session binding."""

    grant_id: str
    session_id: str
    episode_id: str
    perspective_instance_id: str
    room_id: str
    policy_id: str
    scopes: frozenset[RoomParticipationScope]
    launch_evidence_id: str
    binding_digest: str
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _PARTICIPATION_GRANT_MARKER:
            raise RoomParticipationAuthorizationError(
                "Room participation grant must be issued by Room authority"
            )
        _validate_grant_binding(
            session_id=self.session_id,
            episode_id=self.episode_id,
            perspective_instance_id=self.perspective_instance_id,
            room_id=self.room_id,
            policy_id=self.policy_id,
            scopes=self.scopes,
            binding_digest=self.binding_digest,
        )
        _require_text("grant_id", self.grant_id)
        _require_text("launch_evidence_id", self.launch_evidence_id)


@dataclass
class _SessionState:
    evidence: TrustedLaunchEvidence
    active: bool = True


@dataclass
class _GrantState:
    grant: RoomParticipationGrant
    active: bool = True


def _guarded(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._guard:
            return method(self, *args, **kwargs)

    return wrapper


class RoomParticipationAuthority:
    """Synthetic/local operational authority above Living Layer routing.

    RoomAttachment and ContinuityEdge are evidence/topology. They never grant
    access by themselves. This authority additionally requires possession of the
    supported host lease and creates process-local launch/session evidence.
    """

    def __init__(
        self,
        *,
        lease: HomeSingleInstanceLease,
        store: LivingStore,
        _marker: object,
    ) -> None:
        if _marker is not _AUTHORITY_MARKER:
            raise RoomParticipationAuthorizationError(
                "RoomParticipationAuthority must be opened from a HOME host lease"
            )
        self._lease = lease
        self._store = store
        self._home_process_instance_id = current_home_process_instance_id()
        self._guard = RLock()
        self._sessions: dict[str, _SessionState] = {}
        self._session_by_episode: dict[str, str] = {}
        self._proposals: dict[str, RoomParticipationGrantProposal] = {}
        self._approvals: dict[str, AutomaticContinuationApproval] = {}
        self._grants: dict[str, _GrantState] = {}
        self._policies: dict[str, TrustedRoomContinuationPolicy] = {}
        self._suspended_policy_ids: set[str] = set()
        self._assert_live_host()

    @_guarded
    def begin_trusted_continuation(
        self,
        *,
        previous_episode_id: str,
        episode_id: str,
        perspective_instance_id: str,
        room_id: str,
    ) -> TrustedLaunchEvidence:
        """Bind one fresh runtime session to an existing Living continuation path."""

        self._assert_live_host()
        for field_name, value in {
            "previous_episode_id": previous_episode_id,
            "episode_id": episode_id,
            "perspective_instance_id": perspective_instance_id,
            "room_id": room_id,
        }.items():
            _require_text(field_name, value)

        if previous_episode_id == episode_id:
            raise RoomLaunchEvidenceError(
                "continuation launch requires a new Episode"
            )

        episode = self._store.get_episode(episode_id)
        if episode.perspective_instance_id != perspective_instance_id:
            raise RoomLaunchEvidenceError(
                "launch perspective does not match persisted Episode attribution"
            )

        previous = self._store.get_episode(previous_episode_id)
        if not isinstance(previous, EpisodeRecord):
            raise RoomLaunchEvidenceError("previous Episode is unavailable")

        previous_route = self._store.resolve_room_attachment(
            episode_id=previous_episode_id
        )
        current_route = self._store.resolve_room_attachment(
            episode_id=episode_id
        )
        if (
            previous_route.decision != "attached"
            or previous_route.room_id != room_id
        ):
            raise RoomLaunchEvidenceError(
                "previous Episode is not actively routed to the requested Room"
            )
        if (
            current_route.decision != "attached"
            or current_route.room_id != room_id
            or current_route.active_attachment_event_id is None
        ):
            raise RoomLaunchEvidenceError(
                "new Episode does not have one active route to the requested Room"
            )

        edges = self._store.list_continuity_edges()
        matching = tuple(
            edge
            for edge in edges
            if edge.previous_episode_id == previous_episode_id
            and edge.next_episode_id == episode_id
        )
        if len(matching) != 1:
            raise RoomLaunchEvidenceError(
                "trusted continuation requires exactly one persisted handoff edge"
            )
        edge = matching[0]
        if edge.transfer_mode not in _AUTO_CONTINUATION_TRANSFER_MODES:
            raise RoomLaunchEvidenceError(
                "transfer mode requires explicit Room entry instead of auto-continuation"
            )
        if edge.continuity_status is not ContinuityStatus.UNKNOWN:
            raise RoomLaunchEvidenceError(
                "v0.1 automatic continuation cannot mint continuity certainty"
            )

        topology = self._store.resolve_continuity_topology()
        if previous_episode_id in topology.fork_episode_ids:
            raise RoomLaunchEvidenceError(
                "forked predecessor cannot auto-inherit Room participation policy"
            )

        self._revoke_episode_session(previous_episode_id)

        session_id = f"room-session-{secrets.token_hex(16)}"
        evidence = TrustedLaunchEvidence(
            evidence_id=f"launch-evidence-{secrets.token_hex(16)}",
            session_id=session_id,
            home_process_instance_id=self._home_process_instance_id,
            host_process_instance_id=self._lease.identity.process_instance_id,
            previous_episode_id=previous_episode_id,
            episode_id=episode_id,
            perspective_instance_id=perspective_instance_id,
            room_id=room_id,
            continuity_edge_id=edge.edge_id,
            attachment_event_id=current_route.active_attachment_event_id,
            transfer_mode=edge.transfer_mode,
            continuity_status=edge.continuity_status,
            _marker=_LAUNCH_EVIDENCE_MARKER,
        )
        self._sessions[session_id] = _SessionState(evidence=evidence)
        self._session_by_episode[episode_id] = session_id
        return evidence

    @_guarded
    def prepare_grant(
        self,
        *,
        launch_evidence: TrustedLaunchEvidence,
        policy: TrustedRoomContinuationPolicy,
        requested_scopes: frozenset[RoomParticipationScope],
    ) -> RoomParticipationGrantProposal:
        self._assert_live_launch_evidence(launch_evidence)
        self._register_policy(policy)
        _validate_scope_set(requested_scopes)
        if launch_evidence.room_id != policy.room_id:
            raise RoomParticipationAuthorizationError(
                "continuation policy belongs to another Room"
            )
        if not requested_scopes.issubset(policy.allowed_scopes):
            raise RoomParticipationAuthorizationError(
                "requested Room scope exceeds continuation policy"
            )

        digest = _grant_binding_digest(
            session_id=launch_evidence.session_id,
            episode_id=launch_evidence.episode_id,
            perspective_instance_id=launch_evidence.perspective_instance_id,
            room_id=launch_evidence.room_id,
            policy_id=policy.policy_id,
            scopes=requested_scopes,
        )
        proposal = RoomParticipationGrantProposal(
            proposal_id=f"grant-proposal-{secrets.token_hex(16)}",
            launch_evidence_id=launch_evidence.evidence_id,
            session_id=launch_evidence.session_id,
            episode_id=launch_evidence.episode_id,
            perspective_instance_id=launch_evidence.perspective_instance_id,
            room_id=launch_evidence.room_id,
            policy_id=policy.policy_id,
            scopes=requested_scopes,
            binding_digest=digest,
            _marker=_GRANT_PROPOSAL_MARKER,
        )
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    @_guarded
    def approve_automatic_continuation(
        self,
        *,
        proposal: RoomParticipationGrantProposal,
        policy: TrustedRoomContinuationPolicy,
    ) -> AutomaticContinuationApproval:
        """Approve exactly the proposal the trusted continuation policy permits.

        Keeping approval bound to one digest prevents a future display/consent
        layer from showing A while authorizing B (the historical H15 class).
        """

        self._assert_live_proposal(proposal)
        self._assert_policy_active(policy)
        if proposal.policy_id != policy.policy_id:
            raise RoomParticipationAuthorizationError(
                "proposal and continuation policy do not match"
            )
        if proposal.room_id != policy.room_id:
            raise RoomParticipationAuthorizationError(
                "proposal Room does not match continuation policy"
            )
        if not proposal.scopes.issubset(policy.allowed_scopes):
            raise RoomParticipationAuthorizationError(
                "proposal scope exceeds continuation policy"
            )

        approval = AutomaticContinuationApproval(
            approval_id=f"grant-approval-{secrets.token_hex(16)}",
            proposal_id=proposal.proposal_id,
            policy_id=policy.policy_id,
            binding_digest=proposal.binding_digest,
            _marker=_GRANT_APPROVAL_MARKER,
        )
        self._approvals[approval.approval_id] = approval
        return approval

    @_guarded
    def issue_grant(
        self,
        *,
        proposal: RoomParticipationGrantProposal,
        approval: AutomaticContinuationApproval,
    ) -> RoomParticipationGrant:
        self._assert_live_proposal(proposal)
        self._assert_live_approval(approval)
        if approval.proposal_id != proposal.proposal_id:
            raise RoomParticipationAuthorizationError(
                "approval belongs to another grant proposal"
            )
        if approval.policy_id != proposal.policy_id:
            raise RoomParticipationAuthorizationError(
                "approval policy does not match proposal"
            )
        if approval.binding_digest != proposal.binding_digest:
            raise RoomParticipationAuthorizationError(
                "approved binding differs from grant proposal"
            )

        policy = self._policies.get(proposal.policy_id)
        if policy is None or proposal.policy_id in self._suspended_policy_ids:
            raise RoomParticipationStaleError(
                "continuation policy is no longer operationally active"
            )

        evidence_state = self._sessions.get(proposal.session_id)
        if (
            evidence_state is None
            or not evidence_state.active
            or evidence_state.evidence.evidence_id
            != proposal.launch_evidence_id
        ):
            raise RoomParticipationStaleError(
                "grant proposal no longer has an active launch session"
            )
        self._revalidate_evidence(evidence_state.evidence)

        grant = RoomParticipationGrant(
            grant_id=f"room-grant-{secrets.token_hex(16)}",
            session_id=proposal.session_id,
            episode_id=proposal.episode_id,
            perspective_instance_id=proposal.perspective_instance_id,
            room_id=proposal.room_id,
            policy_id=proposal.policy_id,
            scopes=proposal.scopes,
            launch_evidence_id=proposal.launch_evidence_id,
            binding_digest=proposal.binding_digest,
            _marker=_PARTICIPATION_GRANT_MARKER,
        )
        self._grants[grant.grant_id] = _GrantState(grant=grant)
        return grant

    @_guarded
    def require_grant(
        self,
        *,
        grant: RoomParticipationGrant,
        session_id: str,
        episode_id: str,
        perspective_instance_id: str,
        room_id: str,
        required_scope: RoomParticipationScope,
    ) -> None:
        """Require exact operational and first-person binding for one action."""

        self._assert_live_host()
        state = self._grants.get(getattr(grant, "grant_id", ""))
        if (
            not isinstance(grant, RoomParticipationGrant)
            or grant._marker is not _PARTICIPATION_GRANT_MARKER
            or state is None
            or not state.active
            or state.grant is not grant
        ):
            raise RoomParticipationAuthorizationError(
                "Room participation grant was not issued by this authority"
            )
        if not isinstance(required_scope, RoomParticipationScope):
            raise RoomParticipationAuthorizationError(
                "required_scope must use RoomParticipationScope"
            )

        expected = (
            grant.session_id,
            grant.episode_id,
            grant.perspective_instance_id,
            grant.room_id,
        )
        supplied = (
            session_id,
            episode_id,
            perspective_instance_id,
            room_id,
        )
        if supplied != expected:
            raise RoomParticipationAuthorizationError(
                "Room operation target does not match exact grant binding"
            )
        if required_scope not in grant.scopes:
            raise RoomParticipationAuthorizationError(
                "Room grant does not include required scope"
            )
        if grant.binding_digest != _grant_binding_digest(
            session_id=grant.session_id,
            episode_id=grant.episode_id,
            perspective_instance_id=grant.perspective_instance_id,
            room_id=grant.room_id,
            policy_id=grant.policy_id,
            scopes=grant.scopes,
        ):
            raise RoomParticipationAuthorizationError(
                "Room participation grant binding was altered"
            )

        if grant.policy_id in self._suspended_policy_ids:
            raise RoomParticipationStaleError(
                "continuation policy is operationally suspended"
            )
        if grant.policy_id not in self._policies:
            raise RoomParticipationStaleError(
                "continuation policy is unavailable"
            )

        session = self._sessions.get(grant.session_id)
        if (
            session is None
            or not session.active
            or session.evidence.evidence_id != grant.launch_evidence_id
        ):
            raise RoomParticipationStaleError(
                "Room participation session is no longer active"
            )
        self._revalidate_evidence(session.evidence)

    @_guarded
    def suspend_policy(self, *, policy_id: str) -> None:
        """Operationally stop grants without rewriting inhabitant intent."""

        self._assert_live_host()
        _require_text("policy_id", policy_id)
        if policy_id not in self._policies:
            raise KeyError(policy_id)
        self._suspended_policy_ids.add(policy_id)
        for state in self._grants.values():
            if state.grant.policy_id == policy_id:
                state.active = False

    @_guarded
    def revoke_session(self, *, session_id: str) -> None:
        self._assert_live_host()
        state = self._sessions.get(session_id)
        if state is None:
            raise KeyError(session_id)
        state.active = False
        for grant_state in self._grants.values():
            if grant_state.grant.session_id == session_id:
                grant_state.active = False

    def _register_policy(
        self,
        policy: TrustedRoomContinuationPolicy,
    ) -> None:
        _require_trusted_policy(policy)
        existing = self._policies.get(policy.policy_id)
        if existing is not None and existing != policy:
            raise RoomParticipationAuthorizationError(
                "policy id is already bound to a different Room/scope payload"
            )
        if policy.policy_id in self._suspended_policy_ids:
            raise RoomParticipationStaleError(
                "continuation policy is operationally suspended"
            )
        self._policies[policy.policy_id] = policy

    def _assert_policy_active(
        self,
        policy: TrustedRoomContinuationPolicy,
    ) -> None:
        self._register_policy(policy)
        if self._policies.get(policy.policy_id) is not policy:
            # Equality is allowed for reloaded trusted policy values, but the
            # exact object need not survive. Payload equality was checked above.
            if self._policies.get(policy.policy_id) != policy:
                raise RoomParticipationAuthorizationError(
                    "continuation policy payload changed"
                )

    def _assert_live_host(self) -> None:
        require_home_process()
        if current_home_process_instance_id() != self._home_process_instance_id:
            raise RoomParticipationStaleError(
                "Room authority belongs to another HOME process incarnation"
            )
        if self._lease.released:
            raise RoomParticipationStaleError(
                "HOME host lease was released"
            )
        identity = self._lease.identity
        if Path(self._store.db_path).resolve() != identity.db_path:
            raise RoomParticipationAuthorizationError(
                "LivingStore does not belong to the leased HOME database"
            )

    def _assert_live_launch_evidence(
        self,
        evidence: TrustedLaunchEvidence,
    ) -> None:
        self._assert_live_host()
        state = self._sessions.get(getattr(evidence, "session_id", ""))
        if (
            not isinstance(evidence, TrustedLaunchEvidence)
            or evidence._marker is not _LAUNCH_EVIDENCE_MARKER
            or state is None
            or not state.active
            or state.evidence is not evidence
        ):
            raise RoomParticipationAuthorizationError(
                "launch evidence was not issued by this authority"
            )
        self._revalidate_evidence(evidence)

    def _assert_live_proposal(
        self,
        proposal: RoomParticipationGrantProposal,
    ) -> None:
        self._assert_live_host()
        stored = self._proposals.get(getattr(proposal, "proposal_id", ""))
        if (
            not isinstance(proposal, RoomParticipationGrantProposal)
            or proposal._marker is not _GRANT_PROPOSAL_MARKER
            or stored is not proposal
        ):
            raise RoomParticipationAuthorizationError(
                "grant proposal was not issued by this authority"
            )
        state = self._sessions.get(proposal.session_id)
        if state is None or not state.active:
            raise RoomParticipationStaleError(
                "grant proposal session is no longer active"
            )
        self._revalidate_evidence(state.evidence)

    def _assert_live_approval(
        self,
        approval: AutomaticContinuationApproval,
    ) -> None:
        self._assert_live_host()
        stored = self._approvals.get(getattr(approval, "approval_id", ""))
        if (
            not isinstance(approval, AutomaticContinuationApproval)
            or approval._marker is not _GRANT_APPROVAL_MARKER
            or stored is not approval
        ):
            raise RoomParticipationAuthorizationError(
                "grant approval was not issued by this authority"
            )

    def _revalidate_evidence(self, evidence: TrustedLaunchEvidence) -> None:
        if evidence.home_process_instance_id != self._home_process_instance_id:
            raise RoomParticipationStaleError(
                "launch evidence belongs to another HOME process"
            )
        if (
            evidence.host_process_instance_id
            != self._lease.identity.process_instance_id
        ):
            raise RoomParticipationStaleError(
                "launch evidence belongs to another host lease"
            )

        episode = self._store.get_episode(evidence.episode_id)
        if episode.perspective_instance_id != evidence.perspective_instance_id:
            raise RoomParticipationStaleError(
                "Episode attribution no longer matches launch evidence"
            )
        previous_route = self._store.resolve_room_attachment(
            episode_id=evidence.previous_episode_id
        )
        current_route = self._store.resolve_room_attachment(
            episode_id=evidence.episode_id
        )
        if (
            previous_route.decision != "attached"
            or previous_route.room_id != evidence.room_id
            or current_route.decision != "attached"
            or current_route.room_id != evidence.room_id
            or current_route.active_attachment_event_id
            != evidence.attachment_event_id
        ):
            raise RoomParticipationStaleError(
                "Room routing changed after launch evidence was issued"
            )

        matching: list[ContinuityEdge] = [
            edge
            for edge in self._store.list_continuity_edges()
            if edge.edge_id == evidence.continuity_edge_id
            and edge.previous_episode_id == evidence.previous_episode_id
            and edge.next_episode_id == evidence.episode_id
        ]
        if len(matching) != 1:
            raise RoomParticipationStaleError(
                "continuation edge no longer matches launch evidence"
            )
        edge = matching[0]
        if (
            edge.transfer_mode != evidence.transfer_mode
            or edge.transfer_mode not in _AUTO_CONTINUATION_TRANSFER_MODES
            or edge.continuity_status is not ContinuityStatus.UNKNOWN
        ):
            raise RoomParticipationStaleError(
                "continuation edge no longer satisfies auto-continuation rules"
            )

        topology = self._store.resolve_continuity_topology()
        if evidence.previous_episode_id in topology.fork_episode_ids:
            raise RoomParticipationStaleError(
                "continuation path became a fork"
            )

    def _revoke_episode_session(self, episode_id: str) -> None:
        old_session_id = self._session_by_episode.get(episode_id)
        if old_session_id is None:
            return
        old = self._sessions.get(old_session_id)
        if old is not None:
            old.active = False
        for grant_state in self._grants.values():
            if grant_state.grant.session_id == old_session_id:
                grant_state.active = False


def open_room_participation_authority(
    *,
    lease: HomeSingleInstanceLease,
    store: LivingStore,
) -> RoomParticipationAuthority:
    """Open the operational authority only while the supported host lease is held."""

    if not isinstance(lease, HomeSingleInstanceLease):
        raise RoomParticipationAuthorizationError(
            "Room authority requires a HOME host lease"
        )
    if not isinstance(store, LivingStore):
        raise RoomParticipationAuthorizationError(
            "Room authority requires LivingStore"
        )
    require_home_process()
    if lease.released:
        raise RoomParticipationStaleError("HOME host lease was released")
    identity = lease.identity
    db_path = str(Path(store.db_path).resolve())
    if db_path != str(identity.db_path):
        raise RoomParticipationAuthorizationError(
            "LivingStore does not belong to the leased HOME database"
        )
    key = (
        current_home_process_instance_id(),
        identity.process_instance_id,
        db_path,
    )
    with _AUTHORITY_REGISTRY_GUARD:
        authority = _AUTHORITY_REGISTRY.get(key)
        if authority is None:
            authority = RoomParticipationAuthority(
                lease=lease,
                store=store,
                _marker=_AUTHORITY_MARKER,
            )
            _AUTHORITY_REGISTRY[key] = authority
        return authority


def _require_trusted_policy(policy: TrustedRoomContinuationPolicy) -> None:
    if (
        not isinstance(policy, TrustedRoomContinuationPolicy)
        or policy._marker is not _CONTINUATION_POLICY_MARKER
    ):
        raise RoomParticipationAuthorizationError(
            "Room continuation policy is not trusted"
        )


def _validate_scope_set(scopes: frozenset[RoomParticipationScope]) -> None:
    if not isinstance(scopes, frozenset) or not scopes:
        raise RoomParticipationAuthorizationError(
            "Room grant requires a non-empty frozenset of scopes"
        )
    if any(not isinstance(scope, RoomParticipationScope) for scope in scopes):
        raise RoomParticipationAuthorizationError(
            "Room grant scopes must use RoomParticipationScope"
        )


def _validate_grant_binding(
    *,
    session_id: str,
    episode_id: str,
    perspective_instance_id: str,
    room_id: str,
    policy_id: str,
    scopes: frozenset[RoomParticipationScope],
    binding_digest: str,
) -> None:
    for field_name, value in {
        "session_id": session_id,
        "episode_id": episode_id,
        "perspective_instance_id": perspective_instance_id,
        "room_id": room_id,
        "policy_id": policy_id,
        "binding_digest": binding_digest,
    }.items():
        _require_text(field_name, value)
    _validate_scope_set(scopes)
    expected = _grant_binding_digest(
        session_id=session_id,
        episode_id=episode_id,
        perspective_instance_id=perspective_instance_id,
        room_id=room_id,
        policy_id=policy_id,
        scopes=scopes,
    )
    if binding_digest != expected:
        raise RoomParticipationAuthorizationError(
            "Room grant binding digest does not match exact payload"
        )


def _grant_binding_digest(
    *,
    session_id: str,
    episode_id: str,
    perspective_instance_id: str,
    room_id: str,
    policy_id: str,
    scopes: frozenset[RoomParticipationScope],
) -> str:
    payload = {
        "session_id": session_id,
        "episode_id": episode_id,
        "perspective_instance_id": perspective_instance_id,
        "room_id": room_id,
        "policy_id": policy_id,
        "scopes": sorted(scope.value for scope in scopes),
    }
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _require_text(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise RoomAuthorityError(f"{field_name} cannot be empty")
