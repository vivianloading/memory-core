from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from threading import Lock
from uuid import uuid4

from home_memory_core.home_state_ordering import (
    HomeStateCut,
    HomeStateOrderingCoordinator,
    HomeStateOrderingIntegrityError,
    home_state_coordinator_for_path,
    require_canonical_home_state_coordinator,
)
from home_memory_core.process_boundary import current_home_process_instance_id
from home_memory_core.wake_issuance import (
    WakeIssuanceAuthority,
)
from home_memory_core.wake_packet import (
    WakeAuthority,
    WakeUseBoundary,
)
from home_memory_core.wake_presentation import (
    RenderedWakePresentation,
    build_wake_presentation_plan,
    render_wake_presentation,
)


WAKE_LOCAL_HANDOFF_VERSION = "wake-local-handoff-v0.1"
WAKE_LOCAL_ENVELOPE_VERSION = "wake-local-envelope-v0.1"
WAKE_LOCAL_ACCEPTANCE_STATUS = "accepted_local"

_WAKE_HANDOFF_ENVELOPE_MARKER = object()
_WAKE_HANDOFF_RECEIPT_MARKER = object()


class WakeLocalHandoffError(RuntimeError):
    """Wake local handoff violated the v0.1 ordering contract."""


class WakeLocalHandoffIntegrityError(WakeLocalHandoffError):
    """A local handoff artifact no longer matches exact accepted state."""


class WakeLocalHandoffAuthorizationError(WakeLocalHandoffError):
    """A process-local handoff witness was not issued by this boundary."""


@dataclass(frozen=True)
class WakeHandoffEnvelope:
    envelope_version: str
    request_id: str
    episode_id: str
    user_input: str
    wake_id: str
    issuance_id: str
    rendered: RenderedWakePresentation
    handoff_nonce: str
    use_boundary: WakeUseBoundary
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _WAKE_HANDOFF_ENVELOPE_MARKER:
            raise WakeLocalHandoffAuthorizationError(
                "Wake handoff envelope must come from the local handoff authority"
            )
        if self.envelope_version != WAKE_LOCAL_ENVELOPE_VERSION:
            raise WakeLocalHandoffIntegrityError(
                "unexpected Wake handoff envelope version"
            )
        for field_name in (
            "request_id",
            "episode_id",
            "user_input",
            "wake_id",
            "issuance_id",
            "handoff_nonce",
        ):
            _text(field_name, getattr(self, field_name))
        if not isinstance(self.rendered, RenderedWakePresentation):
            raise WakeLocalHandoffIntegrityError(
                "Wake handoff envelope requires rendered Presentation"
            )
        if self.rendered.receipt.wake_id != self.wake_id:
            raise WakeLocalHandoffIntegrityError(
                "Wake handoff envelope wake id differs from rendered receipt"
            )
        if self.rendered.receipt.issuance_id != self.issuance_id:
            raise WakeLocalHandoffIntegrityError(
                "Wake handoff envelope issuance id differs from rendered receipt"
            )
        if not isinstance(self.use_boundary, WakeUseBoundary):
            raise WakeLocalHandoffIntegrityError(
                "Wake handoff envelope use boundary is invalid"
            )
        if self.use_boundary != self.rendered.use_boundary:
            raise WakeLocalHandoffIntegrityError(
                "Wake handoff envelope use boundary differs from rendered artifact"
            )


@dataclass(frozen=True)
class WakeHandoffReceipt:
    handoff_version: str
    handoff_id: str
    request_id: str
    episode_id: str
    wake_id: str
    issuance_id: str
    coordinator_id: str
    home_process_instance_id: str
    canonical_db_binding_digest: str
    local_transport_boundary_id: str
    generation: int
    handoff_nonce: str
    envelope_digest: str
    rendered_payload_digest: str
    presentation_plan_digest: str
    acceptance_status: str
    use_boundary: WakeUseBoundary
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _WAKE_HANDOFF_RECEIPT_MARKER:
            raise WakeLocalHandoffAuthorizationError(
                "Wake handoff receipt must come from local transport acceptance"
            )
        if self.handoff_version != WAKE_LOCAL_HANDOFF_VERSION:
            raise WakeLocalHandoffIntegrityError(
                "unexpected Wake handoff receipt version"
            )
        for field_name in (
            "handoff_id",
            "request_id",
            "episode_id",
            "wake_id",
            "issuance_id",
            "coordinator_id",
            "home_process_instance_id",
            "local_transport_boundary_id",
            "handoff_nonce",
        ):
            _text(field_name, getattr(self, field_name))
        _digest(
            "canonical_db_binding_digest",
            self.canonical_db_binding_digest,
        )
        _digest("envelope_digest", self.envelope_digest)
        _digest(
            "rendered_payload_digest",
            self.rendered_payload_digest,
        )
        _digest(
            "presentation_plan_digest",
            self.presentation_plan_digest,
        )
        if (
            not isinstance(self.generation, int)
            or isinstance(self.generation, bool)
            or self.generation < 0
        ):
            raise WakeLocalHandoffIntegrityError(
                "Wake handoff generation must be non-negative integer"
            )
        if self.acceptance_status != WAKE_LOCAL_ACCEPTANCE_STATUS:
            raise WakeLocalHandoffIntegrityError(
                "Wake handoff receipt must record accepted_local"
            )
        if not isinstance(self.use_boundary, WakeUseBoundary):
            raise WakeLocalHandoffIntegrityError(
                "Wake handoff receipt use boundary is invalid"
            )


@dataclass(frozen=True)
class _AcceptedEnvelopeState:
    boundary: "LocalWakeTransportBoundary"
    envelope: WakeHandoffEnvelope
    envelope_digest: str
    receipt: WakeHandoffReceipt
    receipt_digest: str


class LocalWakeTransportBoundary:
    """Short HOME-controlled process-local acceptance point.

    This boundary performs no network I/O, model execution, or caller callback.
    """

    def __init__(
        self,
        *,
        coordinator: HomeStateOrderingCoordinator,
    ) -> None:
        if not isinstance(
            coordinator,
            HomeStateOrderingCoordinator,
        ):
            raise TypeError(
                "coordinator must be HomeStateOrderingCoordinator"
            )
        try:
            require_canonical_home_state_coordinator(
                coordinator
            )
        except HomeStateOrderingIntegrityError as error:
            raise WakeLocalHandoffIntegrityError(
                "local Wake transport boundary requires canonical HOME coordinator"
            ) from error
        self._coordinator = coordinator
        self._origin = self
        self._home_process_instance_id = (
            current_home_process_instance_id()
        )
        self._boundary_id = f"wake-local-transport-{uuid4().hex}"
        self._acceptance_guard = Lock()
        self._used_nonces: set[str] = set()
        self._accepted: dict[str, _AcceptedEnvelopeState] = {}

    @property
    def boundary_id(self) -> str:
        return self._boundary_id

    def require_live_acceptance(
        self,
        *,
        receipt: WakeHandoffReceipt,
    ) -> WakeHandoffEnvelope:
        self._assert_live_process()
        if not isinstance(receipt, WakeHandoffReceipt):
            raise TypeError("receipt must be WakeHandoffReceipt")
        with self._acceptance_guard:
            state = self._accepted.get(receipt.handoff_id)
        if (
            state is None
            or state.boundary is not self
            or state.receipt is not receipt
        ):
            raise WakeLocalHandoffAuthorizationError(
                "Wake handoff receipt is not the exact live local acceptance receipt"
            )
        if (
            receipt.home_process_instance_id
            != self._home_process_instance_id
        ):
            raise WakeLocalHandoffAuthorizationError(
                "Wake handoff receipt belongs to another HOME process incarnation"
            )
        if receipt.local_transport_boundary_id != self._boundary_id:
            raise WakeLocalHandoffAuthorizationError(
                "Wake handoff receipt belongs to another local transport boundary"
            )
        receipt_digest = _semantic_digest(receipt)
        if receipt_digest != state.receipt_digest:
            raise WakeLocalHandoffIntegrityError(
                "accepted Wake handoff receipt changed after local acceptance"
            )

        digest = _semantic_digest(state.envelope)
        if (
            digest != state.envelope_digest
            or digest != receipt.envelope_digest
        ):
            raise WakeLocalHandoffIntegrityError(
                "accepted Wake envelope changed after local acceptance"
            )
        if (
            state.envelope.rendered.receipt.payload_digest
            != receipt.rendered_payload_digest
            or state.envelope.rendered.receipt.plan_digest
            != receipt.presentation_plan_digest
        ):
            raise WakeLocalHandoffIntegrityError(
                "accepted rendered Wake differs from handoff receipt"
            )
        return state.envelope

    def _assert_live_process(self) -> None:
        try:
            require_canonical_home_state_coordinator(
                self._coordinator
            )
        except HomeStateOrderingIntegrityError as error:
            raise WakeLocalHandoffAuthorizationError(
                "local Wake transport boundary lost canonical coordinator binding"
            ) from error
        if getattr(self, "_origin", None) is not self:
            raise WakeLocalHandoffAuthorizationError(
                "local Wake transport boundary is not the originating boundary object"
            )
        if (
            current_home_process_instance_id()
            != self._home_process_instance_id
        ):
            raise WakeLocalHandoffAuthorizationError(
                "local Wake transport boundary belongs to another HOME process incarnation"
            )

    def _accept_exact(
        self,
        *,
        envelope: WakeHandoffEnvelope,
        cut: HomeStateCut,
    ) -> WakeHandoffReceipt:
        self._assert_live_process()
        if not isinstance(envelope, WakeHandoffEnvelope):
            raise TypeError("envelope must be WakeHandoffEnvelope")
        self._coordinator.require_active_cut(cut=cut)

        envelope_digest = _semantic_digest(envelope)
        rendered_receipt = envelope.rendered.receipt

        with self._acceptance_guard:
            if envelope.handoff_nonce in self._used_nonces:
                raise WakeLocalHandoffAuthorizationError(
                    "Wake handoff envelope nonce was already accepted"
                )

            receipt = WakeHandoffReceipt(
                handoff_version=WAKE_LOCAL_HANDOFF_VERSION,
                handoff_id=f"wake-handoff-{uuid4().hex}",
                request_id=envelope.request_id,
                episode_id=envelope.episode_id,
                wake_id=envelope.wake_id,
                issuance_id=envelope.issuance_id,
                coordinator_id=cut.coordinator_id,
                home_process_instance_id=(
                    cut.home_process_instance_id
                ),
                canonical_db_binding_digest=(
                    cut.canonical_db_binding_digest
                ),
                local_transport_boundary_id=self._boundary_id,
                generation=cut.generation,
                handoff_nonce=envelope.handoff_nonce,
                envelope_digest=envelope_digest,
                rendered_payload_digest=(
                    rendered_receipt.payload_digest
                ),
                presentation_plan_digest=(
                    rendered_receipt.plan_digest
                ),
                acceptance_status=WAKE_LOCAL_ACCEPTANCE_STATUS,
                use_boundary=envelope.use_boundary,
                _marker=_WAKE_HANDOFF_RECEIPT_MARKER,
            )
            self._used_nonces.add(envelope.handoff_nonce)
            self._accepted[receipt.handoff_id] = _AcceptedEnvelopeState(
                boundary=self,
                envelope=envelope,
                envelope_digest=envelope_digest,
                receipt=receipt,
                receipt_digest=_semantic_digest(receipt),
            )

        self._coordinator.require_active_cut(cut=cut)
        return receipt


class WakeLocalHandoffAuthority:
    """Fresh Wake orchestration through one stable local HOME state cut."""

    def __init__(
        self,
        *,
        wake_issuance_authority: WakeIssuanceAuthority,
        coordinator: HomeStateOrderingCoordinator,
        local_transport_boundary: LocalWakeTransportBoundary,
    ) -> None:
        if not isinstance(
            wake_issuance_authority,
            WakeIssuanceAuthority,
        ):
            raise TypeError(
                "wake_issuance_authority must be WakeIssuanceAuthority"
            )
        if not isinstance(
            coordinator,
            HomeStateOrderingCoordinator,
        ):
            raise TypeError(
                "coordinator must be HomeStateOrderingCoordinator"
            )
        if not isinstance(
            local_transport_boundary,
            LocalWakeTransportBoundary,
        ):
            raise TypeError(
                "local_transport_boundary must be LocalWakeTransportBoundary"
            )
        try:
            require_canonical_home_state_coordinator(
                coordinator
            )
        except HomeStateOrderingIntegrityError as error:
            raise WakeLocalHandoffIntegrityError(
                "Wake handoff authority requires canonical HOME coordinator"
            ) from error
        if local_transport_boundary._coordinator is not coordinator:
            raise WakeLocalHandoffIntegrityError(
                "local transport boundary uses another HOME coordinator"
            )
        if (
            wake_issuance_authority._canonical_db_binding_digest
            != coordinator.canonical_db_binding_digest
        ):
            raise WakeLocalHandoffIntegrityError(
                "Wake issuer and HOME coordinator database bindings differ"
            )
        self._wake_issuance_authority = wake_issuance_authority
        self._coordinator = coordinator
        self._local_transport_boundary = (
            local_transport_boundary
        )

    @property
    def local_transport_boundary(
        self,
    ) -> LocalWakeTransportBoundary:
        return self._local_transport_boundary

    def handoff(
        self,
        *,
        request_id: str,
        episode_id: str,
        user_input: str,
    ) -> WakeHandoffReceipt:
        try:
            require_canonical_home_state_coordinator(
                self._coordinator
            )
        except HomeStateOrderingIntegrityError as error:
            raise WakeLocalHandoffAuthorizationError(
                "Wake handoff authority lost canonical coordinator binding"
            ) from error

        for field_name, value in {
            "request_id": request_id,
            "episode_id": episode_id,
            "user_input": user_input,
        }.items():
            _text(field_name, value)

        cut = self._coordinator.acquire_cut()
        try:
            issued = WakeIssuanceAuthority.issue(
                self._wake_issuance_authority,
                episode_id=episode_id,
            )
            plan = build_wake_presentation_plan(
                authority=self._wake_issuance_authority,
                issued=issued,
            )
            rendered = render_wake_presentation(
                authority=self._wake_issuance_authority,
                issued=issued,
                plan=plan,
            )
            envelope = WakeHandoffEnvelope(
                envelope_version=WAKE_LOCAL_ENVELOPE_VERSION,
                request_id=request_id,
                episode_id=episode_id,
                user_input=user_input,
                wake_id=issued.packet.wake_id,
                issuance_id=(
                    issued.issuance_receipt.issuance_id
                ),
                rendered=rendered,
                handoff_nonce=f"wake-handoff-nonce-{uuid4().hex}",
                use_boundary=rendered.use_boundary,
                _marker=_WAKE_HANDOFF_ENVELOPE_MARKER,
            )
            self._coordinator.require_active_cut(cut=cut)
            receipt = self._local_transport_boundary._accept_exact(
                envelope=envelope,
                cut=cut,
            )
            if receipt.generation != cut.generation:
                raise WakeLocalHandoffIntegrityError(
                    "Wake handoff receipt generation differs from active cut"
                )
            return receipt
        finally:
            self._coordinator.release_cut(cut=cut)


def open_wake_local_handoff_authority(
    *,
    wake_issuance_authority: WakeIssuanceAuthority,
) -> WakeLocalHandoffAuthority:
    if not isinstance(
        wake_issuance_authority,
        WakeIssuanceAuthority,
    ):
        raise TypeError(
            "wake_issuance_authority must be WakeIssuanceAuthority"
        )
    coordinator = home_state_coordinator_for_path(
        wake_issuance_authority._canonical_db_path
    )
    boundary = LocalWakeTransportBoundary(
        coordinator=coordinator
    )
    return WakeLocalHandoffAuthority(
        wake_issuance_authority=wake_issuance_authority,
        coordinator=coordinator,
        local_transport_boundary=boundary,
    )


def _semantic_digest(value: object) -> str:
    canonical = _canonical_semantic_value(value)
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _canonical_semantic_value(value: object) -> object:
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
        if value.tzinfo is None or value.utcoffset() is None:
            raise WakeLocalHandoffIntegrityError(
                "handoff semantic datetime must be timezone-aware"
            )
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
    raise WakeLocalHandoffIntegrityError(
        "unsupported Wake handoff semantic value: "
        f"{type(value).__name__}"
    )


def _text(field_name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise WakeLocalHandoffIntegrityError(
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
        raise WakeLocalHandoffIntegrityError(
            f"{field_name} must be lowercase sha256"
        )
