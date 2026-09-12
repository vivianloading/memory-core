import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from home_memory_core.evidence import EvidenceRef
from home_memory_core.interpretation import (
    InterpretationRecord,
    create_interpretation_record,
)
from home_memory_core.revision import SupersessionRecord
from home_memory_core.source import SourceRecord
from home_memory_core.state import validate_supersession_graph
from home_memory_core.suppression import (
    SuppressedMemoryError,
    SuppressionRecord,
    is_interpretation_usable as interpretation_is_usable,
    is_supersession_usable as supersession_is_usable,
)


class MemoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connection() as connection:
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
                );

                CREATE TABLE IF NOT EXISTS interpretations (
                    interpretation_id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    perspective_owner TEXT NOT NULL,
                    about_subject TEXT NOT NULL,
                    scope TEXT NOT NULL
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

                CREATE TABLE IF NOT EXISTS supersessions (
                    previous_interpretation_id TEXT NOT NULL,
                    new_interpretation_id TEXT NOT NULL,

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

    def add_source(self, source: SourceRecord) -> None:
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

    def suppress_source(
        self,
        suppression: SuppressionRecord,
    ) -> None:
        with self._connection() as connection:
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

    def add_interpretation(
        self,
        interpretation: InterpretationRecord,
    ) -> None:
        if not interpretation.evidence:
            raise ValueError(
                "interpretation must have at least one evidence reference"
            )

        with self._connection() as connection:
            suppressed_ids = self._get_suppressed_source_ids_from_connection(
                connection=connection,
            )

            for evidence in interpretation.evidence:
                self._validate_evidence_against_stored_source(
                    connection=connection,
                    evidence=evidence,
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
                        about_subject,
                        scope
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        interpretation.interpretation_id,
                        interpretation.text,
                        interpretation.perspective_owner,
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

            if previous.about_subject != new.about_subject:
                raise ValueError(
                    "supersession must stay about the same subject"
                )

            for evidence in supersession.reason_evidence:
                self._validate_evidence_against_stored_source(
                    connection=connection,
                    evidence=evidence,
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
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()

        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

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
    ) -> None:
        row = connection.execute(
            """
            SELECT
                content,
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

        if row["content_sha256"] != evidence.source_sha256:
            raise ValueError(
                "evidence source hash does not match "
                "the stored source snapshot"
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
            about_subject=row["about_subject"],
            scope=row["scope"],
            evidence=evidence,
        )

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
            ORDER BY rowid
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