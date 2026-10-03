from __future__ import annotations

from functools import lru_cache
import re
import sqlite3

from home_memory_core.interpretation import SYNTHETIC_UNATTRIBUTED_INSTANCE_ID
from home_memory_core.living_store import ATTACHMENT_TABLE, EPISODE_TABLE, ROOM_TABLE


CURRENT_SCHEMA_VERSION = "current-persistence-v0.1"
CURRENT_SCHEMA_MARKER_TABLE = "current_schema_marker"
CURRENT_STATE_TABLE = "current_state_records"
CURRENT_STATE_EVIDENCE_TABLE = "current_state_evidence_bindings"
CURRENT_END_TABLE = "current_state_end_events"
CURRENT_END_EVIDENCE_TABLE = "current_end_evidence_bindings"
CURRENT_TABLES = frozenset({
    CURRENT_SCHEMA_MARKER_TABLE,
    CURRENT_STATE_TABLE,
    CURRENT_STATE_EVIDENCE_TABLE,
    CURRENT_END_TABLE,
    CURRENT_END_EVIDENCE_TABLE,
})
CURRENT_TRIGGERS = frozenset({
    "current_schema_marker_no_update", "current_schema_marker_no_delete",
    "current_state_no_replace", "current_state_no_update", "current_state_no_delete",
    "current_state_room_exists", "current_state_room_episode_binding",
    "current_state_room_attachment_binding", "current_state_supersession_line",
    "current_state_evidence_no_replace", "current_state_evidence_no_update",
    "current_state_evidence_no_delete", "current_state_evidence_exact_source",
    "current_state_evidence_not_suppressed",
    "current_end_no_replace", "current_end_no_update", "current_end_no_delete",
    "current_end_target_binding",
    "current_end_evidence_no_replace", "current_end_evidence_no_update",
    "current_end_evidence_no_delete", "current_end_evidence_exact_source",
    "current_end_evidence_not_suppressed",
})


def current_schema_script() -> str:
    return f"""
    BEGIN IMMEDIATE;
    CREATE TABLE {CURRENT_SCHEMA_MARKER_TABLE} (
        marker_key TEXT PRIMARY KEY CHECK (marker_key='current_persistence_schema'),
        schema_version TEXT NOT NULL CHECK (schema_version='{CURRENT_SCHEMA_VERSION}')
    );
    INSERT INTO {CURRENT_SCHEMA_MARKER_TABLE}
      VALUES ('current_persistence_schema','{CURRENT_SCHEMA_VERSION}');

    CREATE TABLE {CURRENT_STATE_TABLE} (
        state_id TEXT PRIMARY KEY CHECK(length(trim(state_id))>0),
        namespace TEXT NOT NULL CHECK(namespace IN ('room','shared')),
        owner_id TEXT NOT NULL CHECK(length(trim(owner_id))>0),
        key TEXT NOT NULL CHECK(length(trim(key))>0),
        state_kind TEXT NOT NULL CHECK(length(trim(state_kind))>0),
        recorded_instant_us INTEGER NOT NULL,
        semantic_change_authority TEXT NOT NULL
          CHECK(semantic_change_authority IN ('room_first_person','shared_governance')),
        episode_id TEXT,
        perspective_instance_id TEXT,
        room_attachment_event_id TEXT,
        supersedes_state_id TEXT,
        payload_json TEXT NOT NULL CHECK(length(trim(payload_json))>0),
        CHECK(
          (namespace='room' AND semantic_change_authority='room_first_person'
           AND episode_id IS NOT NULL AND perspective_instance_id IS NOT NULL
           AND room_attachment_event_id IS NOT NULL
           AND perspective_instance_id<>'{SYNTHETIC_UNATTRIBUTED_INSTANCE_ID}')
          OR
          (namespace='shared' AND semantic_change_authority='shared_governance'
           AND episode_id IS NULL AND perspective_instance_id IS NULL
           AND room_attachment_event_id IS NULL)
        ),
        CHECK(supersedes_state_id IS NULL OR supersedes_state_id<>state_id),
        FOREIGN KEY(episode_id) REFERENCES {EPISODE_TABLE}(episode_id)
          ON UPDATE RESTRICT ON DELETE RESTRICT,
        FOREIGN KEY(room_attachment_event_id) REFERENCES {ATTACHMENT_TABLE}(attachment_event_id)
          ON UPDATE RESTRICT ON DELETE RESTRICT,
        FOREIGN KEY(supersedes_state_id) REFERENCES {CURRENT_STATE_TABLE}(state_id)
          ON UPDATE RESTRICT ON DELETE RESTRICT
    );
    CREATE TABLE {CURRENT_STATE_EVIDENCE_TABLE} (
        state_id TEXT NOT NULL,
        position INTEGER NOT NULL CHECK(position>=0),
        source_ref TEXT NOT NULL CHECK(length(trim(source_ref))>0),
        source_id TEXT NOT NULL,
        source_sha256 TEXT NOT NULL CHECK(length(trim(source_sha256))>0),
        start_char INTEGER NOT NULL CHECK(start_char>=0),
        end_char INTEGER NOT NULL CHECK(end_char>start_char),
        PRIMARY KEY(state_id,position), UNIQUE(state_id,source_ref),
        FOREIGN KEY(state_id) REFERENCES {CURRENT_STATE_TABLE}(state_id)
          ON UPDATE RESTRICT ON DELETE RESTRICT,
        FOREIGN KEY(source_id) REFERENCES sources(source_id)
          ON UPDATE RESTRICT ON DELETE RESTRICT
    );
    CREATE TABLE {CURRENT_END_TABLE} (
        end_event_id TEXT PRIMARY KEY CHECK(length(trim(end_event_id))>0),
        state_id TEXT NOT NULL,
        recorded_instant_us INTEGER NOT NULL,
        semantic_change_authority TEXT NOT NULL
          CHECK(semantic_change_authority IN ('room_first_person','shared_governance')),
        episode_id TEXT,
        perspective_instance_id TEXT,
        room_attachment_event_id TEXT,
        payload_json TEXT NOT NULL CHECK(length(trim(payload_json))>0),
        CHECK(
          (semantic_change_authority='room_first_person' AND episode_id IS NOT NULL
           AND perspective_instance_id IS NOT NULL AND room_attachment_event_id IS NOT NULL
           AND perspective_instance_id<>'{SYNTHETIC_UNATTRIBUTED_INSTANCE_ID}')
          OR
          (semantic_change_authority='shared_governance' AND episode_id IS NULL
           AND perspective_instance_id IS NULL AND room_attachment_event_id IS NULL)
        ),
        FOREIGN KEY(state_id) REFERENCES {CURRENT_STATE_TABLE}(state_id)
          ON UPDATE RESTRICT ON DELETE RESTRICT,
        FOREIGN KEY(episode_id) REFERENCES {EPISODE_TABLE}(episode_id)
          ON UPDATE RESTRICT ON DELETE RESTRICT,
        FOREIGN KEY(room_attachment_event_id) REFERENCES {ATTACHMENT_TABLE}(attachment_event_id)
          ON UPDATE RESTRICT ON DELETE RESTRICT
    );
    CREATE TABLE {CURRENT_END_EVIDENCE_TABLE} (
        end_event_id TEXT NOT NULL,
        position INTEGER NOT NULL CHECK(position>=0),
        source_ref TEXT NOT NULL CHECK(length(trim(source_ref))>0),
        source_id TEXT NOT NULL,
        source_sha256 TEXT NOT NULL CHECK(length(trim(source_sha256))>0),
        start_char INTEGER NOT NULL CHECK(start_char>=0),
        end_char INTEGER NOT NULL CHECK(end_char>start_char),
        PRIMARY KEY(end_event_id,position), UNIQUE(end_event_id,source_ref),
        FOREIGN KEY(end_event_id) REFERENCES {CURRENT_END_TABLE}(end_event_id)
          ON UPDATE RESTRICT ON DELETE RESTRICT,
        FOREIGN KEY(source_id) REFERENCES sources(source_id)
          ON UPDATE RESTRICT ON DELETE RESTRICT
    );

    CREATE TRIGGER current_schema_marker_no_update BEFORE UPDATE ON {CURRENT_SCHEMA_MARKER_TABLE}
      BEGIN SELECT RAISE(ABORT,'Current schema marker is immutable'); END;
    CREATE TRIGGER current_schema_marker_no_delete BEFORE DELETE ON {CURRENT_SCHEMA_MARKER_TABLE}
      BEGIN SELECT RAISE(ABORT,'Current schema marker is immutable'); END;
    CREATE TRIGGER current_state_no_replace BEFORE INSERT ON {CURRENT_STATE_TABLE}
      WHEN EXISTS(SELECT 1 FROM {CURRENT_STATE_TABLE} WHERE state_id=NEW.state_id)
      BEGIN SELECT RAISE(ABORT,'Current state id already exists'); END;
    CREATE TRIGGER current_state_no_update BEFORE UPDATE ON {CURRENT_STATE_TABLE}
      BEGIN SELECT RAISE(ABORT,'Current state history is append-only'); END;
    CREATE TRIGGER current_state_no_delete BEFORE DELETE ON {CURRENT_STATE_TABLE}
      BEGIN SELECT RAISE(ABORT,'Current state history is append-only'); END;
    CREATE TRIGGER current_state_room_exists BEFORE INSERT ON {CURRENT_STATE_TABLE}
      WHEN NEW.namespace='room'
       AND NOT EXISTS(SELECT 1 FROM {ROOM_TABLE} WHERE room_id=NEW.owner_id)
      BEGIN SELECT RAISE(ABORT,'Room Current owner does not exist'); END;
    CREATE TRIGGER current_state_room_episode_binding BEFORE INSERT ON {CURRENT_STATE_TABLE}
      WHEN NEW.namespace='room' AND NOT EXISTS(
        SELECT 1 FROM {EPISODE_TABLE} WHERE episode_id=NEW.episode_id
          AND perspective_instance_id=NEW.perspective_instance_id)
      BEGIN SELECT RAISE(ABORT,'Room Current Episode/Perspective binding is invalid'); END;
    CREATE TRIGGER current_state_room_attachment_binding BEFORE INSERT ON {CURRENT_STATE_TABLE}
      WHEN NEW.namespace='room' AND NOT EXISTS(
        SELECT 1 FROM {ATTACHMENT_TABLE} a
        WHERE a.attachment_event_id=NEW.room_attachment_event_id
          AND a.episode_id=NEW.episode_id AND a.route_kind='attached'
          AND a.room_id=NEW.owner_id)
      BEGIN SELECT RAISE(ABORT,'Room Current attachment provenance is invalid'); END;
    CREATE TRIGGER current_state_supersession_line BEFORE INSERT ON {CURRENT_STATE_TABLE}
      WHEN NEW.supersedes_state_id IS NOT NULL AND NOT EXISTS(
        SELECT 1 FROM {CURRENT_STATE_TABLE} p WHERE p.state_id=NEW.supersedes_state_id
          AND p.namespace=NEW.namespace AND p.owner_id=NEW.owner_id
          AND p.key=NEW.key AND p.state_kind=NEW.state_kind
          AND p.recorded_instant_us<=NEW.recorded_instant_us)
      BEGIN SELECT RAISE(ABORT,'Current supersession must stay on one semantic line'); END;

    CREATE TRIGGER current_state_evidence_no_replace BEFORE INSERT ON {CURRENT_STATE_EVIDENCE_TABLE}
      WHEN EXISTS(SELECT 1 FROM {CURRENT_STATE_EVIDENCE_TABLE}
        WHERE state_id=NEW.state_id AND (position=NEW.position OR source_ref=NEW.source_ref))
      BEGIN SELECT RAISE(ABORT,'Current state evidence binding already exists'); END;
    CREATE TRIGGER current_state_evidence_no_update BEFORE UPDATE ON {CURRENT_STATE_EVIDENCE_TABLE}
      BEGIN SELECT RAISE(ABORT,'Current state evidence is append-only'); END;
    CREATE TRIGGER current_state_evidence_no_delete BEFORE DELETE ON {CURRENT_STATE_EVIDENCE_TABLE}
      BEGIN SELECT RAISE(ABORT,'Current state evidence is append-only'); END;
    CREATE TRIGGER current_state_evidence_exact_source BEFORE INSERT ON {CURRENT_STATE_EVIDENCE_TABLE}
      WHEN NOT EXISTS(SELECT 1 FROM sources s WHERE s.source_id=NEW.source_id
        AND s.content_sha256=NEW.source_sha256 AND NEW.end_char<=length(s.content))
      BEGIN SELECT RAISE(ABORT,'Current state evidence does not match exact source'); END;
    CREATE TRIGGER current_state_evidence_not_suppressed BEFORE INSERT ON {CURRENT_STATE_EVIDENCE_TABLE}
      WHEN EXISTS(SELECT 1 FROM source_suppressions WHERE source_id=NEW.source_id)
      BEGIN SELECT RAISE(ABORT,'Current state evidence source is suppressed'); END;

    CREATE TRIGGER current_end_no_replace BEFORE INSERT ON {CURRENT_END_TABLE}
      WHEN EXISTS(SELECT 1 FROM {CURRENT_END_TABLE} WHERE end_event_id=NEW.end_event_id)
      BEGIN SELECT RAISE(ABORT,'Current end-event id already exists'); END;
    CREATE TRIGGER current_end_no_update BEFORE UPDATE ON {CURRENT_END_TABLE}
      BEGIN SELECT RAISE(ABORT,'Current end-event history is append-only'); END;
    CREATE TRIGGER current_end_no_delete BEFORE DELETE ON {CURRENT_END_TABLE}
      BEGIN SELECT RAISE(ABORT,'Current end-event history is append-only'); END;
    CREATE TRIGGER current_end_target_binding BEFORE INSERT ON {CURRENT_END_TABLE}
      WHEN NOT EXISTS(
        SELECT 1 FROM {CURRENT_STATE_TABLE} s WHERE s.state_id=NEW.state_id
          AND s.semantic_change_authority=NEW.semantic_change_authority
          AND s.recorded_instant_us<=NEW.recorded_instant_us
          AND ((s.namespace='room' AND NEW.semantic_change_authority='room_first_person'
                AND EXISTS(SELECT 1 FROM {EPISODE_TABLE} e WHERE e.episode_id=NEW.episode_id
                  AND e.perspective_instance_id=NEW.perspective_instance_id))
                AND EXISTS(SELECT 1 FROM {ATTACHMENT_TABLE} a
                  WHERE a.attachment_event_id=NEW.room_attachment_event_id
                    AND a.episode_id=NEW.episode_id AND a.route_kind='attached'
                    AND a.room_id=s.owner_id))
               OR (s.namespace='shared' AND NEW.semantic_change_authority='shared_governance'
                   AND NEW.episode_id IS NULL AND NEW.perspective_instance_id IS NULL
                   AND NEW.room_attachment_event_id IS NULL)))
      BEGIN SELECT RAISE(ABORT,'Current end-event target/provenance binding is invalid'); END;

    CREATE TRIGGER current_end_evidence_no_replace BEFORE INSERT ON {CURRENT_END_EVIDENCE_TABLE}
      WHEN EXISTS(SELECT 1 FROM {CURRENT_END_EVIDENCE_TABLE}
        WHERE end_event_id=NEW.end_event_id AND (position=NEW.position OR source_ref=NEW.source_ref))
      BEGIN SELECT RAISE(ABORT,'Current end evidence binding already exists'); END;
    CREATE TRIGGER current_end_evidence_no_update BEFORE UPDATE ON {CURRENT_END_EVIDENCE_TABLE}
      BEGIN SELECT RAISE(ABORT,'Current end evidence is append-only'); END;
    CREATE TRIGGER current_end_evidence_no_delete BEFORE DELETE ON {CURRENT_END_EVIDENCE_TABLE}
      BEGIN SELECT RAISE(ABORT,'Current end evidence is append-only'); END;
    CREATE TRIGGER current_end_evidence_exact_source BEFORE INSERT ON {CURRENT_END_EVIDENCE_TABLE}
      WHEN NOT EXISTS(SELECT 1 FROM sources s WHERE s.source_id=NEW.source_id
        AND s.content_sha256=NEW.source_sha256 AND NEW.end_char<=length(s.content))
      BEGIN SELECT RAISE(ABORT,'Current end evidence does not match exact source'); END;
    CREATE TRIGGER current_end_evidence_not_suppressed BEFORE INSERT ON {CURRENT_END_EVIDENCE_TABLE}
      WHEN EXISTS(SELECT 1 FROM source_suppressions WHERE source_id=NEW.source_id)
      BEGIN SELECT RAISE(ABORT,'Current end evidence source is suppressed'); END;
    """


def normalize_sql(sql: str | None) -> str:
    return "" if sql is None else re.sub(r"\s+", " ", sql.strip()).lower()


@lru_cache(maxsize=1)
def expected_current_schema_sql() -> dict[tuple[str, str], str]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(f"""
          CREATE TABLE {ROOM_TABLE}(room_id TEXT PRIMARY KEY);
          CREATE TABLE {EPISODE_TABLE}(episode_id TEXT PRIMARY KEY,perspective_instance_id TEXT NOT NULL);
          CREATE TABLE {ATTACHMENT_TABLE}(attachment_event_id TEXT PRIMARY KEY,episode_id TEXT NOT NULL,route_kind TEXT NOT NULL,room_id TEXT);
          CREATE TABLE sources(source_id TEXT PRIMARY KEY,content TEXT NOT NULL,content_sha256 TEXT NOT NULL);
          CREATE TABLE source_suppressions(source_id TEXT PRIMARY KEY);
        """)
        connection.executescript(current_schema_script())
        rows = connection.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','trigger') AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {
            (row["type"], row["name"]): normalize_sql(row["sql"])
            for row in rows
            if row["name"] in CURRENT_TABLES or row["name"] in CURRENT_TRIGGERS
        }
    finally:
        connection.close()