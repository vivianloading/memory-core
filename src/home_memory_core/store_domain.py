from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sqlite3

from home_memory_core.real_authority_ordering import (
    RealStoreLifecycleError,
    RealStoreLifecycleState,
    activate_bootstrapped_real_store,
    begin_real_store_bootstrap,
    mark_real_store_closing,
    mark_real_store_destroyed,
    restore_real_store_active_after_failed_reset,
)


SYNTHETIC_STORE_DOMAIN = "synthetic"
REAL_STORE_DOMAIN = "real"
_DOMAIN_TABLE = "home_store_domain"
_DOMAIN_KEY = "store_domain"
_REAL_STORE_BOOTSTRAP_MARKER = object()

# Unmarked legacy databases may be adopted as synthetic only when every user
# table is a recognized historical HOME synthetic table with at least the
# columns required by the current compatibility reader. Unknown tables fail
# closed: absence of a known real_* name is not proof of a synthetic domain.
_LEGACY_SYNTHETIC_TABLE_COLUMNS: dict[str, frozenset[str]] = {
    "sources": frozenset({"source_id", "content", "authored_by", "scope", "content_sha256"}),
    "source_suppressions": frozenset({"suppression_id", "source_id", "requested_by", "reason"}),
    "interpretations": frozenset({
        "interpretation_id", "text", "perspective_owner", "perspective_instance_id",
        "about_subject", "scope",
    }),
    "interpretation_evidence": frozenset({
        "interpretation_id", "position", "source_id", "source_sha256",
        "start_char", "end_char",
    }),
    "interpretation_threads": frozenset({
        "thread_id", "question", "perspective_owner", "perspective_instance_id",
        "about_subject", "scope",
    }),
    "interpretation_thread_memberships": frozenset({
        "admission_id", "interpretation_id", "thread_id",
        "perspective_instance_id", "admitted_by_instance_id",
    }),
    "supersessions": frozenset({"previous_interpretation_id", "new_interpretation_id"}),
    "supersession_evidence": frozenset({
        "previous_interpretation_id", "new_interpretation_id", "position",
        "source_id", "source_sha256", "start_char", "end_char",
    }),
}


class StoreDomainError(RuntimeError):
    """A database was opened through the wrong HOME data domain."""


class RealDataDisabledError(RuntimeError):
    """Real-data runtime access is intentionally unavailable."""


@dataclass(frozen=True)
class RealStoreBootstrapCapability:
    """Maintenance-only capability for the closed real-data entrance.

    Task #06a.0 exposes no production minting path. The capability can create,
    inspect, and remove an *empty* real-domain store marker, but it does not
    make MemoryStore real-data capable and grants no payload read/write access.
    """

    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _REAL_STORE_BOOTSTRAP_MARKER:
            raise RealDataDisabledError(
                "real-store bootstrap capability cannot be caller-minted"
            )


def ensure_synthetic_store_domain(connection: sqlite3.Connection) -> None:
    """Ensure a store is mechanically marked synthetic.

    Legacy pre-#06 HOME databases may be adopted only as synthetic. A real
    marker is never downgraded or relabeled by this function.
    """

    existing = _read_domain_from_connection(connection)
    if existing is None:
        _validate_unmarked_legacy_synthetic_database(connection)
        _create_domain_marker(
            connection=connection,
            domain=SYNTHETIC_STORE_DOMAIN,
            allow_existing_user_tables=True,
        )
        return
    if existing != SYNTHETIC_STORE_DOMAIN:
        raise StoreDomainError(
            "MemoryStore synthetic path refuses a real-domain database"
        )
    _ensure_immutability_triggers(connection)


def assert_synthetic_store_domain(connection: sqlite3.Connection) -> None:
    existing = _read_domain_from_connection(connection)
    if existing != SYNTHETIC_STORE_DOMAIN:
        if existing == REAL_STORE_DOMAIN:
            raise StoreDomainError(
                "MemoryStore synthetic path refuses a real-domain database"
            )
        raise StoreDomainError(
            "database has no valid HOME store-domain marker; initialize first"
        )


def assert_real_store_domain(connection: sqlite3.Connection) -> None:
    existing = _read_domain_from_connection(connection)
    if existing != REAL_STORE_DOMAIN:
        if existing == SYNTHETIC_STORE_DOMAIN:
            raise StoreDomainError(
                "real-data path refuses a synthetic-domain database"
            )
        raise StoreDomainError(
            "database has no valid HOME real store-domain marker"
        )


def read_store_domain(db_path: str | Path) -> str | None:
    path = Path(db_path)
    if not path.exists():
        return None

    connection = sqlite3.connect(path)
    try:
        return _read_domain_from_connection(connection)
    finally:
        connection.close()


def create_empty_real_store(
    *,
    db_path: str | Path,
    capability: RealStoreBootstrapCapability,
) -> None:
    """Create/open a marker-only real domain through trusted bootstrap code.

    A newly-created store begins a new same-process lifecycle generation. This
    prevents writer objects from an earlier destroyed store at the same path
    from silently becoming valid again.
    """

    _require_real_store_bootstrap_capability(capability)
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    coordinator = begin_real_store_bootstrap(path)

    with coordinator.lock:
        path_existed = path.exists()
        if coordinator.state is RealStoreLifecycleState.CLOSING:
            raise RealStoreLifecycleError("real store is closing")
        if coordinator.state is RealStoreLifecycleState.DESTROYED and path_existed:
            raise RealStoreLifecycleError(
                "destroyed real-store lifecycle cannot adopt an externally recreated file"
            )

        connection = sqlite3.connect(path)
        try:
            with connection:
                existing = _read_domain_from_connection(connection)
                if existing is not None:
                    if existing != REAL_STORE_DOMAIN:
                        raise StoreDomainError(
                            "refusing to convert a synthetic store into a real store"
                        )
                    _ensure_immutability_triggers(connection)
                    activate_bootstrapped_real_store(path, is_new_store=False)
                    return

                _create_domain_marker(
                    connection=connection,
                    domain=REAL_STORE_DOMAIN,
                    allow_existing_user_tables=False,
                )
                activate_bootstrapped_real_store(path, is_new_store=not path_existed)
        finally:
            connection.close()

def destroy_real_store(
    *,
    db_path: str | Path,
    capability: RealStoreBootstrapCapability,
) -> None:
    """Coarsely remove a local real-domain pilot store and SQLite sidecars.

    This is a whole-store lifecycle transition, not secure physical erasure.
    Reset is serialized with all supported real authority operations. Because
    current writers own no persistent SQLite handle outside that coordinator,
    acquiring the coordinator waits for in-flight writes to close their handles;
    stale writer objects are invalidated by the lifecycle generation change.
    """

    _require_real_store_bootstrap_capability(capability)
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(path)

    coordinator = begin_real_store_bootstrap(path)
    with coordinator.lock:
        connection = sqlite3.connect(path)
        try:
            existing = _read_domain_from_connection(connection)
        finally:
            connection.close()
        if existing != REAL_STORE_DOMAIN:
            raise StoreDomainError("whole-store reset refuses a non-real HOME store")

        mark_real_store_closing(path)
        try:
            for candidate in (
                path,
                Path(f"{path}-wal"),
                Path(f"{path}-shm"),
                Path(f"{path}-journal"),
            ):
                try:
                    candidate.unlink()
                except FileNotFoundError:
                    pass
            mark_real_store_destroyed(path)
        except Exception:
            if path.exists():
                restore_real_store_active_after_failed_reset(path)
            else:
                mark_real_store_destroyed(path)
            raise

def _require_real_store_bootstrap_capability(
    capability: RealStoreBootstrapCapability,
) -> None:
    if not isinstance(capability, RealStoreBootstrapCapability):
        raise RealDataDisabledError(
            "real-store maintenance requires a trusted bootstrap capability"
        )
    if capability._marker is not _REAL_STORE_BOOTSTRAP_MARKER:
        raise RealDataDisabledError(
            "real-store maintenance capability is invalid"
        )


def _read_domain_from_connection(
    connection: sqlite3.Connection,
) -> str | None:
    table_exists = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (_DOMAIN_TABLE,),
    ).fetchone()
    if table_exists is None:
        return None

    rows = connection.execute(
        f"SELECT domain FROM {_DOMAIN_TABLE} WHERE marker_key = ?",
        (_DOMAIN_KEY,),
    ).fetchall()
    if len(rows) != 1:
        raise StoreDomainError(
            "HOME store-domain marker is missing or internally inconsistent"
        )

    domain = rows[0][0]
    if domain not in {SYNTHETIC_STORE_DOMAIN, REAL_STORE_DOMAIN}:
        raise StoreDomainError("HOME store-domain marker has an invalid value")
    return domain


def _validate_unmarked_legacy_synthetic_database(
    connection: sqlite3.Connection,
) -> None:
    user_tables = tuple(
        row[0]
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
              AND name != ?
            ORDER BY name
            """,
            (_DOMAIN_TABLE,),
        ).fetchall()
    )
    if not user_tables:
        return

    unknown = sorted(set(user_tables) - set(_LEGACY_SYNTHETIC_TABLE_COLUMNS))
    if unknown:
        raise StoreDomainError(
            "unmarked database contains unknown user tables; refusing synthetic adoption"
        )

    for table_name in user_tables:
        actual_columns = {
            row[1]
            for row in connection.execute(
                f"PRAGMA table_info({table_name})"
            ).fetchall()
        }
        required_columns = _LEGACY_SYNTHETIC_TABLE_COLUMNS[table_name]
        if not required_columns.issubset(actual_columns):
            raise StoreDomainError(
                "unmarked database does not match a recognized legacy synthetic schema"
            )


def _create_domain_marker(
    *,
    connection: sqlite3.Connection,
    domain: str,
    allow_existing_user_tables: bool,
) -> None:
    if domain not in {SYNTHETIC_STORE_DOMAIN, REAL_STORE_DOMAIN}:
        raise StoreDomainError("invalid HOME store domain")

    existing_user_tables = tuple(
        row[0]
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
              AND name != ?
            ORDER BY name
            """,
            (_DOMAIN_TABLE,),
        ).fetchall()
    )
    if existing_user_tables and not allow_existing_user_tables:
        raise StoreDomainError(
            "refusing to label a non-empty unmarked database as real"
        )

    connection.execute(
        f"""
        CREATE TABLE {_DOMAIN_TABLE} (
            marker_key TEXT PRIMARY KEY
                CHECK (marker_key = '{_DOMAIN_KEY}'),
            domain TEXT NOT NULL
                CHECK (domain IN ('{SYNTHETIC_STORE_DOMAIN}', '{REAL_STORE_DOMAIN}'))
        )
        """
    )
    connection.execute(
        f"INSERT INTO {_DOMAIN_TABLE} (marker_key, domain) VALUES (?, ?)",
        (_DOMAIN_KEY, domain),
    )
    _ensure_immutability_triggers(connection)


def _ensure_immutability_triggers(connection: sqlite3.Connection) -> None:
    connection.executescript(
        f"""
        CREATE TRIGGER IF NOT EXISTS home_store_domain_no_update
        BEFORE UPDATE ON {_DOMAIN_TABLE}
        BEGIN
            SELECT RAISE(ABORT, 'HOME store domain is immutable');
        END;

        CREATE TRIGGER IF NOT EXISTS home_store_domain_no_delete
        BEFORE DELETE ON {_DOMAIN_TABLE}
        BEGIN
            SELECT RAISE(ABORT, 'HOME store domain is immutable');
        END;
        """
    )
