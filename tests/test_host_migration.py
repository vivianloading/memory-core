from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import warnings
import zipfile

from _trusted_test_support import trusted_test_real_store_bootstrap_capability
from home_memory_core.host_migration import (
    HostMigrationError,
    create_closed_synthetic_backup,
    restore_closed_synthetic_backup,
    validate_closed_synthetic_backup,
    verify_restored_closed_synthetic_store,
)
from home_memory_core.host_startup import start_home_mini_host
from home_memory_core.interpretation import SYNTHETIC_UNATTRIBUTED_INSTANCE_ID
from home_memory_core.living_continuity import (
    ContinuityEdge,
    ContinuityStatus,
    EpisodeRecord,
    RoomAttachmentEvent,
    RoomRecord,
    RoomRouteKind,
    TransferMode,
)
from home_memory_core.living_store import LivingStore
from home_memory_core.source import create_source_record
from home_memory_core.storage import MemoryStore
from home_memory_core.store_domain import create_empty_real_store
from home_memory_core.suppression import SuppressedMemoryError, create_suppression_record


_CONFIG = """\
[home]
schema = "home-mini-host-v0.1"
runtime_root = "."
database = "data/home.db"
real_data_allowed = false

[secrets]
mode = "disabled"
"""


class HostMigrationTests(unittest.TestCase):
    def _write_config(self, root: Path) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / "home-mini.toml"
        path.write_text(_CONFIG, encoding="utf-8")
        return path

    def _create_synthetic_store(self, root: Path) -> tuple[Path, object, object]:
        config = self._write_config(root)
        db_path = root / "data" / "home.db"
        store = MemoryStore(db_path)
        store.initialize()

        active = create_source_record(
            source_id="migration-active",
            content="HOME 搬家以后，这段 synthetic fixture 仍然在。",
            authored_by="fixture",
            scope="shared",
        )
        suppressed = create_source_record(
            source_id="migration-suppressed",
            content="这段 synthetic fixture 必须保持 stop-use。",
            authored_by="fixture",
            scope="shared",
        )
        store.add_source(active)
        store.add_source(suppressed)
        stop = create_suppression_record(
            suppression_id="migration-stop-use",
            source_id=suppressed.source_id,
            requested_by="fixture",
            reason="migration rehearsal must preserve suppression state",
        )
        store.suppress_source(stop)
        return config, active, suppressed

    def _seed_living_layer(self, root: Path) -> dict[str, object]:
        db_path = root / "data" / "home.db"
        living = LivingStore(db_path)
        living.initialize()

        room = RoomRecord(room_id="room-portable")
        first = EpisodeRecord(
            episode_id="episode-before-move",
            perspective_instance_id="perspective-before-move",
            runtime_instance_id="runtime-source-host",
            model_ref="model-a",
        )
        second = EpisodeRecord(
            episode_id="episode-after-handoff",
            perspective_instance_id="perspective-after-handoff",
            runtime_instance_id="runtime-source-host-2",
            model_ref="model-b",
        )
        edge = ContinuityEdge(
            edge_id="edge-portable-handoff",
            previous_episode_id=first.episode_id,
            next_episode_id=second.episode_id,
            transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
            continuity_status=ContinuityStatus.UNKNOWN,
            support_refs=("portable-handoff-receipt",),
        )
        attachment = RoomAttachmentEvent(
            attachment_event_id="route-portable-handoff",
            episode_id=second.episode_id,
            route_kind=RoomRouteKind.ATTACHED,
            room_id=room.room_id,
            basis="ordinary_handoff",
            support_refs=(edge.edge_id,),
        )

        living.add_room(room)
        living.add_episode(first)
        living.add_episode(second)
        living.add_continuity_edge(edge)
        living.add_room_attachment(attachment)

        return {
            "room": room,
            "first": first,
            "second": second,
            "edge": edge,
            "attachment": attachment,
        }

    def test_backup_restore_round_trip_preserves_active_and_suppressed_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_config, active, suppressed = self._create_synthetic_store(root / "source")
            bundle = root / "move.homebackup.zip"

            created = create_closed_synthetic_backup(
                config_path=source_config,
                bundle_path=bundle,
            )
            self.assertTrue(bundle.is_file())
            self.assertFalse(created.manifest.real_data_allowed)
            self.assertEqual(created.manifest.secrets_mode, "disabled")

            target_config = self._write_config(root / "target")
            restored = restore_closed_synthetic_backup(
                bundle_path=bundle,
                target_config_path=target_config,
            )
            self.assertEqual(
                restored.restored_database_sha256,
                created.manifest.database_sha256,
            )

            reopened = MemoryStore(root / "target" / "data" / "home.db")
            self.assertEqual(reopened.get_source(active.source_id), active)
            self.assertFalse(reopened.is_source_usable(suppressed.source_id))
            with self.assertRaises(SuppressedMemoryError):
                reopened.get_source(suppressed.source_id)
            self.assertEqual(
                reopened.get_source_for_audit(suppressed.source_id),
                suppressed,
            )

            verified = verify_restored_closed_synthetic_store(
                bundle_path=bundle,
                target_config_path=target_config,
            )
            self.assertEqual(
                verified.restored_database_sha256,
                created.manifest.database_sha256,
            )

    def test_backup_restore_preserves_living_layer_without_rebinding_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "source-machine"
            source_config, _, _ = self._create_synthetic_store(source_root)
            seeded = self._seed_living_layer(source_root)
            bundle = root / "portable.homebackup.zip"

            create_closed_synthetic_backup(
                config_path=source_config,
                bundle_path=bundle,
            )

            target_root = root / "mac-mini-target"
            target_config = self._write_config(target_root)
            restore_closed_synthetic_backup(
                bundle_path=bundle,
                target_config_path=target_config,
            )

            moved = LivingStore(target_root / "data" / "home.db")
            self.assertEqual(
                moved.get_room(seeded["room"].room_id),
                seeded["room"],
            )
            self.assertEqual(
                moved.get_episode(seeded["first"].episode_id),
                seeded["first"],
            )
            self.assertEqual(
                moved.get_episode(seeded["second"].episode_id),
                seeded["second"],
            )
            self.assertEqual(
                moved.list_continuity_edges(),
                (seeded["edge"],),
            )

            route = moved.resolve_room_attachment(
                episode_id=seeded["second"].episode_id
            )
            self.assertEqual(route.decision, "attached")
            self.assertEqual(route.room_id, seeded["room"].room_id)
            self.assertEqual(
                moved.list_continuity_edges()[0].continuity_status,
                ContinuityStatus.UNKNOWN,
            )

    def test_second_hop_backup_restore_works_from_first_restored_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_config, active, suppressed = self._create_synthetic_store(root / "source")
            first_bundle = root / "first.homebackup.zip"
            create_closed_synthetic_backup(
                config_path=source_config,
                bundle_path=first_bundle,
            )

            first_target_config = self._write_config(root / "target-one")
            restore_closed_synthetic_backup(
                bundle_path=first_bundle,
                target_config_path=first_target_config,
            )

            second_bundle = root / "second.homebackup.zip"
            create_closed_synthetic_backup(
                config_path=first_target_config,
                bundle_path=second_bundle,
            )
            second_target_config = self._write_config(root / "target-two")
            restore_closed_synthetic_backup(
                bundle_path=second_bundle,
                target_config_path=second_target_config,
            )

            moved_again = MemoryStore(root / "target-two" / "data" / "home.db")
            self.assertEqual(moved_again.get_source(active.source_id), active)
            self.assertFalse(moved_again.is_source_usable(suppressed.source_id))

    def test_backup_refuses_partial_living_layer_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, _, _ = self._create_synthetic_store(root)
            db_path = root / "data" / "home.db"

            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    "CREATE TABLE living_rooms (room_id TEXT PRIMARY KEY)"
                )
                connection.commit()
            finally:
                connection.close()

            with self.assertRaises(HostMigrationError):
                create_closed_synthetic_backup(
                    config_path=config,
                    bundle_path=root / "partial-living.homebackup.zip",
                )

    def test_backup_refuses_unattributed_episode_pollution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, _, _ = self._create_synthetic_store(root)
            self._seed_living_layer(root)

            db_path = root / "data" / "home.db"
            connection = sqlite3.connect(db_path)
            connection.execute("PRAGMA ignore_check_constraints = ON")
            try:
                connection.execute(
                    """
                    INSERT INTO living_episodes (
                        episode_id,
                        perspective_instance_id,
                        runtime_instance_id,
                        model_ref
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        "unattributed-backup-episode",
                        SYNTHETIC_UNATTRIBUTED_INSTANCE_ID,
                        None,
                        None,
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            with self.assertRaises(HostMigrationError):
                create_closed_synthetic_backup(
                    config_path=config,
                    bundle_path=root / "unattributed.homebackup.zip",
                )

    def test_restore_refuses_repacked_unattributed_episode_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "source"
            source_config, _, _ = self._create_synthetic_store(source_root)
            self._seed_living_layer(source_root)

            valid_bundle = root / "valid-living.homebackup.zip"
            create_closed_synthetic_backup(
                config_path=source_config,
                bundle_path=valid_bundle,
            )

            tampered_db = root / "tampered.sqlite3"
            with zipfile.ZipFile(valid_bundle, "r") as source:
                manifest = json.loads(
                    source.read("manifest.json").decode("utf-8")
                )
                tampered_db.write_bytes(source.read("database.sqlite3"))

            connection = sqlite3.connect(tampered_db)
            connection.execute("PRAGMA ignore_check_constraints = ON")
            try:
                connection.execute(
                    """
                    INSERT INTO living_episodes (
                        episode_id,
                        perspective_instance_id,
                        runtime_instance_id,
                        model_ref
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        "unattributed-restore-episode",
                        SYNTHETIC_UNATTRIBUTED_INSTANCE_ID,
                        None,
                        None,
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            database_bytes = tampered_db.read_bytes()
            manifest["database_sha256"] = sha256(database_bytes).hexdigest()
            manifest["database_bytes"] = len(database_bytes)
            manifest_bytes = (
                json.dumps(
                    manifest,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")

            tampered_bundle = root / "tampered-unattributed.homebackup.zip"
            with zipfile.ZipFile(
                tampered_bundle,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as target:
                target.writestr("manifest.json", manifest_bytes)
                target.writestr("database.sqlite3", database_bytes)

            self.assertIsNotNone(
                validate_closed_synthetic_backup(tampered_bundle)
            )
            target_root = root / "target"
            target_config = self._write_config(target_root)
            with self.assertRaises(HostMigrationError):
                restore_closed_synthetic_backup(
                    bundle_path=tampered_bundle,
                    target_config_path=target_config,
                )
            self.assertFalse((target_root / "data" / "home.db").exists())

    def test_backup_refuses_same_name_tampered_living_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, _, _ = self._create_synthetic_store(root)
            self._seed_living_layer(root)

            db_path = root / "data" / "home.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    "DROP TRIGGER living_episodes_no_update"
                )
                connection.execute(
                    """
                    CREATE TRIGGER living_episodes_no_update
                    BEFORE UPDATE ON living_episodes
                    BEGIN
                        SELECT 1;
                    END
                    """
                )
                connection.commit()
            finally:
                connection.close()

            with self.assertRaises(HostMigrationError):
                create_closed_synthetic_backup(
                    config_path=config,
                    bundle_path=root / "tampered-trigger.homebackup.zip",
                )

    def test_backup_refuses_real_domain_store_even_when_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            db_path = root / "data" / "home.db"
            create_empty_real_store(
                db_path=db_path,
                capability=trusted_test_real_store_bootstrap_capability(),
            )
            with self.assertRaises(HostMigrationError):
                create_closed_synthetic_backup(
                    config_path=config,
                    bundle_path=root / "forbidden.homebackup.zip",
                )

    def test_backup_refuses_while_supported_runtime_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, _, _ = self._create_synthetic_store(root)
            with start_home_mini_host(config):
                with self.assertRaises(HostMigrationError):
                    create_closed_synthetic_backup(
                        config_path=config,
                        bundle_path=root / "busy.homebackup.zip",
                    )

    def test_restore_refuses_existing_target_database_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_config, _, _ = self._create_synthetic_store(root / "source")
            bundle = root / "move.homebackup.zip"
            create_closed_synthetic_backup(
                config_path=source_config,
                bundle_path=bundle,
            )

            target_config = self._write_config(root / "target")
            target_db = root / "target" / "data" / "home.db"
            target_db.parent.mkdir(parents=True, exist_ok=True)
            target_db.write_bytes(b"do-not-overwrite")

            with self.assertRaises(HostMigrationError):
                restore_closed_synthetic_backup(
                    bundle_path=bundle,
                    target_config_path=target_config,
                )
            self.assertEqual(target_db.read_bytes(), b"do-not-overwrite")

    def test_restore_rejects_database_tamper_and_leaves_no_target_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_config, _, _ = self._create_synthetic_store(root / "source")
            bundle = root / "valid.homebackup.zip"
            create_closed_synthetic_backup(
                config_path=source_config,
                bundle_path=bundle,
            )

            tampered = root / "tampered.homebackup.zip"
            with zipfile.ZipFile(bundle, "r") as source:
                manifest = source.read("manifest.json")
                database = bytearray(source.read("database.sqlite3"))
            database[-1] ^= 0x01
            with zipfile.ZipFile(tampered, "w", compression=zipfile.ZIP_DEFLATED) as target:
                target.writestr("manifest.json", manifest)
                target.writestr("database.sqlite3", database)

            self.assertIsNotNone(validate_closed_synthetic_backup(tampered))
            target_config = self._write_config(root / "target")
            with self.assertRaises(HostMigrationError):
                restore_closed_synthetic_backup(
                    bundle_path=tampered,
                    target_config_path=target_config,
                )
            self.assertFalse((root / "target" / "data" / "home.db").exists())

    def test_validate_rejects_extra_or_duplicate_bundle_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_config, _, _ = self._create_synthetic_store(root / "source")
            bundle = root / "valid.homebackup.zip"
            create_closed_synthetic_backup(
                config_path=source_config,
                bundle_path=bundle,
            )

            extra = root / "extra.homebackup.zip"
            with zipfile.ZipFile(bundle, "r") as source, zipfile.ZipFile(extra, "w") as target:
                for info in source.infolist():
                    target.writestr(info.filename, source.read(info.filename))
                target.writestr("unexpected.txt", b"nope")
            with self.assertRaises(HostMigrationError):
                validate_closed_synthetic_backup(extra)

            duplicate = root / "duplicate.homebackup.zip"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(bundle, "r") as source, zipfile.ZipFile(duplicate, "w") as target:
                    target.writestr("manifest.json", source.read("manifest.json"))
                    target.writestr("database.sqlite3", source.read("database.sqlite3"))
                    target.writestr("database.sqlite3", source.read("database.sqlite3"))
            with self.assertRaises(HostMigrationError):
                validate_closed_synthetic_backup(duplicate)

    def test_backup_refuses_overwriting_existing_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, _, _ = self._create_synthetic_store(root / "source")
            bundle = root / "existing.homebackup.zip"
            bundle.write_bytes(b"existing")
            with self.assertRaises(HostMigrationError):
                create_closed_synthetic_backup(
                    config_path=config,
                    bundle_path=bundle,
                )
            self.assertEqual(bundle.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
