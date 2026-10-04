from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
import json
from pathlib import Path
import secrets
import sqlite3
from threading import Lock

from home_memory_core.current_store import (
    CurrentSourceBinding,
    CurrentStore,
    CurrentStoreIntegrityError,
    assert_current_data_integrity,
    assert_current_schema,
)
from home_memory_core.current_store_schema import (
    CURRENT_END_EVIDENCE_TABLE,
    CURRENT_END_TABLE,
    CURRENT_STATE_EVIDENCE_TABLE,
    CURRENT_STATE_TABLE,
)
from home_memory_core.current_view import (
    CurrentNamespace,
    CurrentStateEndEvent,
    CurrentStateRecord,
)
from home_memory_core.living_authority import (
    RoomParticipationAuthority,
    RoomParticipationGrant,
    RoomParticipationScope,
)
from home_memory_core.store_domain import assert_synthetic_store_domain


CURRENT_ADMISSION_SCHEMA_VERSION = "current-admission-v0.1"
CURRENT_ADMISSION_SCHEMA_MARKER_TABLE = "current_admission_schema_marker"
CURRENT_STATE_ADMISSION_TABLE = "current_state_admissions"
CURRENT_END_ADMISSION_TABLE = "current_end_admissions"

CURRENT_ADMISSION_TABLES = frozenset(
    {
        CURRENT_ADMISSION_SCHEMA_MARKER_TABLE,
        CURRENT_STATE_ADMISSION_TABLE,
        CURRENT_END_ADMISSION_TABLE,
    }
)

CURRENT_ADMISSION_TRIGGERS = frozenset(
    {
        "current_admission_schema_marker_no_update",
        "current_admission_schema_marker_no_delete",
        "current_state_admission_no_replace",
        "current_state_admission_no_update",
        "current_state_admission_no_delete",
        "current_state_admission_unique_id",
        "current_state_admission_effect_binding",
        "current_state_admission_supersession_binding",
        "current_end_admission_no_replace",
        "current_end_admission_no_update",
        "current_end_admission_no_delete",
        "current_end_admission_unique_id",
        "current_end_admission_effect_binding",
        "current_end_admission_target_binding",
    }
)

_ADMISSION_AUTHORITY_MARKER = object()
_ADMISSION_RECEIPT_MARKER = object()
_ADMISSION_AUTHORITY_REGISTRY_GUARD = Lock()
_ADMISSION_AUTHORITY_REGISTRY: dict[
    tuple[int, str],
    "CurrentAdmissionAuthority",
] = {}


class CurrentAdmissionError(RuntimeError):
    """Base error for Current authority-aware admission."""


class CurrentAdmissionIntegrityError(CurrentAdmissionError):
    """Admission schema or persisted audit provenance is inconsistent."""


class CurrentAdmissionAuthorizationError(PermissionError, CurrentAdmissionError):
    """A Current effect lacks the exact live authority required for admission."""


class CurrentAdmissionConflictError(CurrentAdmissionError):
    """An admitted effect conflicts with existing immutable history."""


class CurrentAdmissionEffectKind(StrEnum):
    STATE = "state"
    END_EVENT = "end_event"


@dataclass(frozen=True)
class CurrentAdmissionAuditRecord:
    admission_id: str
    effect_kind: CurrentAdmissionEffectKind
    effect_id: str
    effect_digest: str
    admission_binding_digest: str
    grant_id: str
    grant_binding_digest: str
    policy_fingerprint: str
    launch_evidence_id: str
    policy_id: str
    policy_issuance_id: str
    proposal_id: str
    approval_id: str
    session_id: str
    episode_id: str
    perspective_instance_id: str
    room_id: str
    room_attachment_event_id: str
    required_scope: RoomParticipationScope
    predecessor_admission_id: str | None


@dataclass(frozen=True)
class CurrentAdmissionReceipt:
    """Process-local proof that one exact Current effect crossed live authority."""

    admission_id: str
    effect_kind: CurrentAdmissionEffectKind
    effect_id: str
    effect_digest: str
    admission_binding_digest: str
    grant_id: str
    grant_binding_digest: str
    policy_fingerprint: str
    launch_evidence_id: str
    policy_id: str
    policy_issuance_id: str
    proposal_id: str
    approval_id: str
    session_id: str
    episode_id: str
    perspective_instance_id: str
    room_id: str
    room_attachment_event_id: str
    required_scope: RoomParticipationScope
    predecessor_admission_id: str | None
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _ADMISSION_RECEIPT_MARKER:
            raise CurrentAdmissionAuthorizationError(
                "Current admission receipt must come from live admission authority"
            )
        _validate_audit_record(_receipt_as_audit(self))


@dataclass
class _ReceiptState:
    receipt: CurrentAdmissionReceipt
    fingerprint: str


class CurrentAdmissionStore:
    """Durable audit ledger for authority-aware Current admission.

    Persisted rows are audit provenance, not authentication credentials. A live
    CurrentAdmissionReceipt is process-local and must come from the admission
    authority that performed the combined write.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        if not self.db_path.exists():
            raise CurrentAdmissionIntegrityError(
                "Current admission requires an initialized synthetic HOME store"
            )
        connection = self._connect()
        try:
            assert_synthetic_store_domain(connection)
            assert_current_schema(connection)
            assert_current_data_integrity(connection)
            existing = self._existing_tables(connection)
            if existing:
                if existing != CURRENT_ADMISSION_TABLES:
                    raise CurrentAdmissionIntegrityError(
                        "partial Current admission schema exists"
                    )
                assert_current_admission_schema(connection)
                assert_current_admission_data_integrity(connection)
                return
            connection.executescript(current_admission_schema_script())
            assert_synthetic_store_domain(connection)
            assert_current_schema(connection)
            assert_current_data_integrity(connection)
            assert_current_admission_schema(connection)
            assert_current_admission_data_integrity(connection)
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def list_for_audit(self) -> tuple[CurrentAdmissionAuditRecord, ...]:
        connection = self._connect()
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            assert_synthetic_store_domain(connection)
            assert_current_schema(connection)
            assert_current_data_integrity(connection)
            assert_current_admission_schema(connection)
            assert_current_admission_data_integrity(connection)
            records = [
                _state_admission_from_row(row)
                for row in connection.execute(
                    f"SELECT * FROM {CURRENT_STATE_ADMISSION_TABLE} ORDER BY state_id"
                ).fetchall()
            ]
            records.extend(
                _end_admission_from_row(row)
                for row in connection.execute(
                    f"SELECT * FROM {CURRENT_END_ADMISSION_TABLE} ORDER BY end_event_id"
                ).fetchall()
            )
            return tuple(records)
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _existing_tables(self, connection: sqlite3.Connection) -> frozenset[str]:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        return frozenset(names.intersection(CURRENT_ADMISSION_TABLES))


class CurrentAdmissionAuthority:
    """Synthetic/local authority for atomic Room Current admission.

    This layer deliberately has no Shared admission path. It holds one exact
    RoomParticipationGrant across the Current write and admission-audit commit.
    """

    def __init__(
        self,
        *,
        current_store: CurrentStore,
        admission_store: CurrentAdmissionStore,
        room_authority: RoomParticipationAuthority,
        _marker: object,
    ) -> None:
        if _marker is not _ADMISSION_AUTHORITY_MARKER:
            raise CurrentAdmissionAuthorizationError(
                "CurrentAdmissionAuthority must be opened by HOME"
            )
        if not isinstance(current_store, CurrentStore):
            raise TypeError("current_store must be CurrentStore")
        if not isinstance(admission_store, CurrentAdmissionStore):
            raise TypeError("admission_store must be CurrentAdmissionStore")
        if not isinstance(room_authority, RoomParticipationAuthority):
            raise TypeError("room_authority must be RoomParticipationAuthority")
        current_path = Path(current_store.db_path).resolve()
        if current_path != Path(admission_store.db_path).resolve():
            raise CurrentAdmissionAuthorizationError(
                "Current and admission stores must use the same database"
            )
        room_path = Path(room_authority._store.db_path).resolve()
        if room_path != current_path:
            raise CurrentAdmissionAuthorizationError(
                "Room authority belongs to another HOME database"
            )
        room_authority._assert_live_host()
        self._current_store = current_store
        self._admission_store = admission_store
        self._room_authority = room_authority
        self._receipts: dict[str, _ReceiptState] = {}

    def admit_room_state(
        self,
        *,
        record: CurrentStateRecord,
        source_bindings: tuple[CurrentSourceBinding, ...],
        grant: RoomParticipationGrant,
        supersedes_receipt: CurrentAdmissionReceipt | None = None,
    ) -> CurrentAdmissionReceipt:
        if not isinstance(record, CurrentStateRecord):
            raise TypeError("record must be CurrentStateRecord")
        if record.namespace is not CurrentNamespace.ROOM:
            raise CurrentAdmissionAuthorizationError(
                "Slice 2 v0.1 admits Room Current only; Shared admission is closed"
            )
        assert record.episode_id is not None
        assert record.perspective_instance_id is not None

        connection = self._current_store._write_connection()
        try:
            assert_current_admission_schema(connection)
            assert_current_admission_data_integrity(connection)
            predecessor_admission_id = self._require_supersession_receipt(
                connection=connection,
                record=record,
                receipt=supersedes_receipt,
            )
            with self._room_authority.hold_grant_for_operation(
                grant=grant,
                session_id=grant.session_id,
                episode_id=record.episode_id,
                perspective_instance_id=record.perspective_instance_id,
                room_id=record.owner_id,
                required_scope=RoomParticipationScope.CHANGE_CURRENT_STANCE,
            ):
                room_attachment_event_id = (
                    self._current_store._append_state_in_transaction(
                        connection=connection,
                        record=record,
                        source_bindings=source_bindings,
                    )
                )
                if room_attachment_event_id is None:
                    raise CurrentAdmissionIntegrityError(
                        "Room Current admission requires exact attachment provenance"
                    )
                receipt = self._insert_state_admission(
                    connection=connection,
                    record=record,
                    grant=grant,
                    room_attachment_event_id=room_attachment_event_id,
                    predecessor_admission_id=predecessor_admission_id,
                )
                assert_current_admission_data_integrity(connection)
                connection.commit()
                self._register_receipt(receipt)
                return receipt
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise CurrentAdmissionConflictError(
                f"Current state admission conflicts with persisted history: {record.state_id}"
            ) from error
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def admit_room_end_event(
        self,
        *,
        event: CurrentStateEndEvent,
        source_bindings: tuple[CurrentSourceBinding, ...],
        grant: RoomParticipationGrant,
        target_state_receipt: CurrentAdmissionReceipt,
    ) -> CurrentAdmissionReceipt:
        if not isinstance(event, CurrentStateEndEvent):
            raise TypeError("event must be CurrentStateEndEvent")
        if event.episode_id is None or event.perspective_instance_id is None:
            raise CurrentAdmissionAuthorizationError(
                "Room Current end-event admission requires Episode/Perspective provenance"
            )

        connection = self._current_store._write_connection()
        try:
            assert_current_admission_schema(connection)
            assert_current_admission_data_integrity(connection)
            target_receipt = self._require_live_receipt(
                connection=connection,
                receipt=target_state_receipt,
                effect_kind=CurrentAdmissionEffectKind.STATE,
                effect_id=event.state_id,
            )
            target = connection.execute(
                f"SELECT namespace,owner_id FROM {CURRENT_STATE_TABLE} WHERE state_id=?",
                (event.state_id,),
            ).fetchone()
            if target is None:
                raise CurrentAdmissionIntegrityError(
                    "Current end-event target disappeared before admission"
                )
            namespace = CurrentNamespace(target["namespace"])
            if namespace is not CurrentNamespace.ROOM:
                raise CurrentAdmissionAuthorizationError(
                    "Slice 2 v0.1 admits Room Current only; Shared admission is closed"
                )
            room_id = target["owner_id"]
            with self._room_authority.hold_grant_for_operation(
                grant=grant,
                session_id=grant.session_id,
                episode_id=event.episode_id,
                perspective_instance_id=event.perspective_instance_id,
                room_id=room_id,
                required_scope=RoomParticipationScope.CHANGE_CURRENT_STANCE,
            ):
                room_attachment_event_id, written_namespace, written_owner = (
                    self._current_store._append_end_event_in_transaction(
                        connection=connection,
                        event=event,
                        source_bindings=source_bindings,
                    )
                )
                if (
                    written_namespace is not CurrentNamespace.ROOM
                    or written_owner != room_id
                    or room_attachment_event_id is None
                ):
                    raise CurrentAdmissionIntegrityError(
                        "Current end-event target changed during admission"
                    )
                receipt = self._insert_end_admission(
                    connection=connection,
                    event=event,
                    grant=grant,
                    room_id=room_id,
                    room_attachment_event_id=room_attachment_event_id,
                    target_state_admission_id=target_receipt.admission_id,
                )
                assert_current_admission_data_integrity(connection)
                connection.commit()
                self._register_receipt(receipt)
                return receipt
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise CurrentAdmissionConflictError(
                f"Current end-event admission conflicts with persisted history: {event.end_event_id}"
            ) from error
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def require_live_receipt(
        self,
        *,
        receipt: CurrentAdmissionReceipt,
        effect_kind: CurrentAdmissionEffectKind,
        effect_id: str,
    ) -> None:
        connection = self._admission_store._connect()
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            assert_current_admission_schema(connection)
            assert_current_admission_data_integrity(connection)
            self._require_live_receipt(
                connection=connection,
                receipt=receipt,
                effect_kind=effect_kind,
                effect_id=effect_id,
            )
        finally:
            connection.close()

    def _require_supersession_receipt(
        self,
        *,
        connection: sqlite3.Connection,
        record: CurrentStateRecord,
        receipt: CurrentAdmissionReceipt | None,
    ) -> str | None:
        parent_id = record.supersedes_state_id
        if parent_id is None:
            if receipt is not None:
                raise CurrentAdmissionAuthorizationError(
                    "root Current state cannot carry a predecessor admission receipt"
                )
            return None
        if receipt is None:
            raise CurrentAdmissionAuthorizationError(
                "admitted supersession requires the live receipt for its parent state"
            )
        parent = self._require_live_receipt(
            connection=connection,
            receipt=receipt,
            effect_kind=CurrentAdmissionEffectKind.STATE,
            effect_id=parent_id,
        )
        return parent.admission_id

    def _require_live_receipt(
        self,
        *,
        connection: sqlite3.Connection,
        receipt: CurrentAdmissionReceipt,
        effect_kind: CurrentAdmissionEffectKind,
        effect_id: str,
    ) -> CurrentAdmissionReceipt:
        if not isinstance(effect_kind, CurrentAdmissionEffectKind):
            raise CurrentAdmissionAuthorizationError(
                "effect_kind must use CurrentAdmissionEffectKind"
            )
        state = self._receipts.get(getattr(receipt, "admission_id", ""))
        if (
            not isinstance(receipt, CurrentAdmissionReceipt)
            or receipt._marker is not _ADMISSION_RECEIPT_MARKER
            or state is None
            or state.receipt is not receipt
            or state.fingerprint != _receipt_fingerprint(receipt)
        ):
            raise CurrentAdmissionAuthorizationError(
                "Current admission receipt was not issued by this live authority"
            )
        if receipt.effect_kind is not effect_kind or receipt.effect_id != effect_id:
            raise CurrentAdmissionAuthorizationError(
                "Current admission receipt belongs to another effect"
            )
        table, id_column = _admission_table_for_kind(effect_kind)
        row = connection.execute(
            f"SELECT * FROM {table} WHERE {id_column}=?",
            (effect_id,),
        ).fetchone()
        if row is None:
            raise CurrentAdmissionIntegrityError(
                "live Current admission receipt has no durable audit record"
            )
        audit = (
            _state_admission_from_row(row)
            if effect_kind is CurrentAdmissionEffectKind.STATE
            else _end_admission_from_row(row)
        )
        if (
            audit.admission_id != receipt.admission_id
            or audit.effect_digest != receipt.effect_digest
            or audit.admission_binding_digest != receipt.admission_binding_digest
        ):
            raise CurrentAdmissionIntegrityError(
                "live Current admission receipt differs from durable audit record"
            )
        return receipt

    def _insert_state_admission(
        self,
        *,
        connection: sqlite3.Connection,
        record: CurrentStateRecord,
        grant: RoomParticipationGrant,
        room_attachment_event_id: str,
        predecessor_admission_id: str | None,
    ) -> CurrentAdmissionReceipt:
        effect_digest = _state_effect_digest(connection, record.state_id)
        admission_id = f"current-admission-{secrets.token_hex(16)}"
        values = _grant_provenance(
            grant=grant,
            room_attachment_event_id=room_attachment_event_id,
        )
        binding_digest = _admission_binding_digest(
            admission_id=admission_id,
            effect_kind=CurrentAdmissionEffectKind.STATE,
            effect_id=record.state_id,
            effect_digest=effect_digest,
            predecessor_admission_id=predecessor_admission_id,
            **values,
        )
        connection.execute(
            f"""INSERT INTO {CURRENT_STATE_ADMISSION_TABLE} (
                state_id,admission_id,effect_digest,admission_binding_digest,
                grant_id,grant_binding_digest,policy_fingerprint,
                launch_evidence_id,policy_id,policy_issuance_id,
                proposal_id,approval_id,session_id,episode_id,
                perspective_instance_id,room_id,room_attachment_event_id,
                required_scope,predecessor_admission_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record.state_id,
                admission_id,
                effect_digest,
                binding_digest,
                values["grant_id"],
                values["grant_binding_digest"],
                values["policy_fingerprint"],
                values["launch_evidence_id"],
                values["policy_id"],
                values["policy_issuance_id"],
                values["proposal_id"],
                values["approval_id"],
                values["session_id"],
                values["episode_id"],
                values["perspective_instance_id"],
                values["room_id"],
                values["room_attachment_event_id"],
                values["required_scope"].value,
                predecessor_admission_id,
            ),
        )
        return CurrentAdmissionReceipt(
            admission_id=admission_id,
            effect_kind=CurrentAdmissionEffectKind.STATE,
            effect_id=record.state_id,
            effect_digest=effect_digest,
            admission_binding_digest=binding_digest,
            predecessor_admission_id=predecessor_admission_id,
            _marker=_ADMISSION_RECEIPT_MARKER,
            **values,
        )

    def _insert_end_admission(
        self,
        *,
        connection: sqlite3.Connection,
        event: CurrentStateEndEvent,
        grant: RoomParticipationGrant,
        room_id: str,
        room_attachment_event_id: str,
        target_state_admission_id: str,
    ) -> CurrentAdmissionReceipt:
        effect_digest = _end_effect_digest(connection, event.end_event_id)
        admission_id = f"current-admission-{secrets.token_hex(16)}"
        values = _grant_provenance(
            grant=grant,
            room_attachment_event_id=room_attachment_event_id,
            room_id=room_id,
        )
        binding_digest = _admission_binding_digest(
            admission_id=admission_id,
            effect_kind=CurrentAdmissionEffectKind.END_EVENT,
            effect_id=event.end_event_id,
            effect_digest=effect_digest,
            predecessor_admission_id=target_state_admission_id,
            **values,
        )
        connection.execute(
            f"""INSERT INTO {CURRENT_END_ADMISSION_TABLE} (
                end_event_id,admission_id,effect_digest,admission_binding_digest,
                grant_id,grant_binding_digest,policy_fingerprint,
                launch_evidence_id,policy_id,policy_issuance_id,
                proposal_id,approval_id,session_id,episode_id,
                perspective_instance_id,room_id,room_attachment_event_id,
                required_scope,target_state_admission_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                event.end_event_id,
                admission_id,
                effect_digest,
                binding_digest,
                values["grant_id"],
                values["grant_binding_digest"],
                values["policy_fingerprint"],
                values["launch_evidence_id"],
                values["policy_id"],
                values["policy_issuance_id"],
                values["proposal_id"],
                values["approval_id"],
                values["session_id"],
                values["episode_id"],
                values["perspective_instance_id"],
                values["room_id"],
                values["room_attachment_event_id"],
                values["required_scope"].value,
                target_state_admission_id,
            ),
        )
        return CurrentAdmissionReceipt(
            admission_id=admission_id,
            effect_kind=CurrentAdmissionEffectKind.END_EVENT,
            effect_id=event.end_event_id,
            effect_digest=effect_digest,
            admission_binding_digest=binding_digest,
            predecessor_admission_id=target_state_admission_id,
            _marker=_ADMISSION_RECEIPT_MARKER,
            **values,
        )

    def _register_receipt(self, receipt: CurrentAdmissionReceipt) -> None:
        if receipt.admission_id in self._receipts:
            raise CurrentAdmissionIntegrityError(
                "Current admission id was already issued in this process"
            )
        self._receipts[receipt.admission_id] = _ReceiptState(
            receipt=receipt,
            fingerprint=_receipt_fingerprint(receipt),
        )


def open_current_admission_authority(
    *,
    current_store: CurrentStore,
    admission_store: CurrentAdmissionStore,
    room_authority: RoomParticipationAuthority,
) -> CurrentAdmissionAuthority:
    if not isinstance(current_store, CurrentStore):
        raise TypeError("current_store must be CurrentStore")
    if not isinstance(admission_store, CurrentAdmissionStore):
        raise TypeError("admission_store must be CurrentAdmissionStore")
    if not isinstance(room_authority, RoomParticipationAuthority):
        raise TypeError("room_authority must be RoomParticipationAuthority")
    admission_store.initialize()
    current_path = str(Path(current_store.db_path).resolve())
    if str(Path(admission_store.db_path).resolve()) != current_path:
        raise CurrentAdmissionAuthorizationError(
            "Current and admission stores must use the same database"
        )
    if str(Path(room_authority._store.db_path).resolve()) != current_path:
        raise CurrentAdmissionAuthorizationError(
            "Room authority belongs to another HOME database"
        )
    room_authority._assert_live_host()
    key = (id(room_authority), current_path)
    with _ADMISSION_AUTHORITY_REGISTRY_GUARD:
        authority = _ADMISSION_AUTHORITY_REGISTRY.get(key)
        if authority is None:
            authority = CurrentAdmissionAuthority(
                current_store=current_store,
                admission_store=admission_store,
                room_authority=room_authority,
                _marker=_ADMISSION_AUTHORITY_MARKER,
            )
            _ADMISSION_AUTHORITY_REGISTRY[key] = authority
        return authority


def current_admission_schema_script() -> str:
    return f"""
    BEGIN IMMEDIATE;

    CREATE TABLE {CURRENT_ADMISSION_SCHEMA_MARKER_TABLE} (
        marker_key TEXT PRIMARY KEY
          CHECK(marker_key='current_admission_schema'),
        schema_version TEXT NOT NULL
          CHECK(schema_version='{CURRENT_ADMISSION_SCHEMA_VERSION}')
    ) WITHOUT ROWID;

    INSERT INTO {CURRENT_ADMISSION_SCHEMA_MARKER_TABLE} (
        marker_key,schema_version
    ) VALUES (
        'current_admission_schema','{CURRENT_ADMISSION_SCHEMA_VERSION}'
    );

    CREATE TABLE {CURRENT_STATE_ADMISSION_TABLE} (
        state_id TEXT PRIMARY KEY,
        admission_id TEXT NOT NULL CHECK(length(trim(admission_id))>0),
        effect_digest TEXT NOT NULL CHECK(length(effect_digest)=64),
        admission_binding_digest TEXT NOT NULL
          CHECK(length(admission_binding_digest)=64),
        grant_id TEXT NOT NULL CHECK(length(trim(grant_id))>0),
        grant_binding_digest TEXT NOT NULL
          CHECK(length(grant_binding_digest)>0),
        policy_fingerprint TEXT NOT NULL
          CHECK(length(policy_fingerprint)>0),
        launch_evidence_id TEXT NOT NULL
          CHECK(length(trim(launch_evidence_id))>0),
        policy_id TEXT NOT NULL CHECK(length(trim(policy_id))>0),
        policy_issuance_id TEXT NOT NULL
          CHECK(length(trim(policy_issuance_id))>0),
        proposal_id TEXT NOT NULL CHECK(length(trim(proposal_id))>0),
        approval_id TEXT NOT NULL CHECK(length(trim(approval_id))>0),
        session_id TEXT NOT NULL CHECK(length(trim(session_id))>0),
        episode_id TEXT NOT NULL CHECK(length(trim(episode_id))>0),
        perspective_instance_id TEXT NOT NULL
          CHECK(length(trim(perspective_instance_id))>0),
        room_id TEXT NOT NULL CHECK(length(trim(room_id))>0),
        room_attachment_event_id TEXT NOT NULL
          CHECK(length(trim(room_attachment_event_id))>0),
        required_scope TEXT NOT NULL
          CHECK(required_scope='room.change_current_stance'),
        predecessor_admission_id TEXT,
        FOREIGN KEY(state_id) REFERENCES {CURRENT_STATE_TABLE}(state_id)
          ON UPDATE RESTRICT ON DELETE RESTRICT
    ) WITHOUT ROWID;

    CREATE TABLE {CURRENT_END_ADMISSION_TABLE} (
        end_event_id TEXT PRIMARY KEY,
        admission_id TEXT NOT NULL CHECK(length(trim(admission_id))>0),
        effect_digest TEXT NOT NULL CHECK(length(effect_digest)=64),
        admission_binding_digest TEXT NOT NULL
          CHECK(length(admission_binding_digest)=64),
        grant_id TEXT NOT NULL CHECK(length(trim(grant_id))>0),
        grant_binding_digest TEXT NOT NULL
          CHECK(length(grant_binding_digest)>0),
        policy_fingerprint TEXT NOT NULL
          CHECK(length(policy_fingerprint)>0),
        launch_evidence_id TEXT NOT NULL
          CHECK(length(trim(launch_evidence_id))>0),
        policy_id TEXT NOT NULL CHECK(length(trim(policy_id))>0),
        policy_issuance_id TEXT NOT NULL
          CHECK(length(trim(policy_issuance_id))>0),
        proposal_id TEXT NOT NULL CHECK(length(trim(proposal_id))>0),
        approval_id TEXT NOT NULL CHECK(length(trim(approval_id))>0),
        session_id TEXT NOT NULL CHECK(length(trim(session_id))>0),
        episode_id TEXT NOT NULL CHECK(length(trim(episode_id))>0),
        perspective_instance_id TEXT NOT NULL
          CHECK(length(trim(perspective_instance_id))>0),
        room_id TEXT NOT NULL CHECK(length(trim(room_id))>0),
        room_attachment_event_id TEXT NOT NULL
          CHECK(length(trim(room_attachment_event_id))>0),
        required_scope TEXT NOT NULL
          CHECK(required_scope='room.change_current_stance'),
        target_state_admission_id TEXT NOT NULL
          CHECK(length(trim(target_state_admission_id))>0),
        FOREIGN KEY(end_event_id) REFERENCES {CURRENT_END_TABLE}(end_event_id)
          ON UPDATE RESTRICT ON DELETE RESTRICT
    ) WITHOUT ROWID;

    CREATE TRIGGER current_admission_schema_marker_no_update
      BEFORE UPDATE ON {CURRENT_ADMISSION_SCHEMA_MARKER_TABLE}
      BEGIN SELECT RAISE(ABORT,'Current admission schema marker is immutable'); END;
    CREATE TRIGGER current_admission_schema_marker_no_delete
      BEFORE DELETE ON {CURRENT_ADMISSION_SCHEMA_MARKER_TABLE}
      BEGIN SELECT RAISE(ABORT,'Current admission schema marker is immutable'); END;

    CREATE TRIGGER current_state_admission_no_replace
      BEFORE INSERT ON {CURRENT_STATE_ADMISSION_TABLE}
      WHEN EXISTS(
        SELECT 1 FROM {CURRENT_STATE_ADMISSION_TABLE}
        WHERE state_id=NEW.state_id)
      BEGIN SELECT RAISE(ABORT,'Current state already has an admission'); END;
    CREATE TRIGGER current_state_admission_no_update
      BEFORE UPDATE ON {CURRENT_STATE_ADMISSION_TABLE}
      BEGIN SELECT RAISE(ABORT,'Current state admission is append-only'); END;
    CREATE TRIGGER current_state_admission_no_delete
      BEFORE DELETE ON {CURRENT_STATE_ADMISSION_TABLE}
      BEGIN SELECT RAISE(ABORT,'Current state admission is append-only'); END;
    CREATE TRIGGER current_state_admission_unique_id
      BEFORE INSERT ON {CURRENT_STATE_ADMISSION_TABLE}
      WHEN EXISTS(
        SELECT 1 FROM {CURRENT_STATE_ADMISSION_TABLE}
        WHERE admission_id=NEW.admission_id
      ) OR EXISTS(
        SELECT 1 FROM {CURRENT_END_ADMISSION_TABLE}
        WHERE admission_id=NEW.admission_id
      )
      BEGIN SELECT RAISE(ABORT,'Current admission id already exists'); END;
    CREATE TRIGGER current_state_admission_effect_binding
      BEFORE INSERT ON {CURRENT_STATE_ADMISSION_TABLE}
      WHEN NOT EXISTS(
        SELECT 1 FROM {CURRENT_STATE_TABLE} s
        WHERE s.state_id=NEW.state_id
          AND s.namespace='room'
          AND s.owner_id=NEW.room_id
          AND s.episode_id=NEW.episode_id
          AND s.perspective_instance_id=NEW.perspective_instance_id
          AND s.room_attachment_event_id=NEW.room_attachment_event_id
      )
      BEGIN SELECT RAISE(ABORT,'Current state admission effect binding is invalid'); END;
    CREATE TRIGGER current_state_admission_supersession_binding
      BEFORE INSERT ON {CURRENT_STATE_ADMISSION_TABLE}
      WHEN EXISTS(
        SELECT 1 FROM {CURRENT_STATE_TABLE} s
        WHERE s.state_id=NEW.state_id
          AND (
            (
              s.supersedes_state_id IS NULL
              AND NEW.predecessor_admission_id IS NOT NULL
            )
            OR
            (
              s.supersedes_state_id IS NOT NULL
              AND NOT EXISTS(
                SELECT 1 FROM {CURRENT_STATE_ADMISSION_TABLE} a
                WHERE a.admission_id=NEW.predecessor_admission_id
                  AND a.state_id=s.supersedes_state_id
              )
            )
          )
      )
      BEGIN SELECT RAISE(ABORT,'Current state admission supersession is invalid'); END;

    CREATE TRIGGER current_end_admission_no_replace
      BEFORE INSERT ON {CURRENT_END_ADMISSION_TABLE}
      WHEN EXISTS(
        SELECT 1 FROM {CURRENT_END_ADMISSION_TABLE}
        WHERE end_event_id=NEW.end_event_id)
      BEGIN SELECT RAISE(ABORT,'Current end event already has an admission'); END;
    CREATE TRIGGER current_end_admission_no_update
      BEFORE UPDATE ON {CURRENT_END_ADMISSION_TABLE}
      BEGIN SELECT RAISE(ABORT,'Current end admission is append-only'); END;
    CREATE TRIGGER current_end_admission_no_delete
      BEFORE DELETE ON {CURRENT_END_ADMISSION_TABLE}
      BEGIN SELECT RAISE(ABORT,'Current end admission is append-only'); END;
    CREATE TRIGGER current_end_admission_unique_id
      BEFORE INSERT ON {CURRENT_END_ADMISSION_TABLE}
      WHEN EXISTS(
        SELECT 1 FROM {CURRENT_STATE_ADMISSION_TABLE}
        WHERE admission_id=NEW.admission_id
      ) OR EXISTS(
        SELECT 1 FROM {CURRENT_END_ADMISSION_TABLE}
        WHERE admission_id=NEW.admission_id
      )
      BEGIN SELECT RAISE(ABORT,'Current admission id already exists'); END;
    CREATE TRIGGER current_end_admission_effect_binding
      BEFORE INSERT ON {CURRENT_END_ADMISSION_TABLE}
      WHEN NOT EXISTS(
        SELECT 1
        FROM {CURRENT_END_TABLE} e
        JOIN {CURRENT_STATE_TABLE} s ON s.state_id=e.state_id
        WHERE e.end_event_id=NEW.end_event_id
          AND s.namespace='room'
          AND s.owner_id=NEW.room_id
          AND e.episode_id=NEW.episode_id
          AND e.perspective_instance_id=NEW.perspective_instance_id
          AND e.room_attachment_event_id=NEW.room_attachment_event_id
      )
      BEGIN SELECT RAISE(ABORT,'Current end admission effect binding is invalid'); END;
    CREATE TRIGGER current_end_admission_target_binding
      BEFORE INSERT ON {CURRENT_END_ADMISSION_TABLE}
      WHEN NOT EXISTS(
        SELECT 1
        FROM {CURRENT_END_TABLE} e
        JOIN {CURRENT_STATE_ADMISSION_TABLE} a
          ON a.state_id=e.state_id
        WHERE e.end_event_id=NEW.end_event_id
          AND a.admission_id=NEW.target_state_admission_id
      )
      BEGIN SELECT RAISE(ABORT,'Current end admission target is invalid'); END;
    """


def assert_current_admission_schema(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT type,name,tbl_name,sql
        FROM sqlite_master
        WHERE type IN ('table','trigger','index')
        """
    ).fetchall()
    unexpected = tuple(
        (row["type"], row["name"])
        for row in rows
        if row["tbl_name"] in CURRENT_ADMISSION_TABLES
        and (
            (
                row["type"] == "trigger"
                and row["name"] not in CURRENT_ADMISSION_TRIGGERS
            )
            or (
                row["type"] == "index"
                and row["sql"] is not None
            )
        )
    )
    if unexpected:
        raise CurrentAdmissionIntegrityError(
            "Current admission tables have unexpected trigger/index behavior"
        )
    actual = {
        (row["type"], row["name"]): _normalize_sql(row["sql"])
        for row in rows
        if (
            row["name"] in CURRENT_ADMISSION_TABLES
            or row["name"] in CURRENT_ADMISSION_TRIGGERS
        )
    }
    if actual != _expected_admission_schema_sql():
        raise CurrentAdmissionIntegrityError(
            "Current admission schema or trigger definitions were altered"
        )
    marker = connection.execute(
        f"SELECT marker_key,schema_version FROM {CURRENT_ADMISSION_SCHEMA_MARKER_TABLE}"
    ).fetchall()
    if len(marker) != 1 or tuple(marker[0]) != (
        "current_admission_schema",
        CURRENT_ADMISSION_SCHEMA_VERSION,
    ):
        raise CurrentAdmissionIntegrityError(
            "Current admission schema marker is invalid"
        )


def assert_current_admission_data_integrity(
    connection: sqlite3.Connection,
) -> None:
    state_rows = connection.execute(
        f"SELECT * FROM {CURRENT_STATE_ADMISSION_TABLE} ORDER BY state_id"
    ).fetchall()
    end_rows = connection.execute(
        f"SELECT * FROM {CURRENT_END_ADMISSION_TABLE} ORDER BY end_event_id"
    ).fetchall()
    seen_admission_ids: set[str] = set()

    for row in state_rows:
        audit = _state_admission_from_row(row)
        _validate_audit_record(audit)
        if audit.admission_id in seen_admission_ids:
            raise CurrentAdmissionIntegrityError(
                "Current admission id is duplicated"
            )
        seen_admission_ids.add(audit.admission_id)
        parent = connection.execute(
            f"SELECT * FROM {CURRENT_STATE_TABLE} WHERE state_id=?",
            (audit.effect_id,),
        ).fetchone()
        if parent is None:
            raise CurrentAdmissionIntegrityError(
                "Current state admission has no effect row"
            )
        if (
            parent["namespace"] != "room"
            or parent["owner_id"] != audit.room_id
            or parent["episode_id"] != audit.episode_id
            or parent["perspective_instance_id"] != audit.perspective_instance_id
            or parent["room_attachment_event_id"]
            != audit.room_attachment_event_id
        ):
            raise CurrentAdmissionIntegrityError(
                "Current state admission differs from effect provenance"
            )
        if _state_effect_digest(connection, audit.effect_id) != audit.effect_digest:
            raise CurrentAdmissionIntegrityError(
                "Current state admission effect digest is stale"
            )
        parent_state_id = parent["supersedes_state_id"]
        if parent_state_id is None:
            if audit.predecessor_admission_id is not None:
                raise CurrentAdmissionIntegrityError(
                    "root Current state claims predecessor admission"
                )
        else:
            predecessor = connection.execute(
                f"""SELECT state_id FROM {CURRENT_STATE_ADMISSION_TABLE}
                    WHERE admission_id=?""",
                (audit.predecessor_admission_id,),
            ).fetchone()
            if predecessor is None or predecessor["state_id"] != parent_state_id:
                raise CurrentAdmissionIntegrityError(
                    "Current state admission predecessor is invalid"
                )
        _assert_binding_digest(audit)

    for row in end_rows:
        audit = _end_admission_from_row(row)
        _validate_audit_record(audit)
        if audit.admission_id in seen_admission_ids:
            raise CurrentAdmissionIntegrityError(
                "Current admission id is duplicated"
            )
        seen_admission_ids.add(audit.admission_id)
        parent = connection.execute(
            f"""SELECT e.*,s.namespace,s.owner_id
                FROM {CURRENT_END_TABLE} e
                JOIN {CURRENT_STATE_TABLE} s ON s.state_id=e.state_id
                WHERE e.end_event_id=?""",
            (audit.effect_id,),
        ).fetchone()
        if parent is None:
            raise CurrentAdmissionIntegrityError(
                "Current end admission has no effect row"
            )
        if (
            parent["namespace"] != "room"
            or parent["owner_id"] != audit.room_id
            or parent["episode_id"] != audit.episode_id
            or parent["perspective_instance_id"] != audit.perspective_instance_id
            or parent["room_attachment_event_id"]
            != audit.room_attachment_event_id
        ):
            raise CurrentAdmissionIntegrityError(
                "Current end admission differs from effect provenance"
            )
        if _end_effect_digest(connection, audit.effect_id) != audit.effect_digest:
            raise CurrentAdmissionIntegrityError(
                "Current end admission effect digest is stale"
            )
        target = connection.execute(
            f"""SELECT a.admission_id
                FROM {CURRENT_END_TABLE} e
                JOIN {CURRENT_STATE_ADMISSION_TABLE} a
                  ON a.state_id=e.state_id
                WHERE e.end_event_id=?""",
            (audit.effect_id,),
        ).fetchone()
        if (
            target is None
            or target["admission_id"] != audit.predecessor_admission_id
        ):
            raise CurrentAdmissionIntegrityError(
                "Current end admission target is invalid"
            )
        _assert_binding_digest(audit)


def _grant_provenance(
    *,
    grant: RoomParticipationGrant,
    room_attachment_event_id: str,
    room_id: str | None = None,
) -> dict[str, object]:
    if not isinstance(grant, RoomParticipationGrant):
        raise CurrentAdmissionAuthorizationError(
            "Current admission requires RoomParticipationGrant"
        )
    required_scope = RoomParticipationScope.CHANGE_CURRENT_STANCE
    return {
        "grant_id": grant.grant_id,
        "grant_binding_digest": grant.binding_digest,
        "policy_fingerprint": grant.policy_fingerprint,
        "launch_evidence_id": grant.launch_evidence_id,
        "policy_id": grant.policy_id,
        "policy_issuance_id": grant.policy_issuance_id,
        "proposal_id": grant.proposal_id,
        "approval_id": grant.approval_id,
        "session_id": grant.session_id,
        "episode_id": grant.episode_id,
        "perspective_instance_id": grant.perspective_instance_id,
        "room_id": grant.room_id if room_id is None else room_id,
        "room_attachment_event_id": room_attachment_event_id,
        "required_scope": required_scope,
    }


def _state_effect_digest(connection: sqlite3.Connection, state_id: str) -> str:
    row = connection.execute(
        f"SELECT * FROM {CURRENT_STATE_TABLE} WHERE state_id=?",
        (state_id,),
    ).fetchone()
    if row is None:
        raise CurrentAdmissionIntegrityError("Current state effect is missing")
    bindings = connection.execute(
        f"""SELECT position,source_ref,source_id,source_sha256,start_char,end_char
            FROM {CURRENT_STATE_EVIDENCE_TABLE}
            WHERE state_id=? ORDER BY position""",
        (state_id,),
    ).fetchall()
    return _digest_effect(
        "state",
        row,
        bindings,
        (
            "state_id",
            "namespace",
            "owner_id",
            "key",
            "state_kind",
            "recorded_instant_us",
            "semantic_change_authority",
            "episode_id",
            "perspective_instance_id",
            "room_attachment_event_id",
            "supersedes_state_id",
            "source_ref_count",
            "payload_json",
        ),
    )


def _end_effect_digest(connection: sqlite3.Connection, end_event_id: str) -> str:
    row = connection.execute(
        f"SELECT * FROM {CURRENT_END_TABLE} WHERE end_event_id=?",
        (end_event_id,),
    ).fetchone()
    if row is None:
        raise CurrentAdmissionIntegrityError("Current end effect is missing")
    bindings = connection.execute(
        f"""SELECT position,source_ref,source_id,source_sha256,start_char,end_char
            FROM {CURRENT_END_EVIDENCE_TABLE}
            WHERE end_event_id=? ORDER BY position""",
        (end_event_id,),
    ).fetchall()
    return _digest_effect(
        "end_event",
        row,
        bindings,
        (
            "end_event_id",
            "state_id",
            "recorded_instant_us",
            "semantic_change_authority",
            "episode_id",
            "perspective_instance_id",
            "room_attachment_event_id",
            "source_ref_count",
            "payload_json",
        ),
    )


def _digest_effect(
    kind: str,
    row: sqlite3.Row,
    bindings: list[sqlite3.Row],
    columns: tuple[str, ...],
) -> str:
    payload = {
        "kind": kind,
        "row": {column: row[column] for column in columns},
        "bindings": [
            {
                "position": item["position"],
                "source_ref": item["source_ref"],
                "source_id": item["source_id"],
                "source_sha256": item["source_sha256"],
                "start_char": item["start_char"],
                "end_char": item["end_char"],
            }
            for item in bindings
        ],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _admission_binding_digest(
    *,
    admission_id: str,
    effect_kind: CurrentAdmissionEffectKind,
    effect_id: str,
    effect_digest: str,
    grant_id: str,
    grant_binding_digest: str,
    policy_fingerprint: str,
    launch_evidence_id: str,
    policy_id: str,
    policy_issuance_id: str,
    proposal_id: str,
    approval_id: str,
    session_id: str,
    episode_id: str,
    perspective_instance_id: str,
    room_id: str,
    room_attachment_event_id: str,
    required_scope: RoomParticipationScope,
    predecessor_admission_id: str | None,
) -> str:
    payload = {
        "admission_id": admission_id,
        "effect_kind": effect_kind.value,
        "effect_id": effect_id,
        "effect_digest": effect_digest,
        "grant_id": grant_id,
        "grant_binding_digest": grant_binding_digest,
        "policy_fingerprint": policy_fingerprint,
        "launch_evidence_id": launch_evidence_id,
        "policy_id": policy_id,
        "policy_issuance_id": policy_issuance_id,
        "proposal_id": proposal_id,
        "approval_id": approval_id,
        "session_id": session_id,
        "episode_id": episode_id,
        "perspective_instance_id": perspective_instance_id,
        "room_id": room_id,
        "room_attachment_event_id": room_attachment_event_id,
        "required_scope": required_scope.value,
        "predecessor_admission_id": predecessor_admission_id,
    }
    return sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _assert_binding_digest(audit: CurrentAdmissionAuditRecord) -> None:
    expected = _admission_binding_digest(
        admission_id=audit.admission_id,
        effect_kind=audit.effect_kind,
        effect_id=audit.effect_id,
        effect_digest=audit.effect_digest,
        grant_id=audit.grant_id,
        grant_binding_digest=audit.grant_binding_digest,
        policy_fingerprint=audit.policy_fingerprint,
        launch_evidence_id=audit.launch_evidence_id,
        policy_id=audit.policy_id,
        policy_issuance_id=audit.policy_issuance_id,
        proposal_id=audit.proposal_id,
        approval_id=audit.approval_id,
        session_id=audit.session_id,
        episode_id=audit.episode_id,
        perspective_instance_id=audit.perspective_instance_id,
        room_id=audit.room_id,
        room_attachment_event_id=audit.room_attachment_event_id,
        required_scope=audit.required_scope,
        predecessor_admission_id=audit.predecessor_admission_id,
    )
    if expected != audit.admission_binding_digest:
        raise CurrentAdmissionIntegrityError(
            "Current admission binding digest is invalid"
        )


def _state_admission_from_row(row: sqlite3.Row) -> CurrentAdmissionAuditRecord:
    return _audit_from_row(
        row=row,
        effect_kind=CurrentAdmissionEffectKind.STATE,
        effect_id=row["state_id"],
        predecessor_admission_id=row["predecessor_admission_id"],
    )


def _end_admission_from_row(row: sqlite3.Row) -> CurrentAdmissionAuditRecord:
    return _audit_from_row(
        row=row,
        effect_kind=CurrentAdmissionEffectKind.END_EVENT,
        effect_id=row["end_event_id"],
        predecessor_admission_id=row["target_state_admission_id"],
    )


def _audit_from_row(
    *,
    row: sqlite3.Row,
    effect_kind: CurrentAdmissionEffectKind,
    effect_id: str,
    predecessor_admission_id: str | None,
) -> CurrentAdmissionAuditRecord:
    return CurrentAdmissionAuditRecord(
        admission_id=row["admission_id"],
        effect_kind=effect_kind,
        effect_id=effect_id,
        effect_digest=row["effect_digest"],
        admission_binding_digest=row["admission_binding_digest"],
        grant_id=row["grant_id"],
        grant_binding_digest=row["grant_binding_digest"],
        policy_fingerprint=row["policy_fingerprint"],
        launch_evidence_id=row["launch_evidence_id"],
        policy_id=row["policy_id"],
        policy_issuance_id=row["policy_issuance_id"],
        proposal_id=row["proposal_id"],
        approval_id=row["approval_id"],
        session_id=row["session_id"],
        episode_id=row["episode_id"],
        perspective_instance_id=row["perspective_instance_id"],
        room_id=row["room_id"],
        room_attachment_event_id=row["room_attachment_event_id"],
        required_scope=RoomParticipationScope(row["required_scope"]),
        predecessor_admission_id=predecessor_admission_id,
    )


def _receipt_as_audit(
    receipt: CurrentAdmissionReceipt,
) -> CurrentAdmissionAuditRecord:
    return CurrentAdmissionAuditRecord(
        admission_id=receipt.admission_id,
        effect_kind=receipt.effect_kind,
        effect_id=receipt.effect_id,
        effect_digest=receipt.effect_digest,
        admission_binding_digest=receipt.admission_binding_digest,
        grant_id=receipt.grant_id,
        grant_binding_digest=receipt.grant_binding_digest,
        policy_fingerprint=receipt.policy_fingerprint,
        launch_evidence_id=receipt.launch_evidence_id,
        policy_id=receipt.policy_id,
        policy_issuance_id=receipt.policy_issuance_id,
        proposal_id=receipt.proposal_id,
        approval_id=receipt.approval_id,
        session_id=receipt.session_id,
        episode_id=receipt.episode_id,
        perspective_instance_id=receipt.perspective_instance_id,
        room_id=receipt.room_id,
        room_attachment_event_id=receipt.room_attachment_event_id,
        required_scope=receipt.required_scope,
        predecessor_admission_id=receipt.predecessor_admission_id,
    )


def _validate_audit_record(record: CurrentAdmissionAuditRecord) -> None:
    if not isinstance(record.effect_kind, CurrentAdmissionEffectKind):
        raise CurrentAdmissionIntegrityError(
            "Current admission effect kind is invalid"
        )
    if record.required_scope is not RoomParticipationScope.CHANGE_CURRENT_STANCE:
        raise CurrentAdmissionIntegrityError(
            "Current admission scope is not change_current_stance"
        )
    for field_name in (
        "admission_id",
        "effect_id",
        "effect_digest",
        "admission_binding_digest",
        "grant_id",
        "grant_binding_digest",
        "policy_fingerprint",
        "launch_evidence_id",
        "policy_id",
        "policy_issuance_id",
        "proposal_id",
        "approval_id",
        "session_id",
        "episode_id",
        "perspective_instance_id",
        "room_id",
        "room_attachment_event_id",
    ):
        value = getattr(record, field_name)
        if not isinstance(value, str) or not value.strip():
            raise CurrentAdmissionIntegrityError(
                f"{field_name} must be non-empty text"
            )
    if (
        len(record.effect_digest) != 64
        or len(record.admission_binding_digest) != 64
        or any(ch not in "0123456789abcdef" for ch in record.effect_digest)
        or any(ch not in "0123456789abcdef" for ch in record.admission_binding_digest)
    ):
        raise CurrentAdmissionIntegrityError(
            "Current admission digests must be lowercase sha256 hex"
        )
    if (
        record.predecessor_admission_id is not None
        and (
            not isinstance(record.predecessor_admission_id, str)
            or not record.predecessor_admission_id.strip()
        )
    ):
        raise CurrentAdmissionIntegrityError(
            "predecessor_admission_id must be non-empty text when present"
        )


def _receipt_fingerprint(receipt: CurrentAdmissionReceipt) -> str:
    audit = _receipt_as_audit(receipt)
    payload = {
        "admission_id": audit.admission_id,
        "effect_kind": audit.effect_kind.value,
        "effect_id": audit.effect_id,
        "effect_digest": audit.effect_digest,
        "admission_binding_digest": audit.admission_binding_digest,
        "grant_id": audit.grant_id,
        "grant_binding_digest": audit.grant_binding_digest,
        "policy_fingerprint": audit.policy_fingerprint,
        "launch_evidence_id": audit.launch_evidence_id,
        "policy_id": audit.policy_id,
        "policy_issuance_id": audit.policy_issuance_id,
        "proposal_id": audit.proposal_id,
        "approval_id": audit.approval_id,
        "session_id": audit.session_id,
        "episode_id": audit.episode_id,
        "perspective_instance_id": audit.perspective_instance_id,
        "room_id": audit.room_id,
        "room_attachment_event_id": audit.room_attachment_event_id,
        "required_scope": audit.required_scope.value,
        "predecessor_admission_id": audit.predecessor_admission_id,
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _admission_table_for_kind(
    effect_kind: CurrentAdmissionEffectKind,
) -> tuple[str, str]:
    if effect_kind is CurrentAdmissionEffectKind.STATE:
        return CURRENT_STATE_ADMISSION_TABLE, "state_id"
    if effect_kind is CurrentAdmissionEffectKind.END_EVENT:
        return CURRENT_END_ADMISSION_TABLE, "end_event_id"
    raise CurrentAdmissionAuthorizationError("unknown Current admission effect kind")


def _normalize_sql(sql: str | None) -> str:
    return "" if sql is None else sql.strip()


def _expected_admission_schema_sql() -> dict[tuple[str, str], str]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(
            f"""
            CREATE TABLE {CURRENT_STATE_TABLE} (
                state_id TEXT PRIMARY KEY,
                namespace TEXT,
                owner_id TEXT,
                episode_id TEXT,
                perspective_instance_id TEXT,
                room_attachment_event_id TEXT,
                supersedes_state_id TEXT
            );
            CREATE TABLE {CURRENT_END_TABLE} (
                end_event_id TEXT PRIMARY KEY,
                state_id TEXT,
                episode_id TEXT,
                perspective_instance_id TEXT,
                room_attachment_event_id TEXT
            );
            """
        )
        connection.executescript(current_admission_schema_script())
        rows = connection.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','trigger')"
        ).fetchall()
        return {
            (row["type"], row["name"]): _normalize_sql(row["sql"])
            for row in rows
            if (
                row["name"] in CURRENT_ADMISSION_TABLES
                or row["name"] in CURRENT_ADMISSION_TRIGGERS
            )
        }
    finally:
        connection.close()
