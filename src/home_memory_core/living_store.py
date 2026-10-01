from __future__ import annotations

from pathlib import Path
import sqlite3

from home_memory_core.living_continuity import (
    ContinuityEdge,
    ContinuityStatus,
    ContinuityTopology,
    EpisodeRecord,
    LivingContinuityError,
    RoomAttachmentEvent,
    RoomAttachmentResolution,
    RoomRecord,
    RoomRouteKind,
    TransferMode,
    resolve_continuity_topology,
    resolve_room_attachment,
)
from home_memory_core.store_domain import assert_synthetic_store_domain


LIVING_SCHEMA_VERSION = "living-layer-v0.1"
LIVING_SCHEMA_MARKER_TABLE = "living_schema_marker"
ROOM_TABLE = "living_rooms"
EPISODE_TABLE = "living_episodes"
CONTINUITY_EDGE_TABLE = "living_continuity_edges"
CONTINUITY_SUPPORT_TABLE = "living_continuity_support"
ATTACHMENT_TABLE = "living_room_attachment_events"
ATTACHMENT_SUPPORT_TABLE = "living_room_attachment_support"

_REQUIRED_TABLES = frozenset(
    {
        LIVING_SCHEMA_MARKER_TABLE,
        ROOM_TABLE,
        EPISODE_TABLE,
        CONTINUITY_EDGE_TABLE,
        CONTINUITY_SUPPORT_TABLE,
        ATTACHMENT_TABLE,
        ATTACHMENT_SUPPORT_TABLE,
    }
)

_REQUIRED_TRIGGERS = frozenset(
    {
        "living_schema_marker_no_update",
        "living_schema_marker_no_delete",
        "living_rooms_no_update",
        "living_rooms_no_delete",
        "living_episodes_no_update",
        "living_episodes_no_delete",
        "living_continuity_edges_no_update",
        "living_continuity_edges_no_delete",
        "living_continuity_support_no_update",
        "living_continuity_support_no_delete",
        "living_room_attachment_events_no_update",
        "living_room_attachment_events_no_delete",
        "living_room_attachment_support_no_update",
        "living_room_attachment_support_no_delete",
    }
)


class LivingStoreError(RuntimeError):
    """Base error for Living Layer persistence."""


class LivingStoreIntegrityError(LivingStoreError):
    """Persisted Living Layer state is missing or internally inconsistent."""


class LivingStoreConflictError(LivingStoreError):
    """A write conflicts with an existing immutable Living Layer record."""


class LivingStore:
    """Synthetic-only persistence for the first HOME Living Layer slice.

    This store deliberately does not enable real-data use, model delivery,
    identity adjudication, Current View, Shared Space, or Wake Packet behavior.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        """Install the Living Layer schema inside an existing synthetic HOME store.

        The caller must initialize the ordinary synthetic HOME store first. This
        method never creates or upgrades the HOME store-domain marker itself.
        """

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            assert_synthetic_store_domain(connection)

            existing = self._existing_living_tables(connection)
            if existing:
                if existing != _REQUIRED_TABLES:
                    raise LivingStoreIntegrityError(
                        "partial Living Layer schema exists"
                    )
                assert_living_schema(connection)
                connection.commit()
                return

            connection.executescript(
                f"""
                CREATE TABLE {LIVING_SCHEMA_MARKER_TABLE} (
                    marker_key TEXT PRIMARY KEY
                        CHECK (marker_key = 'living_layer_schema'),
                    schema_version TEXT NOT NULL
                        CHECK (schema_version = '{LIVING_SCHEMA_VERSION}')
                );

                INSERT INTO {LIVING_SCHEMA_MARKER_TABLE} (
                    marker_key,
                    schema_version
                ) VALUES (
                    'living_layer_schema',
                    '{LIVING_SCHEMA_VERSION}'
                );

                CREATE TABLE {ROOM_TABLE} (
                    room_id TEXT PRIMARY KEY
                        CHECK (length(trim(room_id)) > 0)
                );

                CREATE TABLE {EPISODE_TABLE} (
                    episode_id TEXT PRIMARY KEY
                        CHECK (length(trim(episode_id)) > 0),
                    perspective_instance_id TEXT NOT NULL
                        CHECK (length(trim(perspective_instance_id)) > 0),
                    runtime_instance_id TEXT
                        CHECK (
                            runtime_instance_id IS NULL
                            OR length(trim(runtime_instance_id)) > 0
                        ),
                    model_ref TEXT
                        CHECK (
                            model_ref IS NULL
                            OR length(trim(model_ref)) > 0
                        )
                );

                CREATE TABLE {CONTINUITY_EDGE_TABLE} (
                    edge_id TEXT PRIMARY KEY
                        CHECK (length(trim(edge_id)) > 0),
                    previous_episode_id TEXT NOT NULL,
                    next_episode_id TEXT NOT NULL,
                    transfer_mode TEXT NOT NULL
                        CHECK (
                            transfer_mode IN (
                                'live_runtime',
                                'native_checkpoint_resume',
                                'partial_state_resume',
                                'history_reconstruction',
                                'text_context_handoff',
                                'no_known_transfer'
                            )
                        ),
                    continuity_status TEXT NOT NULL
                        CHECK (
                            continuity_status IN (
                                'verified',
                                'partial',
                                'unknown'
                            )
                        ),

                    UNIQUE (
                        previous_episode_id,
                        next_episode_id
                    ),

                    CHECK (
                        previous_episode_id <> next_episode_id
                    ),

                    FOREIGN KEY (previous_episode_id)
                        REFERENCES {EPISODE_TABLE}(episode_id)
                        ON UPDATE RESTRICT
                        ON DELETE RESTRICT,

                    FOREIGN KEY (next_episode_id)
                        REFERENCES {EPISODE_TABLE}(episode_id)
                        ON UPDATE RESTRICT
                        ON DELETE RESTRICT
                );

                CREATE TABLE {CONTINUITY_SUPPORT_TABLE} (
                    edge_id TEXT NOT NULL,
                    position INTEGER NOT NULL
                        CHECK (position >= 0),
                    support_ref TEXT NOT NULL
                        CHECK (length(trim(support_ref)) > 0),

                    PRIMARY KEY (edge_id, position),
                    UNIQUE (edge_id, support_ref),

                    FOREIGN KEY (edge_id)
                        REFERENCES {CONTINUITY_EDGE_TABLE}(edge_id)
                        ON UPDATE RESTRICT
                        ON DELETE RESTRICT
                );

                CREATE TABLE {ATTACHMENT_TABLE} (
                    attachment_event_id TEXT PRIMARY KEY
                        CHECK (length(trim(attachment_event_id)) > 0),
                    episode_id TEXT NOT NULL,
                    route_kind TEXT NOT NULL
                        CHECK (route_kind IN ('attached', 'unattached')),
                    room_id TEXT,
                    basis TEXT NOT NULL
                        CHECK (length(trim(basis)) > 0),
                    supersedes_attachment_event_id TEXT,

                    CHECK (
                        (
                            route_kind = 'attached'
                            AND room_id IS NOT NULL
                            AND length(trim(room_id)) > 0
                        )
                        OR
                        (
                            route_kind = 'unattached'
                            AND room_id IS NULL
                        )
                    ),

                    CHECK (
                        supersedes_attachment_event_id IS NULL
                        OR supersedes_attachment_event_id <> attachment_event_id
                    ),

                    FOREIGN KEY (episode_id)
                        REFERENCES {EPISODE_TABLE}(episode_id)
                        ON UPDATE RESTRICT
                        ON DELETE RESTRICT,

                    FOREIGN KEY (room_id)
                        REFERENCES {ROOM_TABLE}(room_id)
                        ON UPDATE RESTRICT
                        ON DELETE RESTRICT,

                    FOREIGN KEY (supersedes_attachment_event_id)
                        REFERENCES {ATTACHMENT_TABLE}(attachment_event_id)
                        ON UPDATE RESTRICT
                        ON DELETE RESTRICT
                );

                CREATE TABLE {ATTACHMENT_SUPPORT_TABLE} (
                    attachment_event_id TEXT NOT NULL,
                    position INTEGER NOT NULL
                        CHECK (position >= 0),
                    support_ref TEXT NOT NULL
                        CHECK (length(trim(support_ref)) > 0),

                    PRIMARY KEY (
                        attachment_event_id,
                        position
                    ),
                    UNIQUE (
                        attachment_event_id,
                        support_ref
                    ),

                    FOREIGN KEY (attachment_event_id)
                        REFERENCES {ATTACHMENT_TABLE}(attachment_event_id)
                        ON UPDATE RESTRICT
                        ON DELETE RESTRICT
                );

                CREATE TRIGGER living_schema_marker_no_update
                BEFORE UPDATE ON {LIVING_SCHEMA_MARKER_TABLE}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Living Layer schema marker is immutable'
                    );
                END;

                CREATE TRIGGER living_schema_marker_no_delete
                BEFORE DELETE ON {LIVING_SCHEMA_MARKER_TABLE}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Living Layer schema marker is immutable'
                    );
                END;

                CREATE TRIGGER living_rooms_no_update
                BEFORE UPDATE ON {ROOM_TABLE}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Living Layer rooms are append-only'
                    );
                END;

                CREATE TRIGGER living_rooms_no_delete
                BEFORE DELETE ON {ROOM_TABLE}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Living Layer rooms are append-only'
                    );
                END;

                CREATE TRIGGER living_episodes_no_update
                BEFORE UPDATE ON {EPISODE_TABLE}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Living Layer episodes are append-only'
                    );
                END;

                CREATE TRIGGER living_episodes_no_delete
                BEFORE DELETE ON {EPISODE_TABLE}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Living Layer episodes are append-only'
                    );
                END;

                CREATE TRIGGER living_continuity_edges_no_update
                BEFORE UPDATE ON {CONTINUITY_EDGE_TABLE}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Living Layer continuity edges are append-only'
                    );
                END;

                CREATE TRIGGER living_continuity_edges_no_delete
                BEFORE DELETE ON {CONTINUITY_EDGE_TABLE}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Living Layer continuity edges are append-only'
                    );
                END;

                CREATE TRIGGER living_continuity_support_no_update
                BEFORE UPDATE ON {CONTINUITY_SUPPORT_TABLE}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Living Layer continuity support is append-only'
                    );
                END;

                CREATE TRIGGER living_continuity_support_no_delete
                BEFORE DELETE ON {CONTINUITY_SUPPORT_TABLE}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Living Layer continuity support is append-only'
                    );
                END;

                CREATE TRIGGER living_room_attachment_events_no_update
                BEFORE UPDATE ON {ATTACHMENT_TABLE}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Living Layer room attachments are append-only'
                    );
                END;

                CREATE TRIGGER living_room_attachment_events_no_delete
                BEFORE DELETE ON {ATTACHMENT_TABLE}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Living Layer room attachments are append-only'
                    );
                END;

                CREATE TRIGGER living_room_attachment_support_no_update
                BEFORE UPDATE ON {ATTACHMENT_SUPPORT_TABLE}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Living Layer room attachment support is append-only'
                    );
                END;

                CREATE TRIGGER living_room_attachment_support_no_delete
                BEFORE DELETE ON {ATTACHMENT_SUPPORT_TABLE}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Living Layer room attachment support is append-only'
                    );
                END;
                """
            )

            assert_living_schema(connection)
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def add_room(self, room: RoomRecord) -> None:
        if not isinstance(room, RoomRecord):
            raise TypeError("room must be RoomRecord")

        connection = self._write_connection()
        try:
            connection.execute(
                f"INSERT INTO {ROOM_TABLE} (room_id) VALUES (?)",
                (room.room_id,),
            )
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise LivingStoreConflictError(
                f"room record conflicts with persisted state: {room.room_id}"
            ) from error
        finally:
            connection.close()

    def get_room(self, room_id: str) -> RoomRecord:
        connection = self._read_connection()
        try:
            row = connection.execute(
                f"SELECT room_id FROM {ROOM_TABLE} WHERE room_id = ?",
                (room_id,),
            ).fetchone()
            if row is None:
                raise KeyError(room_id)
            return RoomRecord(room_id=row["room_id"])
        finally:
            connection.close()

    def add_episode(self, episode: EpisodeRecord) -> None:
        if not isinstance(episode, EpisodeRecord):
            raise TypeError("episode must be EpisodeRecord")

        connection = self._write_connection()
        try:
            connection.execute(
                f"""
                INSERT INTO {EPISODE_TABLE} (
                    episode_id,
                    perspective_instance_id,
                    runtime_instance_id,
                    model_ref
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    episode.episode_id,
                    episode.perspective_instance_id,
                    episode.runtime_instance_id,
                    episode.model_ref,
                ),
            )
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise LivingStoreConflictError(
                "episode record conflicts with persisted state: "
                f"{episode.episode_id}"
            ) from error
        finally:
            connection.close()

    def get_episode(self, episode_id: str) -> EpisodeRecord:
        connection = self._read_connection()
        try:
            row = connection.execute(
                f"""
                SELECT
                    episode_id,
                    perspective_instance_id,
                    runtime_instance_id,
                    model_ref
                FROM {EPISODE_TABLE}
                WHERE episode_id = ?
                """,
                (episode_id,),
            ).fetchone()
            if row is None:
                raise KeyError(episode_id)
            return self._episode_from_row(row)
        finally:
            connection.close()

    def add_continuity_edge(self, edge: ContinuityEdge) -> None:
        if not isinstance(edge, ContinuityEdge):
            raise TypeError("edge must be ContinuityEdge")

        connection = self._write_connection()
        try:
            episodes = self._read_all_episodes(connection)
            existing_edges = self._read_all_continuity_edges(connection)

            try:
                resolve_continuity_topology(
                    episodes=episodes,
                    edges=existing_edges + (edge,),
                )
            except LivingContinuityError as error:
                raise LivingStoreIntegrityError(str(error)) from error

            connection.execute(
                f"""
                INSERT INTO {CONTINUITY_EDGE_TABLE} (
                    edge_id,
                    previous_episode_id,
                    next_episode_id,
                    transfer_mode,
                    continuity_status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    edge.edge_id,
                    edge.previous_episode_id,
                    edge.next_episode_id,
                    edge.transfer_mode.value,
                    edge.continuity_status.value,
                ),
            )
            self._insert_support_refs(
                connection=connection,
                table=CONTINUITY_SUPPORT_TABLE,
                owner_column="edge_id",
                owner_id=edge.edge_id,
                support_refs=edge.support_refs,
            )
            connection.commit()
        except (sqlite3.IntegrityError, LivingStoreIntegrityError) as error:
            connection.rollback()
            if isinstance(error, LivingStoreIntegrityError):
                raise
            raise LivingStoreConflictError(
                "continuity edge conflicts with persisted state: "
                f"{edge.edge_id}"
            ) from error
        finally:
            connection.close()

    def list_continuity_edges(self) -> tuple[ContinuityEdge, ...]:
        connection = self._read_connection()
        try:
            return self._read_all_continuity_edges(connection)
        finally:
            connection.close()

    def resolve_continuity_topology(self) -> ContinuityTopology:
        connection = self._read_connection()
        try:
            episodes = self._read_all_episodes(connection)
            edges = self._read_all_continuity_edges(connection)
            try:
                return resolve_continuity_topology(
                    episodes=episodes,
                    edges=edges,
                )
            except LivingContinuityError as error:
                raise LivingStoreIntegrityError(str(error)) from error
        finally:
            connection.close()

    def add_room_attachment(self, event: RoomAttachmentEvent) -> None:
        if not isinstance(event, RoomAttachmentEvent):
            raise TypeError("event must be RoomAttachmentEvent")

        connection = self._write_connection()
        try:
            episode_exists = connection.execute(
                f"SELECT 1 FROM {EPISODE_TABLE} WHERE episode_id = ?",
                (event.episode_id,),
            ).fetchone()
            if episode_exists is None:
                raise LivingStoreIntegrityError(
                    "room attachment episode is missing"
                )

            if event.route_kind is RoomRouteKind.ATTACHED:
                room_exists = connection.execute(
                    f"SELECT 1 FROM {ROOM_TABLE} WHERE room_id = ?",
                    (event.room_id,),
                ).fetchone()
                if room_exists is None:
                    raise LivingStoreIntegrityError(
                        "room attachment target room is missing"
                    )

            existing = self._read_room_attachment_events(
                connection,
                episode_id=event.episode_id,
            )
            try:
                resolve_room_attachment(
                    episode_id=event.episode_id,
                    events=existing + (event,),
                )
            except LivingContinuityError as error:
                raise LivingStoreIntegrityError(str(error)) from error

            connection.execute(
                f"""
                INSERT INTO {ATTACHMENT_TABLE} (
                    attachment_event_id,
                    episode_id,
                    route_kind,
                    room_id,
                    basis,
                    supersedes_attachment_event_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.attachment_event_id,
                    event.episode_id,
                    event.route_kind.value,
                    event.room_id,
                    event.basis,
                    event.supersedes_attachment_event_id,
                ),
            )
            self._insert_support_refs(
                connection=connection,
                table=ATTACHMENT_SUPPORT_TABLE,
                owner_column="attachment_event_id",
                owner_id=event.attachment_event_id,
                support_refs=event.support_refs,
            )
            connection.commit()
        except (sqlite3.IntegrityError, LivingStoreIntegrityError) as error:
            connection.rollback()
            if isinstance(error, LivingStoreIntegrityError):
                raise
            raise LivingStoreConflictError(
                "room attachment conflicts with persisted state: "
                f"{event.attachment_event_id}"
            ) from error
        finally:
            connection.close()

    def list_room_attachment_events(
        self,
        *,
        episode_id: str,
    ) -> tuple[RoomAttachmentEvent, ...]:
        connection = self._read_connection()
        try:
            return self._read_room_attachment_events(
                connection,
                episode_id=episode_id,
            )
        finally:
            connection.close()

    def resolve_room_attachment(
        self,
        *,
        episode_id: str,
    ) -> RoomAttachmentResolution:
        connection = self._read_connection()
        try:
            events = self._read_room_attachment_events(
                connection,
                episode_id=episode_id,
            )
            try:
                return resolve_room_attachment(
                    episode_id=episode_id,
                    events=events,
                )
            except LivingContinuityError as error:
                raise LivingStoreIntegrityError(str(error)) from error
        finally:
            connection.close()

    def _write_connection(self) -> sqlite3.Connection:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            assert_synthetic_store_domain(connection)
            assert_living_schema(connection)
            return connection
        except Exception:
            connection.close()
            raise

    def _read_connection(self) -> sqlite3.Connection:
        connection = self._connect()
        try:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            assert_synthetic_store_domain(connection)
            assert_living_schema(connection)
            return connection
        except Exception:
            connection.close()
            raise

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _existing_living_tables(
        self,
        connection: sqlite3.Connection,
    ) -> frozenset[str]:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()
        names = {row[0] for row in rows}
        return frozenset(names.intersection(_REQUIRED_TABLES))

    def _read_all_episodes(
        self,
        connection: sqlite3.Connection,
    ) -> tuple[EpisodeRecord, ...]:
        rows = connection.execute(
            f"""
            SELECT
                episode_id,
                perspective_instance_id,
                runtime_instance_id,
                model_ref
            FROM {EPISODE_TABLE}
            ORDER BY rowid
            """
        ).fetchall()
        return tuple(self._episode_from_row(row) for row in rows)

    def _episode_from_row(self, row: sqlite3.Row) -> EpisodeRecord:
        return EpisodeRecord(
            episode_id=row["episode_id"],
            perspective_instance_id=row["perspective_instance_id"],
            runtime_instance_id=row["runtime_instance_id"],
            model_ref=row["model_ref"],
        )

    def _read_all_continuity_edges(
        self,
        connection: sqlite3.Connection,
    ) -> tuple[ContinuityEdge, ...]:
        rows = connection.execute(
            f"""
            SELECT
                edge_id,
                previous_episode_id,
                next_episode_id,
                transfer_mode,
                continuity_status
            FROM {CONTINUITY_EDGE_TABLE}
            ORDER BY rowid
            """
        ).fetchall()

        result: list[ContinuityEdge] = []
        for row in rows:
            support_refs = self._read_support_refs(
                connection=connection,
                table=CONTINUITY_SUPPORT_TABLE,
                owner_column="edge_id",
                owner_id=row["edge_id"],
            )
            try:
                result.append(
                    ContinuityEdge(
                        edge_id=row["edge_id"],
                        previous_episode_id=row["previous_episode_id"],
                        next_episode_id=row["next_episode_id"],
                        transfer_mode=TransferMode(row["transfer_mode"]),
                        continuity_status=ContinuityStatus(
                            row["continuity_status"]
                        ),
                        support_refs=support_refs,
                    )
                )
            except (ValueError, LivingContinuityError) as error:
                raise LivingStoreIntegrityError(
                    "persisted continuity edge is invalid"
                ) from error
        return tuple(result)

    def _read_room_attachment_events(
        self,
        connection: sqlite3.Connection,
        *,
        episode_id: str,
    ) -> tuple[RoomAttachmentEvent, ...]:
        rows = connection.execute(
            f"""
            SELECT
                attachment_event_id,
                episode_id,
                route_kind,
                room_id,
                basis,
                supersedes_attachment_event_id
            FROM {ATTACHMENT_TABLE}
            WHERE episode_id = ?
            ORDER BY rowid
            """,
            (episode_id,),
        ).fetchall()

        result: list[RoomAttachmentEvent] = []
        for row in rows:
            support_refs = self._read_support_refs(
                connection=connection,
                table=ATTACHMENT_SUPPORT_TABLE,
                owner_column="attachment_event_id",
                owner_id=row["attachment_event_id"],
            )
            try:
                result.append(
                    RoomAttachmentEvent(
                        attachment_event_id=row["attachment_event_id"],
                        episode_id=row["episode_id"],
                        route_kind=RoomRouteKind(row["route_kind"]),
                        room_id=row["room_id"],
                        basis=row["basis"],
                        supersedes_attachment_event_id=(
                            row["supersedes_attachment_event_id"]
                        ),
                        support_refs=support_refs,
                    )
                )
            except (ValueError, LivingContinuityError) as error:
                raise LivingStoreIntegrityError(
                    "persisted room attachment is invalid"
                ) from error
        return tuple(result)

    def _insert_support_refs(
        self,
        *,
        connection: sqlite3.Connection,
        table: str,
        owner_column: str,
        owner_id: str,
        support_refs: tuple[str, ...],
    ) -> None:
        if table not in {
            CONTINUITY_SUPPORT_TABLE,
            ATTACHMENT_SUPPORT_TABLE,
        }:
            raise ValueError("unsupported Living Layer support table")
        if owner_column not in {
            "edge_id",
            "attachment_event_id",
        }:
            raise ValueError("unsupported Living Layer support owner")

        for position, support_ref in enumerate(support_refs):
            connection.execute(
                f"""
                INSERT INTO {table} (
                    {owner_column},
                    position,
                    support_ref
                ) VALUES (?, ?, ?)
                """,
                (owner_id, position, support_ref),
            )

    def _read_support_refs(
        self,
        *,
        connection: sqlite3.Connection,
        table: str,
        owner_column: str,
        owner_id: str,
    ) -> tuple[str, ...]:
        rows = connection.execute(
            f"""
            SELECT position, support_ref
            FROM {table}
            WHERE {owner_column} = ?
            ORDER BY position
            """,
            (owner_id,),
        ).fetchall()

        expected = list(range(len(rows)))
        actual = [row["position"] for row in rows]
        if actual != expected:
            raise LivingStoreIntegrityError(
                "persisted Living Layer support positions are incomplete"
            )
        return tuple(row["support_ref"] for row in rows)


def assert_living_schema(connection: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if not _REQUIRED_TABLES.issubset(tables):
        raise LivingStoreIntegrityError(
            "Living Layer schema is missing or incomplete"
        )

    marker_rows = connection.execute(
        f"""
        SELECT schema_version
        FROM {LIVING_SCHEMA_MARKER_TABLE}
        WHERE marker_key = 'living_layer_schema'
        """
    ).fetchall()
    marker_versions = [row[0] for row in marker_rows]
    if marker_versions != [LIVING_SCHEMA_VERSION]:
        raise LivingStoreIntegrityError(
            "Living Layer schema marker is invalid"
        )

    triggers = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
    }
    if not _REQUIRED_TRIGGERS.issubset(triggers):
        raise LivingStoreIntegrityError(
            "Living Layer append-only triggers are incomplete"
        )
