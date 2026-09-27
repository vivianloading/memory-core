"""Private, exact schema for the synthetic-only #08a.1b production slice.

No exercise authority front calls this module. There is no migration/repair of
partial payload stores: install atomically from a verified empty 1a marker, or
verify the complete profile and all authority state without modifying it.
"""
from __future__ import annotations

import sqlite3
from uuid import uuid4

from home_memory_core.production_authority import ProductionAuthorityError, _read_ownership


SCHEMA_ID = "production-manual-event-synthetic-v0.1"
ADAPTER_ID = "manual_event_v0.1"
ADAPTER_VERSION = "0.1"

_OWNERSHIP = {
    "home_store_domain": """CREATE TABLE home_store_domain (
        marker_key TEXT PRIMARY KEY CHECK(marker_key = 'store_domain'),
        domain TEXT NOT NULL CHECK(domain = 'production-contract'),
        incarnation TEXT NOT NULL CHECK(length(incarnation) > 0),
        scope TEXT NOT NULL
    )""",
    "production_no_update": """CREATE TRIGGER production_no_update
        BEFORE UPDATE OF marker_key, domain, scope ON home_store_domain BEGIN
        SELECT RAISE(ABORT, 'production ownership is immutable'); END""",
    "production_no_delete": """CREATE TRIGGER production_no_delete
        BEFORE DELETE ON home_store_domain BEGIN
        SELECT RAISE(ABORT, 'production ownership is immutable'); END""",
}
_TABLES = {
    "production_origins": """CREATE TABLE production_origins (
        origin_id TEXT PRIMARY KEY NOT NULL,
        external_object_key TEXT UNIQUE NOT NULL,
        namespace TEXT NOT NULL,
        adapter_id TEXT NOT NULL,
        adapter_version TEXT NOT NULL
    )""",
    "production_stop_use": """CREATE TABLE production_stop_use (
        origin_id TEXT PRIMARY KEY NOT NULL REFERENCES production_origins(origin_id),
        stopped INTEGER NOT NULL CHECK(stopped IN (0, 1)),
        stop_operation_id TEXT,
        CHECK((stopped = 0 AND stop_operation_id IS NULL) OR
              (stopped = 1 AND stop_operation_id IS NOT NULL AND length(stop_operation_id) > 0))
    )""",
    "production_sources": """CREATE TABLE production_sources (
        source_id TEXT PRIMARY KEY NOT NULL,
        origin_id TEXT NOT NULL REFERENCES production_stop_use(origin_id),
        snapshot_id TEXT UNIQUE NOT NULL,
        snapshot_version INTEGER NOT NULL CHECK(snapshot_version >= 1),
        scope TEXT NOT NULL,
        content TEXT NOT NULL,
        content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
        UNIQUE(origin_id, snapshot_version)
    )""",
    "production_captures": """CREATE TABLE production_captures (
        capture_event_id TEXT PRIMARY KEY NOT NULL,
        source_id TEXT NOT NULL REFERENCES production_sources(source_id),
        session_id TEXT NOT NULL
    )""",
    "production_profile": """CREATE TABLE production_profile (
        profile_key TEXT PRIMARY KEY CHECK(profile_key = 'profile'),
        schema_id TEXT NOT NULL,
        store_incarnation TEXT NOT NULL,
        namespace TEXT NOT NULL,
        adapter_id TEXT NOT NULL,
        adapter_version TEXT NOT NULL
    )""",
}
_TRIGGERS = {}
for _table in _TABLES:
    for _action in ("UPDATE", "DELETE"):
        if _table == "production_stop_use" and _action == "UPDATE":
            continue
        _name = f"{_table}_no_{_action.lower()}"
        _TRIGGERS[_name] = f"""CREATE TRIGGER {_name} BEFORE {_action} ON {_table}
            BEGIN SELECT RAISE(ABORT, 'production state is immutable'); END"""
_TRIGGERS["production_stop_use_one_way"] = """CREATE TRIGGER production_stop_use_one_way
    BEFORE UPDATE ON production_stop_use
    WHEN OLD.stopped = 1 OR NEW.stopped != 1 OR NEW.origin_id != OLD.origin_id
    BEGIN SELECT RAISE(ABORT, 'production stop-use is irreversible'); END"""
_SCHEMA = {**_OWNERSHIP, **_TABLES, **_TRIGGERS}


def _catalog(connection):
    return dict(connection.execute(
        "SELECT name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    ))


def _normalized(sql):
    return " ".join(sql.split()).rstrip(";") if type(sql) is str else None


def _verify_catalog(connection, expected):
    actual = _catalog(connection)
    if actual.keys() != expected.keys() or any(
        _normalized(actual[name]) != _normalized(sql) for name, sql in expected.items()
    ):
        raise ProductionAuthorityError("production schema is missing, damaged or unknown")


def _install(connection, tables):
    for table in tables:
        connection.execute(_TABLES[table])
        for name, sql in _TRIGGERS.items():
            if name.startswith(table + "_"):
                connection.execute(sql)


def _initialize_origin_schema(connection):
    _install(connection, ("production_origins",))


def _initialize_stop_use_schema(connection):
    _install(connection, ("production_stop_use",))


def _initialize_source_schema(connection):
    _install(connection, ("production_sources", "production_captures"))


def _seal_profile(connection, scope, incarnation):
    _install(connection, ("production_profile",))
    connection.execute(
        "INSERT INTO production_profile VALUES ('profile', ?, ?, ?, ?, ?)",
        (SCHEMA_ID, incarnation, scope.origin_namespace_id.value, ADAPTER_ID, ADAPTER_VERSION),
    )


def bootstrap(connection, scope):
    """Called only by the BOOTSTRAPPING root, inside its lease/transaction."""
    catalog = _catalog(connection)
    if not catalog:
        for sql in _OWNERSHIP.values():
            connection.execute(sql)
        connection.execute(
            "INSERT INTO home_store_domain VALUES ('store_domain', 'production-contract', ?, ?)",
            (uuid4().hex, scope._metadata()),
        )
        catalog = _catalog(connection)
    if catalog.keys() == _OWNERSHIP.keys():
        _verify_catalog(connection, _OWNERSHIP)
        incarnation = _read_ownership(connection, scope)
        _initialize_origin_schema(connection)
        _initialize_stop_use_schema(connection)
        _initialize_source_schema(connection)
        _seal_profile(connection, scope, incarnation)
    else:
        # Any additional object means we must verify the whole profile. Never
        # backfill stop-use/origin state or certify unknown payload as usable.
        incarnation = _read_ownership(connection, scope)
    assert_ready(connection, scope, incarnation)
    return incarnation


def assert_ready(connection, scope, expected_incarnation):
    """Metadata-only validation, repeated inside each protected transaction."""
    _verify_catalog(connection, _SCHEMA)
    if not expected_incarnation or _read_ownership(connection, scope) != expected_incarnation:
        raise ProductionAuthorityError("production store incarnation mismatch")
    expected_profile = ("profile", SCHEMA_ID, expected_incarnation,
                        scope.origin_namespace_id.value, ADAPTER_ID, ADAPTER_VERSION)
    if connection.execute("SELECT * FROM production_profile").fetchall() != [expected_profile]:
        raise ProductionAuthorityError("production profile authority is invalid")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ProductionAuthorityError("production authority references are damaged")
    # Every committed origin must have explicit stop-use state, source snapshots
    # and capture evidence. A missing row is never interpreted as 'not stopped'.
    if connection.execute("""SELECT 1 FROM production_origins o
        LEFT JOIN production_stop_use u ON u.origin_id = o.origin_id
        WHERE u.origin_id IS NULL OR o.namespace != ? OR o.adapter_id != ?
           OR o.adapter_version != ? OR length(o.origin_id) = 0 OR length(o.external_object_key) = 0
           OR NOT EXISTS (SELECT 1 FROM production_sources s WHERE s.origin_id = o.origin_id)
        LIMIT 1""", (scope.origin_namespace_id.value, ADAPTER_ID, ADAPTER_VERSION)).fetchone():
        raise ProductionAuthorityError("production origin/stop-use state is incomplete")
    if connection.execute("""SELECT 1 FROM production_sources s
        WHERE s.scope != ? OR length(s.source_id) = 0 OR length(s.snapshot_id) = 0
           OR typeof(s.snapshot_version) != 'integer' OR s.snapshot_version < 1
           OR length(s.content_sha256) != 64
           OR s.content_sha256 GLOB '*[^0-9a-f]*'
           OR NOT EXISTS (SELECT 1 FROM production_captures c WHERE c.source_id = s.source_id)
        LIMIT 1""", (scope._metadata(),)).fetchone():
        raise ProductionAuthorityError("production source authority is incomplete")
    if connection.execute("""SELECT 1 FROM production_sources GROUP BY origin_id
        HAVING MIN(snapshot_version) != 1 OR MAX(snapshot_version) != COUNT(*) LIMIT 1""").fetchone():
        raise ProductionAuthorityError("production snapshot version history is incomplete")
    if connection.execute("""SELECT 1 FROM production_stop_use WHERE
        stopped NOT IN (0, 1) OR typeof(stopped) != 'integer'
        OR (stopped = 0 AND stop_operation_id IS NOT NULL)
        OR (stopped = 1 AND (stop_operation_id IS NULL OR length(stop_operation_id) = 0))
        LIMIT 1""").fetchone():
        raise ProductionAuthorityError("production stop-use state is invalid")
    if connection.execute("""SELECT 1 FROM production_captures WHERE
        length(capture_event_id) = 0 OR length(session_id) = 0 LIMIT 1""").fetchone():
        raise ProductionAuthorityError("production capture state is invalid")


def source_metadata(connection, source_id):
    """Does not fetch payload; callers must already hold production admission."""
    row = connection.execute("""SELECT s.source_id, s.origin_id, s.snapshot_id,
        s.snapshot_version, o.external_object_key, u.stopped
        FROM production_sources s
        JOIN production_origins o ON o.origin_id = s.origin_id
        JOIN production_stop_use u ON u.origin_id = s.origin_id
        WHERE s.source_id = ?""", (source_id,)).fetchone()
    if row is None:
        raise ProductionAuthorityError("production source is unavailable")
    return row


def require_usable(connection, origin_id):
    row = connection.execute(
        "SELECT stopped FROM production_stop_use WHERE origin_id = ?", (origin_id,),
    ).fetchone()
    if row != (0,):
        raise ProductionAuthorityError("production origin is unavailable for normal use")
