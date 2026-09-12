import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from home_memory_core.source import create_source_record
from home_memory_core.storage import MemoryStore
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
                    WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
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
                "CREATE TABLE old_synthetic_fixture (value TEXT)"
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


if __name__ == "__main__":
    unittest.main()
