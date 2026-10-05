from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
import secrets
import sqlite3
from threading import Lock
from typing import Callable

from home_memory_core.current_resolver import (
    CurrentResolver,
)
from home_memory_core.current_view import CurrentNamespace
from home_memory_core.living_continuity import (
    LivingContinuityError,
    resolve_room_attachment,
)
from home_memory_core.living_store import (
    LivingStore,
    LivingStoreIntegrityError,
    assert_living_data_integrity,
)
from home_memory_core.process_boundary import (
    current_home_process_instance_id,
)
from home_memory_core.wake_packet import (
    WakeAssemblyReceipt,
    WakePacket,
    _instant as _wake_instant,
    assemble_wake_packet_v0_1,
)


WAKE_ISSUANCE_VERSION = "wake-issuance-v0.1"

_WAKE_ISSUANCE_AUTHORITY_MARKER = object()
_WAKE_ISSUANCE_RECEIPT_MARKER = object()


class WakeIssuanceError(RuntimeError):
    """Base error for runtime-bound Wake issuance."""


class WakeIssuanceAuthorizationError(WakeIssuanceError):
    """A Wake issuance object is not bound to the exact live authority."""


class WakeIssuanceIntegrityError(WakeIssuanceError):
    """Canonical or issued Wake state violates the issuance contract."""


@dataclass(frozen=True)
class WakeIssuanceReceipt:
    """Process-local proof for one exact Packet/assembly-receipt pair."""

    issuance_id: str
    issuance_version: str
    authority_id: str
    home_process_instance_id: str
    canonical_db_binding_digest: str
    wake_id: str
    episode_id: str
    as_of: datetime
    packet_digest: str
    assembly_receipt_digest: str
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _WAKE_ISSUANCE_RECEIPT_MARKER:
            raise WakeIssuanceAuthorizationError(
                "Wake issuance receipt must come from live issuance authority"
            )
        for field_name in (
            "issuance_id",
            "authority_id",
            "home_process_instance_id",
            "wake_id",
            "episode_id",
        ):
            _require_text(field_name, getattr(self, field_name))
        if self.issuance_version != WAKE_ISSUANCE_VERSION:
            raise WakeIssuanceIntegrityError(
                "Wake issuance receipt version is invalid"
            )
        _require_aware("as_of", self.as_of)
        _require_digest(
            "canonical_db_binding_digest",
            self.canonical_db_binding_digest,
        )
        _require_digest("packet_digest", self.packet_digest)
        _require_digest(
            "assembly_receipt_digest",
            self.assembly_receipt_digest,
        )


@dataclass(frozen=True)
class IssuedWakePacket:
    """Exact typed Wake artifact plus live process-local issuance proof."""

    packet: WakePacket
    assembly_receipt: WakeAssemblyReceipt
    issuance_receipt: WakeIssuanceReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.packet, WakePacket):
            raise WakeIssuanceIntegrityError(
                "issued Wake packet must contain WakePacket"
            )
        if not isinstance(self.assembly_receipt, WakeAssemblyReceipt):
            raise WakeIssuanceIntegrityError(
                "issued Wake packet must contain WakeAssemblyReceipt"
            )
        if not isinstance(self.issuance_receipt, WakeIssuanceReceipt):
            raise WakeIssuanceIntegrityError(
                "issued Wake packet must contain WakeIssuanceReceipt"
            )

        receipt = self.issuance_receipt
        if (
            self.packet.wake_id != receipt.wake_id
            or self.packet.episode_id != receipt.episode_id
            or self.assembly_receipt.wake_id != receipt.wake_id
            or self.assembly_receipt.episode_id != receipt.episode_id
        ):
            raise WakeIssuanceIntegrityError(
                "issued Wake identity differs from issuance receipt"
            )
        if (
            _wake_instant(self.packet.as_of)
            != _wake_instant(receipt.as_of)
            or _wake_instant(self.assembly_receipt.as_of)
            != _wake_instant(receipt.as_of)
        ):
            raise WakeIssuanceIntegrityError(
                "issued Wake time differs from issuance receipt"
            )
        if _artifact_digest(self.packet) != receipt.packet_digest:
            raise WakeIssuanceIntegrityError(
                "issued Wake packet differs from receipt digest"
            )
        if (
            _artifact_digest(self.assembly_receipt)
            != receipt.assembly_receipt_digest
        ):
            raise WakeIssuanceIntegrityError(
                "Wake assembly receipt differs from issuance digest"
            )


@dataclass
class _LiveReceiptState:
    receipt: WakeIssuanceReceipt
    fingerprint: str


class WakeIssuanceAuthority:
    """Runtime-bound issuer for one canonical HOME database.

    WakePacket remains typed data with no producer authentication. This
    authority proves only that one exact Packet/assembly-receipt pair was
    produced from one canonical read snapshot by this exact live authority.
    """

    def __init__(
        self,
        *,
        living_store: LivingStore,
        current_resolver: CurrentResolver,
        clock: Callable[[], datetime],
        _marker: object,
    ) -> None:
        if _marker is not _WAKE_ISSUANCE_AUTHORITY_MARKER:
            raise WakeIssuanceAuthorizationError(
                "WakeIssuanceAuthority must be opened through HOME"
            )
        if not isinstance(living_store, LivingStore):
            raise TypeError("living_store must be LivingStore")
        if not isinstance(current_resolver, CurrentResolver):
            raise TypeError("current_resolver must be CurrentResolver")
        if not callable(clock):
            raise TypeError("clock must be callable")

        CurrentResolver._assert_live_binding(current_resolver)
        living_path = Path(living_store.db_path).resolve()
        current_path = Path(
            current_resolver._canonical_db_path
        ).resolve()
        if living_path != current_path:
            raise WakeIssuanceAuthorizationError(
                "Living Store and Current Resolver must use the same canonical HOME database"
            )

        self._bound_living_store = living_store
        # Caller-owned store object is binding evidence only. Operational
        # reads use a fresh canonical-path store so instance monkeypatching or
        # mutable caller configuration cannot become producer authority.
        self._living_store = LivingStore(current_path)
        self._current_resolver = current_resolver
        self._clock = clock
        self._canonical_db_path = current_path
        self._canonical_db_binding_digest = _database_binding_digest(
            current_path
        )
        self._home_process_instance_id = (
            current_home_process_instance_id()
        )
        self._authority_id = (
            f"wake-issuer-{secrets.token_hex(16)}"
        )
        self._receipt_guard = Lock()
        self._receipts: dict[str, _LiveReceiptState] = {}

    @property
    def authority_id(self) -> str:
        return self._authority_id

    def issue(
        self,
        *,
        episode_id: str,
    ) -> IssuedWakePacket:
        """Issue one Wake artifact from one canonical SQLite read snapshot."""

        _require_text("episode_id", episode_id)
        self._assert_live_binding()

        # Capture the operation cut exactly once, before opening/reading the
        # canonical snapshot. Lower layers receive the explicit cut.
        as_of = self._clock()
        if not isinstance(as_of, datetime):
            raise WakeIssuanceIntegrityError(
                "Wake issuance clock must return datetime"
            )
        _require_aware("as_of", as_of)

        connection = CurrentResolver._read_connection(
            self._current_resolver
        )
        try:
            if not connection.in_transaction:
                raise WakeIssuanceIntegrityError(
                    "Wake issuance requires an active SQLite read transaction"
                )
            assert_living_data_integrity(connection)

            episodes = LivingStore._read_all_episodes(
                self._living_store,
                connection,
            )
            episode_by_id = {
                item.episode_id: item
                for item in episodes
            }
            try:
                episode = episode_by_id[episode_id]
            except KeyError as error:
                raise KeyError(episode_id) from error

            continuity_edges = LivingStore._read_all_continuity_edges(
                self._living_store,
                connection,
            )
            route_events = LivingStore._read_room_attachment_events(
                self._living_store,
                connection,
                episode_id=episode_id,
            )
            try:
                route = resolve_room_attachment(
                    episode_id=episode_id,
                    events=route_events,
                )
            except LivingContinuityError as error:
                raise LivingStoreIntegrityError(str(error)) from error

            room_current = None
            if route.decision == "attached":
                if route.room_id is None:
                    raise WakeIssuanceIntegrityError(
                        "attached canonical route lacks room_id"
                    )
                room_current = (
                    CurrentResolver._resolve_owner_in_connection(
                        self._current_resolver,
                        connection=connection,
                        namespace=CurrentNamespace.ROOM,
                        owner_id=route.room_id,
                        as_of=as_of,
                    )
                )

            wake_id = f"wake-{secrets.token_hex(16)}"
            packet, assembly_receipt = assemble_wake_packet_v0_1(
                wake_id=wake_id,
                as_of=as_of,
                episode=episode,
                route=route,
                continuity_edges=continuity_edges,
                room_current=room_current,
            )
        finally:
            connection.close()

        # Recheck all live bindings after the snapshot operation and before
        # minting process-local proof.
        self._assert_live_binding()

        receipt = WakeIssuanceReceipt(
            issuance_id=f"wake-issuance-{secrets.token_hex(16)}",
            issuance_version=WAKE_ISSUANCE_VERSION,
            authority_id=self._authority_id,
            home_process_instance_id=self._home_process_instance_id,
            canonical_db_binding_digest=(
                self._canonical_db_binding_digest
            ),
            wake_id=packet.wake_id,
            episode_id=packet.episode_id,
            as_of=packet.as_of,
            packet_digest=_artifact_digest(packet),
            assembly_receipt_digest=_artifact_digest(
                assembly_receipt
            ),
            _marker=_WAKE_ISSUANCE_RECEIPT_MARKER,
        )
        with self._receipt_guard:
            if receipt.issuance_id in self._receipts:
                raise WakeIssuanceIntegrityError(
                    "Wake issuance id was already registered"
                )
            self._receipts[receipt.issuance_id] = _LiveReceiptState(
                receipt=receipt,
                fingerprint=_issuance_receipt_fingerprint(
                    receipt
                ),
            )

        return IssuedWakePacket(
            packet=packet,
            assembly_receipt=assembly_receipt,
            issuance_receipt=receipt,
        )

    def require_live_issuance(
        self,
        *,
        issued: IssuedWakePacket,
    ) -> WakePacket:
        """Verify exact artifact binding to this exact live issuer."""

        self._assert_live_binding()
        if not isinstance(issued, IssuedWakePacket):
            raise WakeIssuanceAuthorizationError(
                "live Wake verification requires IssuedWakePacket"
            )

        receipt = issued.issuance_receipt
        with self._receipt_guard:
            state = self._receipts.get(
                getattr(receipt, "issuance_id", "")
            )
            live_match = (
                isinstance(receipt, WakeIssuanceReceipt)
                and receipt._marker is _WAKE_ISSUANCE_RECEIPT_MARKER
                and state is not None
                and state.receipt is receipt
                and state.fingerprint
                == _issuance_receipt_fingerprint(receipt)
            )
        if not live_match:
            raise WakeIssuanceAuthorizationError(
                "Wake issuance receipt was not issued by this live authority"
            )

        if (
            receipt.authority_id != self._authority_id
            or receipt.home_process_instance_id
            != self._home_process_instance_id
            or receipt.canonical_db_binding_digest
            != self._canonical_db_binding_digest
        ):
            raise WakeIssuanceAuthorizationError(
                "Wake issuance receipt belongs to another runtime binding"
            )

        # IssuedWakePacket already validates artifact digests at construction;
        # recompute here so verification remains safe even if a future wrapper
        # implementation changes.
        if _artifact_digest(issued.packet) != receipt.packet_digest:
            raise WakeIssuanceIntegrityError(
                "live Wake packet digest no longer matches issuance"
            )
        if (
            _artifact_digest(issued.assembly_receipt)
            != receipt.assembly_receipt_digest
        ):
            raise WakeIssuanceIntegrityError(
                "live Wake assembly digest no longer matches issuance"
            )
        return issued.packet

    def _assert_live_binding(self) -> None:
        current_process = current_home_process_instance_id()
        if current_process != self._home_process_instance_id:
            raise WakeIssuanceAuthorizationError(
                "Wake issuance authority belongs to another HOME process incarnation"
            )
        CurrentResolver._assert_live_binding(
            self._current_resolver
        )
        try:
            living_path = Path(
                self._bound_living_store.db_path
            ).resolve()
            resolver_path = Path(
                self._current_resolver._canonical_db_path
            ).resolve()
        except (OSError, RuntimeError) as error:
            raise WakeIssuanceAuthorizationError(
                "Wake issuance canonical database binding cannot be resolved"
            ) from error
        if (
            living_path != self._canonical_db_path
            or resolver_path != self._canonical_db_path
            or _database_binding_digest(resolver_path)
            != self._canonical_db_binding_digest
        ):
            raise WakeIssuanceAuthorizationError(
                "Wake issuance canonical database binding changed"
            )


def open_wake_issuance_authority(
    *,
    living_store: LivingStore,
    current_resolver: CurrentResolver,
    clock: Callable[[], datetime],
) -> WakeIssuanceAuthority:
    """Open one live process-local Wake issuer.

    Opening a second authority intentionally creates a distinct live issuer.
    Its receipts cannot authorize artifacts issued by the first.
    """

    if not isinstance(living_store, LivingStore):
        raise TypeError("living_store must be LivingStore")
    if not isinstance(current_resolver, CurrentResolver):
        raise TypeError("current_resolver must be CurrentResolver")
    if not callable(clock):
        raise TypeError("clock must be callable")
    CurrentResolver._assert_live_binding(current_resolver)

    living_path = Path(living_store.db_path).resolve()
    current_path = Path(
        current_resolver._canonical_db_path
    ).resolve()
    if living_path != current_path:
        raise WakeIssuanceAuthorizationError(
            "Living Store and Current Resolver must share one canonical database"
        )
    return WakeIssuanceAuthority(
        living_store=living_store,
        current_resolver=current_resolver,
        clock=clock,
        _marker=_WAKE_ISSUANCE_AUTHORITY_MARKER,
    )


def _artifact_digest(value: object) -> str:
    payload = _canonical_value(value)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _canonical_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "__dataclass__": (
                f"{value.__class__.__module__}."
                f"{value.__class__.__qualname__}"
            ),
            "fields": [
                [item.name, _canonical_value(getattr(value, item.name))]
                for item in fields(value)
            ],
        }
    if isinstance(value, Enum):
        return {
            "__enum__": (
                f"{value.__class__.__module__}."
                f"{value.__class__.__qualname__}"
            ),
            "value": _canonical_value(value.value),
        }
    if isinstance(value, datetime):
        _require_aware("digest datetime", value)
        return {
            "__datetime__": value.isoformat(timespec="microseconds"),
        }
    if isinstance(value, timedelta):
        return {
            "__timedelta_microseconds__": (
                (value.days * 86_400 + value.seconds) * 1_000_000
                + value.microseconds
            ),
        }
    if isinstance(value, tuple):
        return {
            "__tuple__": [
                _canonical_value(item)
                for item in value
            ],
        }
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise WakeIssuanceIntegrityError(
        f"unsupported Wake issuance digest value: {type(value).__name__}"
    )


def _issuance_receipt_fingerprint(
    receipt: WakeIssuanceReceipt,
) -> str:
    return _artifact_digest(
        (
            receipt.issuance_id,
            receipt.issuance_version,
            receipt.authority_id,
            receipt.home_process_instance_id,
            receipt.canonical_db_binding_digest,
            receipt.wake_id,
            receipt.episode_id,
            receipt.as_of,
            receipt.packet_digest,
            receipt.assembly_receipt_digest,
        )
    )


def _database_binding_digest(path: Path) -> str:
    canonical = str(path.resolve()).encode("utf-8")
    return sha256(canonical).hexdigest()


def _require_text(field_name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise WakeIssuanceIntegrityError(
            f"{field_name} must be non-empty text"
        )


def _require_digest(field_name: str, value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise WakeIssuanceIntegrityError(
            f"{field_name} must be a lowercase sha256 digest"
        )


def _require_aware(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise WakeIssuanceIntegrityError(
            f"{field_name} must be timezone-aware"
        )