import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from functools import wraps
from hashlib import sha256
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Callable, TypeVar

from home_memory_core.evidence import EvidenceRef
from home_memory_core.lineage import (
    LineageIntegrityError,
    LineageResolutionInput,
    _create_store_assembled_input,
)
from home_memory_core.interpretation import (
    InterpretationRecord,
    SYNTHETIC_UNATTRIBUTED_INSTANCE_ID,
    create_interpretation_record,
)
from home_memory_core.revision import SupersessionRecord
from home_memory_core.source import SourceRecord
from home_memory_core.state import validate_supersession_graph
from home_memory_core.store_domain import (
    SYNTHETIC_STORE_DOMAIN,
    assert_synthetic_store_domain,
    ensure_synthetic_store_domain,
)
from home_memory_core.suppression import (
    SuppressedMemoryError,
    SuppressionLedgerIntegrityError,
    SuppressionRecord,
    suppression_datetime_from_iso,
    suppression_datetime_to_iso,
    suppression_instant,
    is_interpretation_usable as interpretation_is_usable,
    is_supersession_usable as supersession_is_usable,
)
from home_memory_core.thread import (
    InterpretationThread,
    ThreadAdmissionRecord,
    ThreadTopology,
)


_WRITE_RESULT = TypeVar("_WRITE_RESULT")
_AUTHORITY_LOCK_REGISTRY_GUARD = Lock()
_AUTHORITY_LOCKS: dict[str, RLock] = {}


LEGACY_SUPPRESSION_SCHEMA_VERSION = "source-suppression-v0.1"
SUPPRESSION_SCHEMA_VERSION = "source-suppression-v0.2"
SUPPRESSION_SCHEMA_MARKER_TABLE = "source_suppression_schema_marker"
SUPPRESSION_SCHEMA_MARKER_TRIGGERS = frozenset(
    {
        "source_suppression_schema_marker_no_update",
        "source_suppression_schema_marker_no_delete",
    }
)


SOURCE_SUPPRESSION_TRIGGERS = frozenset(
    {
        "source_suppressions_no_replace",
        "source_suppressions_no_update",
        "source_suppressions_no_delete",
    }
)


SOURCE_SUPPRESSION_TIMING_TABLE = "source_suppression_timing"
SOURCE_SUPPRESSION_TIMING_TRIGGERS = frozenset(
    {
        "source_suppression_timing_no_replace",
        "source_suppression_timing_no_update",
        "source_suppression_timing_no_delete",
    }
)


def _source_suppression_timing_table_sql() -> str:
    return f"""
        CREATE TABLE {SOURCE_SUPPRESSION_TIMING_TABLE} (
            suppression_id TEXT PRIMARY KEY,
            timing_status TEXT NOT NULL
                CHECK(timing_status IN ('timed','timing_unknown')),
            effective_instant_us INTEGER,
            recorded_instant_us INTEGER,
            effective_at_iso TEXT,
            recorded_at_iso TEXT,
            CHECK(
                (
                    timing_status='timed'
                    AND typeof(effective_instant_us)='integer'
                    AND typeof(recorded_instant_us)='integer'
                    AND effective_instant_us<=recorded_instant_us
                    AND effective_at_iso IS NOT NULL
                    AND length(trim(effective_at_iso))>0
                    AND recorded_at_iso IS NOT NULL
                    AND length(trim(recorded_at_iso))>0
                )
                OR
                (
                    timing_status='timing_unknown'
                    AND effective_instant_us IS NULL
                    AND recorded_instant_us IS NULL
                    AND effective_at_iso IS NULL
                    AND recorded_at_iso IS NULL
                )
            ),
            FOREIGN KEY(suppression_id)
                REFERENCES source_suppressions(suppression_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT
        ) WITHOUT ROWID
    """


def _source_suppression_timing_trigger_sql() -> dict[str, str]:
    return {
        "source_suppression_timing_no_replace": f"""
            CREATE TRIGGER source_suppression_timing_no_replace
            BEFORE INSERT ON {SOURCE_SUPPRESSION_TIMING_TABLE}
            WHEN EXISTS(
                SELECT 1 FROM {SOURCE_SUPPRESSION_TIMING_TABLE}
                WHERE suppression_id=NEW.suppression_id
            )
            BEGIN
                SELECT RAISE(ABORT,'source suppression timing already exists');
            END
        """,
        "source_suppression_timing_no_update": f"""
            CREATE TRIGGER source_suppression_timing_no_update
            BEFORE UPDATE ON {SOURCE_SUPPRESSION_TIMING_TABLE}
            BEGIN
                SELECT RAISE(ABORT,'source suppression timing is append-only');
            END
        """,
        "source_suppression_timing_no_delete": f"""
            CREATE TRIGGER source_suppression_timing_no_delete
            BEFORE DELETE ON {SOURCE_SUPPRESSION_TIMING_TABLE}
            BEGIN
                SELECT RAISE(ABORT,'source suppression timing is append-only');
            END
        """,
    }


def _assert_source_suppression_timing(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        """
        SELECT sql FROM sqlite_master
        WHERE type='table' AND name=?
        """,
        (SOURCE_SUPPRESSION_TIMING_TABLE,),
    ).fetchone()
    if (
        row is None
        or _normalize_schema_sql(row["sql"])
        != _normalize_schema_sql(_source_suppression_timing_table_sql())
    ):
        raise SuppressionLedgerIntegrityError(
            "source suppression timing table is missing or altered"
        )

    schema_rows = connection.execute(
        """
        SELECT type,name,sql
        FROM sqlite_master
        WHERE tbl_name=?
          AND type IN ('trigger','index')
        """,
        (SOURCE_SUPPRESSION_TIMING_TABLE,),
    ).fetchall()
    unexpected_indexes = tuple(
        item["name"]
        for item in schema_rows
        if item["type"] == "index" and item["sql"] is not None
    )
    if unexpected_indexes:
        raise SuppressionLedgerIntegrityError(
            "source suppression timing has unexpected user-defined indexes"
        )

    actual = {
        item["name"]: _normalize_schema_sql(item["sql"])
        for item in schema_rows
        if item["type"] == "trigger"
    }
    expected = {
        name: _normalize_schema_sql(sql)
        for name, sql in _source_suppression_timing_trigger_sql().items()
    }
    if actual != expected:
        raise SuppressionLedgerIntegrityError(
            "source suppression timing guards were altered"
        )

    missing = connection.execute(
        f"""
        SELECT 1
        FROM source_suppressions AS suppressions
        LEFT JOIN {SOURCE_SUPPRESSION_TIMING_TABLE} AS timing
          ON timing.suppression_id=suppressions.suppression_id
        WHERE timing.suppression_id IS NULL
        LIMIT 1
        """
    ).fetchone()
    if missing is not None:
        raise SuppressionLedgerIntegrityError(
            "source suppression is missing explicit timing status"
        )

    rows = connection.execute(
        f"""
        SELECT
            timing.suppression_id,
            timing.timing_status,
            timing.effective_instant_us,
            timing.recorded_instant_us,
            timing.effective_at_iso,
            timing.recorded_at_iso,
            suppressions.suppression_id AS parent_id
        FROM {SOURCE_SUPPRESSION_TIMING_TABLE} AS timing
        LEFT JOIN source_suppressions AS suppressions
          ON suppressions.suppression_id=timing.suppression_id
        ORDER BY timing.suppression_id
        """
    ).fetchall()
    for item in rows:
        if item["parent_id"] is None:
            raise SuppressionLedgerIntegrityError(
                "source suppression timing has no suppression parent"
            )
        if item["timing_status"] == "timing_unknown":
            if any(
                item[field] is not None
                for field in (
                    "effective_instant_us",
                    "recorded_instant_us",
                    "effective_at_iso",
                    "recorded_at_iso",
                )
            ):
                raise SuppressionLedgerIntegrityError(
                    "timing_unknown suppression cannot claim exact timing"
                )
            continue
        if item["timing_status"] != "timed":
            raise SuppressionLedgerIntegrityError(
                "source suppression timing status is invalid"
            )
        try:
            effective_at = suppression_datetime_from_iso(
                item["effective_at_iso"]
            )
            recorded_at = suppression_datetime_from_iso(
                item["recorded_at_iso"]
            )
            effective_us = suppression_instant(effective_at)
            recorded_us = suppression_instant(recorded_at)
        except ValueError as error:
            raise SuppressionLedgerIntegrityError(
                "source suppression timing contains invalid datetime encoding"
            ) from error
        if (
            effective_us != item["effective_instant_us"]
            or recorded_us != item["recorded_instant_us"]
            or effective_us > recorded_us
        ):
            raise SuppressionLedgerIntegrityError(
                "source suppression timing scalar does not match encoded datetime"
            )


def _source_suppression_marker_table_sql(
    version: str = SUPPRESSION_SCHEMA_VERSION,
) -> str:
    if version not in {
        LEGACY_SUPPRESSION_SCHEMA_VERSION,
        SUPPRESSION_SCHEMA_VERSION,
    }:
        raise ValueError("unsupported suppression schema marker version")
    return f"""
        CREATE TABLE {SUPPRESSION_SCHEMA_MARKER_TABLE} (
            marker_key TEXT PRIMARY KEY
                CHECK (marker_key='source_suppression_schema'),
            schema_version TEXT NOT NULL
                CHECK (schema_version='{version}')
        ) WITHOUT ROWID
    """


def _source_suppression_marker_trigger_sql() -> dict[str, str]:
    return {
        "source_suppression_schema_marker_no_update": f"""
            CREATE TRIGGER source_suppression_schema_marker_no_update
            BEFORE UPDATE ON {SUPPRESSION_SCHEMA_MARKER_TABLE}
            BEGIN
                SELECT RAISE(ABORT,'source suppression schema marker is immutable');
            END
        """,
        "source_suppression_schema_marker_no_delete": f"""
            CREATE TRIGGER source_suppression_schema_marker_no_delete
            BEFORE DELETE ON {SUPPRESSION_SCHEMA_MARKER_TABLE}
            BEGIN
                SELECT RAISE(ABORT,'source suppression schema marker is immutable');
            END
        """,
    }


def _suppression_schema_marker_exists(connection: sqlite3.Connection) -> bool:
    return (
        connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='table' AND name=?
            """,
            (SUPPRESSION_SCHEMA_MARKER_TABLE,),
        ).fetchone()
        is not None
    )


def _source_suppression_schema_marker_version(
    connection: sqlite3.Connection,
) -> str | None:
    table_row = connection.execute(
        """
        SELECT sql FROM sqlite_master
        WHERE type='table' AND name=?
        """,
        (SUPPRESSION_SCHEMA_MARKER_TABLE,),
    ).fetchone()
    if table_row is None:
        return None

    rows = connection.execute(
        f"""
        SELECT marker_key,schema_version
        FROM {SUPPRESSION_SCHEMA_MARKER_TABLE}
        """
    ).fetchall()
    if len(rows) != 1 or rows[0]["marker_key"] != "source_suppression_schema":
        raise SuppressionLedgerIntegrityError(
            "source suppression schema completion marker is inconsistent"
        )
    version = rows[0]["schema_version"]
    if version not in {
        LEGACY_SUPPRESSION_SCHEMA_VERSION,
        SUPPRESSION_SCHEMA_VERSION,
    }:
        raise SuppressionLedgerIntegrityError(
            "source suppression schema completion marker version is unknown"
        )

    if (
        _normalize_schema_sql(table_row["sql"])
        != _normalize_schema_sql(
            _source_suppression_marker_table_sql(version)
        )
    ):
        raise SuppressionLedgerIntegrityError(
            "source suppression schema completion marker is altered"
        )

    trigger_rows = connection.execute(
        """
        SELECT name,sql
        FROM sqlite_master
        WHERE type='trigger' AND tbl_name=?
        """,
        (SUPPRESSION_SCHEMA_MARKER_TABLE,),
    ).fetchall()
    actual = {
        row["name"]: _normalize_schema_sql(row["sql"])
        for row in trigger_rows
    }
    expected = {
        name: _normalize_schema_sql(sql)
        for name, sql in _source_suppression_marker_trigger_sql().items()
    }
    if actual != expected:
        raise SuppressionLedgerIntegrityError(
            "source suppression schema completion marker guards were altered"
        )
    return version


def _assert_source_suppression_schema_marker(
    connection: sqlite3.Connection,
) -> None:
    version = _source_suppression_schema_marker_version(connection)
    if version != SUPPRESSION_SCHEMA_VERSION:
        raise SuppressionLedgerIntegrityError(
            "source suppression schema completion marker is not current"
        )


def _install_or_upgrade_source_suppression_schema_marker(
    connection: sqlite3.Connection,
) -> None:
    version = _source_suppression_schema_marker_version(connection)
    if version == SUPPRESSION_SCHEMA_VERSION:
        return

    if version == LEGACY_SUPPRESSION_SCHEMA_VERSION:
        staging = "source_suppression_schema_marker_legacy_v01"
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (staging,),
        ).fetchone() is not None:
            raise SuppressionLedgerIntegrityError(
                "suppression marker migration staging table already exists"
            )
        for name in SUPPRESSION_SCHEMA_MARKER_TRIGGERS:
            connection.execute(f"DROP TRIGGER {name}")
        connection.execute(
            f"ALTER TABLE {SUPPRESSION_SCHEMA_MARKER_TABLE} RENAME TO {staging}"
        )
        connection.execute(_source_suppression_marker_table_sql())
        connection.execute(
            f"""
            INSERT INTO {SUPPRESSION_SCHEMA_MARKER_TABLE}
                (marker_key,schema_version)
            VALUES ('source_suppression_schema',?)
            """,
            (SUPPRESSION_SCHEMA_VERSION,),
        )
        connection.execute(f"DROP TABLE {staging}")
    elif version is None:
        connection.execute(_source_suppression_marker_table_sql())
        connection.execute(
            f"""
            INSERT INTO {SUPPRESSION_SCHEMA_MARKER_TABLE}
                (marker_key,schema_version)
            VALUES ('source_suppression_schema',?)
            """,
            (SUPPRESSION_SCHEMA_VERSION,),
        )
    else:
        raise SuppressionLedgerIntegrityError(
            "unsupported suppression schema marker migration"
        )

    for sql in _source_suppression_marker_trigger_sql().values():
        connection.execute(sql)
    _assert_source_suppression_schema_marker(connection)


def _source_suppression_table_sql(
    table_name: str = "source_suppressions",
) -> str:
    if table_name not in {
        "source_suppressions",
        "source_suppressions_migration_v01",
    }:
        raise ValueError("unsupported suppression table name")
    return f"""
        CREATE TABLE {table_name} (
            suppression_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL UNIQUE,
            requested_by TEXT NOT NULL,
            reason TEXT NOT NULL,
            FOREIGN KEY (source_id)
                REFERENCES sources(source_id)
                ON DELETE RESTRICT
        ) WITHOUT ROWID
    """


def _legacy_source_suppression_table_sql() -> str:
    """Exact pre-Slice-3A synthetic schema accepted for one-way migration."""

    return """
        CREATE TABLE source_suppressions (
            suppression_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL UNIQUE,
            requested_by TEXT NOT NULL,
            reason TEXT NOT NULL,
            FOREIGN KEY (source_id)
                REFERENCES sources(source_id)
                ON DELETE RESTRICT
        )
    """


def _assert_missing_suppression_ledger_is_bootstrap_safe(
    connection: sqlite3.Connection,
) -> None:
    """Reject ledger loss in an already HOME-marked synthetic store.

    The decision must be made before ensure_synthetic_store_domain() can add a
    marker to a genuinely fresh or recognized unmarked legacy database.
    """

    ledger_exists = connection.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='source_suppressions'
        """
    ).fetchone() is not None
    if ledger_exists:
        return

    domain_table_exists = connection.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='home_store_domain'
        """
    ).fetchone() is not None
    if not domain_table_exists:
        return

    try:
        rows = connection.execute(
            """
            SELECT domain
            FROM home_store_domain
            WHERE marker_key='store_domain'
            """
        ).fetchall()
    except sqlite3.DatabaseError:
        # Let the existing store-domain boundary classify malformed markers.
        return

    if len(rows) == 1 and rows[0][0] == SYNTHETIC_STORE_DOMAIN:
        raise SuppressionLedgerIntegrityError(
            "trusted synthetic HOME store is missing the source suppression ledger"
        )


def _source_suppression_timing_exists(
    connection: sqlite3.Connection,
) -> bool:
    return (
        connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='table' AND name=?
            """,
            (SOURCE_SUPPRESSION_TIMING_TABLE,),
        ).fetchone()
        is not None
    )


def _prepare_source_suppression_table(
    connection: sqlite3.Connection,
) -> None:
    marker_version = _source_suppression_schema_marker_version(connection)
    timing_exists = _source_suppression_timing_exists(connection)

    row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type='table' AND name='source_suppressions'
        """
    ).fetchone()
    if row is None:
        if marker_version is not None or timing_exists:
            raise SuppressionLedgerIntegrityError(
                "suppression schema evidence exists without the suppression ledger"
            )
        return

    actual = _normalize_schema_sql(row["sql"])
    target = _normalize_schema_sql(_source_suppression_table_sql())
    if actual == target:
        if marker_version is None:
            raise SuppressionLedgerIntegrityError(
                "canonical source suppression ledger lacks completed-upgrade marker"
            )
        if marker_version == LEGACY_SUPPRESSION_SCHEMA_VERSION:
            if timing_exists:
                raise SuppressionLedgerIntegrityError(
                    "legacy suppression marker cannot coexist with timing sidecar"
                )
            _assert_source_suppression_ledger_core(connection)
            return
        if marker_version == SUPPRESSION_SCHEMA_VERSION:
            assert_source_suppression_ledger(connection)
            return
        raise SuppressionLedgerIntegrityError(
            "unsupported source suppression schema marker version"
        )
    legacy = _normalize_schema_sql(_legacy_source_suppression_table_sql())
    if actual != legacy:
        raise SuppressionLedgerIntegrityError(
            "source suppression table is not a recognized migratable schema"
        )
    if marker_version is not None or timing_exists:
        raise SuppressionLedgerIntegrityError(
            "completed source suppression schema cannot re-enter legacy migration"
        )

    _assert_source_suppression_rows(connection)
    legacy_name = "source_suppressions_legacy_v01"
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (legacy_name,),
    ).fetchone() is not None:
        raise SuppressionLedgerIntegrityError(
            "suppression migration staging table already exists"
        )
    attached_triggers = connection.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type='trigger' AND tbl_name='source_suppressions'
        """
    ).fetchall()
    if attached_triggers:
        raise SuppressionLedgerIntegrityError(
            "legacy suppression table has unexpected attached triggers"
        )

    previous_legacy_mode = int(
        connection.execute("PRAGMA legacy_alter_table").fetchone()[0]
    )
    try:
        connection.execute("PRAGMA legacy_alter_table=ON")
        # Legacy rename mode deliberately does not rewrite references inside
        # triggers on other tables. Current evidence triggers therefore keep
        # referring to the canonical name while the old table is staged.
        connection.execute(
            f"ALTER TABLE source_suppressions RENAME TO {legacy_name}"
        )
        connection.execute(_source_suppression_table_sql())
        connection.execute(
            f"""
            INSERT INTO source_suppressions (
                suppression_id,source_id,requested_by,reason
            )
            SELECT suppression_id,source_id,requested_by,reason
            FROM {legacy_name}
            """
        )
        connection.execute(f"DROP TABLE {legacy_name}")
    finally:
        connection.execute(
            f"PRAGMA legacy_alter_table={previous_legacy_mode}"
        )


def _source_suppression_guard_sql() -> dict[str, str]:
    return {
        "source_suppressions_no_replace": """
            CREATE TRIGGER source_suppressions_no_replace
            BEFORE INSERT ON source_suppressions
            WHEN EXISTS (
                SELECT 1 FROM source_suppressions
                WHERE suppression_id=NEW.suppression_id
                   OR source_id=NEW.source_id
            )
            BEGIN
                SELECT RAISE(ABORT,'source suppression is append-only');
            END
        """,
        "source_suppressions_no_update": """
            CREATE TRIGGER source_suppressions_no_update
            BEFORE UPDATE ON source_suppressions
            BEGIN
                SELECT RAISE(ABORT,'source suppression is append-only');
            END
        """,
        "source_suppressions_no_delete": """
            CREATE TRIGGER source_suppressions_no_delete
            BEFORE DELETE ON source_suppressions
            BEGIN
                SELECT RAISE(ABORT,'source suppression is append-only');
            END
        """,
    }


def _normalize_schema_sql(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.replace("\n", " ").replace("\t", " ").split()).lower()


def _assert_source_suppression_ledger_core(
    connection: sqlite3.Connection,
) -> None:
    """Audit the immutable stop-use ledger independent of lifecycle version."""

    columns = tuple(
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(source_suppressions)"
        ).fetchall()
    )
    if columns != (
        "suppression_id",
        "source_id",
        "requested_by",
        "reason",
    ):
        raise SuppressionLedgerIntegrityError(
            "source suppression ledger schema is unavailable"
        )

    table_row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type='table' AND name='source_suppressions'
        """
    ).fetchone()
    if (
        table_row is None
        or _normalize_schema_sql(table_row["sql"])
        != _normalize_schema_sql(_source_suppression_table_sql())
    ):
        raise SuppressionLedgerIntegrityError(
            "source suppression table definition was altered"
        )

    rows = connection.execute(
        """
        SELECT type,name,tbl_name,sql
        FROM sqlite_master
        WHERE tbl_name='source_suppressions'
          AND type IN ('trigger','index')
        """
    ).fetchall()
    unexpected = tuple(
        (row["type"], row["name"])
        for row in rows
        if (
            row["type"] == "trigger"
            and row["name"] not in SOURCE_SUPPRESSION_TRIGGERS
        )
        or (
            row["type"] == "index"
            and row["sql"] is not None
        )
    )
    if unexpected:
        raise SuppressionLedgerIntegrityError(
            "source suppression ledger has unexpected mutation behavior"
        )

    actual_triggers = {
        row["name"]: _normalize_schema_sql(row["sql"])
        for row in rows
        if row["type"] == "trigger"
    }
    expected_triggers = {
        name: _normalize_schema_sql(sql)
        for name, sql in _source_suppression_guard_sql().items()
    }
    if actual_triggers != expected_triggers:
        raise SuppressionLedgerIntegrityError(
            "source suppression append-only guards were altered"
        )

    _assert_source_suppression_rows(connection)


def assert_source_suppression_ledger(connection: sqlite3.Connection) -> None:
    """Fail closed unless stop-use ledger and lifecycle timing are fully current."""

    _assert_source_suppression_schema_marker(connection)
    _assert_source_suppression_ledger_core(connection)
    _assert_source_suppression_timing(connection)


def _assert_source_suppression_rows(
    connection: sqlite3.Connection,
) -> None:
    invalid = connection.execute(
        """
        SELECT 1
        FROM source_suppressions AS suppressions
        LEFT JOIN sources
          ON sources.source_id=suppressions.source_id
        WHERE sources.source_id IS NULL
           OR length(trim(suppressions.suppression_id))=0
           OR length(trim(suppressions.source_id))=0
           OR length(trim(suppressions.requested_by))=0
           OR length(trim(suppressions.reason))=0
        LIMIT 1
        """
    ).fetchone()
    if invalid is not None:
        raise SuppressionLedgerIntegrityError(
            "source suppression ledger contains invalid provenance"
        )


def _execute_sql_script_in_current_transaction(
    connection: sqlite3.Connection,
    script: str,
) -> None:
    """Execute a DDL script without sqlite3.executescript() transaction breaks."""

    if not connection.in_transaction:
        raise SuppressionLedgerIntegrityError(
            "schema installation requires an active SQLite transaction"
        )

    pending = ""
    for character in script:
        pending += character
        if character != ";":
            continue
        if not sqlite3.complete_statement(pending):
            continue
        statement = pending.strip()
        pending = ""
        if statement:
            connection.execute(statement)
        if not connection.in_transaction:
            raise SuppressionLedgerIntegrityError(
                "schema installation escaped its SQLite transaction"
            )

    if pending.strip():
        raise SuppressionLedgerIntegrityError(
            "schema installation script ended with incomplete SQL"
        )


def _authority_lock_for_path(db_path: Path) -> RLock:
    key = str(db_path.expanduser().resolve())
    with _AUTHORITY_LOCK_REGISTRY_GUARD:
        lock = _AUTHORITY_LOCKS.get(key)
        if lock is None:
            lock = RLock()
            _AUTHORITY_LOCKS[key] = lock
        return lock


def _authority_ordered_write(
    method: Callable[..., _WRITE_RESULT],
) -> Callable[..., _WRITE_RESULT]:
    """Serialize authority-affecting writes with request handoff.

    This is intentionally a same-process v0.1 coordination primitive. Raw
    SQLite access and other processes remain outside this contract.
    """

    @wraps(method)
    def wrapper(self: "MemoryStore", *args: Any, **kwargs: Any) -> _WRITE_RESULT:
        with self._authority_ordering_lock:
            return method(self, *args, **kwargs)

    return wrapper


class MemoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._authority_ordering_lock = _authority_lock_for_path(self.db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # MemoryStore remains the synthetic-domain storage API in Task #06a.0.
        # Existing pre-real-data HOME databases may be marked synthetic here,
        # but a database already marked real is never downgraded or adopted.
        with self._unverified_connection() as connection:
            # One write transaction covers trust classification, any admitted
            # legacy migration, schema/guard installation, marker installation,
            # and the final integrity audit. No concurrent writer can alter the
            # stop-use ledger between those phases.
            connection.execute("BEGIN IMMEDIATE")
            _assert_missing_suppression_ledger_is_bootstrap_safe(connection)
            ensure_synthetic_store_domain(connection)
            _prepare_source_suppression_table(connection)
            _execute_sql_script_in_current_transaction(
                connection,
                """
                CREATE TABLE IF NOT EXISTS sources (
                    source_id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    authored_by TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS source_suppressions (
                    suppression_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL UNIQUE,
                    requested_by TEXT NOT NULL,
                    reason TEXT NOT NULL,

                    FOREIGN KEY (source_id)
                        REFERENCES sources(source_id)
                        ON DELETE RESTRICT
                ) WITHOUT ROWID;

                CREATE TRIGGER IF NOT EXISTS source_suppressions_no_replace
                BEFORE INSERT ON source_suppressions
                WHEN EXISTS (
                    SELECT 1 FROM source_suppressions
                    WHERE suppression_id=NEW.suppression_id
                       OR source_id=NEW.source_id
                )
                BEGIN
                    SELECT RAISE(ABORT,'source suppression is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS source_suppressions_no_update
                BEFORE UPDATE ON source_suppressions
                BEGIN
                    SELECT RAISE(ABORT,'source suppression is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS source_suppressions_no_delete
                BEFORE DELETE ON source_suppressions
                BEGIN
                    SELECT RAISE(ABORT,'source suppression is append-only');
                END;

                CREATE TABLE IF NOT EXISTS source_suppression_timing (
                    suppression_id TEXT PRIMARY KEY,
                    timing_status TEXT NOT NULL
                        CHECK(timing_status IN ('timed','timing_unknown')),
                    effective_instant_us INTEGER,
                    recorded_instant_us INTEGER,
                    effective_at_iso TEXT,
                    recorded_at_iso TEXT,
                    CHECK(
                        (
                            timing_status='timed'
                            AND typeof(effective_instant_us)='integer'
                            AND typeof(recorded_instant_us)='integer'
                            AND effective_instant_us<=recorded_instant_us
                            AND effective_at_iso IS NOT NULL
                            AND length(trim(effective_at_iso))>0
                            AND recorded_at_iso IS NOT NULL
                            AND length(trim(recorded_at_iso))>0
                        )
                        OR
                        (
                            timing_status='timing_unknown'
                            AND effective_instant_us IS NULL
                            AND recorded_instant_us IS NULL
                            AND effective_at_iso IS NULL
                            AND recorded_at_iso IS NULL
                        )
                    ),
                    FOREIGN KEY(suppression_id)
                        REFERENCES source_suppressions(suppression_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                ) WITHOUT ROWID;

                CREATE TRIGGER IF NOT EXISTS source_suppression_timing_no_replace
                BEFORE INSERT ON source_suppression_timing
                WHEN EXISTS(
                    SELECT 1 FROM source_suppression_timing
                    WHERE suppression_id=NEW.suppression_id
                )
                BEGIN
                    SELECT RAISE(ABORT,'source suppression timing already exists');
                END;

                CREATE TRIGGER IF NOT EXISTS source_suppression_timing_no_update
                BEFORE UPDATE ON source_suppression_timing
                BEGIN
                    SELECT RAISE(ABORT,'source suppression timing is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS source_suppression_timing_no_delete
                BEFORE DELETE ON source_suppression_timing
                BEGIN
                    SELECT RAISE(ABORT,'source suppression timing is append-only');
                END;

                CREATE TABLE IF NOT EXISTS interpretations (
                    interpretation_id TEXT PRIMARY KEY
                        CHECK (length(trim(interpretation_id)) > 0),
                    text TEXT NOT NULL
                        CHECK (length(trim(text)) > 0),
                    perspective_owner TEXT NOT NULL
                        CHECK (length(trim(perspective_owner)) > 0),
                    perspective_instance_id TEXT NOT NULL
                        CHECK (length(trim(perspective_instance_id)) > 0),
                    about_subject TEXT NOT NULL
                        CHECK (length(trim(about_subject)) > 0),
                    scope TEXT NOT NULL
                        CHECK (length(trim(scope)) > 0)
                );

                CREATE TABLE IF NOT EXISTS interpretation_evidence (
                    interpretation_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    source_id TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    start_char INTEGER NOT NULL,
                    end_char INTEGER NOT NULL,

                    PRIMARY KEY (
                        interpretation_id,
                        position
                    ),

                    FOREIGN KEY (interpretation_id)
                        REFERENCES interpretations(interpretation_id)
                        ON DELETE RESTRICT,

                    FOREIGN KEY (source_id)
                        REFERENCES sources(source_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS interpretation_threads (
                    thread_id TEXT PRIMARY KEY
                        CHECK (length(trim(thread_id)) > 0),
                    question TEXT NOT NULL
                        CHECK (length(trim(question)) > 0),
                    perspective_owner TEXT NOT NULL
                        CHECK (length(trim(perspective_owner)) > 0),
                    perspective_instance_id TEXT NOT NULL
                        CHECK (length(trim(perspective_instance_id)) > 0),
                    about_subject TEXT NOT NULL
                        CHECK (length(trim(about_subject)) > 0),
                    scope TEXT NOT NULL
                        CHECK (length(trim(scope)) > 0)
                );

                CREATE TABLE IF NOT EXISTS interpretation_thread_memberships (
                    admission_id TEXT PRIMARY KEY
                        CHECK (length(trim(admission_id)) > 0),
                    interpretation_id TEXT NOT NULL UNIQUE
                        CHECK (length(trim(interpretation_id)) > 0),
                    thread_id TEXT NOT NULL
                        CHECK (length(trim(thread_id)) > 0),
                    perspective_instance_id TEXT NOT NULL
                        CHECK (length(trim(perspective_instance_id)) > 0),
                    admitted_by_instance_id TEXT NOT NULL
                        CHECK (length(trim(admitted_by_instance_id)) > 0),

                    FOREIGN KEY (interpretation_id)
                        REFERENCES interpretations(interpretation_id)
                        ON DELETE RESTRICT,

                    FOREIGN KEY (thread_id)
                        REFERENCES interpretation_threads(thread_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS supersessions (
                    previous_interpretation_id TEXT NOT NULL,
                    new_interpretation_id TEXT NOT NULL UNIQUE,

                    PRIMARY KEY (
                        previous_interpretation_id,
                        new_interpretation_id
                    ),

                    FOREIGN KEY (previous_interpretation_id)
                        REFERENCES interpretations(interpretation_id)
                        ON DELETE RESTRICT,

                    FOREIGN KEY (new_interpretation_id)
                        REFERENCES interpretations(interpretation_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS supersession_evidence (
                    previous_interpretation_id TEXT NOT NULL,
                    new_interpretation_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    source_id TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    start_char INTEGER NOT NULL,
                    end_char INTEGER NOT NULL,

                    PRIMARY KEY (
                        previous_interpretation_id,
                        new_interpretation_id,
                        position
                    ),

                    FOREIGN KEY (
                        previous_interpretation_id,
                        new_interpretation_id
                    )
                        REFERENCES supersessions(
                            previous_interpretation_id,
                            new_interpretation_id
                        )
                        ON DELETE RESTRICT,

                    FOREIGN KEY (source_id)
                        REFERENCES sources(source_id)
                        ON DELETE RESTRICT
                );
                """
            )
            connection.execute(
                f"""
                INSERT INTO {SOURCE_SUPPRESSION_TIMING_TABLE} (
                    suppression_id,
                    timing_status,
                    effective_instant_us,
                    recorded_instant_us,
                    effective_at_iso,
                    recorded_at_iso
                )
                SELECT
                    suppressions.suppression_id,
                    'timing_unknown',
                    NULL,
                    NULL,
                    NULL,
                    NULL
                FROM source_suppressions AS suppressions
                WHERE NOT EXISTS (
                    SELECT 1 FROM {SOURCE_SUPPRESSION_TIMING_TABLE} AS timing
                    WHERE timing.suppression_id=suppressions.suppression_id
                )
                """
            )
            _install_or_upgrade_source_suppression_schema_marker(connection)
            assert_source_suppression_ledger(connection)
            if not connection.in_transaction:
                raise SuppressionLedgerIntegrityError(
                    "MemoryStore initialization lost its SQLite write transaction"
                )

    @_authority_ordered_write
    def add_source(self, source: SourceRecord) -> None:
        self._validate_source_record_integrity(source=source)

        with self._connection() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO sources (
                        source_id,
                        content,
                        authored_by,
                        scope,
                        content_sha256
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        source.source_id,
                        source.content,
                        source.authored_by,
                        source.scope,
                        source.content_sha256,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    f"source_id already exists: {source.source_id}"
                ) from error

    def get_source(self, source_id: str) -> SourceRecord:
        with self._connection() as connection:
            source = self._get_source_from_connection(
                connection=connection,
                source_id=source_id,
            )

            suppressed_ids = self._get_suppressed_source_ids_from_connection(
                connection=connection,
            )

            if source.source_id in suppressed_ids:
                raise SuppressedMemoryError(
                    "source is suppressed and cannot be used"
                )

            return source

    def get_source_for_audit(self, source_id: str) -> SourceRecord:
        with self._connection() as connection:
            return self._get_source_from_connection(
                connection=connection,
                source_id=source_id,
            )

    @_authority_ordered_write
    def suppress_source(
        self,
        suppression: SuppressionRecord,
    ) -> None:
        if not isinstance(suppression, SuppressionRecord):
            raise TypeError("suppression must be SuppressionRecord")
        if not suppression.timing_known:
            raise ValueError(
                "new source suppression writes require explicit effective_at and recorded_at"
            )

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            assert_source_suppression_ledger(connection)
            self._get_source_from_connection(
                connection=connection,
                source_id=suppression.source_id,
            )

            try:
                connection.execute(
                    """
                    INSERT INTO source_suppressions (
                        suppression_id,
                        source_id,
                        requested_by,
                        reason
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        suppression.suppression_id,
                        suppression.source_id,
                        suppression.requested_by,
                        suppression.reason,
                    ),
                )
                assert suppression.effective_at is not None
                assert suppression.recorded_at is not None
                connection.execute(
                    f"""
                    INSERT INTO {SOURCE_SUPPRESSION_TIMING_TABLE} (
                        suppression_id,
                        timing_status,
                        effective_instant_us,
                        recorded_instant_us,
                        effective_at_iso,
                        recorded_at_iso
                    )
                    VALUES (?, 'timed', ?, ?, ?, ?)
                    """,
                    (
                        suppression.suppression_id,
                        suppression_instant(suppression.effective_at),
                        suppression_instant(suppression.recorded_at),
                        suppression_datetime_to_iso(
                            suppression.effective_at
                        ),
                        suppression_datetime_to_iso(
                            suppression.recorded_at
                        ),
                    ),
                )
                assert_source_suppression_ledger(connection)
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    "source suppression could not be stored"
                ) from error

    def get_suppressions(
        self,
    ) -> tuple[SuppressionRecord, ...]:
        with self._connection() as connection:
            return self._get_suppressions_from_connection(
                connection=connection,
            )

    def is_source_usable(self, source_id: str) -> bool:
        with self._connection() as connection:
            self._get_source_from_connection(
                connection=connection,
                source_id=source_id,
            )

            suppressed_ids = self._get_suppressed_source_ids_from_connection(
                connection=connection,
            )

            return source_id not in suppressed_ids

    @_authority_ordered_write
    def add_interpretation(
        self,
        interpretation: InterpretationRecord,
    ) -> None:
        self._validate_interpretation_record(
            interpretation=interpretation,
        )

        with self._connection() as connection:
            suppressed_ids = self._get_suppressed_source_ids_from_connection(
                connection=connection,
            )

            for evidence in interpretation.evidence:
                self._validate_evidence_against_stored_source(
                    connection=connection,
                    evidence=evidence,
                    expected_scope=interpretation.scope,
                )

                if evidence.source_id in suppressed_ids:
                    raise SuppressedMemoryError(
                        "cannot create an interpretation from "
                        "a suppressed source"
                    )

            try:
                connection.execute(
                    """
                    INSERT INTO interpretations (
                        interpretation_id,
                        text,
                        perspective_owner,
                        perspective_instance_id,
                        about_subject,
                        scope
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        interpretation.interpretation_id,
                        interpretation.text,
                        interpretation.perspective_owner,
                        interpretation.perspective_instance_id,
                        interpretation.about_subject,
                        interpretation.scope,
                    ),
                )

                for position, evidence in enumerate(
                    interpretation.evidence
                ):
                    connection.execute(
                        """
                        INSERT INTO interpretation_evidence (
                            interpretation_id,
                            position,
                            source_id,
                            source_sha256,
                            start_char,
                            end_char
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            interpretation.interpretation_id,
                            position,
                            evidence.source_id,
                            evidence.source_sha256,
                            evidence.start_char,
                            evidence.end_char,
                        ),
                    )

            except sqlite3.IntegrityError as error:
                raise ValueError(
                    "interpretation could not be stored"
                ) from error

    def get_interpretation(
        self,
        interpretation_id: str,
    ) -> InterpretationRecord:
        with self._connection() as connection:
            interpretation = self._get_interpretation_from_connection(
                connection=connection,
                interpretation_id=interpretation_id,
            )

            suppressions = self._get_suppressions_from_connection(
                connection=connection,
            )

            if not interpretation_is_usable(
                interpretation=interpretation,
                suppressions=suppressions,
            ):
                raise SuppressedMemoryError(
                    "interpretation is suppressed and cannot be used"
                )

            return interpretation

    def get_interpretation_for_audit(
        self,
        interpretation_id: str,
    ) -> InterpretationRecord:
        with self._connection() as connection:
            return self._get_interpretation_from_connection(
                connection=connection,
                interpretation_id=interpretation_id,
            )

    def is_interpretation_usable(
        self,
        interpretation_id: str,
    ) -> bool:
        with self._connection() as connection:
            interpretation = self._get_interpretation_from_connection(
                connection=connection,
                interpretation_id=interpretation_id,
            )

            suppressions = self._get_suppressions_from_connection(
                connection=connection,
            )

            return interpretation_is_usable(
                interpretation=interpretation,
                suppressions=suppressions,
            )

    @_authority_ordered_write
    def add_thread(self, thread: InterpretationThread) -> None:
        self._validate_thread_record(thread=thread)

        with self._connection() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO interpretation_threads (
                        thread_id,
                        question,
                        perspective_owner,
                        perspective_instance_id,
                        about_subject,
                        scope
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        thread.thread_id,
                        thread.question,
                        thread.perspective_owner,
                        thread.perspective_instance_id,
                        thread.about_subject,
                        thread.scope,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    f"thread_id already exists: {thread.thread_id}"
                ) from error

    def get_thread(
        self,
        thread_id: str,
    ) -> InterpretationThread:
        with self._connection() as connection:
            return self._get_thread_from_connection(
                connection=connection,
                thread_id=thread_id,
            )

    @_authority_ordered_write
    def admit_interpretation(
        self,
        admission: ThreadAdmissionRecord,
    ) -> None:
        self._validate_thread_admission_record(admission=admission)

        with self._connection() as connection:
            thread = self._get_thread_from_connection(
                connection=connection,
                thread_id=admission.thread_id,
            )

            interpretation = self._get_interpretation_from_connection(
                connection=connection,
                interpretation_id=admission.interpretation_id,
            )

            self._validate_interpretation_against_thread(
                interpretation=interpretation,
                thread=thread,
            )

            if (
                admission.perspective_instance_id
                != thread.perspective_instance_id
                or admission.perspective_instance_id
                != interpretation.perspective_instance_id
            ):
                raise ValueError(
                    "thread admission perspective instance "
                    "does not match persisted interpretation and thread"
                )

            for evidence in interpretation.evidence:
                self._validate_evidence_against_stored_source(
                    connection=connection,
                    evidence=evidence,
                    expected_scope=thread.scope,
                )

            try:
                connection.execute(
                    """
                    INSERT INTO interpretation_thread_memberships (
                        admission_id,
                        interpretation_id,
                        thread_id,
                        perspective_instance_id,
                        admitted_by_instance_id
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        admission.admission_id,
                        admission.interpretation_id,
                        admission.thread_id,
                        admission.perspective_instance_id,
                        admission.admitted_by_instance_id,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    "interpretation thread admission could not be stored"
                ) from error

    def get_thread_topology(
        self,
        thread_id: str,
    ) -> ThreadTopology:
        with self._read_snapshot() as connection:
            return self._get_thread_topology_from_connection(
                connection=connection,
                thread_id=thread_id,
            )

    def get_lineage_resolution_input(
        self,
        thread_id: str,
    ) -> LineageResolutionInput:
        """Assemble one complete, payload-free thread snapshot.

        Membership, revision topology, required evidence dependencies, and
        current source-suppression state are read in one explicit SQLite read
        transaction. Any known structural incompleteness fails closed.
        """
        with self._read_snapshot() as connection:
            return self._build_lineage_resolution_input_from_connection(
                connection=connection,
                thread_id=thread_id,
            )

    @_authority_ordered_write
    def add_supersession(
        self,
        supersession: SupersessionRecord,
    ) -> None:
        if not supersession.reason_evidence:
            raise ValueError("supersession must have evidence")

        with self._connection() as connection:
            previous = self._get_interpretation_from_connection(
                connection=connection,
                interpretation_id=(
                    supersession.previous_interpretation_id
                ),
            )

            new = self._get_interpretation_from_connection(
                connection=connection,
                interpretation_id=(
                    supersession.new_interpretation_id
                ),
            )

            if previous.interpretation_id == new.interpretation_id:
                raise ValueError(
                    "an interpretation cannot supersede itself"
                )

            if (
                previous.perspective_owner
                != new.perspective_owner
            ):
                raise ValueError(
                    "supersession must stay within "
                    "the same perspective owner"
                )

            if (
                previous.perspective_instance_id
                != new.perspective_instance_id
            ):
                raise ValueError(
                    "supersession must stay within "
                    "the same perspective instance"
                )

            if previous.about_subject != new.about_subject:
                raise ValueError(
                    "supersession must stay about the same subject"
                )

            if previous.scope != new.scope:
                raise ValueError(
                    "supersession must stay within the same scope"
                )

            previous_admission = (
                self._get_thread_admission_from_connection(
                    connection=connection,
                    interpretation_id=previous.interpretation_id,
                )
            )

            new_admission = (
                self._get_thread_admission_from_connection(
                    connection=connection,
                    interpretation_id=new.interpretation_id,
                )
            )

            if previous_admission.thread_id != new_admission.thread_id:
                raise ValueError(
                    "supersession must stay within "
                    "the same interpretation thread"
                )

            thread = self._get_thread_from_connection(
                connection=connection,
                thread_id=previous_admission.thread_id,
            )

            self._validate_interpretation_against_thread(
                interpretation=previous,
                thread=thread,
            )
            self._validate_interpretation_against_thread(
                interpretation=new,
                thread=thread,
            )

            if (
                previous_admission.perspective_instance_id
                != thread.perspective_instance_id
                or new_admission.perspective_instance_id
                != thread.perspective_instance_id
            ):
                raise ValueError(
                    "supersession crosses a perspective instance boundary"
                )

            for evidence in supersession.reason_evidence:
                self._validate_evidence_against_stored_source(
                    connection=connection,
                    evidence=evidence,
                    expected_scope=thread.scope,
                )

            suppressions = self._get_suppressions_from_connection(
                connection=connection,
            )

            if not supersession_is_usable(
                supersession=supersession,
                previous=previous,
                new=new,
                suppressions=suppressions,
            ):
                raise SuppressedMemoryError(
                    "cannot create a supersession from suppressed memory"
                )

            existing_supersessions = (
                self._get_supersessions_from_connection(
                    connection=connection,
                )
            )

            validate_supersession_graph(
                supersessions=(
                    *existing_supersessions,
                    supersession,
                )
            )

            try:
                connection.execute(
                    """
                    INSERT INTO supersessions (
                        previous_interpretation_id,
                        new_interpretation_id
                    )
                    VALUES (?, ?)
                    """,
                    (
                        supersession.previous_interpretation_id,
                        supersession.new_interpretation_id,
                    ),
                )

                for position, evidence in enumerate(
                    supersession.reason_evidence
                ):
                    connection.execute(
                        """
                        INSERT INTO supersession_evidence (
                            previous_interpretation_id,
                            new_interpretation_id,
                            position,
                            source_id,
                            source_sha256,
                            start_char,
                            end_char
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            supersession.previous_interpretation_id,
                            supersession.new_interpretation_id,
                            position,
                            evidence.source_id,
                            evidence.source_sha256,
                            evidence.start_char,
                            evidence.end_char,
                        ),
                    )

            except sqlite3.IntegrityError as error:
                raise ValueError(
                    "supersession could not be stored"
                ) from error

    def get_supersessions(
        self,
    ) -> tuple[SupersessionRecord, ...]:
        with self._connection() as connection:
            return self._get_supersessions_from_connection(
                connection=connection,
            )

    def is_supersession_usable(
        self,
        *,
        previous_interpretation_id: str,
        new_interpretation_id: str,
    ) -> bool:
        with self._connection() as connection:
            supersession = self._get_supersession_from_connection(
                connection=connection,
                previous_interpretation_id=previous_interpretation_id,
                new_interpretation_id=new_interpretation_id,
            )

            previous = self._get_interpretation_from_connection(
                connection=connection,
                interpretation_id=previous_interpretation_id,
            )

            new = self._get_interpretation_from_connection(
                connection=connection,
                interpretation_id=new_interpretation_id,
            )

            suppressions = self._get_suppressions_from_connection(
                connection=connection,
            )

            return supersession_is_usable(
                supersession=supersession,
                previous=previous,
                new=new,
                suppressions=suppressions,
            )

    @contextmanager
    def _request_delivery_ordering_guard(self) -> Iterator[None]:
        """Serialize one request handoff against authority-affecting writes.

        v0.1 scope: one Python process. The guard is shared by MemoryStore
        instances that address the same resolved SQLite path.
        """
        with self._authority_ordering_lock:
            yield

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()

        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @contextmanager
    def _unverified_connection(self) -> Iterator[sqlite3.Connection]:
        """Initialization-only connection before a domain marker exists."""
        connection = self._connect_raw()

        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @contextmanager
    def _read_snapshot(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()

        try:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            yield connection
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = self._connect_raw()
        try:
            assert_synthetic_store_domain(connection)
        except BaseException:
            connection.close()
            raise
        return connection

    def _connect_raw(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _validate_source_record_integrity(
        self,
        *,
        source: SourceRecord,
    ) -> None:
        actual_digest = sha256(
            source.content.encode("utf-8")
        ).hexdigest()

        if actual_digest != source.content_sha256:
            raise ValueError(
                "source content hash does not match source content"
            )

    def _get_source_from_connection(
        self,
        *,
        connection: sqlite3.Connection,
        source_id: str,
    ) -> SourceRecord:
        row = connection.execute(
            """
            SELECT
                source_id,
                content,
                authored_by,
                scope,
                content_sha256
            FROM sources
            WHERE source_id = ?
            """,
            (source_id,),
        ).fetchone()

        if row is None:
            raise KeyError(source_id)

        actual_digest = sha256(
            row["content"].encode("utf-8")
        ).hexdigest()

        if actual_digest != row["content_sha256"]:
            raise ValueError(
                "stored source content hash does not match content"
            )

        return SourceRecord(
            source_id=row["source_id"],
            content=row["content"],
            authored_by=row["authored_by"],
            scope=row["scope"],
            content_sha256=row["content_sha256"],
        )

    def _validate_evidence_against_stored_source(
        self,
        *,
        connection: sqlite3.Connection,
        evidence: EvidenceRef,
        expected_scope: str | None = None,
    ) -> None:
        row = connection.execute(
            """
            SELECT
                content,
                scope,
                content_sha256
            FROM sources
            WHERE source_id = ?
            """,
            (evidence.source_id,),
        ).fetchone()

        if row is None:
            raise ValueError(
                f"evidence source does not exist: "
                f"{evidence.source_id}"
            )

        actual_digest = sha256(
            row["content"].encode("utf-8")
        ).hexdigest()

        if actual_digest != row["content_sha256"]:
            raise ValueError(
                "stored source content hash does not match content"
            )

        if row["content_sha256"] != evidence.source_sha256:
            raise ValueError(
                "evidence source hash does not match "
                "the stored source snapshot"
            )

        if (
            expected_scope is not None
            and row["scope"] != expected_scope
        ):
            raise ValueError(
                "evidence source scope does not match "
                "the derived record scope"
            )

        if evidence.start_char < 0:
            raise ValueError(
                "evidence start_char cannot be negative"
            )

        if evidence.end_char <= evidence.start_char:
            raise ValueError(
                "evidence end_char must be greater than start_char"
            )

        if evidence.end_char > len(row["content"]):
            raise ValueError(
                "evidence range exceeds stored source content"
            )

    def _get_interpretation_from_connection(
        self,
        *,
        connection: sqlite3.Connection,
        interpretation_id: str,
    ) -> InterpretationRecord:
        row = connection.execute(
            """
            SELECT
                interpretation_id,
                text,
                perspective_owner,
                perspective_instance_id,
                about_subject,
                scope
            FROM interpretations
            WHERE interpretation_id = ?
            """,
            (interpretation_id,),
        ).fetchone()

        if row is None:
            raise KeyError(interpretation_id)

        evidence_rows = connection.execute(
            """
            SELECT
                source_id,
                source_sha256,
                start_char,
                end_char
            FROM interpretation_evidence
            WHERE interpretation_id = ?
            ORDER BY position
            """,
            (interpretation_id,),
        ).fetchall()

        evidence = tuple(
            EvidenceRef(
                source_id=evidence_row["source_id"],
                source_sha256=evidence_row["source_sha256"],
                start_char=evidence_row["start_char"],
                end_char=evidence_row["end_char"],
            )
            for evidence_row in evidence_rows
        )

        return create_interpretation_record(
            interpretation_id=row["interpretation_id"],
            text=row["text"],
            perspective_owner=row["perspective_owner"],
            perspective_instance_id=row["perspective_instance_id"],
            about_subject=row["about_subject"],
            scope=row["scope"],
            evidence=evidence,
        )

    def _get_thread_topology_from_connection(
        self,
        *,
        connection: sqlite3.Connection,
        thread_id: str,
    ) -> ThreadTopology:
        self._get_thread_from_connection(
            connection=connection,
            thread_id=thread_id,
        )

        interpretation_rows = connection.execute(
            """
            SELECT interpretation_id
            FROM interpretation_thread_memberships
            WHERE thread_id = ?
            ORDER BY rowid
            """,
            (thread_id,),
        ).fetchall()

        touching_edge_rows = connection.execute(
            """
            SELECT
                supersessions.previous_interpretation_id,
                supersessions.new_interpretation_id,
                previous_membership.thread_id AS previous_thread_id,
                new_membership.thread_id AS new_thread_id
            FROM supersessions
            LEFT JOIN interpretation_thread_memberships
                AS previous_membership
                ON previous_membership.interpretation_id
                = supersessions.previous_interpretation_id
            LEFT JOIN interpretation_thread_memberships
                AS new_membership
                ON new_membership.interpretation_id
                = supersessions.new_interpretation_id
            WHERE
                previous_membership.thread_id = ?
                OR new_membership.thread_id = ?
            ORDER BY supersessions.rowid
            """,
            (thread_id, thread_id),
        ).fetchall()

        for row in touching_edge_rows:
            if (
                row["previous_thread_id"] != thread_id
                or row["new_thread_id"] != thread_id
            ):
                raise LineageIntegrityError(
                    "thread topology is not closed under known supersession edges"
                )

        return ThreadTopology(
            thread_id=thread_id,
            interpretation_ids=frozenset(
                row["interpretation_id"]
                for row in interpretation_rows
            ),
            supersession_edges=frozenset(
                (
                    row["previous_interpretation_id"],
                    row["new_interpretation_id"],
                )
                for row in touching_edge_rows
            ),
        )

    def _build_lineage_resolution_input_from_connection(
        self,
        *,
        connection: sqlite3.Connection,
        thread_id: str,
    ) -> LineageResolutionInput:
        thread = self._get_thread_from_connection(
            connection=connection,
            thread_id=thread_id,
        )

        member_rows = connection.execute(
            """
            SELECT
                memberships.interpretation_id,
                memberships.perspective_instance_id AS admission_instance_id,
                memberships.admitted_by_instance_id,
                interpretations.perspective_owner,
                interpretations.perspective_instance_id,
                interpretations.about_subject,
                interpretations.scope
            FROM interpretation_thread_memberships AS memberships
            JOIN interpretations
                ON interpretations.interpretation_id
                = memberships.interpretation_id
            WHERE memberships.thread_id = ?
            ORDER BY memberships.rowid
            """,
            (thread_id,),
        ).fetchall()

        interpretation_ids = frozenset(
            row["interpretation_id"]
            for row in member_rows
        )

        for row in member_rows:
            if (
                not row["admitted_by_instance_id"].strip()
                or row["perspective_owner"] != thread.perspective_owner
                or row["perspective_instance_id"]
                != thread.perspective_instance_id
                or row["admission_instance_id"]
                != thread.perspective_instance_id
                or row["about_subject"] != thread.about_subject
                or row["scope"] != thread.scope
                or row["perspective_instance_id"]
                == SYNTHETIC_UNATTRIBUTED_INSTANCE_ID
            ):
                raise LineageIntegrityError(
                    "thread membership metadata is internally inconsistent"
                )

        topology = self._get_thread_topology_from_connection(
            connection=connection,
            thread_id=thread_id,
        )

        if topology.interpretation_ids != interpretation_ids:
            raise LineageIntegrityError(
                "thread membership changed during snapshot assembly"
            )

        evidence_rows = connection.execute(
            """
            SELECT
                memberships.interpretation_id,
                COUNT(evidence.position) AS evidence_count,
                COUNT(sources.source_id) AS source_count,
                MAX(
                    CASE
                        WHEN evidence.source_sha256 != sources.content_sha256
                        THEN 1 ELSE 0
                    END
                ) AS hash_metadata_mismatch,
                MAX(
                    CASE
                        WHEN sources.scope != ?
                        THEN 1 ELSE 0
                    END
                ) AS scope_mismatch,
                MAX(
                    CASE
                        WHEN suppressions.source_id IS NOT NULL
                        THEN 1 ELSE 0
                    END
                ) AS blocked
            FROM interpretation_thread_memberships AS memberships
            LEFT JOIN interpretation_evidence AS evidence
                ON evidence.interpretation_id
                = memberships.interpretation_id
            LEFT JOIN sources
                ON sources.source_id = evidence.source_id
            LEFT JOIN source_suppressions AS suppressions
                ON suppressions.source_id = evidence.source_id
            WHERE memberships.thread_id = ?
            GROUP BY memberships.interpretation_id
            ORDER BY memberships.rowid
            """,
            (thread.scope, thread_id),
        ).fetchall()

        if len(evidence_rows) != len(interpretation_ids):
            raise LineageIntegrityError(
                "thread evidence view is incomplete"
            )

        blocked_interpretation_ids: set[str] = set()

        for row in evidence_rows:
            if row["evidence_count"] <= 0:
                raise LineageIntegrityError(
                    "thread interpretation is missing required evidence"
                )
            if row["source_count"] != row["evidence_count"]:
                raise LineageIntegrityError(
                    "thread interpretation references a missing source"
                )
            if row["hash_metadata_mismatch"]:
                raise LineageIntegrityError(
                    "thread evidence source hash metadata does not match"
                )
            if row["scope_mismatch"]:
                raise LineageIntegrityError(
                    "thread evidence crosses the thread scope boundary"
                )
            if row["blocked"]:
                blocked_interpretation_ids.add(
                    row["interpretation_id"]
                )

        edge_rows = connection.execute(
            """
            SELECT
                supersessions.previous_interpretation_id,
                supersessions.new_interpretation_id,
                COUNT(evidence.position) AS evidence_count,
                COUNT(sources.source_id) AS source_count,
                MAX(
                    CASE
                        WHEN evidence.source_sha256 != sources.content_sha256
                        THEN 1 ELSE 0
                    END
                ) AS hash_metadata_mismatch,
                MAX(
                    CASE
                        WHEN sources.scope != ?
                        THEN 1 ELSE 0
                    END
                ) AS scope_mismatch,
                MAX(
                    CASE
                        WHEN suppressions.source_id IS NOT NULL
                        THEN 1 ELSE 0
                    END
                ) AS blocked
            FROM supersessions
            JOIN interpretation_thread_memberships AS previous_membership
                ON previous_membership.interpretation_id
                = supersessions.previous_interpretation_id
            JOIN interpretation_thread_memberships AS new_membership
                ON new_membership.interpretation_id
                = supersessions.new_interpretation_id
            LEFT JOIN supersession_evidence AS evidence
                ON evidence.previous_interpretation_id
                = supersessions.previous_interpretation_id
                AND evidence.new_interpretation_id
                = supersessions.new_interpretation_id
            LEFT JOIN sources
                ON sources.source_id = evidence.source_id
            LEFT JOIN source_suppressions AS suppressions
                ON suppressions.source_id = evidence.source_id
            WHERE
                previous_membership.thread_id = ?
                AND new_membership.thread_id = ?
            GROUP BY
                supersessions.previous_interpretation_id,
                supersessions.new_interpretation_id
            ORDER BY supersessions.rowid
            """,
            (thread.scope, thread_id, thread_id),
        ).fetchall()

        edges_from_rows = frozenset(
            (
                row["previous_interpretation_id"],
                row["new_interpretation_id"],
            )
            for row in edge_rows
        )

        if edges_from_rows != topology.supersession_edges:
            raise LineageIntegrityError(
                "thread revision edge view is incomplete"
            )

        blocked_supersession_edges: set[tuple[str, str]] = set()

        for row in edge_rows:
            edge = (
                row["previous_interpretation_id"],
                row["new_interpretation_id"],
            )
            if row["evidence_count"] <= 0:
                raise LineageIntegrityError(
                    "thread supersession is missing required reason evidence"
                )
            if row["source_count"] != row["evidence_count"]:
                raise LineageIntegrityError(
                    "thread supersession references a missing source"
                )
            if row["hash_metadata_mismatch"]:
                raise LineageIntegrityError(
                    "thread supersession source hash metadata does not match"
                )
            if row["scope_mismatch"]:
                raise LineageIntegrityError(
                    "thread supersession evidence crosses the scope boundary"
                )
            if row["blocked"]:
                blocked_supersession_edges.add(edge)

        return _create_store_assembled_input(
            thread_id=thread_id,
            interpretation_ids=interpretation_ids,
            supersession_edges=topology.supersession_edges,
            blocked_interpretation_ids=frozenset(
                blocked_interpretation_ids
            ),
            blocked_supersession_edges=frozenset(
                blocked_supersession_edges
            ),
        )

    def _get_thread_from_connection(
        self,
        *,
        connection: sqlite3.Connection,
        thread_id: str,
    ) -> InterpretationThread:
        row = connection.execute(
            """
            SELECT
                thread_id,
                question,
                perspective_owner,
                perspective_instance_id,
                about_subject,
                scope
            FROM interpretation_threads
            WHERE thread_id = ?
            """,
            (thread_id,),
        ).fetchone()

        if row is None:
            raise KeyError(thread_id)

        return InterpretationThread(
            thread_id=row["thread_id"],
            question=row["question"],
            perspective_owner=row["perspective_owner"],
            perspective_instance_id=row["perspective_instance_id"],
            about_subject=row["about_subject"],
            scope=row["scope"],
        )

    def _get_thread_admission_from_connection(
        self,
        *,
        connection: sqlite3.Connection,
        interpretation_id: str,
    ) -> ThreadAdmissionRecord:
        row = connection.execute(
            """
            SELECT
                admission_id,
                thread_id,
                interpretation_id,
                perspective_instance_id,
                admitted_by_instance_id
            FROM interpretation_thread_memberships
            WHERE interpretation_id = ?
            """,
            (interpretation_id,),
        ).fetchone()

        if row is None:
            raise ValueError(
                "interpretation must be admitted to a thread "
                "before it can participate in supersession"
            )

        return ThreadAdmissionRecord(
            admission_id=row["admission_id"],
            thread_id=row["thread_id"],
            interpretation_id=row["interpretation_id"],
            perspective_instance_id=row[
                "perspective_instance_id"
            ],
            admitted_by_instance_id=row[
                "admitted_by_instance_id"
            ],
        )

    def _validate_interpretation_against_thread(
        self,
        *,
        interpretation: InterpretationRecord,
        thread: InterpretationThread,
    ) -> None:
        if interpretation.perspective_owner != thread.perspective_owner:
            raise ValueError(
                "interpretation perspective owner "
                "does not match the thread"
            )

        if (
            interpretation.perspective_instance_id
            != thread.perspective_instance_id
        ):
            raise ValueError(
                "interpretation perspective instance "
                "does not match the thread"
            )

        if interpretation.about_subject != thread.about_subject:
            raise ValueError(
                "interpretation subject does not match the thread"
            )

        if interpretation.scope != thread.scope:
            raise ValueError(
                "interpretation scope does not match the thread"
            )

    def _validate_interpretation_record(
        self,
        *,
        interpretation: InterpretationRecord,
    ) -> None:
        values = {
            "interpretation_id": interpretation.interpretation_id,
            "text": interpretation.text,
            "perspective_owner": interpretation.perspective_owner,
            "perspective_instance_id": (
                interpretation.perspective_instance_id
            ),
            "about_subject": interpretation.about_subject,
            "scope": interpretation.scope,
        }

        for field_name, value in values.items():
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")

        if not interpretation.evidence:
            raise ValueError(
                "interpretation must have at least one evidence reference"
            )

    def _validate_thread_record(
        self,
        *,
        thread: InterpretationThread,
    ) -> None:
        values = {
            "thread_id": thread.thread_id,
            "question": thread.question,
            "perspective_owner": thread.perspective_owner,
            "perspective_instance_id": thread.perspective_instance_id,
            "about_subject": thread.about_subject,
            "scope": thread.scope,
        }

        for field_name, value in values.items():
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")

        if (
            thread.perspective_instance_id
            == SYNTHETIC_UNATTRIBUTED_INSTANCE_ID
        ):
            raise ValueError(
                "a real interpretation thread needs a concrete "
                "perspective instance"
            )

    def _validate_thread_admission_record(
        self,
        *,
        admission: ThreadAdmissionRecord,
    ) -> None:
        values = {
            "admission_id": admission.admission_id,
            "thread_id": admission.thread_id,
            "interpretation_id": admission.interpretation_id,
            "perspective_instance_id": (
                admission.perspective_instance_id
            ),
            "admitted_by_instance_id": (
                admission.admitted_by_instance_id
            ),
        }

        for field_name, value in values.items():
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")

    def _get_suppressions_from_connection(
        self,
        *,
        connection: sqlite3.Connection,
    ) -> tuple[SuppressionRecord, ...]:
        assert_source_suppression_ledger(connection)
        rows = connection.execute(
            f"""
            SELECT
                suppressions.suppression_id,
                suppressions.source_id,
                suppressions.requested_by,
                suppressions.reason,
                timing.timing_status,
                timing.effective_at_iso,
                timing.recorded_at_iso
            FROM source_suppressions AS suppressions
            JOIN {SOURCE_SUPPRESSION_TIMING_TABLE} AS timing
              ON timing.suppression_id=suppressions.suppression_id
            ORDER BY suppressions.suppression_id
            """
        ).fetchall()

        result: list[SuppressionRecord] = []
        for row in rows:
            if row["timing_status"] == "timing_unknown":
                effective_at = None
                recorded_at = None
            elif row["timing_status"] == "timed":
                effective_at = suppression_datetime_from_iso(
                    row["effective_at_iso"]
                )
                recorded_at = suppression_datetime_from_iso(
                    row["recorded_at_iso"]
                )
            else:
                raise SuppressionLedgerIntegrityError(
                    "suppression timing status is invalid"
                )
            result.append(
                SuppressionRecord(
                    suppression_id=row["suppression_id"],
                    source_id=row["source_id"],
                    requested_by=row["requested_by"],
                    reason=row["reason"],
                    effective_at=effective_at,
                    recorded_at=recorded_at,
                )
            )
        return tuple(result)

    def _get_suppressed_source_ids_from_connection(
        self,
        *,
        connection: sqlite3.Connection,
    ) -> frozenset[str]:
        assert_source_suppression_ledger(connection)
        rows = connection.execute(
            """
            SELECT source_id
            FROM source_suppressions
            """
        ).fetchall()

        return frozenset(
            row["source_id"]
            for row in rows
        )

    def _get_supersession_from_connection(
        self,
        *,
        connection: sqlite3.Connection,
        previous_interpretation_id: str,
        new_interpretation_id: str,
    ) -> SupersessionRecord:
        row = connection.execute(
            """
            SELECT
                previous_interpretation_id,
                new_interpretation_id
            FROM supersessions
            WHERE
                previous_interpretation_id = ?
                AND new_interpretation_id = ?
            """,
            (
                previous_interpretation_id,
                new_interpretation_id,
            ),
        ).fetchone()

        if row is None:
            raise KeyError(
                (
                    previous_interpretation_id,
                    new_interpretation_id,
                )
            )

        evidence_rows = connection.execute(
            """
            SELECT
                source_id,
                source_sha256,
                start_char,
                end_char
            FROM supersession_evidence
            WHERE
                previous_interpretation_id = ?
                AND new_interpretation_id = ?
            ORDER BY position
            """,
            (
                previous_interpretation_id,
                new_interpretation_id,
            ),
        ).fetchall()

        return SupersessionRecord(
            previous_interpretation_id=row[
                "previous_interpretation_id"
            ],
            new_interpretation_id=row[
                "new_interpretation_id"
            ],
            reason_evidence=tuple(
                EvidenceRef(
                    source_id=evidence_row["source_id"],
                    source_sha256=evidence_row[
                        "source_sha256"
                    ],
                    start_char=evidence_row["start_char"],
                    end_char=evidence_row["end_char"],
                )
                for evidence_row in evidence_rows
            ),
        )

    def _get_supersessions_from_connection(
        self,
        *,
        connection: sqlite3.Connection,
    ) -> tuple[SupersessionRecord, ...]:
        rows = connection.execute(
            """
            SELECT
                previous_interpretation_id,
                new_interpretation_id
            FROM supersessions
            ORDER BY rowid
            """
        ).fetchall()

        return tuple(
            self._get_supersession_from_connection(
                connection=connection,
                previous_interpretation_id=row[
                    "previous_interpretation_id"
                ],
                new_interpretation_id=row[
                    "new_interpretation_id"
                ],
            )
            for row in rows
        )
