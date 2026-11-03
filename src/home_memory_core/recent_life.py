from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from home_memory_core.home_state_ordering import (
    home_state_coordinator_for_path,
)
from home_memory_core.interpretation import (
    SYNTHETIC_UNATTRIBUTED_INSTANCE_ID,
)
from home_memory_core.living_store import (
    assert_living_data_integrity,
    assert_living_schema,
)
from home_memory_core.storage import (
    MemoryStore,
    assert_source_suppression_ledger,
)
from home_memory_core.store_domain import (
    assert_synthetic_store_domain,
)


RECENT_LIFE_SCHEMA_VERSION = "recent-life-v0.1"
RECENT_LIFE_SCHEMA_MARKER_TABLE = "recent_life_schema_marker"
RECENT_LIFE_EVENT_TABLE = "recent_life_events"
RECENT_LIFE_SOURCE_TABLE = "recent_life_event_sources"
RECENT_LIFE_WINDOW_LIMIT = 4

RECENT_LIFE_SCHEMA_TABLES = frozenset(
    {
        RECENT_LIFE_SCHEMA_MARKER_TABLE,
        RECENT_LIFE_EVENT_TABLE,
        RECENT_LIFE_SOURCE_TABLE,
    }
)


class RecentLifeError(RuntimeError):
    """Recent Life persistence or provenance is invalid."""


class RecentLifeIntegrityError(RecentLifeError):
    """Persisted Recent Life schema/data is inconsistent."""


@dataclass(frozen=True)
class RecentLifeEvent:
    event_id: str
    room_id: str
    episode_id: str
    perspective_instance_id: str
    room_attachment_event_id: str
    summary: str
    occurred_at: datetime
    recorded_at: datetime
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "room_id",
            "episode_id",
            "perspective_instance_id",
            "room_attachment_event_id",
            "summary",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise RecentLifeError(
                    f"{name} must be non-empty exact str"
                )
        if (
            self.perspective_instance_id
            == SYNTHETIC_UNATTRIBUTED_INSTANCE_ID
        ):
            raise RecentLifeError(
                "Recent Life requires concrete Perspective attribution"
            )
        _aware("occurred_at", self.occurred_at)
        _aware("recorded_at", self.recorded_at)
        if _instant(self.occurred_at) > _instant(self.recorded_at):
            raise RecentLifeError(
                "Recent Life event cannot be recorded before it occurred"
            )
        if (
            not isinstance(self.source_refs, tuple)
            or not self.source_refs
            or any(
                type(item) is not str
                or not item.strip()
                for item in self.source_refs
            )
            or len(set(self.source_refs)) != len(self.source_refs)
        ):
            raise RecentLifeError(
                "Recent Life requires unique source provenance refs"
            )


class RecentLifeStore:
    """Append-only, source-backed recent-life events for one HOME database."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._coordinator = home_state_coordinator_for_path(
            self.db_path
        )

    def initialize(self) -> None:
        connection = self._connect()
        try:
            assert_synthetic_store_domain(connection)
            assert_living_schema(connection)
            assert_living_data_integrity(connection)
            assert_source_suppression_ledger(connection)
            existing = _existing_tables(connection)
            if existing:
                if existing != RECENT_LIFE_SCHEMA_TABLES:
                    raise RecentLifeIntegrityError(
                        "partial Recent Life schema exists"
                    )
                assert_recent_life_schema(connection)
                return
            connection.executescript(_schema_script())
            assert_recent_life_schema(connection)
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def add_event(self, event: RecentLifeEvent) -> None:
        if not isinstance(event, RecentLifeEvent):
            raise TypeError(
                "event must be RecentLifeEvent"
            )
        with self._write_transaction() as connection:
            episode = connection.execute(
                """
                SELECT perspective_instance_id
                FROM living_episodes
                WHERE episode_id = ?
                """,
                (event.episode_id,),
            ).fetchone()
            if (
                episode is None
                or episode["perspective_instance_id"]
                != event.perspective_instance_id
            ):
                raise RecentLifeError(
                    "Recent Life Episode/Perspective attribution is not canonical"
                )
            room = connection.execute(
                """
                SELECT 1
                FROM living_rooms
                WHERE room_id = ?
                """,
                (event.room_id,),
            ).fetchone()
            if room is None:
                raise RecentLifeError(
                    "Recent Life Room does not exist"
                )
            attachment = connection.execute(
                """
                SELECT
                    episode_id,
                    route_kind,
                    room_id
                FROM living_room_attachment_events
                WHERE attachment_event_id = ?
                """,
                (
                    event.room_attachment_event_id,
                ),
            ).fetchone()
            if (
                attachment is None
                or attachment["episode_id"]
                != event.episode_id
                or attachment["route_kind"]
                != "attached"
                or attachment["room_id"]
                != event.room_id
            ):
                raise RecentLifeError(
                    "Recent Life Room attribution lacks matching attachment evidence"
                )

            memory = MemoryStore(self.db_path)
            suppressed = (
                memory._get_suppressed_source_ids_from_connection(
                    connection=connection
                )
            )
            for source_id in event.source_refs:
                source = memory._get_source_from_connection(
                    connection=connection,
                    source_id=source_id,
                )
                if source.scope != event.room_id:
                    raise RecentLifeError(
                        "Recent Life source scope differs from Room"
                    )
                if source_id in suppressed:
                    raise RecentLifeError(
                        "Recent Life cannot be created from suppressed source"
                    )

            try:
                connection.execute(
                    f"""
                    INSERT INTO {RECENT_LIFE_EVENT_TABLE} (
                        event_id,
                        room_id,
                        episode_id,
                        perspective_instance_id,
                        room_attachment_event_id,
                        summary,
                        occurred_instant_us,
                        occurred_at_iso,
                        recorded_instant_us,
                        recorded_at_iso
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.room_id,
                        event.episode_id,
                        event.perspective_instance_id,
                        event.room_attachment_event_id,
                        event.summary,
                        _instant(event.occurred_at),
                        _iso(event.occurred_at),
                        _instant(event.recorded_at),
                        _iso(event.recorded_at),
                    ),
                )
                for position, source_id in enumerate(
                    event.source_refs
                ):
                    connection.execute(
                        f"""
                        INSERT INTO {RECENT_LIFE_SOURCE_TABLE} (
                            event_id,
                            position,
                            source_id
                        ) VALUES (?, ?, ?)
                        """,
                        (
                            event.event_id,
                            position,
                            source_id,
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                raise RecentLifeError(
                    "Recent Life event conflicts with canonical persistence"
                ) from exc

    @staticmethod
    def schema_available(
        connection: sqlite3.Connection,
    ) -> bool:
        existing = _existing_tables(connection)
        if not existing:
            return False
        if existing != RECENT_LIFE_SCHEMA_TABLES:
            raise RecentLifeIntegrityError(
                "partial Recent Life schema exists"
            )
        assert_recent_life_schema(connection)
        return True

    @staticmethod
    def read_recent_for_room_in_connection(
        connection: sqlite3.Connection,
        *,
        room_id: str,
        as_of: datetime,
        limit: int = RECENT_LIFE_WINDOW_LIMIT,
    ) -> tuple[RecentLifeEvent, ...]:
        if type(room_id) is not str or not room_id.strip():
            raise RecentLifeError(
                "room_id must be non-empty exact str"
            )
        _aware("as_of", as_of)
        if type(limit) is not int or limit < 1 or limit > 12:
            raise RecentLifeError(
                "Recent Life limit must be exact int in 1..12"
            )
        if not RecentLifeStore.schema_available(connection):
            return ()

        assert_source_suppression_ledger(connection)
        rows = connection.execute(
            f"""
            SELECT
                event_id,
                room_id,
                episode_id,
                perspective_instance_id,
                room_attachment_event_id,
                summary,
                occurred_instant_us,
                occurred_at_iso,
                recorded_instant_us,
                recorded_at_iso
            FROM {RECENT_LIFE_EVENT_TABLE}
            WHERE room_id = ?
              AND occurred_instant_us <= ?
              AND recorded_instant_us <= ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM {RECENT_LIFE_SOURCE_TABLE} AS event_sources
                  JOIN source_suppressions AS suppressions
                    ON suppressions.source_id = event_sources.source_id
                  WHERE event_sources.event_id =
                        {RECENT_LIFE_EVENT_TABLE}.event_id
              )
            ORDER BY
                occurred_instant_us DESC,
                recorded_instant_us DESC,
                event_id DESC
            LIMIT ?
            """,
            (
                room_id,
                _instant(as_of),
                _instant(as_of),
                limit,
            ),
        ).fetchall()

        result: list[RecentLifeEvent] = []
        for row in rows:
            source_rows = connection.execute(
                f"""
                SELECT source_id
                FROM {RECENT_LIFE_SOURCE_TABLE}
                WHERE event_id = ?
                ORDER BY position
                """,
                (row["event_id"],),
            ).fetchall()
            result.append(
                RecentLifeEvent(
                    event_id=row["event_id"],
                    room_id=row["room_id"],
                    episode_id=row["episode_id"],
                    perspective_instance_id=(
                        row["perspective_instance_id"]
                    ),
                    room_attachment_event_id=(
                        row["room_attachment_event_id"]
                    ),
                    summary=row["summary"],
                    occurred_at=_from_iso(
                        row["occurred_at_iso"]
                    ),
                    recorded_at=_from_iso(
                        row["recorded_at_iso"]
                    ),
                    source_refs=tuple(
                        item["source_id"]
                        for item in source_rows
                    ),
                )
            )
        return tuple(result)

    @contextmanager
    def _write_transaction(
        self,
    ) -> Iterator[sqlite3.Connection]:
        permit = self._coordinator.acquire_writer()
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            assert_synthetic_store_domain(connection)
            assert_living_schema(connection)
            assert_living_data_integrity(connection)
            assert_source_suppression_ledger(connection)
            assert_recent_life_schema(connection)
            yield connection
            connection.commit()
            permit.record_successful_commit()
        except BaseException:
            if (
                connection is not None
                and connection.in_transaction
            ):
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()
            permit.release()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def assert_recent_life_schema(
    connection: sqlite3.Connection,
) -> None:
    expected = {
        item["name"]: _normalize(item["sql"])
        for item in _reference_schema_objects()
    }
    rows = connection.execute(
        """
        SELECT name, sql
        FROM sqlite_master
        WHERE (
            type = 'table'
            AND name IN (?, ?, ?)
        ) OR (
            type = 'trigger'
            AND name LIKE 'recent_life_%'
        )
        """,
        (
            RECENT_LIFE_SCHEMA_MARKER_TABLE,
            RECENT_LIFE_EVENT_TABLE,
            RECENT_LIFE_SOURCE_TABLE,
        ),
    ).fetchall()
    actual = {
        row["name"]: _normalize(row["sql"])
        for row in rows
        if row["sql"] is not None
    }
    if actual != expected:
        raise RecentLifeIntegrityError(
            "Recent Life schema definitions drifted"
        )


def _schema_script() -> str:
    return f"""
        BEGIN IMMEDIATE;

        CREATE TABLE {RECENT_LIFE_SCHEMA_MARKER_TABLE} (
            marker_key TEXT PRIMARY KEY
                CHECK(marker_key = 'recent_life_schema'),
            schema_version TEXT NOT NULL
                CHECK(schema_version = '{RECENT_LIFE_SCHEMA_VERSION}')
        );

        INSERT INTO {RECENT_LIFE_SCHEMA_MARKER_TABLE} (
            marker_key,
            schema_version
        ) VALUES (
            'recent_life_schema',
            '{RECENT_LIFE_SCHEMA_VERSION}'
        );

        CREATE TABLE {RECENT_LIFE_EVENT_TABLE} (
            event_id TEXT PRIMARY KEY
                CHECK(length(trim(event_id)) > 0),
            room_id TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            perspective_instance_id TEXT NOT NULL
                CHECK(length(trim(perspective_instance_id)) > 0),
            room_attachment_event_id TEXT NOT NULL
                CHECK(length(trim(room_attachment_event_id)) > 0),
            summary TEXT NOT NULL
                CHECK(length(trim(summary)) > 0),
            occurred_instant_us INTEGER NOT NULL,
            occurred_at_iso TEXT NOT NULL
                CHECK(length(trim(occurred_at_iso)) > 0),
            recorded_instant_us INTEGER NOT NULL,
            recorded_at_iso TEXT NOT NULL
                CHECK(length(trim(recorded_at_iso)) > 0),
            CHECK(occurred_instant_us <= recorded_instant_us),
            FOREIGN KEY(room_id)
                REFERENCES living_rooms(room_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            FOREIGN KEY(episode_id)
                REFERENCES living_episodes(episode_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            FOREIGN KEY(room_attachment_event_id)
                REFERENCES living_room_attachment_events(attachment_event_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT
        );

        CREATE TABLE {RECENT_LIFE_SOURCE_TABLE} (
            event_id TEXT NOT NULL,
            position INTEGER NOT NULL
                CHECK(position >= 0),
            source_id TEXT NOT NULL,
            PRIMARY KEY(event_id, position),
            UNIQUE(event_id, source_id),
            FOREIGN KEY(event_id)
                REFERENCES {RECENT_LIFE_EVENT_TABLE}(event_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            FOREIGN KEY(source_id)
                REFERENCES sources(source_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT
        ) WITHOUT ROWID;

        CREATE TRIGGER recent_life_schema_marker_no_update
        BEFORE UPDATE ON {RECENT_LIFE_SCHEMA_MARKER_TABLE}
        BEGIN
            SELECT RAISE(ABORT,'Recent Life schema marker is immutable');
        END;

        CREATE TRIGGER recent_life_schema_marker_no_delete
        BEFORE DELETE ON {RECENT_LIFE_SCHEMA_MARKER_TABLE}
        BEGIN
            SELECT RAISE(ABORT,'Recent Life schema marker is immutable');
        END;

        CREATE TRIGGER recent_life_events_no_replace
        BEFORE INSERT ON {RECENT_LIFE_EVENT_TABLE}
        WHEN EXISTS(
            SELECT 1 FROM {RECENT_LIFE_EVENT_TABLE}
            WHERE event_id = NEW.event_id
        )
        BEGIN
            SELECT RAISE(ABORT,'Recent Life event id already exists');
        END;

        CREATE TRIGGER recent_life_events_no_update
        BEFORE UPDATE ON {RECENT_LIFE_EVENT_TABLE}
        BEGIN
            SELECT RAISE(ABORT,'Recent Life events are append-only');
        END;

        CREATE TRIGGER recent_life_events_no_delete
        BEFORE DELETE ON {RECENT_LIFE_EVENT_TABLE}
        BEGIN
            SELECT RAISE(ABORT,'Recent Life events are append-only');
        END;

        CREATE TRIGGER recent_life_event_sources_no_replace
        BEFORE INSERT ON {RECENT_LIFE_SOURCE_TABLE}
        WHEN EXISTS(
            SELECT 1 FROM {RECENT_LIFE_SOURCE_TABLE}
            WHERE event_id = NEW.event_id
              AND (
                  position = NEW.position
                  OR source_id = NEW.source_id
              )
        )
        BEGIN
            SELECT RAISE(ABORT,'Recent Life source binding already exists');
        END;

        CREATE TRIGGER recent_life_event_sources_no_update
        BEFORE UPDATE ON {RECENT_LIFE_SOURCE_TABLE}
        BEGIN
            SELECT RAISE(ABORT,'Recent Life source bindings are append-only');
        END;

        CREATE TRIGGER recent_life_event_sources_no_delete
        BEFORE DELETE ON {RECENT_LIFE_SOURCE_TABLE}
        BEGIN
            SELECT RAISE(ABORT,'Recent Life source bindings are append-only');
        END;

        COMMIT;
    """


def _reference_schema_objects() -> tuple[sqlite3.Row, ...]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(
            """
            CREATE TABLE living_rooms(room_id TEXT PRIMARY KEY);
            CREATE TABLE living_episodes(
                episode_id TEXT PRIMARY KEY,
                perspective_instance_id TEXT
            );
            CREATE TABLE living_room_attachment_events(
                attachment_event_id TEXT PRIMARY KEY,
                episode_id TEXT,
                route_kind TEXT,
                room_id TEXT
            );
            CREATE TABLE sources(source_id TEXT PRIMARY KEY);
            """
        )
        connection.executescript(_schema_script())
        return tuple(
            connection.execute(
                """
                SELECT name, sql
                FROM sqlite_master
                WHERE (
                    type = 'table'
                    AND name IN (?, ?, ?)
                ) OR (
                    type = 'trigger'
                    AND name LIKE 'recent_life_%'
                )
                ORDER BY name
                """,
                (
                    RECENT_LIFE_SCHEMA_MARKER_TABLE,
                    RECENT_LIFE_EVENT_TABLE,
                    RECENT_LIFE_SOURCE_TABLE,
                ),
            ).fetchall()
        )
    finally:
        connection.close()


def _existing_tables(
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
    return frozenset(
        names.intersection(
            RECENT_LIFE_SCHEMA_TABLES
        )
    )


def _normalize(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(
        value.replace("\n", " ").split()
    ).lower()


def _aware(
    name: str,
    value: datetime,
) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise RecentLifeError(
            f"{name} must be timezone-aware datetime"
        )


def _instant(value: datetime) -> int:
    _aware("datetime", value)
    utc = value.astimezone(timezone.utc)
    epoch = datetime(
        1970,
        1,
        1,
        tzinfo=timezone.utc,
    )
    delta = utc - epoch
    return (
        (delta.days * 86_400 + delta.seconds)
        * 1_000_000
        + delta.microseconds
    )


def _iso(value: datetime) -> str:
    _aware("datetime", value)
    return value.isoformat(timespec="microseconds")


def _from_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise RecentLifeIntegrityError(
            "Recent Life stored datetime is invalid"
        ) from exc
    _aware("stored datetime", parsed)
    return parsed
