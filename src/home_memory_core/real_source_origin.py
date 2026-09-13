from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sqlite3

from home_memory_core.real_authority_ordering import real_authority_maintenance
from home_memory_core.store_domain import assert_real_store_domain


_CLOSED_REAL_SOURCE_ORIGIN_CAPABILITY_MARKER = object()

ORIGIN_SCHEMA_MARKER_TABLE = "real_source_origin_schema_marker"
ORIGIN_SCHEMA_VERSION = "source-origin-v0.1"
ORIGIN_TABLE = "real_source_origins"
SNAPSHOT_TABLE = "real_source_snapshots"
SOURCE_BINDING_TABLE = "real_source_origin_bindings"
CAPTURE_EVENT_TABLE = "real_source_capture_events"
SNAPSHOT_SUPPRESSION_TABLE = "real_snapshot_suppressions"
SUPPRESSION_TABLE = "real_source_suppressions"
SOURCE_DOMAIN_INDEX = "real_source_domain_key"
ORIGIN_DOMAIN_INDEX = "real_origin_domain_key"
SNAPSHOT_DOMAIN_INDEX = "real_snapshot_domain_key"
SOURCE_BINDING_DOMAIN_INDEX = "real_source_origin_binding_domain_key"

_REQUIRED_TABLES = frozenset(
    {
        ORIGIN_SCHEMA_MARKER_TABLE,
        ORIGIN_TABLE,
        SNAPSHOT_TABLE,
        SOURCE_BINDING_TABLE,
        CAPTURE_EVENT_TABLE,
        SNAPSHOT_SUPPRESSION_TABLE,
    }
)
_REQUIRED_TRIGGERS = frozenset(
    {
        "real_source_origin_schema_marker_no_update",
        "real_source_origin_schema_marker_no_delete",
        "real_source_origins_no_update",
        "real_source_origins_no_delete",
        "real_source_origins_block_replace",
        "real_source_snapshots_no_update",
        "real_source_snapshots_no_delete",
        "real_source_snapshots_block_replace",
        "real_source_snapshots_block_post_suppression_origin",
        "real_source_origin_bindings_no_update",
        "real_source_origin_bindings_no_delete",
        "real_source_origin_bindings_block_replace",
        "real_source_origin_bindings_block_suppressed_snapshot",
        "real_source_capture_events_no_update",
        "real_source_capture_events_no_delete",
        "real_source_capture_events_block_replace",
        "real_snapshot_suppressions_no_update",
        "real_snapshot_suppressions_no_delete",
        "real_snapshot_suppressions_block_replace",
    }
)


class RealSourceOriginDisabledError(RuntimeError):
    """Closed source-origin authority is unavailable to normal callers."""


class RealSourceOriginIntegrityError(RuntimeError):
    """Persisted origin/snapshot authority is missing or inconsistent."""


@dataclass(frozen=True)
class ClosedRealSourceOriginExerciseCapability:
    """Synthetic-fixture-only capability for source-origin schema exercises."""

    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _CLOSED_REAL_SOURCE_ORIGIN_CAPABILITY_MARKER:
            raise RealSourceOriginDisabledError(
                "closed source-origin capability cannot be caller-minted"
            )


def initialize_closed_real_source_origin_schema(
    *,
    db_path: str | Path,
    capability: ClosedRealSourceOriginExerciseCapability,
) -> None:
    """Install origin/snapshot authority only on a clean closed real exercise DB.

    Existing source rows are deliberately not auto-certified.  Because HOME has
    not admitted real personal data, fixture stores should be rebuilt under the
    new contract instead of inferring provenance from source IDs or hashes.
    """

    _require_capability(capability)
    path = Path(db_path)
    with real_authority_maintenance(path):
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            assert_real_store_domain(connection)
            _assert_prerequisites(connection)

            marker_exists = _object_exists(
                connection, "table", ORIGIN_SCHEMA_MARKER_TABLE
            )
            artifacts = _existing_artifacts(connection)
            if marker_exists:
                assert_real_source_origin_schema(connection)
                connection.commit()
                return
            if artifacts:
                raise RealSourceOriginIntegrityError(
                    "partial source-origin schema exists without its marker"
                )

            source_count = connection.execute(
                "SELECT COUNT(*) FROM real_sources"
            ).fetchone()[0]
            suppression_count = connection.execute(
                f"SELECT COUNT(*) FROM {SUPPRESSION_TABLE}"
            ).fetchone()[0]
            if source_count or suppression_count:
                raise RealSourceOriginIntegrityError(
                    "existing real source history cannot be auto-certified with origin identity"
                )

            _create_schema(connection)
            assert_real_source_origin_schema(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def assert_real_source_origin_schema(connection: sqlite3.Connection) -> None:
    existing_tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        if row[0] in _REQUIRED_TABLES
    }
    if existing_tables != _REQUIRED_TABLES:
        raise RealSourceOriginIntegrityError(
            "closed source-origin schema is missing or incomplete"
        )

    marker_rows = connection.execute(
        f"SELECT schema_version FROM {ORIGIN_SCHEMA_MARKER_TABLE} "
        "WHERE marker_key='source_origin_schema'"
    ).fetchall()
    if marker_rows != [(ORIGIN_SCHEMA_VERSION,)]:
        raise RealSourceOriginIntegrityError(
            "closed source-origin schema marker is invalid"
        )

    triggers = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    if not _REQUIRED_TRIGGERS.issubset(triggers):
        raise RealSourceOriginIntegrityError(
            "closed source-origin storage invariants are incomplete"
        )

    _assert_required_not_null(
        connection,
        ORIGIN_TABLE,
        {
            "origin_id",
            "access_domain_id",
            "origin_namespace_id",
            "external_object_key",
            "object_kind",
            "origin_key_version",
            "created_at_utc",
        },
    )
    _assert_required_not_null(
        connection,
        SNAPSHOT_TABLE,
        {
            "snapshot_id",
            "access_domain_id",
            "origin_id",
            "snapshot_kind",
            "external_snapshot_key",
            "content_sha256",
            "created_at_utc",
        },
    )
    _assert_required_not_null(
        connection,
        SOURCE_BINDING_TABLE,
        {"source_id", "access_domain_id", "snapshot_id"},
    )
    _assert_required_not_null(
        connection,
        SNAPSHOT_SUPPRESSION_TABLE,
        {"snapshot_id", "source_id", "access_domain_id", "source_suppression_id"},
    )

    _require_unique_columns(
        connection,
        ORIGIN_TABLE,
        ("access_domain_id", "origin_namespace_id", "external_object_key"),
    )
    _require_unique_columns(
        connection,
        SNAPSHOT_TABLE,
        ("origin_id", "snapshot_kind", "external_snapshot_key"),
    )
    _require_unique_columns(connection, SOURCE_BINDING_TABLE, ("snapshot_id",))
    _require_unique_columns(connection, CAPTURE_EVENT_TABLE, ("operation_id",))
    _require_unique_columns(
        connection, SNAPSHOT_SUPPRESSION_TABLE, ("source_suppression_id",)
    )
    _require_unique_columns(connection, SNAPSHOT_SUPPRESSION_TABLE, ("source_id",))

    _require_named_unique_index(
        connection, ORIGIN_TABLE, ORIGIN_DOMAIN_INDEX, ("origin_id", "access_domain_id")
    )
    _require_named_unique_index(
        connection,
        SNAPSHOT_TABLE,
        SNAPSHOT_DOMAIN_INDEX,
        ("snapshot_id", "access_domain_id"),
    )
    _require_named_unique_index(
        connection,
        SOURCE_BINDING_TABLE,
        SOURCE_BINDING_DOMAIN_INDEX,
        ("source_id", "access_domain_id"),
    )

    _require_fk_pairs(
        connection,
        SNAPSHOT_TABLE,
        ORIGIN_TABLE,
        {("origin_id", "origin_id"), ("access_domain_id", "access_domain_id")},
    )
    _require_fk_pairs(
        connection,
        SOURCE_BINDING_TABLE,
        "real_sources",
        {("source_id", "source_id"), ("access_domain_id", "access_domain_id")},
    )
    _require_fk_pairs(
        connection,
        SOURCE_BINDING_TABLE,
        SNAPSHOT_TABLE,
        {("snapshot_id", "snapshot_id"), ("access_domain_id", "access_domain_id")},
    )
    _require_fk_pairs(
        connection,
        SNAPSHOT_SUPPRESSION_TABLE,
        SNAPSHOT_TABLE,
        {("snapshot_id", "snapshot_id"), ("access_domain_id", "access_domain_id")},
    )
    _require_fk_pairs(
        connection,
        SNAPSHOT_SUPPRESSION_TABLE,
        SOURCE_BINDING_TABLE,
        {("source_id", "source_id"), ("access_domain_id", "access_domain_id")},
    )
    _require_fk_pairs(
        connection,
        SNAPSHOT_SUPPRESSION_TABLE,
        SUPPRESSION_TABLE,
        {("source_suppression_id", "suppression_id")},
    )

    missing_binding = connection.execute(
        f"""
        SELECT s.source_id
        FROM real_sources AS s
        LEFT JOIN {SOURCE_BINDING_TABLE} AS b
          ON b.source_id = s.source_id
         AND b.access_domain_id = s.access_domain_id
        WHERE b.source_id IS NULL
        LIMIT 1
        """
    ).fetchone()
    if missing_binding is not None:
        raise RealSourceOriginIntegrityError(
            "real source is missing its canonical snapshot binding"
        )

    inconsistent_hash = connection.execute(
        f"""
        SELECT s.source_id
        FROM real_sources AS s
        JOIN {SOURCE_BINDING_TABLE} AS b
          ON b.source_id = s.source_id
         AND b.access_domain_id = s.access_domain_id
        JOIN {SNAPSHOT_TABLE} AS snap
          ON snap.snapshot_id = b.snapshot_id
         AND snap.access_domain_id = b.access_domain_id
        WHERE s.content_sha256 != snap.content_sha256
        LIMIT 1
        """
    ).fetchone()
    if inconsistent_hash is not None:
        raise RealSourceOriginIntegrityError(
            "real source content hash disagrees with canonical snapshot"
        )

    missing_snapshot_suppression = connection.execute(
        f"""
        SELECT rs.source_id
        FROM {SUPPRESSION_TABLE} AS rs
        LEFT JOIN {SNAPSHOT_SUPPRESSION_TABLE} AS ss
          ON ss.source_suppression_id = rs.suppression_id
        WHERE ss.snapshot_id IS NULL
        LIMIT 1
        """
    ).fetchone()
    if missing_snapshot_suppression is not None:
        raise RealSourceOriginIntegrityError(
            "source suppression is missing canonical snapshot stop-use binding"
        )

    orphan_snapshot_suppression = connection.execute(
        f"""
        SELECT ss.snapshot_id
        FROM {SNAPSHOT_SUPPRESSION_TABLE} AS ss
        LEFT JOIN {SUPPRESSION_TABLE} AS rs
          ON rs.suppression_id = ss.source_suppression_id
        WHERE rs.suppression_id IS NULL
        LIMIT 1
        """
    ).fetchone()
    if orphan_snapshot_suppression is not None:
        raise RealSourceOriginIntegrityError(
            "snapshot stop-use binding has no source suppression authority"
        )


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        f"""
        CREATE TABLE {ORIGIN_SCHEMA_MARKER_TABLE} (
            marker_key TEXT NOT NULL PRIMARY KEY
                CHECK (marker_key = 'source_origin_schema'),
            schema_version TEXT NOT NULL
                CHECK (schema_version = '{ORIGIN_SCHEMA_VERSION}')
        );
        INSERT INTO {ORIGIN_SCHEMA_MARKER_TABLE}(marker_key, schema_version)
        VALUES ('source_origin_schema', '{ORIGIN_SCHEMA_VERSION}');

        CREATE TABLE {ORIGIN_TABLE} (
            origin_id TEXT NOT NULL PRIMARY KEY CHECK(length(trim(origin_id)) > 0),
            access_domain_id TEXT NOT NULL CHECK(length(trim(access_domain_id)) > 0),
            origin_namespace_id TEXT NOT NULL CHECK(length(trim(origin_namespace_id)) > 0),
            external_object_key TEXT NOT NULL CHECK(length(trim(external_object_key)) > 0),
            object_kind TEXT NOT NULL CHECK(length(trim(object_kind)) > 0),
            origin_key_version TEXT NOT NULL CHECK(length(trim(origin_key_version)) > 0),
            created_at_utc TEXT NOT NULL CHECK(length(trim(created_at_utc)) > 0),
            UNIQUE(access_domain_id, origin_namespace_id, external_object_key)
        );
        CREATE UNIQUE INDEX {ORIGIN_DOMAIN_INDEX}
            ON {ORIGIN_TABLE}(origin_id, access_domain_id);

        CREATE TABLE {SNAPSHOT_TABLE} (
            snapshot_id TEXT NOT NULL PRIMARY KEY CHECK(length(trim(snapshot_id)) > 0),
            access_domain_id TEXT NOT NULL CHECK(length(trim(access_domain_id)) > 0),
            origin_id TEXT NOT NULL CHECK(length(trim(origin_id)) > 0),
            snapshot_kind TEXT NOT NULL CHECK(length(trim(snapshot_kind)) > 0),
            external_snapshot_key TEXT NOT NULL CHECK(length(trim(external_snapshot_key)) > 0),
            content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
            created_at_utc TEXT NOT NULL CHECK(length(trim(created_at_utc)) > 0),
            UNIQUE(origin_id, snapshot_kind, external_snapshot_key),
            FOREIGN KEY(origin_id, access_domain_id)
                REFERENCES {ORIGIN_TABLE}(origin_id, access_domain_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT
        );
        CREATE UNIQUE INDEX {SNAPSHOT_DOMAIN_INDEX}
            ON {SNAPSHOT_TABLE}(snapshot_id, access_domain_id);

        CREATE TABLE {SOURCE_BINDING_TABLE} (
            source_id TEXT NOT NULL PRIMARY KEY CHECK(length(trim(source_id)) > 0),
            access_domain_id TEXT NOT NULL CHECK(length(trim(access_domain_id)) > 0),
            snapshot_id TEXT NOT NULL UNIQUE CHECK(length(trim(snapshot_id)) > 0),
            FOREIGN KEY(source_id, access_domain_id)
                REFERENCES real_sources(source_id, access_domain_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            FOREIGN KEY(snapshot_id, access_domain_id)
                REFERENCES {SNAPSHOT_TABLE}(snapshot_id, access_domain_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT
        );
        CREATE UNIQUE INDEX {SOURCE_BINDING_DOMAIN_INDEX}
            ON {SOURCE_BINDING_TABLE}(source_id, access_domain_id);

        CREATE TABLE {CAPTURE_EVENT_TABLE} (
            capture_event_id TEXT NOT NULL PRIMARY KEY CHECK(length(trim(capture_event_id)) > 0),
            operation_id TEXT NOT NULL UNIQUE CHECK(length(trim(operation_id)) > 0),
            requested_source_id TEXT NOT NULL CHECK(length(trim(requested_source_id)) > 0),
            canonical_source_id TEXT NOT NULL CHECK(length(trim(canonical_source_id)) > 0),
            access_domain_id TEXT NOT NULL CHECK(length(trim(access_domain_id)) > 0),
            origin_id TEXT NOT NULL CHECK(length(trim(origin_id)) > 0),
            snapshot_id TEXT NOT NULL CHECK(length(trim(snapshot_id)) > 0),
            replay_disposition TEXT NOT NULL CHECK(length(trim(replay_disposition)) > 0),
            ingress_adapter_id TEXT NOT NULL CHECK(length(trim(ingress_adapter_id)) > 0),
            adapter_version TEXT NOT NULL CHECK(length(trim(adapter_version)) > 0),
            capture_locator TEXT NULL CHECK(capture_locator IS NULL OR length(trim(capture_locator)) > 0),
            recorded_at_utc TEXT NOT NULL CHECK(length(trim(recorded_at_utc)) > 0),
            FOREIGN KEY(origin_id, access_domain_id)
                REFERENCES {ORIGIN_TABLE}(origin_id, access_domain_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            FOREIGN KEY(snapshot_id, access_domain_id)
                REFERENCES {SNAPSHOT_TABLE}(snapshot_id, access_domain_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            FOREIGN KEY(canonical_source_id, access_domain_id)
                REFERENCES {SOURCE_BINDING_TABLE}(source_id, access_domain_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT
        );

        CREATE TABLE {SNAPSHOT_SUPPRESSION_TABLE} (
            snapshot_id TEXT NOT NULL PRIMARY KEY CHECK(length(trim(snapshot_id)) > 0),
            source_id TEXT NOT NULL UNIQUE CHECK(length(trim(source_id)) > 0),
            access_domain_id TEXT NOT NULL CHECK(length(trim(access_domain_id)) > 0),
            source_suppression_id TEXT NOT NULL UNIQUE CHECK(length(trim(source_suppression_id)) > 0),
            FOREIGN KEY(snapshot_id, access_domain_id)
                REFERENCES {SNAPSHOT_TABLE}(snapshot_id, access_domain_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            FOREIGN KEY(source_id, access_domain_id)
                REFERENCES {SOURCE_BINDING_TABLE}(source_id, access_domain_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            FOREIGN KEY(source_suppression_id)
                REFERENCES {SUPPRESSION_TABLE}(suppression_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT
        );

        CREATE TRIGGER real_source_origin_schema_marker_no_update
        BEFORE UPDATE ON {ORIGIN_SCHEMA_MARKER_TABLE}
        BEGIN SELECT RAISE(ABORT, 'source-origin schema marker is immutable'); END;
        CREATE TRIGGER real_source_origin_schema_marker_no_delete
        BEFORE DELETE ON {ORIGIN_SCHEMA_MARKER_TABLE}
        BEGIN SELECT RAISE(ABORT, 'source-origin schema marker is immutable'); END;

        CREATE TRIGGER real_source_origins_no_update
        BEFORE UPDATE ON {ORIGIN_TABLE}
        BEGIN SELECT RAISE(ABORT, 'source origin is immutable'); END;
        CREATE TRIGGER real_source_origins_no_delete
        BEFORE DELETE ON {ORIGIN_TABLE}
        BEGIN SELECT RAISE(ABORT, 'source origin is immutable'); END;
        CREATE TRIGGER real_source_origins_block_replace
        BEFORE INSERT ON {ORIGIN_TABLE}
        WHEN EXISTS (
            SELECT 1 FROM {ORIGIN_TABLE}
            WHERE origin_id=NEW.origin_id
               OR (access_domain_id=NEW.access_domain_id
                   AND origin_namespace_id=NEW.origin_namespace_id
                   AND external_object_key=NEW.external_object_key)
        )
        BEGIN SELECT RAISE(ABORT, 'source origin cannot replace history'); END;

        CREATE TRIGGER real_source_snapshots_no_update
        BEFORE UPDATE ON {SNAPSHOT_TABLE}
        BEGIN SELECT RAISE(ABORT, 'source snapshot is immutable'); END;
        CREATE TRIGGER real_source_snapshots_no_delete
        BEFORE DELETE ON {SNAPSHOT_TABLE}
        BEGIN SELECT RAISE(ABORT, 'source snapshot is immutable'); END;
        CREATE TRIGGER real_source_snapshots_block_replace
        BEFORE INSERT ON {SNAPSHOT_TABLE}
        WHEN EXISTS (
            SELECT 1 FROM {SNAPSHOT_TABLE}
            WHERE snapshot_id=NEW.snapshot_id
               OR (origin_id=NEW.origin_id
                   AND snapshot_kind=NEW.snapshot_kind
                   AND external_snapshot_key=NEW.external_snapshot_key)
        )
        BEGIN SELECT RAISE(ABORT, 'source snapshot cannot replace history'); END;
        CREATE TRIGGER real_source_snapshots_block_post_suppression_origin
        BEFORE INSERT ON {SNAPSHOT_TABLE}
        WHEN EXISTS (
            SELECT 1
            FROM {SNAPSHOT_SUPPRESSION_TABLE} AS ss
            JOIN {SNAPSHOT_TABLE} AS old_snap ON old_snap.snapshot_id=ss.snapshot_id
            WHERE old_snap.origin_id=NEW.origin_id
        )
        BEGIN SELECT RAISE(ABORT, 'new snapshot after suppressed origin history is restricted'); END;

        CREATE TRIGGER real_source_origin_bindings_no_update
        BEFORE UPDATE ON {SOURCE_BINDING_TABLE}
        BEGIN SELECT RAISE(ABORT, 'source origin binding is immutable'); END;
        CREATE TRIGGER real_source_origin_bindings_no_delete
        BEFORE DELETE ON {SOURCE_BINDING_TABLE}
        BEGIN SELECT RAISE(ABORT, 'source origin binding is immutable'); END;
        CREATE TRIGGER real_source_origin_bindings_block_replace
        BEFORE INSERT ON {SOURCE_BINDING_TABLE}
        WHEN EXISTS (
            SELECT 1 FROM {SOURCE_BINDING_TABLE}
            WHERE source_id=NEW.source_id OR snapshot_id=NEW.snapshot_id
        )
        BEGIN SELECT RAISE(ABORT, 'source origin binding cannot replace history'); END;
        CREATE TRIGGER real_source_origin_bindings_block_suppressed_snapshot
        BEFORE INSERT ON {SOURCE_BINDING_TABLE}
        WHEN EXISTS (
            SELECT 1 FROM {SNAPSHOT_SUPPRESSION_TABLE}
            WHERE snapshot_id=NEW.snapshot_id
        )
        BEGIN SELECT RAISE(ABORT, 'suppressed snapshot cannot receive a new source binding'); END;

        CREATE TRIGGER real_source_capture_events_no_update
        BEFORE UPDATE ON {CAPTURE_EVENT_TABLE}
        BEGIN SELECT RAISE(ABORT, 'capture event is immutable'); END;
        CREATE TRIGGER real_source_capture_events_no_delete
        BEFORE DELETE ON {CAPTURE_EVENT_TABLE}
        BEGIN SELECT RAISE(ABORT, 'capture event is immutable'); END;
        CREATE TRIGGER real_source_capture_events_block_replace
        BEFORE INSERT ON {CAPTURE_EVENT_TABLE}
        WHEN EXISTS (
            SELECT 1 FROM {CAPTURE_EVENT_TABLE}
            WHERE capture_event_id=NEW.capture_event_id OR operation_id=NEW.operation_id
        )
        BEGIN SELECT RAISE(ABORT, 'capture event cannot replace history'); END;

        CREATE TRIGGER real_snapshot_suppressions_no_update
        BEFORE UPDATE ON {SNAPSHOT_SUPPRESSION_TABLE}
        BEGIN SELECT RAISE(ABORT, 'snapshot suppression binding is immutable'); END;
        CREATE TRIGGER real_snapshot_suppressions_no_delete
        BEFORE DELETE ON {SNAPSHOT_SUPPRESSION_TABLE}
        BEGIN SELECT RAISE(ABORT, 'snapshot suppression binding is immutable'); END;
        CREATE TRIGGER real_snapshot_suppressions_block_replace
        BEFORE INSERT ON {SNAPSHOT_SUPPRESSION_TABLE}
        WHEN EXISTS (
            SELECT 1 FROM {SNAPSHOT_SUPPRESSION_TABLE}
            WHERE snapshot_id=NEW.snapshot_id
               OR source_id=NEW.source_id
               OR source_suppression_id=NEW.source_suppression_id
        )
        BEGIN SELECT RAISE(ABORT, 'snapshot suppression cannot replace history'); END;
        """
    )


def _assert_prerequisites(connection: sqlite3.Connection) -> None:
    for table in ("real_sources", SUPPRESSION_TABLE):
        if not _object_exists(connection, "table", table):
            raise RealSourceOriginIntegrityError(
                "source-origin schema requires initialized ingress and stop-use schemas"
            )
    if not _object_exists(connection, "index", SOURCE_DOMAIN_INDEX):
        raise RealSourceOriginIntegrityError(
            "source-origin schema requires source/domain integrity key"
        )


def _existing_artifacts(connection: sqlite3.Connection) -> set[str]:
    wanted = set(_REQUIRED_TABLES) | set(_REQUIRED_TRIGGERS) | {
        ORIGIN_DOMAIN_INDEX,
        SNAPSHOT_DOMAIN_INDEX,
        SOURCE_BINDING_DOMAIN_INDEX,
    }
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE name IN (%s)" % ",".join("?" for _ in wanted),
        tuple(wanted),
    ).fetchall()
    return {row[0] for row in rows}


def _assert_required_not_null(
    connection: sqlite3.Connection,
    table: str,
    required: set[str],
) -> None:
    columns = {
        row[1]: row for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if not required.issubset(columns):
        raise RealSourceOriginIntegrityError(f"{table} columns are incomplete")
    if any(columns[name][3] != 1 for name in required):
        raise RealSourceOriginIntegrityError(
            f"{table} authority columns must be NOT NULL"
        )


def _require_unique_columns(
    connection: sqlite3.Connection,
    table: str,
    expected: tuple[str, ...],
) -> None:
    unique_sets = {
        tuple(
            row[2]
            for row in connection.execute(
                f"PRAGMA index_info({index_row[1]})"
            ).fetchall()
        )
        for index_row in connection.execute(f"PRAGMA index_list({table})").fetchall()
        if index_row[2] == 1
    }
    if expected not in unique_sets:
        raise RealSourceOriginIntegrityError(
            f"{table} is missing required unique key {expected!r}"
        )


def _require_named_unique_index(
    connection: sqlite3.Connection,
    table: str,
    index_name: str,
    expected: tuple[str, ...],
) -> None:
    indexes = connection.execute(f"PRAGMA index_list({table})").fetchall()
    matching = [row for row in indexes if row[1] == index_name and row[2] == 1]
    if len(matching) != 1:
        raise RealSourceOriginIntegrityError(f"missing unique index {index_name}")
    columns = tuple(
        row[2]
        for row in connection.execute(f"PRAGMA index_info({index_name})").fetchall()
    )
    if columns != expected:
        raise RealSourceOriginIntegrityError(f"invalid unique index {index_name}")


def _require_fk_pairs(
    connection: sqlite3.Connection,
    table: str,
    target_table: str,
    expected: set[tuple[str, str]],
) -> None:
    pairs = {
        (row[3], row[4])
        for row in connection.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        if row[2] == target_table
    }
    if pairs != expected:
        raise RealSourceOriginIntegrityError(
            f"{table} has invalid foreign key binding to {target_table}"
        )


def _object_exists(connection: sqlite3.Connection, object_type: str, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type=? AND name=?", (object_type, name)
    ).fetchone() is not None


def _require_capability(capability: ClosedRealSourceOriginExerciseCapability) -> None:
    if not isinstance(capability, ClosedRealSourceOriginExerciseCapability):
        raise RealSourceOriginDisabledError(
            "closed source-origin schema requires a trusted exercise capability"
        )
    if capability._marker is not _CLOSED_REAL_SOURCE_ORIGIN_CAPABILITY_MARKER:
        raise RealSourceOriginDisabledError("closed source-origin capability is invalid")
