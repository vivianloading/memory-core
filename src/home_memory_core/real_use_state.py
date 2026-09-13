from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from home_memory_core.real_source_origin import (
    SNAPSHOT_SUPPRESSION_TABLE,
    SNAPSHOT_TABLE,
    SOURCE_BINDING_TABLE,
    RealSourceOriginIntegrityError,
    assert_real_source_origin_schema,
)


STOP_USE_SCHEMA_MARKER_TABLE = "real_stop_use_schema_marker"
STOP_USE_SCHEMA_VERSION = "stop-use-v0.1"
SUPPRESSION_TABLE = "real_source_suppressions"
SOURCE_DOMAIN_INDEX = "real_source_domain_key"

_REQUIRED_STOP_USE_TRIGGERS = frozenset(
    {
        "real_stop_use_schema_marker_no_update",
        "real_stop_use_schema_marker_no_delete",
        "real_source_suppressions_no_update",
        "real_source_suppressions_no_delete",
        "real_source_suppressions_block_replace",
        "real_sources_block_reinsert_suppressed",
    }
)


class RealUseStateIntegrityError(RuntimeError):
    """Persisted real-use state is missing, stale, or mechanically inconsistent."""


class RealSourceSuppressedError(RealUseStateIntegrityError):
    """A supported real operation depends on a source under one-way stop-use."""


def assert_real_stop_use_schema(connection: sqlite3.Connection) -> None:
    marker_exists = _object_exists(connection, "table", STOP_USE_SCHEMA_MARKER_TABLE)
    suppression_exists = _object_exists(connection, "table", SUPPRESSION_TABLE)
    index_exists = _object_exists(connection, "index", SOURCE_DOMAIN_INDEX)

    if not (marker_exists and suppression_exists and index_exists):
        raise RealUseStateIntegrityError(
            "closed real stop-use schema is missing or incomplete"
        )

    marker_rows = connection.execute(
        f"SELECT schema_version FROM {STOP_USE_SCHEMA_MARKER_TABLE} "
        "WHERE marker_key='stop_use_schema'"
    ).fetchall()
    if marker_rows != [(STOP_USE_SCHEMA_VERSION,)]:
        raise RealUseStateIntegrityError(
            "closed real stop-use schema marker is invalid"
        )

    triggers = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    if not _REQUIRED_STOP_USE_TRIGGERS.issubset(triggers):
        raise RealUseStateIntegrityError(
            "closed real stop-use storage invariants are incomplete"
        )

    columns = {
        row[1]: row
        for row in connection.execute(
            f"PRAGMA table_info({SUPPRESSION_TABLE})"
        ).fetchall()
    }
    required_not_null = {
        "suppression_id",
        "source_id",
        "access_domain_id",
        "requested_by_principal_id",
        "requested_by_principal_kind",
        "requested_by_trust_source",
        "operation_id",
        "reason_code",
        "recorded_at_utc",
        "policy_id",
    }
    if not required_not_null.issubset(columns):
        raise RealUseStateIntegrityError(
            "closed real stop-use schema columns are incomplete"
        )
    if any(columns[name][3] != 1 for name in required_not_null):
        raise RealUseStateIntegrityError(
            "closed real stop-use identity/provenance columns must be NOT NULL"
        )

    unique_column_sets = {
        tuple(
            row[2]
            for row in connection.execute(
                f"PRAGMA index_info({index_row[1]})"
            ).fetchall()
        )
        for index_row in connection.execute(
            f"PRAGMA index_list({SUPPRESSION_TABLE})"
        ).fetchall()
        if index_row[2] == 1
    }
    if ("source_id",) not in unique_column_sets:
        raise RealUseStateIntegrityError(
            "closed real stop-use source identity must be unique"
        )
    if ("operation_id",) not in unique_column_sets:
        raise RealUseStateIntegrityError(
            "closed real stop-use operation identity must be unique"
        )

    source_domain_index = connection.execute(
        f"PRAGMA index_list(real_sources)"
    ).fetchall()
    source_domain_unique = False
    for index_row in source_domain_index:
        if index_row[1] != SOURCE_DOMAIN_INDEX or index_row[2] != 1:
            continue
        index_columns = tuple(
            row[2]
            for row in connection.execute(
                f"PRAGMA index_info({SOURCE_DOMAIN_INDEX})"
            ).fetchall()
        )
        source_domain_unique = index_columns == (
            "source_id",
            "access_domain_id",
        )
    if not source_domain_unique:
        raise RealUseStateIntegrityError(
            "closed real stop-use source/domain key is missing"
        )

    foreign_keys = connection.execute(
        f"PRAGMA foreign_key_list({SUPPRESSION_TABLE})"
    ).fetchall()
    source_domain_fk = {
        (row[3], row[4])
        for row in foreign_keys
        if row[2] == "real_sources"
    }
    if source_domain_fk != {
        ("source_id", "source_id"),
        ("access_domain_id", "access_domain_id"),
    }:
        raise RealUseStateIntegrityError(
            "closed real stop-use source/domain foreign key is invalid"
        )


def assert_source_ids_usable(
    connection: sqlite3.Connection,
    source_ids: Iterable[str],
) -> None:
    assert_real_stop_use_schema(connection)
    try:
        assert_real_source_origin_schema(connection)
    except RealSourceOriginIntegrityError as error:
        raise RealUseStateIntegrityError(
            "current-use source-origin authority is unavailable"
        ) from error

    unique_ids = tuple(dict.fromkeys(source_ids))
    if not unique_ids:
        raise RealUseStateIntegrityError(
            "current-use validation requires at least one source dependency"
        )

    for source_id in unique_ids:
        if not isinstance(source_id, str) or not source_id.strip():
            raise RealUseStateIntegrityError("source dependency id is invalid")
        row = connection.execute(
            f"""
            SELECT s.access_domain_id, b.snapshot_id, snap.origin_id
            FROM real_sources AS s
            JOIN {SOURCE_BINDING_TABLE} AS b
              ON b.source_id=s.source_id
             AND b.access_domain_id=s.access_domain_id
            JOIN {SNAPSHOT_TABLE} AS snap
              ON snap.snapshot_id=b.snapshot_id
             AND snap.access_domain_id=b.access_domain_id
            WHERE s.source_id=?
            """,
            (source_id,),
        ).fetchone()
        if row is None:
            exists = connection.execute(
                "SELECT 1 FROM real_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if exists is None:
                raise RealUseStateIntegrityError("source dependency is missing")
            raise RealUseStateIntegrityError(
                "source dependency is missing canonical origin/snapshot binding"
            )

        source_suppressed = connection.execute(
            f"SELECT suppression_id FROM {SUPPRESSION_TABLE} WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        snapshot_suppressed = connection.execute(
            f"SELECT source_suppression_id FROM {SNAPSHOT_SUPPRESSION_TABLE} WHERE snapshot_id = ?",
            (row[1],),
        ).fetchone()
        if (source_suppressed is None) != (snapshot_suppressed is None):
            raise RealUseStateIntegrityError(
                "source and canonical snapshot stop-use authority disagree"
            )
        if source_suppressed is not None:
            if snapshot_suppressed[0] != source_suppressed[0]:
                raise RealUseStateIntegrityError(
                    "source suppression is bound to the wrong canonical snapshot"
                )
            raise RealSourceSuppressedError(
                "required source is unavailable under one-way stop-use"
            )


def assert_interpretation_usable(
    connection: sqlite3.Connection,
    interpretation_id: str,
) -> None:
    if not isinstance(interpretation_id, str) or not interpretation_id.strip():
        raise RealUseStateIntegrityError("interpretation_id is invalid")
    assert_real_stop_use_schema(connection)
    exists = connection.execute(
        "SELECT 1 FROM real_interpretations WHERE interpretation_id = ?",
        (interpretation_id,),
    ).fetchone()
    if exists is None:
        raise RealUseStateIntegrityError("interpretation is missing")
    source_ids = tuple(
        row[0]
        for row in connection.execute(
            """
            SELECT source_id
            FROM real_interpretation_evidence
            WHERE interpretation_id = ?
            ORDER BY position
            """,
            (interpretation_id,),
        ).fetchall()
    )
    if not source_ids:
        raise RealUseStateIntegrityError(
            "interpretation has no persisted source support"
        )
    assert_source_ids_usable(connection, source_ids)


def _object_exists(
    connection: sqlite3.Connection,
    object_type: str,
    name: str,
) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?",
        (object_type, name),
    ).fetchone() is not None
