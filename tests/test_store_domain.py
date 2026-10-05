import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

import home_memory_core.storage as storage_module
from home_memory_core.evidence import create_evidence_ref
from home_memory_core.interpretation import create_interpretation_record
from home_memory_core.source import create_source_record
from home_memory_core.storage import MemoryStore
from home_memory_core.real_ingress import initialize_closed_real_ingress_schema
from home_memory_core.store_domain import (
    REAL_STORE_DOMAIN,
    SYNTHETIC_STORE_DOMAIN,
    RealDataDisabledError,
    RealStoreBootstrapCapability,
    StoreDomainError,
    create_empty_real_store,
    destroy_real_store,
    read_store_domain,
)
from _trusted_test_support import (
    trusted_test_closed_real_ingress_capability,
    trusted_test_real_store_bootstrap_capability,
)


class StoreDomainBoundaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_directory.name)

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_memory_store_initialization_marks_synthetic_domain(self) -> None:
        db_path = self.root / "synthetic.sqlite3"
        store = MemoryStore(db_path)
        store.initialize()

        self.assertEqual(read_store_domain(db_path), SYNTHETIC_STORE_DOMAIN)

    def test_domain_marker_rejects_normal_update_and_delete(self) -> None:
        db_path = self.root / "synthetic.sqlite3"
        store = MemoryStore(db_path)
        store.initialize()

        connection = sqlite3.connect(db_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE home_store_domain SET domain = 'real'"
                )
            connection.rollback()

            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM home_store_domain")
            connection.rollback()
        finally:
            connection.close()

        self.assertEqual(read_store_domain(db_path), SYNTHETIC_STORE_DOMAIN)

    def test_caller_cannot_mint_real_store_bootstrap_capability(self) -> None:
        with self.assertRaises(RealDataDisabledError):
            RealStoreBootstrapCapability(_marker=object())

    def test_empty_real_store_requires_bootstrap_capability(self) -> None:
        db_path = self.root / "real.sqlite3"

        with self.assertRaises(RealDataDisabledError):
            create_empty_real_store(
                db_path=db_path,
                capability=None,  # type: ignore[arg-type]
            )

        self.assertFalse(db_path.exists())

    def test_test_capability_creates_marker_only_real_store(self) -> None:
        db_path = self.root / "real.sqlite3"
        capability = trusted_test_real_store_bootstrap_capability()

        create_empty_real_store(
            db_path=db_path,
            capability=capability,
        )

        self.assertEqual(read_store_domain(db_path), REAL_STORE_DOMAIN)
        connection = sqlite3.connect(db_path)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table' AND name NOT GLOB 'sqlite_*'
                    """
                ).fetchall()
            }
        finally:
            connection.close()

        self.assertEqual(tables, {"home_store_domain"})
        self.assertNotIn("sources", tables)

    def test_memory_store_refuses_real_domain_database(self) -> None:
        db_path = self.root / "real.sqlite3"
        capability = trusted_test_real_store_bootstrap_capability()
        create_empty_real_store(
            db_path=db_path,
            capability=capability,
        )

        store = MemoryStore(db_path)
        with self.assertRaises(StoreDomainError):
            store.initialize()

        connection = sqlite3.connect(db_path)
        try:
            source_table = connection.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'sources'
                """
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNone(source_table)

    def test_memory_store_payload_path_cannot_bypass_real_domain(self) -> None:
        db_path = self.root / "real.sqlite3"
        capability = trusted_test_real_store_bootstrap_capability()
        create_empty_real_store(
            db_path=db_path,
            capability=capability,
        )

        source = create_source_record(
            source_id="must-not-cross-real-boundary",
            content="synthetic fixture only",
            authored_by="synthetic-author",
            scope="synthetic",
        )

        with self.assertRaises(StoreDomainError):
            MemoryStore(db_path).add_source(source)

    def test_source_use_checks_domain_inside_read_snapshot(self) -> None:
        db_path = self.root / "domain-read-snapshot.sqlite3"
        store = MemoryStore(db_path)
        store.initialize()
        source = create_source_record(
            source_id="domain-read-source",
            content="synthetic fixture",
            authored_by="synthetic-author",
            scope="synthetic",
        )
        store.add_source(source)

        original_assert = storage_module.assert_synthetic_store_domain
        observed_transactions = []

        def observing_assert(connection):
            observed_transactions.append(connection.in_transaction)
            original_assert(connection)

        with patch.object(
            storage_module,
            "assert_synthetic_store_domain",
            observing_assert,
        ):
            self.assertEqual(store.get_source(source.source_id), source)

        self.assertEqual(observed_transactions, [True])

    def test_derived_write_holds_domain_trust_inside_write_transaction(self) -> None:
        db_path = self.root / "domain-derived-write.sqlite3"
        store = MemoryStore(db_path)
        store.initialize()
        source = create_source_record(
            source_id="domain-derived-source",
            content="synthetic fixture",
            authored_by="synthetic-author",
            scope="synthetic",
        )
        store.add_source(source)
        evidence = create_evidence_ref(
            source=source,
            start_char=0,
            end_char=len(source.content),
        )
        interpretation = create_interpretation_record(
            interpretation_id="domain-derived-interpretation",
            text="synthetic interpretation",
            perspective_owner="synthetic-owner",
            perspective_instance_id="synthetic-instance",
            about_subject="synthetic-subject",
            scope="synthetic",
            evidence=(evidence,),
        )

        original_assert = storage_module.assert_synthetic_store_domain
        observed_transactions = []
        concurrent_damage_errors = []

        def guarded_assert(connection):
            observed_transactions.append(connection.in_transaction)
            original_assert(connection)

            damage = sqlite3.connect(db_path, timeout=0)
            try:
                damage.execute("DROP TABLE home_store_domain")
                damage.commit()
            except Exception as error:
                concurrent_damage_errors.append(error)
                damage.rollback()
            finally:
                damage.close()

        with patch.object(
            storage_module,
            "assert_synthetic_store_domain",
            guarded_assert,
        ):
            store.add_interpretation(interpretation)

        self.assertEqual(observed_transactions, [True])
        self.assertEqual(len(concurrent_damage_errors), 1)
        self.assertIsInstance(
            concurrent_damage_errors[0],
            sqlite3.OperationalError,
        )
        self.assertEqual(read_store_domain(db_path), SYNTHETIC_STORE_DOMAIN)
        self.assertEqual(
            store.get_interpretation_for_audit(
                interpretation.interpretation_id
            ),
            interpretation,
        )

    def test_real_store_creation_refuses_synthetic_store_conversion(self) -> None:
        db_path = self.root / "synthetic.sqlite3"
        MemoryStore(db_path).initialize()
        capability = trusted_test_real_store_bootstrap_capability()

        with self.assertRaises(StoreDomainError):
            create_empty_real_store(
                db_path=db_path,
                capability=capability,
            )

        self.assertEqual(read_store_domain(db_path), SYNTHETIC_STORE_DOMAIN)

    def test_real_store_creation_refuses_nonempty_unmarked_database(self) -> None:
        db_path = self.root / "legacy.sqlite3"
        connection = sqlite3.connect(db_path)
        try:
            connection.execute("CREATE TABLE legacy_payload (value TEXT)")
            connection.commit()
        finally:
            connection.close()

        capability = trusted_test_real_store_bootstrap_capability()
        with self.assertRaises(StoreDomainError):
            create_empty_real_store(
                db_path=db_path,
                capability=capability,
            )

        self.assertIsNone(read_store_domain(db_path))

    def test_legacy_unmarked_memory_store_can_only_be_adopted_synthetic(self) -> None:
        db_path = self.root / "legacy-synthetic.sqlite3"
        connection = sqlite3.connect(db_path)
        try:
            connection.execute(
                """
                CREATE TABLE sources (
                    source_id TEXT,
                    content TEXT,
                    authored_by TEXT,
                    scope TEXT,
                    content_sha256 TEXT
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

        MemoryStore(db_path).initialize()

        self.assertEqual(read_store_domain(db_path), SYNTHETIC_STORE_DOMAIN)

    def test_destroy_real_store_is_coarse_exit_not_synthetic_delete(self) -> None:
        real_path = self.root / "real.sqlite3"
        synthetic_path = self.root / "synthetic.sqlite3"
        capability = trusted_test_real_store_bootstrap_capability()
        create_empty_real_store(
            db_path=real_path,
            capability=capability,
        )
        sidecars = (
            Path(f"{real_path}-wal"),
            Path(f"{real_path}-shm"),
            Path(f"{real_path}-journal"),
        )
        for sidecar in sidecars:
            sidecar.write_bytes(b"synthetic-sidecar-fixture")

        MemoryStore(synthetic_path).initialize()

        with self.assertRaises(StoreDomainError):
            destroy_real_store(
                db_path=synthetic_path,
                capability=capability,
            )
        self.assertTrue(synthetic_path.exists())

        destroy_real_store(
            db_path=real_path,
            capability=capability,
        )
        self.assertFalse(real_path.exists())
        self.assertTrue(all(not sidecar.exists() for sidecar in sidecars))
        self.assertIsNone(read_store_domain(real_path))

    def test_marker_loss_real_schema_cannot_be_reclassified_synthetic(self) -> None:
        db_path = self.root / "marker-loss-real.sqlite3"
        bootstrap = trusted_test_real_store_bootstrap_capability()
        create_empty_real_store(db_path=db_path, capability=bootstrap)
        ingress_capability = trusted_test_closed_real_ingress_capability()
        initialize_closed_real_ingress_schema(
            db_path=db_path,
            capability=ingress_capability,
        )

        connection = sqlite3.connect(db_path)
        try:
            connection.execute("DROP TABLE home_store_domain")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(StoreDomainError):
            MemoryStore(db_path).initialize()

        self.assertIsNone(read_store_domain(db_path))
        connection = sqlite3.connect(db_path)
        try:
            self.assertIsNotNone(
                connection.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type='table' AND name='real_sources'"
                ).fetchone()
            )
        finally:
            connection.close()

    def test_sqlite_like_wildcard_names_are_not_hidden_from_synthetic_classifier(self) -> None:
        for table_name in ("sqliteXpayload", "sqliteApayload", "sqlitezpayload"):
            with self.subTest(table_name=table_name):
                db_path = self.root / f"{table_name}.sqlite3"
                connection = sqlite3.connect(db_path)
                try:
                    connection.execute(
                        f"CREATE TABLE {table_name} (payload TEXT)"
                    )
                    connection.execute(
                        f"INSERT INTO {table_name} VALUES (?)",
                        ("synthetic sentinel",),
                    )
                    connection.commit()
                finally:
                    connection.close()

                with self.assertRaises(StoreDomainError):
                    MemoryStore(db_path).initialize()

                self.assertIsNone(read_store_domain(db_path))
                check = sqlite3.connect(db_path)
                try:
                    tables = {
                        row[0]
                        for row in check.execute(
                            """
                            SELECT name FROM sqlite_master
                            WHERE type='table'
                            """
                        ).fetchall()
                    }
                finally:
                    check.close()
                self.assertEqual(tables, {table_name})

    def test_literal_sqlite_internal_prefix_remains_ignored(self) -> None:
        db_path = self.root / "sqlite-internal-prefix.sqlite3"
        connection = sqlite3.connect(db_path)
        try:
            connection.execute(
                """
                CREATE TABLE sources (
                    source_id TEXT,
                    content TEXT,
                    authored_by TEXT,
                    scope TEXT,
                    content_sha256 TEXT
                )
                """
            )
            connection.execute(
                "CREATE TABLE temp_autoincrement("
                "id INTEGER PRIMARY KEY AUTOINCREMENT)"
            )
            connection.execute("DROP TABLE temp_autoincrement")
            connection.commit()
            self.assertIsNotNone(
                connection.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type='table' AND name='sqlite_sequence'
                    """
                ).fetchone()
            )
        finally:
            connection.close()

        MemoryStore(db_path).initialize()
        self.assertEqual(
            read_store_domain(db_path),
            SYNTHETIC_STORE_DOMAIN,
        )

    def test_unmarked_unknown_table_is_not_adopted_as_synthetic(self) -> None:
        db_path = self.root / "unknown-unmarked.sqlite3"
        connection = sqlite3.connect(db_path)
        try:
            connection.execute("CREATE TABLE mystery_payload (value TEXT)")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(StoreDomainError):
            MemoryStore(db_path).initialize()
        self.assertIsNone(read_store_domain(db_path))

    def test_unmarked_malformed_known_table_is_not_adopted_as_synthetic(self) -> None:
        db_path = self.root / "malformed-legacy.sqlite3"
        connection = sqlite3.connect(db_path)
        try:
            connection.execute("CREATE TABLE sources (source_id TEXT)")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(StoreDomainError):
            MemoryStore(db_path).initialize()
        self.assertIsNone(read_store_domain(db_path))


if __name__ == "__main__":
    unittest.main()
