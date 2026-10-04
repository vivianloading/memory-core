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
    assert_synthetic_store_domain,
    ensure_synthetic_store_domain,
)
from home_memory_core.suppression import (
    SuppressedMemoryError,
    SuppressionLedgerIntegrityError,
    SuppressionRecord,
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


SOURCE_SUPPRESSION_TRIGGERS = frozenset(
    {
        "source_suppressions_no_replace",
        "source_suppressions_no_update",
        "source_suppressions_no_delete",
    }
)


def _source_suppression_table_sql() -> str:
    return """
        CREATE TABLE source_suppressions (
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


def _migrate_legacy_source_suppression_table(
    connection: sqlite3.Connection,
) -> None:
    row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type='table' AND name='source_suppressions'
        """
    ).fetchone()
    if row is None:
        return

    actual = _normalize_schema_sql(row["sql"])
    target = _normalize_schema_sql(_source_suppression_table_sql())
    if actual == target:
        return
    legacy = _normalize_schema_sql(_legacy_source_suppression_table_sql())
    if actual != legacy:
        raise SuppressionLedgerIntegrityError(
            "source suppression table is not a recognized migratable schema"
        )

    connection.execute(
        "ALTER TABLE source_suppressions RENAME TO source_suppressions_legacy_v01"
    )
    connection.execute(_source_suppression_table_sql())
    connection.execute(
        """
        INSERT INTO source_suppressions (
            suppression_id,source_id,requested_by,reason
        )
        SELECT suppression_id,source_id,requested_by,reason
        FROM source_suppressions_legacy_v01
        """
    )
    connection.execute("DROP TABLE source_suppressions_legacy_v01")


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


def assert_source_suppression_ledger(connection: sqlite3.Connection) -> None:
    """Fail closed if the synthetic stop-use ledger is mutable or malformed."""

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
            ensure_synthetic_store_domain(connection)
            _migrate_legacy_source_suppression_table(connection)
            connection.executescript(
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
            assert_source_suppression_ledger(connection)

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
        rows = connection.execute(
            """
            SELECT
                suppression_id,
                source_id,
                requested_by,
                reason
            FROM source_suppressions
            ORDER BY suppression_id
            """
        ).fetchall()

        return tuple(
            SuppressionRecord(
                suppression_id=row["suppression_id"],
                source_id=row["source_id"],
                requested_by=row["requested_by"],
                reason=row["reason"],
            )
            for row in rows
        )

    def _get_suppressed_source_ids_from_connection(
        self,
        *,
        connection: sqlite3.Connection,
    ) -> frozenset[str]:
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
