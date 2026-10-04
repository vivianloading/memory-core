from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from functools import wraps
from hashlib import sha256
import json
from pathlib import Path
import secrets
from threading import Lock, RLock
from typing import Iterator

from home_memory_core.host_runtime import HomeSingleInstanceLease
from home_memory_core.living_continuity import (
    ContinuityEdge,
    ContinuityStatus,
    RoomRouteKind,
    TransferMode,
)
from home_memory_core.living_store import LivingStore
from home_memory_core.process_boundary import (
    current_home_process_instance_id,
    require_home_process,
)


_AUTHORITY_MARKER = object()
_RUNTIME_LAUNCH_ISSUER_MARKER = object()
_RUNTIME_LAUNCH_RECEIPT_MARKER = object()
_LAUNCH_EVIDENCE_MARKER = object()
_CONTINUATION_POLICY_MARKER = object()
_CONTINUATION_POLICY_ISSUER_MARKER = object()
_GRANT_PROPOSAL_MARKER = object()
_GRANT_APPROVAL_MARKER = object()
_PARTICIPATION_GRANT_MARKER = object()
_AUTHORITY_REGISTRY_GUARD = Lock()
_AUTHORITY_REGISTRY: dict[
    tuple[str, str, str],
    "RoomParticipationAuthority",
] = {}
_POLICY_ISSUANCE_REGISTRY_GUARD = Lock()

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
    issuance_id: str
    room_id: str
    established_episode_id: str
    established_attachment_event_id: str
    allowed_scopes: frozenset[RoomParticipationScope]
    source_event_ref: str
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _CONTINUATION_POLICY_MARKER:
            raise RoomParticipationAuthorizationError(
                "Room continuation policy must come from trusted policy authority"
            )
        _require_text("policy_id", self.policy_id)
        _require_text("issuance_id", self.issuance_id)
        _require_text("room_id", self.room_id)
        _require_text("established_episode_id", self.established_episode_id)
        _require_text(
            "established_attachment_event_id",
            self.established_attachment_event_id,
        )
        _require_text("source_event_ref", self.source_event_ref)
        _validate_scope_set(self.allowed_scopes)


@dataclass
class _TrustedPolicyIssuanceState:
    policy: TrustedRoomContinuationPolicy
    fingerprint: str
    home_process_instance_id: str
    host_process_instance_id: str
    db_path: str


_POLICY_ISSUANCE_REGISTRY: dict[
    str,
    _TrustedPolicyIssuanceState,
] = {}


def _issue_trusted_room_continuation_policy_for_test(
    *,
    lease: HomeSingleInstanceLease,
    store: LivingStore,
    policy_id: str,
    room_id: str,
    established_episode_id: str,
    established_attachment_event_id: str,
    allowed_scopes: frozenset[RoomParticipationScope],
    source_event_ref: str,
    _issuer_marker: object,
) -> TrustedRoomContinuationPolicy:
    """Synthetic-only issuer seam; no production policy issuer exists in v0.1."""

    if _issuer_marker is not _CONTINUATION_POLICY_ISSUER_MARKER:
        raise RoomParticipationAuthorizationError(
            "Room continuation policy issuer is not trusted"
        )
    if not isinstance(lease, HomeSingleInstanceLease):
        raise RoomParticipationAuthorizationError(
            "Room continuation policy issuance requires a HOME host lease"
        )
    if not isinstance(store, LivingStore):
        raise RoomParticipationAuthorizationError(
            "Room continuation policy issuance requires LivingStore"
        )
    require_home_process()
    if lease.released:
        raise RoomParticipationStaleError(
            "HOME host lease was released"
        )
    identity = lease.identity
    db_path = str(Path(store.db_path).resolve())
    if db_path != str(identity.db_path):
        raise RoomParticipationAuthorizationError(
            "policy issuer store does not belong to the HOME host lease"
        )

    policy = TrustedRoomContinuationPolicy(
        policy_id=policy_id,
        issuance_id=f"room-policy-issuance-{secrets.token_hex(16)}",
        room_id=room_id,
        established_episode_id=established_episode_id,
        established_attachment_event_id=established_attachment_event_id,
        allowed_scopes=allowed_scopes,
        source_event_ref=source_event_ref,
        _marker=_CONTINUATION_POLICY_MARKER,
    )
    state = _TrustedPolicyIssuanceState(
        policy=policy,
        fingerprint=_policy_fingerprint(policy),
        home_process_instance_id=current_home_process_instance_id(),
        host_process_instance_id=identity.process_instance_id,
        db_path=db_path,
    )
    with _POLICY_ISSUANCE_REGISTRY_GUARD:
        _POLICY_ISSUANCE_REGISTRY[policy.issuance_id] = state
    return policy


@dataclass(frozen=True)
class SupportedRuntimeLaunchReceipt:
    """One host-observed runtime launch, before Room continuation is authorized."""

    receipt_id: str
    session_id: str
    home_process_instance_id: str
    host_process_instance_id: str
    episode_id: str
    perspective_instance_id: str
    runtime_instance_id: str
    observed_transfer_mode: TransferMode
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _RUNTIME_LAUNCH_RECEIPT_MARKER:
            raise RoomLaunchEvidenceError(
                "runtime launch receipt must be issued by HOME launch authority"
            )
        for field_name in (
            "receipt_id",
            "session_id",
            "home_process_instance_id",
            "host_process_instance_id",
            "episode_id",
            "perspective_instance_id",
        ):
            _require_text(field_name, getattr(self, field_name))
        _require_text("runtime_instance_id", self.runtime_instance_id)
        if not isinstance(self.observed_transfer_mode, TransferMode):
            raise RoomLaunchEvidenceError(
                "observed_transfer_mode must use TransferMode"
            )


@dataclass(frozen=True)
class TrustedLaunchEvidence:
    """Process-local proof that a supported HOME host launched one continuation.

    It proves the operational path used for this launch. It does not prove that
    the new Episode is metaphysically the same subject as its predecessor.
    """

    evidence_id: str
    runtime_launch_receipt_id: str
    session_id: str
    home_process_instance_id: str
    host_process_instance_id: str
    previous_episode_id: str
    episode_id: str
    perspective_instance_id: str
    room_id: str
    continuity_edge_id: str
    previous_attachment_event_id: str
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
            "runtime_launch_receipt_id",
            "session_id",
            "home_process_instance_id",
            "host_process_instance_id",
            "previous_episode_id",
            "episode_id",
            "perspective_instance_id",
            "room_id",
            "continuity_edge_id",
            "previous_attachment_event_id",
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
    policy_fingerprint: str
    session_id: str
    episode_id: str
    perspective_instance_id: str
    room_id: str
    policy_id: str
    policy_issuance_id: str
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
        _require_text("policy_fingerprint", self.policy_fingerprint)
        _validate_grant_binding(
            launch_evidence_id=self.launch_evidence_id,
            policy_fingerprint=self.policy_fingerprint,
            session_id=self.session_id,
            episode_id=self.episode_id,
            perspective_instance_id=self.perspective_instance_id,
            room_id=self.room_id,
            policy_id=self.policy_id,
            policy_issuance_id=self.policy_issuance_id,
            scopes=self.scopes,
            binding_digest=self.binding_digest,
        )


@dataclass(frozen=True)
class AutomaticContinuationApproval:
    approval_id: str
    proposal_id: str
    policy_id: str
    policy_issuance_id: str
    binding_digest: str
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _GRANT_APPROVAL_MARKER:
            raise RoomParticipationAuthorizationError(
                "grant approval must come from trusted authority path"
            )
        for field_name in (
            "approval_id",
            "proposal_id",
            "policy_id",
            "policy_issuance_id",
            "binding_digest",
        ):
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
    policy_issuance_id: str
    policy_fingerprint: str
    scopes: frozenset[RoomParticipationScope]
    launch_evidence_id: str
    proposal_id: str
    approval_id: str
    binding_digest: str
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _PARTICIPATION_GRANT_MARKER:
            raise RoomParticipationAuthorizationError(
                "Room participation grant must be issued by Room authority"
            )
        _validate_grant_binding(
            launch_evidence_id=self.launch_evidence_id,
            policy_fingerprint=self.policy_fingerprint,
            session_id=self.session_id,
            episode_id=self.episode_id,
            perspective_instance_id=self.perspective_instance_id,
            room_id=self.room_id,
            policy_id=self.policy_id,
            policy_issuance_id=self.policy_issuance_id,
            scopes=self.scopes,
            binding_digest=self.binding_digest,
        )
        _require_text("grant_id", self.grant_id)
        _require_text("launch_evidence_id", self.launch_evidence_id)
        _require_text("proposal_id", self.proposal_id)
        _require_text("approval_id", self.approval_id)


@dataclass
class _RuntimeLaunchState:
    receipt: SupportedRuntimeLaunchReceipt
    fingerprint: str
    consumed: bool = False


_RUNTIME_LAUNCH_REGISTRY_GUARD = Lock()
_RUNTIME_LAUNCH_REGISTRY: dict[
    tuple[str, str, str, str],
    _RuntimeLaunchState,
] = {}
_RUNTIME_LAUNCHED_EPISODES: set[
    tuple[str, str, str, str]
] = set()


class TrustedRuntimeLaunchIssuer:
    """Host-private observer that can attest one supported runtime launch.

    v0.1 intentionally has no public production factory for this issuer.
    The eventual runtime adapter must own it and call record_supported_runtime_launch
    at the actual launch boundary. Synthetic tests receive one through trusted
    test support.
    """

    def __init__(
        self,
        *,
        lease: HomeSingleInstanceLease,
        store: LivingStore,
        _marker: object,
    ) -> None:
        if _marker is not _RUNTIME_LAUNCH_ISSUER_MARKER:
            raise RoomLaunchEvidenceError(
                "runtime launch issuer must come from trusted host bootstrap"
            )
        self._lease = lease
        self._canonical_db_path = Path(lease.identity.db_path).resolve()
        # The caller-owned LivingStore proves the open-time binding only.
        # Operational Room authority reads are pinned to the lease-rooted DB.
        self._store = LivingStore(self._canonical_db_path)
        self._home_process_instance_id = current_home_process_instance_id()
        self._guard = RLock()
        self._assert_live_host()

    def record_supported_runtime_launch(
        self,
        *,
        episode_id: str,
        perspective_instance_id: str,
        observed_runtime_instance_id: str,
        observed_transfer_mode: TransferMode,
    ) -> SupportedRuntimeLaunchReceipt:
        with self._guard:
            self._assert_live_host()
            _require_text("episode_id", episode_id)
            _require_text("perspective_instance_id", perspective_instance_id)
            _require_text(
                "observed_runtime_instance_id",
                observed_runtime_instance_id,
            )
            if not isinstance(observed_transfer_mode, TransferMode):
                raise RoomLaunchEvidenceError(
                    "observed_transfer_mode must use TransferMode"
                )

            episode = self._store.get_episode(episode_id)
            if episode.runtime_instance_id is None:
                raise RoomLaunchEvidenceError(
                    "automatic Room participation requires a concrete runtime instance"
                )
            if episode.perspective_instance_id != perspective_instance_id:
                raise RoomLaunchEvidenceError(
                    "runtime launch perspective does not match persisted Episode"
                )
            if episode.runtime_instance_id != observed_runtime_instance_id:
                raise RoomLaunchEvidenceError(
                    "observed runtime instance does not match persisted Episode"
                )

            base = self._registry_base()
            episode_key = (*base, episode_id)
            with _RUNTIME_LAUNCH_REGISTRY_GUARD:
                if episode_key in _RUNTIME_LAUNCHED_EPISODES:
                    raise RoomLaunchEvidenceError(
                        "Episode already has a runtime launch; "
                        "a new runtime requires a new Episode"
                    )

                receipt = SupportedRuntimeLaunchReceipt(
                    receipt_id=f"runtime-launch-{secrets.token_hex(16)}",
                    session_id=f"room-session-{secrets.token_hex(16)}",
                    home_process_instance_id=self._home_process_instance_id,
                    host_process_instance_id=(
                        self._lease.identity.process_instance_id
                    ),
                    episode_id=episode_id,
                    perspective_instance_id=perspective_instance_id,
                    runtime_instance_id=observed_runtime_instance_id,
                    observed_transfer_mode=observed_transfer_mode,
                    _marker=_RUNTIME_LAUNCH_RECEIPT_MARKER,
                )
                receipt_key = (*base, receipt.receipt_id)
                _RUNTIME_LAUNCH_REGISTRY[receipt_key] = _RuntimeLaunchState(
                    receipt=receipt,
                    fingerprint=_runtime_launch_fingerprint(receipt),
                )
                _RUNTIME_LAUNCHED_EPISODES.add(episode_key)
            return receipt

    def _registry_base(self) -> tuple[str, str, str]:
        return (
            self._home_process_instance_id,
            self._lease.identity.process_instance_id,
            str(self._canonical_db_path),
        )

    def _assert_live_host(self) -> None:
        require_home_process()
        if (
            current_home_process_instance_id()
            != self._home_process_instance_id
        ):
            raise RoomParticipationStaleError(
                "runtime launch issuer belongs to another HOME process"
            )
        if self._lease.released:
            raise RoomParticipationStaleError(
                "HOME host lease was released"
            )
        if (
            Path(self._store.db_path).resolve()
            != self._lease.identity.db_path
        ):
            raise RoomLaunchEvidenceError(
                "runtime launch issuer store does not match host lease"
            )


@dataclass
class _SessionState:
    evidence: TrustedLaunchEvidence
    fingerprint: str
    active: bool = True


@dataclass
class _ProposalState:
    proposal: RoomParticipationGrantProposal
    fingerprint: str
    approved: bool = False


@dataclass
class _ApprovalState:
    approval: AutomaticContinuationApproval
    fingerprint: str
    consumed: bool = False


@dataclass
class _GrantState:
    grant: RoomParticipationGrant
    fingerprint: str
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
        self._proposals: dict[str, _ProposalState] = {}
        self._approvals: dict[str, _ApprovalState] = {}
        self._grants: dict[str, _GrantState] = {}
        self._policies: dict[str, TrustedRoomContinuationPolicy] = {}
        self._policy_fingerprints: dict[str, str] = {}
        self._suspended_policy_issuance_ids: set[str] = set()
        self._assert_live_host()

    @_guarded
    def begin_trusted_continuation(
        self,
        *,
        launch_receipt: SupportedRuntimeLaunchReceipt,
        previous_episode_id: str,
        room_id: str,
    ) -> TrustedLaunchEvidence:
        """Bind one host-observed runtime launch to one Living continuation path."""

        self._assert_live_runtime_launch(launch_receipt)
        for field_name, value in {
            "previous_episode_id": previous_episode_id,
            "room_id": room_id,
        }.items():
            _require_text(field_name, value)

        episode_id = launch_receipt.episode_id
        perspective_instance_id = launch_receipt.perspective_instance_id
        if previous_episode_id == episode_id:
            raise RoomLaunchEvidenceError(
                "continuation launch requires a new Episode"
            )

        snapshot = self._store.read_continuation_path_snapshot(
            previous_episode_id=previous_episode_id,
            episode_id=episode_id,
        )
        episode = snapshot.episode
        if episode.perspective_instance_id != perspective_instance_id:
            raise RoomLaunchEvidenceError(
                "launch perspective does not match persisted Episode attribution"
            )

        previous_route = snapshot.previous_route
        current_route = snapshot.current_route
        if (
            previous_route.decision != "attached"
            or previous_route.room_id != room_id
            or previous_route.active_attachment_event_id is None
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

        edges = snapshot.edges
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
        if edge.transfer_mode != launch_receipt.observed_transfer_mode:
            raise RoomLaunchEvidenceError(
                "persisted transfer mode does not match observed runtime launch"
            )
        if edge.transfer_mode not in _AUTO_CONTINUATION_TRANSFER_MODES:
            raise RoomLaunchEvidenceError(
                "transfer mode requires explicit Room entry instead of auto-continuation"
            )
        if edge.continuity_status is not ContinuityStatus.UNKNOWN:
            raise RoomLaunchEvidenceError(
                "v0.1 automatic continuation cannot mint continuity certainty"
            )

        topology = snapshot.topology
        if previous_episode_id in topology.fork_episode_ids:
            raise RoomLaunchEvidenceError(
                "forked predecessor cannot auto-inherit Room participation policy"
            )

        self._consume_runtime_launch(launch_receipt)
        self._revoke_episode_session(previous_episode_id)
        self._revoke_episode_session(episode_id)

        session_id = launch_receipt.session_id
        evidence = TrustedLaunchEvidence(
            evidence_id=f"launch-evidence-{secrets.token_hex(16)}",
            runtime_launch_receipt_id=launch_receipt.receipt_id,
            session_id=session_id,
            home_process_instance_id=self._home_process_instance_id,
            host_process_instance_id=self._lease.identity.process_instance_id,
            previous_episode_id=previous_episode_id,
            episode_id=episode_id,
            perspective_instance_id=perspective_instance_id,
            room_id=room_id,
            continuity_edge_id=edge.edge_id,
            previous_attachment_event_id=(
                previous_route.active_attachment_event_id
            ),
            attachment_event_id=current_route.active_attachment_event_id,
            transfer_mode=edge.transfer_mode,
            continuity_status=edge.continuity_status,
            _marker=_LAUNCH_EVIDENCE_MARKER,
        )
        self._sessions[session_id] = _SessionState(
            evidence=evidence,
            fingerprint=_launch_evidence_fingerprint(evidence),
        )
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
        self._revalidate_evidence(launch_evidence, policy=policy)

        policy_fingerprint = _policy_fingerprint(policy)
        digest = _grant_binding_digest(
            launch_evidence_id=launch_evidence.evidence_id,
            policy_fingerprint=policy_fingerprint,
            session_id=launch_evidence.session_id,
            episode_id=launch_evidence.episode_id,
            perspective_instance_id=launch_evidence.perspective_instance_id,
            room_id=launch_evidence.room_id,
            policy_id=policy.policy_id,
            policy_issuance_id=policy.issuance_id,
            scopes=requested_scopes,
        )
        proposal = RoomParticipationGrantProposal(
            proposal_id=f"grant-proposal-{secrets.token_hex(16)}",
            launch_evidence_id=launch_evidence.evidence_id,
            policy_fingerprint=policy_fingerprint,
            session_id=launch_evidence.session_id,
            episode_id=launch_evidence.episode_id,
            perspective_instance_id=launch_evidence.perspective_instance_id,
            room_id=launch_evidence.room_id,
            policy_id=policy.policy_id,
            policy_issuance_id=policy.issuance_id,
            scopes=requested_scopes,
            binding_digest=digest,
            _marker=_GRANT_PROPOSAL_MARKER,
        )
        self._proposals[proposal.proposal_id] = _ProposalState(
            proposal=proposal,
            fingerprint=_proposal_fingerprint(proposal),
        )
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
        proposal_state = self._proposals[proposal.proposal_id]
        if proposal_state.approved:
            raise RoomParticipationAuthorizationError(
                "grant proposal was already approved"
            )
        self._assert_policy_active(policy)
        if (
            proposal.policy_id != policy.policy_id
            or proposal.policy_issuance_id != policy.issuance_id
        ):
            raise RoomParticipationAuthorizationError(
                "proposal and continuation policy do not match"
            )
        if proposal.policy_fingerprint != _policy_fingerprint(policy):
            raise RoomParticipationAuthorizationError(
                "proposal is bound to another continuation policy payload"
            )
        if proposal.room_id != policy.room_id:
            raise RoomParticipationAuthorizationError(
                "proposal Room does not match continuation policy"
            )
        if not proposal.scopes.issubset(policy.allowed_scopes):
            raise RoomParticipationAuthorizationError(
                "proposal scope exceeds continuation policy"
            )
        proposal_session = self._sessions.get(proposal.session_id)
        if proposal_session is None or not proposal_session.active:
            raise RoomParticipationStaleError(
                "proposal session is no longer active"
            )
        self._revalidate_evidence(
            proposal_session.evidence,
            policy=policy,
        )

        approval = AutomaticContinuationApproval(
            approval_id=f"grant-approval-{secrets.token_hex(16)}",
            proposal_id=proposal.proposal_id,
            policy_id=policy.policy_id,
            policy_issuance_id=policy.issuance_id,
            binding_digest=proposal.binding_digest,
            _marker=_GRANT_APPROVAL_MARKER,
        )
        self._approvals[approval.approval_id] = _ApprovalState(
            approval=approval,
            fingerprint=_approval_fingerprint(approval),
        )
        proposal_state.approved = True
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
        if (
            approval.policy_id != proposal.policy_id
            or approval.policy_issuance_id != proposal.policy_issuance_id
        ):
            raise RoomParticipationAuthorizationError(
                "approval policy does not match proposal"
            )
        if approval.binding_digest != proposal.binding_digest:
            raise RoomParticipationAuthorizationError(
                "approved binding differs from grant proposal"
            )

        self._assert_registered_policy_integrity(
            proposal.policy_issuance_id
        )
        policy = self._policies[proposal.policy_issuance_id]

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
        self._revalidate_evidence(
            evidence_state.evidence,
            policy=policy,
        )

        grant = RoomParticipationGrant(
            grant_id=f"room-grant-{secrets.token_hex(16)}",
            session_id=proposal.session_id,
            episode_id=proposal.episode_id,
            perspective_instance_id=proposal.perspective_instance_id,
            room_id=proposal.room_id,
            policy_id=proposal.policy_id,
            policy_issuance_id=proposal.policy_issuance_id,
            policy_fingerprint=proposal.policy_fingerprint,
            scopes=proposal.scopes,
            launch_evidence_id=proposal.launch_evidence_id,
            proposal_id=proposal.proposal_id,
            approval_id=approval.approval_id,
            binding_digest=proposal.binding_digest,
            _marker=_PARTICIPATION_GRANT_MARKER,
        )
        approval_state = self._approvals[approval.approval_id]
        if approval_state.consumed:
            raise RoomParticipationAuthorizationError(
                "automatic continuation approval was already consumed"
            )
        approval_state.consumed = True
        self._grants[grant.grant_id] = _GrantState(
            grant=grant,
            fingerprint=_grant_fingerprint(grant),
        )
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
            or state.grant is not grant
        ):
            raise RoomParticipationAuthorizationError(
                "Room participation grant was not issued by this authority"
            )
        if state.fingerprint != _grant_fingerprint(grant):
            raise RoomParticipationAuthorizationError(
                "Room participation grant was altered after issuance"
            )
        if not state.active:
            raise RoomParticipationStaleError(
                "Room participation grant is no longer active"
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
            launch_evidence_id=grant.launch_evidence_id,
            policy_fingerprint=grant.policy_fingerprint,
            session_id=grant.session_id,
            episode_id=grant.episode_id,
            perspective_instance_id=grant.perspective_instance_id,
            room_id=grant.room_id,
            policy_id=grant.policy_id,
            policy_issuance_id=grant.policy_issuance_id,
            scopes=grant.scopes,
        ):
            raise RoomParticipationAuthorizationError(
                "Room participation grant binding was altered"
            )

        self._assert_registered_policy_integrity(
            grant.policy_issuance_id
        )
        policy = self._policies[grant.policy_issuance_id]
        if (
            self._policy_fingerprints.get(grant.policy_issuance_id)
            != grant.policy_fingerprint
        ):
            raise RoomParticipationStaleError(
                "grant policy version no longer matches registered policy"
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
        self._revalidate_evidence(
            session.evidence,
            policy=policy,
        )

    @contextmanager
    def _hold_grant_for_operation(
        self,
        *,
        grant: RoomParticipationGrant,
        session_id: str,
        episode_id: str,
        perspective_instance_id: str,
        room_id: str,
        required_scope: RoomParticipationScope,
    ) -> Iterator[None]:
        """Hold exact grant authority across one synchronous local effect.

        The authority lock remains held until the caller's effect has either
        committed or unwound. This prevents process-local suspension or session
        revocation from interleaving after revalidation but before the effect.
        Database writers must establish their own ordering before entering this
        context; Room routing changes remain serialized by the shared SQLite
        write transaction rather than by this process-local lock.
        """

        with self._guard:
            with self._lease._hold_active_for_authority():
                self.require_grant(
                    grant=grant,
                    session_id=session_id,
                    episode_id=episode_id,
                    perspective_instance_id=perspective_instance_id,
                    room_id=room_id,
                    required_scope=required_scope,
                )
                yield

    @_guarded
    def suspend_policy(self, *, policy_id: str) -> None:
        """Operationally stop grants without rewriting inhabitant intent."""

        self._assert_live_host()
        _require_text("policy_id", policy_id)
        matches = [
            issuance_id
            for issuance_id, policy in self._policies.items()
            if policy.policy_id == policy_id
        ]
        if len(matches) != 1:
            raise KeyError(policy_id)
        issuance_id = matches[0]
        self._suspended_policy_issuance_ids.add(issuance_id)
        for state in self._grants.values():
            if state.grant.policy_issuance_id == issuance_id:
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
        _require_trusted_policy(
            policy,
            lease=self._lease,
            store=self._store,
        )
        fingerprint = _policy_fingerprint(policy)
        for existing_issuance_id, existing_policy in self._policies.items():
            if (
                existing_policy.policy_id == policy.policy_id
                and existing_issuance_id != policy.issuance_id
            ):
                raise RoomParticipationAuthorizationError(
                    "policy id is already bound to another trusted issuance"
                )
        existing_fingerprint = self._policy_fingerprints.get(
            policy.issuance_id
        )
        if (
            existing_fingerprint is not None
            and existing_fingerprint != fingerprint
        ):
            raise RoomParticipationAuthorizationError(
                "policy issuance is bound to a different payload"
            )
        if (
            policy.issuance_id
            in self._suspended_policy_issuance_ids
        ):
            raise RoomParticipationStaleError(
                "continuation policy is operationally suspended"
            )
        self._policies[policy.issuance_id] = policy
        self._policy_fingerprints[policy.issuance_id] = fingerprint

    def _assert_policy_active(
        self,
        policy: TrustedRoomContinuationPolicy,
    ) -> None:
        self._register_policy(policy)
        if (
            self._policy_fingerprints.get(policy.issuance_id)
            != _policy_fingerprint(policy)
        ):
            raise RoomParticipationAuthorizationError(
                "continuation policy payload changed"
            )

    def _assert_registered_policy_integrity(
        self,
        policy_issuance_id: str,
    ) -> None:
        policy = self._policies.get(policy_issuance_id)
        expected = self._policy_fingerprints.get(policy_issuance_id)
        if policy is None or expected is None:
            raise RoomParticipationStaleError(
                "continuation policy is unavailable"
            )
        if _policy_fingerprint(policy) != expected:
            raise RoomParticipationAuthorizationError(
                "registered continuation policy was altered"
            )
        if (
            policy_issuance_id
            in self._suspended_policy_issuance_ids
        ):
            raise RoomParticipationStaleError(
                "continuation policy is operationally suspended"
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
        if Path(identity.db_path).resolve() != self._canonical_db_path:
            raise RoomParticipationAuthorizationError(
                "HOME host lease database binding changed"
            )
        if Path(self._store.db_path).resolve() != self._canonical_db_path:
            raise RoomParticipationAuthorizationError(
                "Room authority internal LivingStore left the leased HOME database"
            )

    def _assert_live_runtime_launch(
        self,
        receipt: SupportedRuntimeLaunchReceipt,
    ) -> None:
        self._assert_live_host()
        if (
            not isinstance(receipt, SupportedRuntimeLaunchReceipt)
            or receipt._marker is not _RUNTIME_LAUNCH_RECEIPT_MARKER
        ):
            raise RoomLaunchEvidenceError(
                "runtime launch receipt is forged or untrusted"
            )
        key = (*self._runtime_launch_registry_base(), receipt.receipt_id)
        with _RUNTIME_LAUNCH_REGISTRY_GUARD:
            state = _RUNTIME_LAUNCH_REGISTRY.get(key)
            if (
                state is None
                or state.receipt is not receipt
                or state.fingerprint != _runtime_launch_fingerprint(receipt)
                or state.consumed
            ):
                raise RoomLaunchEvidenceError(
                    "runtime launch receipt is forged, stale, or already consumed"
                )
        if receipt.home_process_instance_id != self._home_process_instance_id:
            raise RoomLaunchEvidenceError(
                "runtime launch receipt belongs to another HOME process"
            )
        if (
            receipt.host_process_instance_id
            != self._lease.identity.process_instance_id
        ):
            raise RoomLaunchEvidenceError(
                "runtime launch receipt belongs to another host lease"
            )
        episode = self._store.get_episode(receipt.episode_id)
        if episode.perspective_instance_id != receipt.perspective_instance_id:
            raise RoomLaunchEvidenceError(
                "runtime launch receipt no longer matches Episode attribution"
            )
        if episode.runtime_instance_id != receipt.runtime_instance_id:
            raise RoomLaunchEvidenceError(
                "runtime launch receipt no longer matches runtime instance"
            )

    def _consume_runtime_launch(
        self,
        receipt: SupportedRuntimeLaunchReceipt,
    ) -> None:
        key = (*self._runtime_launch_registry_base(), receipt.receipt_id)
        with _RUNTIME_LAUNCH_REGISTRY_GUARD:
            state = _RUNTIME_LAUNCH_REGISTRY.get(key)
            if (
                state is None
                or state.receipt is not receipt
                or state.fingerprint != _runtime_launch_fingerprint(receipt)
                or state.consumed
            ):
                raise RoomLaunchEvidenceError(
                    "runtime launch receipt cannot be consumed"
                )
            state.consumed = True

    def _runtime_launch_registry_base(self) -> tuple[str, str, str]:
        return (
            self._home_process_instance_id,
            self._lease.identity.process_instance_id,
            str(Path(self._store.db_path).resolve()),
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
            or stored is None
            or stored.proposal is not proposal
            or stored.fingerprint != _proposal_fingerprint(proposal)
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
            or stored is None
            or stored.approval is not approval
            or stored.fingerprint != _approval_fingerprint(approval)
        ):
            raise RoomParticipationAuthorizationError(
                "grant approval was not issued by this authority"
            )

    def _revalidate_evidence(
        self,
        evidence: TrustedLaunchEvidence,
        *,
        policy: TrustedRoomContinuationPolicy | None = None,
    ) -> None:
        session_state = self._sessions.get(evidence.session_id)
        if (
            session_state is None
            or session_state.evidence is not evidence
            or session_state.fingerprint
            != _launch_evidence_fingerprint(evidence)
        ):
            raise RoomParticipationStaleError(
                "launch evidence was altered or is not active here"
            )
        launch_key = (
            *self._runtime_launch_registry_base(),
            evidence.runtime_launch_receipt_id,
        )
        with _RUNTIME_LAUNCH_REGISTRY_GUARD:
            launch_state = _RUNTIME_LAUNCH_REGISTRY.get(launch_key)
            if (
                launch_state is None
                or not launch_state.consumed
                or launch_state.fingerprint
                != _runtime_launch_fingerprint(launch_state.receipt)
                or launch_state.receipt.session_id != evidence.session_id
                or launch_state.receipt.episode_id != evidence.episode_id
                or launch_state.receipt.perspective_instance_id
                != evidence.perspective_instance_id
                or launch_state.receipt.observed_transfer_mode
                != evidence.transfer_mode
            ):
                raise RoomParticipationStaleError(
                    "host-observed runtime launch no longer matches launch evidence"
                )
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

        snapshot = self._store.read_continuation_path_snapshot(
            previous_episode_id=evidence.previous_episode_id,
            episode_id=evidence.episode_id,
            anchor_episode_id=(
                None
                if policy is None
                else policy.established_episode_id
            ),
        )
        episode = snapshot.episode
        if episode.perspective_instance_id != evidence.perspective_instance_id:
            raise RoomParticipationStaleError(
                "Episode attribution no longer matches launch evidence"
            )
        previous_route = snapshot.previous_route
        current_route = snapshot.current_route
        if (
            previous_route.decision != "attached"
            or previous_route.room_id != evidence.room_id
            or previous_route.active_attachment_event_id
            != evidence.previous_attachment_event_id
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
            for edge in snapshot.edges
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

        topology = snapshot.topology
        if evidence.previous_episode_id in topology.fork_episode_ids:
            raise RoomParticipationStaleError(
                "continuation path became a fork"
            )
        if policy is not None:
            self._assert_policy_lineage(
                policy=policy,
                evidence=evidence,
                snapshot=snapshot,
            )

    def _assert_policy_lineage(
        self,
        *,
        policy: TrustedRoomContinuationPolicy,
        evidence: TrustedLaunchEvidence,
        snapshot,
    ) -> None:
        if policy.room_id != evidence.room_id:
            raise RoomParticipationAuthorizationError(
                "continuation policy belongs to another Room"
            )
        anchor = snapshot.anchor_episode
        anchor_route = snapshot.anchor_route
        if (
            anchor is None
            or anchor.episode_id != policy.established_episode_id
            or anchor_route is None
            or anchor_route.decision != "attached"
            or anchor_route.room_id != policy.room_id
            or anchor_route.active_attachment_event_id
            != policy.established_attachment_event_id
        ):
            raise RoomParticipationStaleError(
                "continuation policy establishment route is no longer exact"
            )

        edge_by_child = {
            edge.next_episode_id: edge
            for edge in snapshot.edges
        }
        route_by_episode = {
            route.episode_id: route
            for route in snapshot.routes
        }

        current = evidence.previous_episode_id
        branch_path: list[str] = []
        inherited_edges: list[ContinuityEdge] = []
        while True:
            branch_path.append(current)
            if current == policy.established_episode_id:
                break
            inherited_edge = edge_by_child.get(current)
            if inherited_edge is None:
                raise RoomParticipationAuthorizationError(
                    "continuation policy was not established on this branch"
                )
            inherited_edges.append(inherited_edge)
            current = inherited_edge.previous_episode_id

        crossed_forks = set(branch_path).intersection(
            snapshot.topology.fork_episode_ids
        )
        if crossed_forks:
            raise RoomParticipationAuthorizationError(
                "continuation policy cannot auto-cross a fork; "
                "the branch must establish a new policy"
            )

        unsupported_edges = [
            edge
            for edge in inherited_edges
            if (
                edge.transfer_mode not in _AUTO_CONTINUATION_TRANSFER_MODES
                or edge.continuity_status is not ContinuityStatus.UNKNOWN
            )
        ]
        if unsupported_edges:
            raise RoomParticipationAuthorizationError(
                "continuation policy cannot auto-cross an explicit-entry barrier"
            )

        for episode_id in branch_path:
            route = route_by_episode.get(episode_id)
            if (
                route is None
                or route.decision != "attached"
                or route.room_id != policy.room_id
            ):
                raise RoomParticipationAuthorizationError(
                    "continuation policy cannot auto-cross a Room route break"
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


def _require_trusted_policy(
    policy: TrustedRoomContinuationPolicy,
    *,
    lease: HomeSingleInstanceLease,
    store: LivingStore,
) -> None:
    if (
        not isinstance(policy, TrustedRoomContinuationPolicy)
        or policy._marker is not _CONTINUATION_POLICY_MARKER
    ):
        raise RoomParticipationAuthorizationError(
            "Room continuation policy is not trusted"
        )
    require_home_process()
    if lease.released:
        raise RoomParticipationStaleError(
            "HOME host lease was released"
        )
    identity = lease.identity
    db_path = str(Path(store.db_path).resolve())
    with _POLICY_ISSUANCE_REGISTRY_GUARD:
        state = _POLICY_ISSUANCE_REGISTRY.get(policy.issuance_id)
        if (
            state is None
            or state.policy is not policy
            or state.fingerprint != _policy_fingerprint(policy)
            or state.home_process_instance_id
            != current_home_process_instance_id()
            or state.host_process_instance_id
            != identity.process_instance_id
            or state.db_path != db_path
        ):
            raise RoomParticipationAuthorizationError(
                "Room continuation policy payload was not issued for this host/store"
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
    if (
        RoomParticipationScope.CHANGE_CURRENT_STANCE in scopes
        and RoomParticipationScope.APPEND_FIRST_PERSON not in scopes
    ):
        raise RoomParticipationAuthorizationError(
            "change_current_stance requires append_first_person authority"
        )


def _validate_grant_binding(
    *,
    launch_evidence_id: str,
    policy_fingerprint: str,
    session_id: str,
    episode_id: str,
    perspective_instance_id: str,
    room_id: str,
    policy_id: str,
    policy_issuance_id: str,
    scopes: frozenset[RoomParticipationScope],
    binding_digest: str,
) -> None:
    for field_name, value in {
        "launch_evidence_id": launch_evidence_id,
        "policy_fingerprint": policy_fingerprint,
        "session_id": session_id,
        "episode_id": episode_id,
        "perspective_instance_id": perspective_instance_id,
        "room_id": room_id,
        "policy_id": policy_id,
        "policy_issuance_id": policy_issuance_id,
        "binding_digest": binding_digest,
    }.items():
        _require_text(field_name, value)
    _validate_scope_set(scopes)
    expected = _grant_binding_digest(
        launch_evidence_id=launch_evidence_id,
        policy_fingerprint=policy_fingerprint,
        session_id=session_id,
        episode_id=episode_id,
        perspective_instance_id=perspective_instance_id,
        room_id=room_id,
        policy_id=policy_id,
        policy_issuance_id=policy_issuance_id,
        scopes=scopes,
    )
    if binding_digest != expected:
        raise RoomParticipationAuthorizationError(
            "Room grant binding digest does not match exact payload"
        )


def _policy_fingerprint(policy: TrustedRoomContinuationPolicy) -> str:
    return _canonical_digest(
        "room-continuation-policy",
        {
            "policy_id": policy.policy_id,
            "issuance_id": policy.issuance_id,
            "room_id": policy.room_id,
            "established_episode_id": policy.established_episode_id,
            "established_attachment_event_id": (
                policy.established_attachment_event_id
            ),
            "allowed_scopes": sorted(
                scope.value for scope in policy.allowed_scopes
            ),
            "source_event_ref": policy.source_event_ref,
        },
    )


def _runtime_launch_fingerprint(
    receipt: SupportedRuntimeLaunchReceipt,
) -> str:
    return _canonical_digest(
        "supported-runtime-launch",
        {
            "receipt_id": receipt.receipt_id,
            "session_id": receipt.session_id,
            "home_process_instance_id": receipt.home_process_instance_id,
            "host_process_instance_id": receipt.host_process_instance_id,
            "episode_id": receipt.episode_id,
            "perspective_instance_id": receipt.perspective_instance_id,
            "runtime_instance_id": receipt.runtime_instance_id,
            "observed_transfer_mode": receipt.observed_transfer_mode.value,
        },
    )


def _launch_evidence_fingerprint(evidence: TrustedLaunchEvidence) -> str:
    return _canonical_digest(
        "trusted-launch-evidence",
        {
            "evidence_id": evidence.evidence_id,
            "runtime_launch_receipt_id": evidence.runtime_launch_receipt_id,
            "session_id": evidence.session_id,
            "home_process_instance_id": evidence.home_process_instance_id,
            "host_process_instance_id": evidence.host_process_instance_id,
            "previous_episode_id": evidence.previous_episode_id,
            "episode_id": evidence.episode_id,
            "perspective_instance_id": evidence.perspective_instance_id,
            "room_id": evidence.room_id,
            "continuity_edge_id": evidence.continuity_edge_id,
            "previous_attachment_event_id": (
                evidence.previous_attachment_event_id
            ),
            "attachment_event_id": evidence.attachment_event_id,
            "transfer_mode": evidence.transfer_mode.value,
            "continuity_status": evidence.continuity_status.value,
        },
    )


def _proposal_fingerprint(
    proposal: RoomParticipationGrantProposal,
) -> str:
    return _canonical_digest(
        "room-grant-proposal",
        {
            "proposal_id": proposal.proposal_id,
            "launch_evidence_id": proposal.launch_evidence_id,
            "policy_fingerprint": proposal.policy_fingerprint,
            "session_id": proposal.session_id,
            "episode_id": proposal.episode_id,
            "perspective_instance_id": proposal.perspective_instance_id,
            "room_id": proposal.room_id,
            "policy_id": proposal.policy_id,
            "policy_issuance_id": proposal.policy_issuance_id,
            "scopes": sorted(scope.value for scope in proposal.scopes),
            "binding_digest": proposal.binding_digest,
        },
    )


def _approval_fingerprint(
    approval: AutomaticContinuationApproval,
) -> str:
    return _canonical_digest(
        "automatic-continuation-approval",
        {
            "approval_id": approval.approval_id,
            "proposal_id": approval.proposal_id,
            "policy_id": approval.policy_id,
            "policy_issuance_id": approval.policy_issuance_id,
            "binding_digest": approval.binding_digest,
        },
    )


def _grant_fingerprint(grant: RoomParticipationGrant) -> str:
    return _canonical_digest(
        "room-participation-grant",
        {
            "grant_id": grant.grant_id,
            "session_id": grant.session_id,
            "episode_id": grant.episode_id,
            "perspective_instance_id": grant.perspective_instance_id,
            "room_id": grant.room_id,
            "policy_id": grant.policy_id,
            "policy_issuance_id": grant.policy_issuance_id,
            "policy_fingerprint": grant.policy_fingerprint,
            "scopes": sorted(scope.value for scope in grant.scopes),
            "launch_evidence_id": grant.launch_evidence_id,
            "proposal_id": grant.proposal_id,
            "approval_id": grant.approval_id,
            "binding_digest": grant.binding_digest,
        },
    )


def _canonical_digest(kind: str, payload: dict[str, object]) -> str:
    raw = json.dumps(
        {"kind": kind, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _grant_binding_digest(
    *,
    launch_evidence_id: str,
    policy_fingerprint: str,
    session_id: str,
    episode_id: str,
    perspective_instance_id: str,
    room_id: str,
    policy_id: str,
    policy_issuance_id: str,
    scopes: frozenset[RoomParticipationScope],
) -> str:
    payload = {
        "launch_evidence_id": launch_evidence_id,
        "policy_fingerprint": policy_fingerprint,
        "session_id": session_id,
        "episode_id": episode_id,
        "perspective_instance_id": perspective_instance_id,
        "room_id": room_id,
        "policy_id": policy_id,
        "policy_issuance_id": policy_issuance_id,
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
