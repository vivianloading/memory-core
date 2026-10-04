from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from home_memory_core.current_store_schema import (
    CURRENT_END_EVIDENCE_TABLE,
    CURRENT_END_TABLE,
    CURRENT_SCHEMA_MARKER_TABLE,
    CURRENT_SCHEMA_VERSION,
    CURRENT_STATE_EVIDENCE_TABLE,
    CURRENT_STATE_TABLE,
    CURRENT_TABLES,
    CURRENT_TRIGGERS,
    current_schema_script,
    expected_current_schema_sql,
    normalize_sql,
)
from home_memory_core.current_view import (
    CurrentNamespace,
    CurrentStateEndEvent,
    CurrentStateKind,
    CurrentStateRecord,
    CurrentViewError,
    DowngradeRule,
    EndKind,
    SemanticChangeAuthority,
    ValidityRule,
)
from home_memory_core.evidence import EvidenceRef
from home_memory_core.living_store import (
    ATTACHMENT_TABLE,
    EPISODE_TABLE,
    ROOM_TABLE,
    assert_living_data_integrity,
    assert_living_schema,
)
from home_memory_core.store_domain import assert_synthetic_store_domain
from home_memory_core.suppression import SuppressedMemoryError


class CurrentStoreError(RuntimeError):
    """Base error for synthetic Current history persistence."""


class CurrentStoreIntegrityError(CurrentStoreError):
    """Persisted Current history or schema violates the v0.1 contract."""


class CurrentStoreConflictError(CurrentStoreError):
    """A write conflicts with immutable persisted Current history."""


@dataclass(frozen=True)
class CurrentSourceBinding:
    """Bind one semantic source_ref label to exact source evidence."""

    source_ref: str
    evidence: EvidenceRef

    def __post_init__(self) -> None:
        _text("source_ref", self.source_ref)
        if not isinstance(self.evidence, EvidenceRef):
            raise TypeError("evidence must be EvidenceRef")
        _validate_evidence_coordinates(self.evidence)


@dataclass(frozen=True)
class PersistedCurrentState:
    record: CurrentStateRecord
    source_bindings: tuple[CurrentSourceBinding, ...]
    room_attachment_event_id: str | None


@dataclass(frozen=True)
class PersistedCurrentEndEvent:
    event: CurrentStateEndEvent
    source_bindings: tuple[CurrentSourceBinding, ...]
    room_attachment_event_id: str | None


class CurrentStore:
    """Synthetic-only durable history backing the derived Current View.

    This slice intentionally exposes no production "what is current?" consumer
    and no operational admission authority. It stores immutable history plus
    exact provenance; later layers decide whether and how it may be used.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        if not self.db_path.exists():
            raise CurrentStoreIntegrityError(
                "Current persistence requires an initialized synthetic HOME store"
            )
        connection = self._connect()
        try:
            self._assert_upstream(connection)
            existing = self._existing_tables(connection)
            if existing:
                if existing != CURRENT_TABLES:
                    raise CurrentStoreIntegrityError("partial Current persistence schema exists")
                assert_current_schema(connection)
                assert_current_data_integrity(connection)
                return
            connection.executescript(current_schema_script())
            # Re-check upstream invariants inside the schema-install transaction.
            # The first check happens before executescript() begins its IMMEDIATE
            # transaction and must not become a time-of-check/time-of-use gap.
            self._assert_upstream(connection)
            assert_current_schema(connection)
            assert_current_data_integrity(connection)
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def add_state_record(
        self,
        *,
        record: CurrentStateRecord,
        source_bindings: tuple[CurrentSourceBinding, ...],
    ) -> None:
        if not isinstance(record, CurrentStateRecord):
            raise TypeError("record must be CurrentStateRecord")
        _binding_shape(record.source_refs, source_bindings)
        connection = self._write_connection()
        try:
            _validate_new_bindings(connection, source_bindings)
            room_attachment_event_id = _active_room_attachment(
                connection,
                namespace=record.namespace,
                owner_id=record.owner_id,
                episode_id=record.episode_id,
                perspective_instance_id=record.perspective_instance_id,
            )
            connection.execute(
                f"""INSERT INTO {CURRENT_STATE_TABLE} (
                  state_id,namespace,owner_id,key,state_kind,recorded_instant_us,
                  semantic_change_authority,episode_id,perspective_instance_id,
                  room_attachment_event_id,supersedes_state_id,source_ref_count,payload_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.state_id, record.namespace.value, record.owner_id,
                    record.key, record.state_kind.value, _instant(record.recorded_at),
                    record.semantic_change_authority.value, record.episode_id,
                    record.perspective_instance_id, room_attachment_event_id,
                    record.supersedes_state_id, len(record.source_refs),
                    _state_payload(record),
                ),
            )
            _insert_bindings(
                connection, CURRENT_STATE_EVIDENCE_TABLE, "state_id",
                record.state_id, source_bindings,
            )
            assert_current_data_integrity(connection)
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise CurrentStoreConflictError(
                f"Current state conflicts with persisted history: {record.state_id}"
            ) from error
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def add_end_event(
        self,
        *,
        event: CurrentStateEndEvent,
        source_bindings: tuple[CurrentSourceBinding, ...],
    ) -> None:
        if not isinstance(event, CurrentStateEndEvent):
            raise TypeError("event must be CurrentStateEndEvent")
        _binding_shape(event.source_refs, source_bindings)
        connection = self._write_connection()
        try:
            _validate_new_bindings(connection, source_bindings)
            target = connection.execute(
                f"SELECT namespace,owner_id FROM {CURRENT_STATE_TABLE} WHERE state_id=?",
                (event.state_id,),
            ).fetchone()
            if target is None:
                raise CurrentStoreIntegrityError("Current end event target is missing")
            room_attachment_event_id = _active_room_attachment(
                connection,
                namespace=CurrentNamespace(target["namespace"]),
                owner_id=target["owner_id"],
                episode_id=event.episode_id,
                perspective_instance_id=event.perspective_instance_id,
            )
            connection.execute(
                f"""INSERT INTO {CURRENT_END_TABLE} (
                  end_event_id,state_id,recorded_instant_us,semantic_change_authority,
                  episode_id,perspective_instance_id,room_attachment_event_id,
                  source_ref_count,payload_json
                ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    event.end_event_id, event.state_id, _instant(event.recorded_at),
                    event.semantic_change_authority.value, event.episode_id,
                    event.perspective_instance_id, room_attachment_event_id,
                    len(event.source_refs), _end_payload(event),
                ),
            )
            _insert_bindings(
                connection, CURRENT_END_EVIDENCE_TABLE, "end_event_id",
                event.end_event_id, source_bindings,
            )
            assert_current_data_integrity(connection)
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise CurrentStoreConflictError(
                f"Current end event conflicts with persisted history: {event.end_event_id}"
            ) from error
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_state_for_audit(self, state_id: str) -> PersistedCurrentState:
        connection = self._read_connection()
        try:
            row = connection.execute(
                f"SELECT * FROM {CURRENT_STATE_TABLE} WHERE state_id=?", (state_id,)
            ).fetchone()
            if row is None:
                raise KeyError(state_id)
            bindings = _read_bindings(
                connection, CURRENT_STATE_EVIDENCE_TABLE, "state_id", state_id
            )
            return PersistedCurrentState(
                _state_from_row(row, bindings), bindings, row["room_attachment_event_id"]
            )
        finally:
            connection.close()

    def list_states_for_audit(self) -> tuple[PersistedCurrentState, ...]:
        connection = self._read_connection()
        try:
            result = []
            for row in connection.execute(
                f"SELECT * FROM {CURRENT_STATE_TABLE} ORDER BY state_id"
            ).fetchall():
                bindings = _read_bindings(
                    connection, CURRENT_STATE_EVIDENCE_TABLE, "state_id", row["state_id"]
                )
                result.append(PersistedCurrentState(
                    _state_from_row(row, bindings), bindings, row["room_attachment_event_id"]
                ))
            return tuple(result)
        finally:
            connection.close()

    def get_end_event_for_audit(self, end_event_id: str) -> PersistedCurrentEndEvent:
        connection = self._read_connection()
        try:
            row = connection.execute(
                f"SELECT * FROM {CURRENT_END_TABLE} WHERE end_event_id=?", (end_event_id,)
            ).fetchone()
            if row is None:
                raise KeyError(end_event_id)
            bindings = _read_bindings(
                connection, CURRENT_END_EVIDENCE_TABLE, "end_event_id", end_event_id
            )
            return PersistedCurrentEndEvent(
                _end_from_row(row, bindings), bindings, row["room_attachment_event_id"]
            )
        finally:
            connection.close()

    def _write_connection(self) -> sqlite3.Connection:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_upstream(connection)
            assert_current_schema(connection)
            assert_current_data_integrity(connection)
            return connection
        except Exception:
            connection.close()
            raise

    def _read_connection(self) -> sqlite3.Connection:
        connection = self._connect()
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            self._assert_upstream(connection)
            assert_current_schema(connection)
            assert_current_data_integrity(connection)
            return connection
        except Exception:
            connection.close()
            raise

    def _assert_upstream(self, connection: sqlite3.Connection) -> None:
        assert_synthetic_store_domain(connection)
        assert_living_schema(connection)
        assert_living_data_integrity(connection)
        names = {r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if not {"sources", "source_suppressions"}.issubset(names):
            raise CurrentStoreIntegrityError("Current persistence requires source tables")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _existing_tables(self, connection: sqlite3.Connection) -> frozenset[str]:
        names = {r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        return frozenset(names.intersection(CURRENT_TABLES))


def assert_current_schema(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT type,name,tbl_name,sql
        FROM sqlite_master
        WHERE type IN ('table','trigger','index')
          AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()

    unexpected_behavior = tuple(
        (row["type"], row["name"])
        for row in rows
        if row["tbl_name"] in CURRENT_TABLES
        and (
            (
                row["type"] == "trigger"
                and row["name"] not in CURRENT_TRIGGERS
            )
            or (
                row["type"] == "index"
                and row["sql"] is not None
            )
        )
    )
    if unexpected_behavior:
        raise CurrentStoreIntegrityError(
            "Current persistence tables have unexpected trigger/index behavior"
        )

    actual = {
        (row["type"], row["name"]): normalize_sql(row["sql"])
        for row in rows
        if row["name"] in CURRENT_TABLES or row["name"] in CURRENT_TRIGGERS
    }
    if actual != expected_current_schema_sql():
        raise CurrentStoreIntegrityError(
            "Current persistence schema or trigger definitions were altered"
        )
    marker = connection.execute(
        f"SELECT marker_key,schema_version FROM {CURRENT_SCHEMA_MARKER_TABLE}"
    ).fetchall()
    if len(marker) != 1 or tuple(marker[0]) != (
        "current_persistence_schema", CURRENT_SCHEMA_VERSION
    ):
        raise CurrentStoreIntegrityError("Current persistence schema marker is invalid")


def assert_current_data_integrity(connection: sqlite3.Connection) -> None:
    try:
        _assert_binding_table_integrity(
            connection,
            child_table=CURRENT_STATE_EVIDENCE_TABLE,
            parent_table=CURRENT_STATE_TABLE,
            parent_column="state_id",
            declared_count_column="source_ref_count",
        )
        _assert_binding_table_integrity(
            connection,
            child_table=CURRENT_END_EVIDENCE_TABLE,
            parent_table=CURRENT_END_TABLE,
            parent_column="end_event_id",
            declared_count_column="source_ref_count",
        )

        states = []
        for row in connection.execute(
            f"SELECT * FROM {CURRENT_STATE_TABLE} ORDER BY rowid"
        ).fetchall():
            bindings = _read_bindings(
                connection, CURRENT_STATE_EVIDENCE_TABLE, "state_id", row["state_id"]
            )
            _persisted_bindings(connection, bindings)
            record = _state_from_row(row, bindings)
            _state_index(row, record)
            _room_provenance(
                connection, record, row["room_attachment_event_id"]
            )
            states.append(record)
        _state_graph(tuple(states))
        state_by_id = {state.state_id: state for state in states}

        seen = set()
        for row in connection.execute(
            f"SELECT * FROM {CURRENT_END_TABLE} ORDER BY end_event_id"
        ).fetchall():
            bindings = _read_bindings(
                connection, CURRENT_END_EVIDENCE_TABLE, "end_event_id", row["end_event_id"]
            )
            _persisted_bindings(connection, bindings)
            event = _end_from_row(row, bindings)
            _end_index(row, event)
            if event.end_event_id in seen:
                raise CurrentStoreIntegrityError("duplicate Current end-event id")
            seen.add(event.end_event_id)
            target = state_by_id.get(event.state_id)
            if target is None:
                raise CurrentStoreIntegrityError("Current end event has no target")
            _end_target(
                connection, event, target, row["room_attachment_event_id"]
            )
    except CurrentStoreIntegrityError:
        raise
    except (CurrentViewError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise CurrentStoreIntegrityError(
            "persisted Current history violates semantic integrity"
        ) from error


def _binding_shape(
    refs: tuple[str, ...], bindings: tuple[CurrentSourceBinding, ...]
) -> None:
    if not isinstance(bindings, tuple) or not bindings:
        raise CurrentStoreIntegrityError("Current history requires exact source bindings")
    actual = tuple(binding.source_ref for binding in bindings)
    if actual != refs or len(set(actual)) != len(actual):
        raise CurrentStoreIntegrityError(
            "typed source bindings must match source_refs one-to-one and in order"
        )


def _validate_new_bindings(
    connection: sqlite3.Connection, bindings: tuple[CurrentSourceBinding, ...]
) -> None:
    for binding in bindings:
        evidence = binding.evidence
        _validate_evidence_coordinates(evidence)
        row = connection.execute(
            "SELECT content,content_sha256 FROM sources WHERE source_id=?",
            (evidence.source_id,),
        ).fetchone()
        if row is None:
            raise CurrentStoreIntegrityError("Current evidence source is missing")
        actual_hash = sha256(row["content"].encode("utf-8")).hexdigest()
        if actual_hash != row["content_sha256"]:
            raise CurrentStoreIntegrityError(
                "stored source content hash does not match content"
            )
        if row["content_sha256"] != evidence.source_sha256:
            raise CurrentStoreIntegrityError("Current evidence source/hash is invalid")
        if not (0 <= evidence.start_char < evidence.end_char <= len(row["content"])):
            raise CurrentStoreIntegrityError("Current evidence range is invalid")
        if connection.execute(
            "SELECT 1 FROM source_suppressions WHERE source_id=?", (evidence.source_id,)
        ).fetchone() is not None:
            raise SuppressedMemoryError("cannot persist Current history from suppressed source")


def _persisted_bindings(
    connection: sqlite3.Connection, bindings: tuple[CurrentSourceBinding, ...]
) -> None:
    if not bindings:
        raise CurrentStoreIntegrityError("persisted Current history is missing evidence")
    for binding in bindings:
        evidence = binding.evidence
        _validate_evidence_coordinates(evidence)
        row = connection.execute(
            "SELECT content,content_sha256 FROM sources WHERE source_id=?", (evidence.source_id,)
        ).fetchone()
        if row is None:
            raise CurrentStoreIntegrityError("persisted Current evidence source is missing")
        actual_hash = sha256(row["content"].encode("utf-8")).hexdigest()
        if actual_hash != row["content_sha256"]:
            raise CurrentStoreIntegrityError(
                "persisted source content hash does not match content"
            )
        if row["content_sha256"] != evidence.source_sha256:
            raise CurrentStoreIntegrityError("persisted Current evidence source/hash is invalid")
        if not (0 <= evidence.start_char < evidence.end_char <= len(row["content"])):
            raise CurrentStoreIntegrityError("persisted Current evidence range is invalid")


def _room_provenance(
    connection: sqlite3.Connection,
    record: CurrentStateRecord,
    room_attachment_event_id: str | None,
) -> None:
    if record.namespace is CurrentNamespace.SHARED:
        if room_attachment_event_id is not None:
            raise CurrentStoreIntegrityError(
                "Shared Current history cannot carry Room attachment provenance"
            )
        return
    if connection.execute(
        f"SELECT 1 FROM {ROOM_TABLE} WHERE room_id=?", (record.owner_id,)
    ).fetchone() is None:
        raise CurrentStoreIntegrityError("Room Current owner is missing")
    if connection.execute(
        f"SELECT 1 FROM {EPISODE_TABLE} WHERE episode_id=? AND perspective_instance_id=?",
        (record.episode_id, record.perspective_instance_id),
    ).fetchone() is None:
        raise CurrentStoreIntegrityError("Room Current Episode/Perspective is invalid")
    _assert_room_attachment_anchor(
        connection,
        room_attachment_event_id=room_attachment_event_id,
        room_id=record.owner_id,
        episode_id=record.episode_id,
    )


def _state_index(row: sqlite3.Row, record: CurrentStateRecord) -> None:
    indexed = (
        row["state_id"], row["namespace"], row["owner_id"], row["key"],
        row["state_kind"], row["recorded_instant_us"],
        row["semantic_change_authority"], row["episode_id"],
        row["perspective_instance_id"], row["supersedes_state_id"],
        row["source_ref_count"],
    )
    expected = (
        record.state_id, record.namespace.value, record.owner_id, record.key,
        record.state_kind.value, _instant(record.recorded_at),
        record.semantic_change_authority.value, record.episode_id,
        record.perspective_instance_id, record.supersedes_state_id,
        len(record.source_refs),
    )
    if indexed != expected:
        raise CurrentStoreIntegrityError("Current state index differs from payload")


def _end_index(row: sqlite3.Row, event: CurrentStateEndEvent) -> None:
    indexed = (
        row["end_event_id"], row["state_id"], row["recorded_instant_us"],
        row["semantic_change_authority"], row["episode_id"], row["perspective_instance_id"],
        row["source_ref_count"],
    )
    expected = (
        event.end_event_id, event.state_id, _instant(event.recorded_at),
        event.semantic_change_authority.value, event.episode_id, event.perspective_instance_id,
        len(event.source_refs),
    )
    if indexed != expected:
        raise CurrentStoreIntegrityError("Current end-event index differs from payload")


def _state_graph(records: tuple[CurrentStateRecord, ...]) -> None:
    by_id = {record.state_id: record for record in records}
    if len(by_id) != len(records):
        raise CurrentStoreIntegrityError("duplicate Current state id")
    kinds_by_key: dict[tuple[CurrentNamespace, str, str], set[CurrentStateKind]] = {}
    for record in records:
        kinds_by_key.setdefault(
            (record.namespace, record.owner_id, record.key),
            set(),
        ).add(record.state_kind)
    if any(len(kinds) > 1 for kinds in kinds_by_key.values()):
        raise CurrentStoreIntegrityError(
            "one Current key cannot change state_kind across history"
        )

    for record in records:
        parent_id = record.supersedes_state_id
        if parent_id is None:
            continue
        parent = by_id.get(parent_id)
        if parent is None:
            raise CurrentStoreIntegrityError("Current supersession parent is missing")
        if (
            parent.namespace is not record.namespace
            or parent.owner_id != record.owner_id
            or parent.key != record.key
            or parent.state_kind is not record.state_kind
            or _instant(record.recorded_at) < _instant(parent.recorded_at)
        ):
            raise CurrentStoreIntegrityError("Current supersession crosses a semantic line")
    for start in by_id:
        seen = set()
        current = start
        while by_id[current].supersedes_state_id is not None:
            parent = by_id[current].supersedes_state_id
            assert parent is not None
            if parent == start or parent in seen:
                raise CurrentStoreIntegrityError("Current supersession graph contains a cycle")
            seen.add(parent)
            current = parent


def _end_target(
    connection: sqlite3.Connection,
    event: CurrentStateEndEvent,
    target: CurrentStateRecord,
    room_attachment_event_id: str | None,
) -> None:
    if event.semantic_change_authority is not target.semantic_change_authority:
        raise CurrentStoreIntegrityError("Current end-event authority differs from target")
    if _instant(event.recorded_at) < _instant(target.recorded_at):
        raise CurrentStoreIntegrityError("Current end-event predates target record")
    if _instant(event.ended_at) < _instant(target.valid_from):
        raise CurrentStoreIntegrityError("Current end-event predates target validity")
    if target.namespace is CurrentNamespace.ROOM:
        if connection.execute(
            f"SELECT 1 FROM {EPISODE_TABLE} WHERE episode_id=? AND perspective_instance_id=?",
            (event.episode_id, event.perspective_instance_id),
        ).fetchone() is None:
            raise CurrentStoreIntegrityError("Room Current end-event provenance is invalid")
        _assert_room_attachment_anchor(
            connection,
            room_attachment_event_id=room_attachment_event_id,
            room_id=target.owner_id,
            episode_id=event.episode_id,
        )
    elif (
        event.episode_id is not None
        or event.perspective_instance_id is not None
        or room_attachment_event_id is not None
    ):
        raise CurrentStoreIntegrityError("Shared Current end-event claims Room provenance")



def _active_room_attachment(
    connection: sqlite3.Connection,
    *,
    namespace: CurrentNamespace,
    owner_id: str,
    episode_id: str | None,
    perspective_instance_id: str | None,
) -> str | None:
    """Return the exact active RoomAttachmentEvent used at admission time.

    The event id is persisted as historical provenance. A later attachment
    correction does not rewrite this anchor; it remains evidence of what route
    the admission actually relied on.
    """

    if namespace is CurrentNamespace.SHARED:
        if episode_id is not None or perspective_instance_id is not None:
            raise CurrentStoreIntegrityError(
                "Shared Current history cannot claim Room first-person provenance"
            )
        return None

    if episode_id is None or perspective_instance_id is None:
        raise CurrentStoreIntegrityError(
            "Room Current history requires Episode/Perspective provenance"
        )
    if connection.execute(
        f"SELECT 1 FROM {ROOM_TABLE} WHERE room_id=?",
        (owner_id,),
    ).fetchone() is None:
        raise CurrentStoreIntegrityError("Room Current owner is missing")
    if connection.execute(
        f"SELECT 1 FROM {EPISODE_TABLE} WHERE episode_id=? AND perspective_instance_id=?",
        (episode_id, perspective_instance_id),
    ).fetchone() is None:
        raise CurrentStoreConflictError(
            "Room Current write conflicts with persisted Episode/Perspective attribution"
        )

    heads = connection.execute(
        f"""
        SELECT a.attachment_event_id,a.route_kind,a.room_id
        FROM {ATTACHMENT_TABLE} AS a
        WHERE a.episode_id=?
          AND NOT EXISTS (
            SELECT 1 FROM {ATTACHMENT_TABLE} AS child
            WHERE child.supersedes_attachment_event_id=a.attachment_event_id
          )
        ORDER BY a.rowid
        """,
        (episode_id,),
    ).fetchall()
    if len(heads) != 1:
        raise CurrentStoreIntegrityError(
            "Room Current admission requires one resolved active Room route"
        )
    head = heads[0]
    if head["route_kind"] != "attached" or head["room_id"] != owner_id:
        raise CurrentStoreIntegrityError(
            "Room Current admission Episode is not actively routed to the target Room"
        )
    return head["attachment_event_id"]


def _assert_room_attachment_anchor(
    connection: sqlite3.Connection,
    *,
    room_attachment_event_id: str | None,
    room_id: str,
    episode_id: str | None,
) -> None:
    if room_attachment_event_id is None or episode_id is None:
        raise CurrentStoreIntegrityError(
            "Room Current history is missing attachment provenance"
        )
    row = connection.execute(
        f"""
        SELECT episode_id,route_kind,room_id
        FROM {ATTACHMENT_TABLE}
        WHERE attachment_event_id=?
        """,
        (room_attachment_event_id,),
    ).fetchone()
    if (
        row is None
        or row["episode_id"] != episode_id
        or row["route_kind"] != "attached"
        or row["room_id"] != room_id
    ):
        raise CurrentStoreIntegrityError(
            "Room Current attachment provenance is invalid"
        )

def _insert_bindings(
    connection: sqlite3.Connection,
    table: str,
    parent_column: str,
    parent_id: str,
    bindings: tuple[CurrentSourceBinding, ...],
) -> None:
    for position, binding in enumerate(bindings):
        evidence = binding.evidence
        connection.execute(
            f"""INSERT INTO {table} ({parent_column},position,source_ref,
                source_id,source_sha256,start_char,end_char) VALUES (?,?,?,?,?,?,?)""",
            (
                parent_id, position, binding.source_ref, evidence.source_id,
                evidence.source_sha256, evidence.start_char, evidence.end_char,
            ),
        )


def _read_bindings(
    connection: sqlite3.Connection, table: str, parent_column: str, parent_id: str
) -> tuple[CurrentSourceBinding, ...]:
    rows = connection.execute(
        f"""SELECT position,source_ref,source_id,source_sha256,start_char,end_char
            FROM {table} WHERE {parent_column}=? ORDER BY position""", (parent_id,)
    ).fetchall()
    if tuple(r["position"] for r in rows) != tuple(range(len(rows))):
        raise CurrentStoreIntegrityError("Current evidence positions must be contiguous")
    refs = tuple(r["source_ref"] for r in rows)
    if len(set(refs)) != len(refs):
        raise CurrentStoreIntegrityError("Current evidence source_ref is duplicated")
    return tuple(
        CurrentSourceBinding(
            source_ref=r["source_ref"],
            evidence=EvidenceRef(
                source_id=r["source_id"], source_sha256=r["source_sha256"],
                start_char=r["start_char"], end_char=r["end_char"],
            ),
        )
        for r in rows
    )


def _state_payload(record: CurrentStateRecord) -> str:
    return json.dumps(
        {
            "value": record.value,
            "event_time": record.event_time.isoformat(),
            "recorded_at": record.recorded_at.isoformat(),
            "valid_from": record.valid_from.isoformat(),
            "validity_rule": record.validity_rule.value,
            "downgrade_rule": record.downgrade_rule.value,
            "valid_until": None if record.valid_until is None else record.valid_until.isoformat(),
            "stale_after_us": None if record.stale_after is None else str(_duration_us(record.stale_after)),
            "source_refs": list(record.source_refs),
        },
        sort_keys=True, separators=(",", ":"),
    )


def _end_payload(event: CurrentStateEndEvent) -> str:
    return json.dumps(
        {
            "ended_at": event.ended_at.isoformat(),
            "recorded_at": event.recorded_at.isoformat(),
            "end_kind": event.end_kind.value,
            "reason": event.reason,
            "source_refs": list(event.source_refs),
        },
        sort_keys=True, separators=(",", ":"),
    )


def _state_from_row(
    row: sqlite3.Row, bindings: tuple[CurrentSourceBinding, ...]
) -> CurrentStateRecord:
    payload = json.loads(row["payload_json"])
    required = {
        "value", "event_time", "recorded_at", "valid_from",
        "validity_rule", "downgrade_rule", "valid_until", "stale_after_us",
        "source_refs",
    }
    if set(payload) != required:
        raise CurrentStoreIntegrityError("Current state payload shape is invalid")
    return CurrentStateRecord(
        state_id=row["state_id"], namespace=CurrentNamespace(row["namespace"]),
        owner_id=row["owner_id"], key=row["key"],
        state_kind=CurrentStateKind(row["state_kind"]), value=payload["value"],
        event_time=_dt(payload["event_time"]), recorded_at=_dt(payload["recorded_at"]),
        valid_from=_dt(payload["valid_from"]),
        validity_rule=ValidityRule(payload["validity_rule"]),
        downgrade_rule=DowngradeRule(payload["downgrade_rule"]),
        semantic_change_authority=SemanticChangeAuthority(row["semantic_change_authority"]),
        episode_id=row["episode_id"], perspective_instance_id=row["perspective_instance_id"],
        valid_until=None if payload["valid_until"] is None else _dt(payload["valid_until"]),
        stale_after=None if payload["stale_after_us"] is None else _td(payload["stale_after_us"]),
        supersedes_state_id=row["supersedes_state_id"],
        source_refs=_sealed_source_refs(payload["source_refs"], bindings),
    )


def _end_from_row(
    row: sqlite3.Row, bindings: tuple[CurrentSourceBinding, ...]
) -> CurrentStateEndEvent:
    payload = json.loads(row["payload_json"])
    if set(payload) != {"ended_at", "recorded_at", "end_kind", "reason", "source_refs"}:
        raise CurrentStoreIntegrityError("Current end-event payload shape is invalid")
    return CurrentStateEndEvent(
        end_event_id=row["end_event_id"], state_id=row["state_id"],
        ended_at=_dt(payload["ended_at"]), recorded_at=_dt(payload["recorded_at"]),
        end_kind=EndKind(payload["end_kind"]), reason=payload["reason"],
        semantic_change_authority=SemanticChangeAuthority(row["semantic_change_authority"]),
        episode_id=row["episode_id"], perspective_instance_id=row["perspective_instance_id"],
        source_refs=_sealed_source_refs(payload["source_refs"], bindings),
    )


def _assert_binding_table_integrity(
    connection: sqlite3.Connection,
    *,
    child_table: str,
    parent_table: str,
    parent_column: str,
    declared_count_column: str,
) -> None:
    orphan = connection.execute(
        f"""
        SELECT 1
        FROM {child_table} AS child
        LEFT JOIN {parent_table} AS parent
          ON parent.{parent_column}=child.{parent_column}
        WHERE parent.{parent_column} IS NULL
        LIMIT 1
        """
    ).fetchone()
    if orphan is not None:
        raise CurrentStoreIntegrityError(
            "Current evidence binding has no parent record"
        )

    mismatch = connection.execute(
        f"""
        SELECT 1
        FROM {parent_table} AS parent
        LEFT JOIN {child_table} AS child
          ON child.{parent_column}=parent.{parent_column}
        GROUP BY parent.{parent_column}, parent.{declared_count_column}
        HAVING COUNT(child.position)<>parent.{declared_count_column}
        LIMIT 1
        """
    ).fetchone()
    if mismatch is not None:
        raise CurrentStoreIntegrityError(
            "Current evidence binding count differs from sealed parent declaration"
        )


def _validate_evidence_coordinates(evidence: EvidenceRef) -> None:
    if (
        type(evidence.start_char) is not int
        or type(evidence.end_char) is not int
    ):
        raise CurrentStoreIntegrityError(
            "Current evidence coordinates must be integer Python str indices"
        )


def _sealed_source_refs(
    payload_value: object,
    bindings: tuple[CurrentSourceBinding, ...],
) -> tuple[str, ...]:
    if (
        not isinstance(payload_value, list)
        or not payload_value
        or any(
            not isinstance(item, str) or not item.strip()
            for item in payload_value
        )
    ):
        raise CurrentStoreIntegrityError(
            "Current payload source_refs declaration is invalid"
        )
    declared = tuple(payload_value)
    actual = tuple(binding.source_ref for binding in bindings)
    if declared != actual:
        raise CurrentStoreIntegrityError(
            "Current payload source_refs differ from sealed evidence bindings"
        )
    return declared


def _dt(value: object) -> datetime:
    if not isinstance(value, str):
        raise CurrentStoreIntegrityError("Current datetime payload must be text")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise CurrentStoreIntegrityError("Current datetime payload is naive")
    return result


def _td(value: object) -> timedelta:
    try:
        micros = int(value)
    except (TypeError, ValueError) as error:
        raise CurrentStoreIntegrityError("stale_after_us is not an integer scalar") from error
    if micros <= 0:
        raise CurrentStoreIntegrityError("stale_after_us must be positive")
    days, remainder = divmod(micros, 86_400_000_000)
    seconds, microseconds = divmod(remainder, 1_000_000)
    try:
        return timedelta(days=days, seconds=seconds, microseconds=microseconds)
    except OverflowError as error:
        raise CurrentStoreIntegrityError("stale_after_us exceeds timedelta domain") from error


def _instant(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CurrentStoreIntegrityError("Current persistence requires aware datetime")
    offset = value.utcoffset()
    assert offset is not None
    wall = (((value.toordinal() * 24 + value.hour) * 60 + value.minute) * 60 + value.second)
    return wall * 1_000_000 + value.microsecond - _duration_us(offset)


def _duration_us(value: timedelta) -> int:
    return value.days * 86_400_000_000 + value.seconds * 1_000_000 + value.microseconds


def _text(field: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CurrentStoreIntegrityError(f"{field} must be non-empty text")