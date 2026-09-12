from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sqlite3


SYNTHETIC_STORE_DOMAIN = "synthetic"
REAL_STORE_DOMAIN = "real"
_DOMAIN_TABLE = "home_store_domain"
_DOMAIN_KEY = "store_domain"
_REAL_STORE_BOOTSTRAP_MARKER = object()


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
    """Create an empty real-domain marker without enabling real payload use."""

    _require_real_store_bootstrap_capability(capability)
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

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
                return

            _create_domain_marker(
                connection=connection,
                domain=REAL_STORE_DOMAIN,
                allow_existing_user_tables=False,
            )
    finally:
        connection.close()


def destroy_real_store(
    *,
    db_path: str | Path,
    capability: RealStoreBootstrapCapability,
) -> None:
    """Coarsely remove a local real-domain pilot store and SQLite sidecars.

    This is a whole-store reset path, not a secure-erasure guarantee. Task
    #06a.0 creates no payload tables in a real store; future real-data GO must
    re-review copy/backup and multi-process behavior before relying on it.
    """

    _require_real_store_bootstrap_capability(capability)
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(path)

    existing = read_store_domain(path)
    if existing != REAL_STORE_DOMAIN:
        raise StoreDomainError(
            "whole-store reset refuses a non-real HOME store"
        )

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
