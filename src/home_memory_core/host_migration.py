from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import BinaryIO
import zipfile

from home_memory_core.host_config import CONFIG_SCHEMA, HomeMiniHostConfig, load_home_mini_host_config
from home_memory_core.host_runtime import HostRuntimeLeaseError
from home_memory_core.host_startup import start_home_mini_host
from home_memory_core.store_domain import SYNTHETIC_STORE_DOMAIN, StoreDomainError, assert_synthetic_store_domain


BACKUP_SCHEMA = "home-mini-closed-backup-v0.1"
_DATABASE_ENTRY = "database.sqlite3"
_MANIFEST_ENTRY = "manifest.json"
_EXPECTED_ENTRIES = frozenset({_DATABASE_ENTRY, _MANIFEST_ENTRY})
_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_DATABASE_BYTES = 64 * 1024 * 1024 * 1024
_COPY_CHUNK_BYTES = 1024 * 1024


class HostMigrationError(RuntimeError):
    """A closed HOME mini-host backup or restore could not be proven safe."""


@dataclass(frozen=True)
class ClosedBackupManifest:
    schema: str
    store_domain: str
    config_schema: str
    real_data_allowed: bool
    secrets_mode: str
    database_entry: str
    database_sha256: str
    database_bytes: int


@dataclass(frozen=True)
class ClosedBackupResult:
    config: HomeMiniHostConfig
    bundle_path: Path
    manifest: ClosedBackupManifest


@dataclass(frozen=True)
class ClosedRestoreResult:
    config: HomeMiniHostConfig
    bundle_path: Path
    manifest: ClosedBackupManifest
    restored_database_sha256: str


def create_closed_synthetic_backup(
    *,
    config_path: str | Path,
    bundle_path: str | Path,
) -> ClosedBackupResult:
    """Create one portable SQLite backup while the closed host owns its runtime.

    This milestone deliberately accepts synthetic-domain databases only. It is
    a deployment/migration rehearsal primitive, not permission to archive real
    personal data. The supported host lease must be free so the snapshot is not
    racing another supported HOME host process.
    """

    config = load_home_mini_host_config(config_path)
    bundle = _canonical_output_path(bundle_path)
    if bundle.exists():
        raise HostMigrationError("backup bundle already exists; refusing overwrite")
    bundle.parent.mkdir(parents=True, exist_ok=True)

    try:
        with start_home_mini_host(config.config_path):
            if not config.db_path.exists() or not config.db_path.is_file():
                raise HostMigrationError("configured HOME database does not exist")
            _reject_sqlite_sidecar_symlinks(config.db_path)
            _validate_closed_synthetic_database(config.db_path)

            with tempfile.TemporaryDirectory(
                prefix=".home-backup-stage-",
                dir=bundle.parent,
            ) as tmp:
                stage_db = Path(tmp) / _DATABASE_ENTRY
                _sqlite_backup(config.db_path, stage_db)
                assert stage_db is not None
                _validate_closed_synthetic_database(stage_db)
                database_sha256, database_bytes = _hash_file(stage_db)
                manifest = ClosedBackupManifest(
                    schema=BACKUP_SCHEMA,
                    store_domain=SYNTHETIC_STORE_DOMAIN,
                    config_schema=CONFIG_SCHEMA,
                    real_data_allowed=False,
                    secrets_mode="disabled",
                    database_entry=_DATABASE_ENTRY,
                    database_sha256=database_sha256,
                    database_bytes=database_bytes,
                )
                _write_bundle_atomic(
                    bundle_path=bundle,
                    stage_db=stage_db,
                    manifest=manifest,
                )
    except HostRuntimeLeaseError as exc:
        raise HostMigrationError(
            "HOME runtime is active; stop the supported host before backup"
        ) from exc

    validated = validate_closed_synthetic_backup(bundle)
    return ClosedBackupResult(
        config=config,
        bundle_path=bundle,
        manifest=validated,
    )


def validate_closed_synthetic_backup(bundle_path: str | Path) -> ClosedBackupManifest:
    """Validate bundle structure and manifest without restoring its database."""

    bundle = _canonical_existing_file(bundle_path, what="backup bundle")
    try:
        with zipfile.ZipFile(bundle, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise HostMigrationError("backup bundle contains duplicate entries")
            if frozenset(names) != _EXPECTED_ENTRIES:
                raise HostMigrationError("backup bundle contains unsupported entries")
            for info in infos:
                if info.is_dir() or (info.flag_bits & 0x1):
                    raise HostMigrationError("backup bundle contains unsupported entry type")

            manifest_info = archive.getinfo(_MANIFEST_ENTRY)
            if manifest_info.file_size > _MAX_MANIFEST_BYTES:
                raise HostMigrationError("backup manifest is unexpectedly large")
            with archive.open(manifest_info, "r") as handle:
                manifest_bytes = _read_limited(handle, _MAX_MANIFEST_BYTES)
            manifest = _parse_manifest(manifest_bytes)

            db_info = archive.getinfo(_DATABASE_ENTRY)
            if db_info.file_size != manifest.database_bytes:
                raise HostMigrationError("backup database size disagrees with manifest")
            if db_info.file_size > _MAX_DATABASE_BYTES:
                raise HostMigrationError("backup database exceeds the supported closed limit")
            return manifest
    except HostMigrationError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError) as exc:
        raise HostMigrationError("cannot validate HOME backup bundle") from exc


def restore_closed_synthetic_backup(
    *,
    bundle_path: str | Path,
    target_config_path: str | Path,
) -> ClosedRestoreResult:
    """Restore one validated closed synthetic bundle into an empty target runtime.

    The target config must keep real data and secret providers disabled. Existing
    database files or SQLite sidecars are never overwritten. The target host
    lease stays held through extraction, validation, and atomic installation.
    """

    bundle = _canonical_existing_file(bundle_path, what="backup bundle")
    manifest = validate_closed_synthetic_backup(bundle)
    config = load_home_mini_host_config(target_config_path)

    try:
        with start_home_mini_host(config.config_path):
            _assert_empty_restore_target(config.db_path)
            config.db_path.parent.mkdir(parents=True, exist_ok=True)
            fd, stage_name = tempfile.mkstemp(
                prefix=".home-restore-",
                suffix=".sqlite3",
                dir=config.db_path.parent,
            )
            os.close(fd)
            stage_db: Path | None = Path(stage_name)
            try:
                assert stage_db is not None
                restored_hash, restored_bytes = _extract_database(
                    bundle_path=bundle,
                    destination=stage_db,
                    expected_manifest=manifest,
                )
                if restored_hash != manifest.database_sha256:
                    raise HostMigrationError("backup database hash disagrees with manifest")
                if restored_bytes != manifest.database_bytes:
                    raise HostMigrationError("backup database length disagrees with manifest")
                _validate_closed_synthetic_database(stage_db)
                _fsync_file(stage_db)
                os.replace(stage_db, config.db_path)
                stage_db = None
                try:
                    _validate_closed_synthetic_database(config.db_path)
                    final_hash, final_bytes = _hash_file(config.db_path)
                    if final_hash != manifest.database_sha256 or final_bytes != manifest.database_bytes:
                        raise HostMigrationError("restored HOME database changed during installation")
                except Exception:
                    _remove_new_restore_artifacts(config.db_path)
                    raise
            finally:
                if stage_db is not None and stage_db.exists():
                    try:
                        stage_db.unlink()
                    except OSError:
                        pass
    except HostRuntimeLeaseError as exc:
        raise HostMigrationError(
            "target HOME runtime is active; stop the supported host before restore"
        ) from exc

    return ClosedRestoreResult(
        config=config,
        bundle_path=bundle,
        manifest=manifest,
        restored_database_sha256=manifest.database_sha256,
    )


def verify_restored_closed_synthetic_store(
    *,
    bundle_path: str | Path,
    target_config_path: str | Path,
) -> ClosedRestoreResult:
    """Re-verify an already restored target without mutating its HOME database."""

    bundle = _canonical_existing_file(bundle_path, what="backup bundle")
    manifest = validate_closed_synthetic_backup(bundle)
    config = load_home_mini_host_config(target_config_path)

    try:
        with start_home_mini_host(config.config_path):
            if not config.db_path.exists() or not config.db_path.is_file():
                raise HostMigrationError("restored HOME database is missing")
            _validate_closed_synthetic_database(config.db_path)
            current_hash, current_bytes = _hash_file(config.db_path)
            if current_hash != manifest.database_sha256 or current_bytes != manifest.database_bytes:
                raise HostMigrationError("restored HOME database no longer matches its bundle")
    except HostRuntimeLeaseError as exc:
        raise HostMigrationError(
            "target HOME runtime is active; stop the supported host before restored-store verification"
        ) from exc

    return ClosedRestoreResult(
        config=config,
        bundle_path=bundle,
        manifest=manifest,
        restored_database_sha256=manifest.database_sha256,
    )


def _canonical_output_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise HostMigrationError("cannot canonicalize backup bundle path") from exc


def _canonical_existing_file(value: str | Path, *, what: str) -> Path:
    path = Path(value).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HostMigrationError(f"{what} does not exist") from exc
    if not resolved.is_file():
        raise HostMigrationError(f"{what} is not a regular file")
    return resolved


def _sqlite_backup(source_path: Path, destination_path: Path) -> None:
    source = None
    destination = None
    try:
        source = sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)
        source.execute("PRAGMA query_only = ON")
        destination = sqlite3.connect(destination_path)
        source.backup(destination)
        destination.commit()
    except sqlite3.Error as exc:
        raise HostMigrationError("SQLite could not create a coherent HOME backup") from exc
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()


def _validate_closed_synthetic_database(path: Path) -> None:
    connection = None
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.execute("PRAGMA query_only = ON")
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise HostMigrationError("HOME database failed SQLite integrity_check")
        foreign_key_issue = connection.execute("PRAGMA foreign_key_check").fetchone()
        if foreign_key_issue is not None:
            raise HostMigrationError("HOME database failed foreign_key_check")
        assert_synthetic_store_domain(connection)
    except HostMigrationError:
        raise
    except StoreDomainError as exc:
        raise HostMigrationError(
            "closed migration accepts synthetic HOME stores only; real-domain backup remains locked"
        ) from exc
    except sqlite3.Error as exc:
        raise HostMigrationError("HOME database could not be validated") from exc
    finally:
        if connection is not None:
            connection.close()


def _write_bundle_atomic(
    *,
    bundle_path: Path,
    stage_db: Path,
    manifest: ClosedBackupManifest,
) -> None:
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{bundle_path.name}.",
        suffix=".tmp",
        dir=bundle_path.parent,
    )
    os.close(fd)
    temp_bundle = Path(temp_name)
    try:
        manifest_bytes = _manifest_bytes(manifest)
        with zipfile.ZipFile(
            temp_bundle,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            archive.writestr(_MANIFEST_ENTRY, manifest_bytes)
            archive.write(stage_db, arcname=_DATABASE_ENTRY)
        _fsync_file(temp_bundle)
        if bundle_path.exists():
            raise HostMigrationError("backup bundle appeared during creation; refusing overwrite")
        os.replace(temp_bundle, bundle_path)
    except Exception:
        try:
            temp_bundle.unlink()
        except OSError:
            pass
        raise


def _manifest_bytes(manifest: ClosedBackupManifest) -> bytes:
    payload = {
        "schema": manifest.schema,
        "store_domain": manifest.store_domain,
        "config_schema": manifest.config_schema,
        "real_data_allowed": manifest.real_data_allowed,
        "secrets_mode": manifest.secrets_mode,
        "database_entry": manifest.database_entry,
        "database_sha256": manifest.database_sha256,
        "database_bytes": manifest.database_bytes,
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _parse_manifest(raw: bytes) -> ClosedBackupManifest:
    try:
        decoded = raw.decode("utf-8")
        value = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HostMigrationError("backup manifest is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise HostMigrationError("backup manifest must be a JSON object")
    expected = {
        "schema",
        "store_domain",
        "config_schema",
        "real_data_allowed",
        "secrets_mode",
        "database_entry",
        "database_sha256",
        "database_bytes",
    }
    if set(value) != expected:
        raise HostMigrationError("backup manifest contains unsupported keys")

    if value["schema"] != BACKUP_SCHEMA:
        raise HostMigrationError("unsupported HOME backup schema")
    if value["store_domain"] != SYNTHETIC_STORE_DOMAIN:
        raise HostMigrationError("closed backup manifest is not synthetic-domain")
    if value["config_schema"] != CONFIG_SCHEMA:
        raise HostMigrationError("backup config schema does not match this HOME host")
    if value["real_data_allowed"] is not False:
        raise HostMigrationError("backup manifest cannot enable real personal data")
    if value["secrets_mode"] != "disabled":
        raise HostMigrationError("backup manifest cannot enable secret providers")
    if value["database_entry"] != _DATABASE_ENTRY:
        raise HostMigrationError("backup manifest references an unsupported database entry")

    digest = value["database_sha256"]
    if not isinstance(digest, str) or len(digest) != 64:
        raise HostMigrationError("backup database hash is malformed")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise HostMigrationError("backup database hash is malformed") from exc

    database_bytes = value["database_bytes"]
    if type(database_bytes) is not int or database_bytes <= 0:
        raise HostMigrationError("backup database length is invalid")
    if database_bytes > _MAX_DATABASE_BYTES:
        raise HostMigrationError("backup database exceeds the supported closed limit")

    return ClosedBackupManifest(
        schema=BACKUP_SCHEMA,
        store_domain=SYNTHETIC_STORE_DOMAIN,
        config_schema=CONFIG_SCHEMA,
        real_data_allowed=False,
        secrets_mode="disabled",
        database_entry=_DATABASE_ENTRY,
        database_sha256=digest.lower(),
        database_bytes=database_bytes,
    )


def _extract_database(
    *,
    bundle_path: Path,
    destination: Path,
    expected_manifest: ClosedBackupManifest,
) -> tuple[str, int]:
    hasher = sha256()
    count = 0
    try:
        with zipfile.ZipFile(bundle_path, "r") as archive:
            info = archive.getinfo(_DATABASE_ENTRY)
            if info.file_size != expected_manifest.database_bytes:
                raise HostMigrationError("backup database size changed after validation")
            with archive.open(info, "r") as source, destination.open("wb") as target:
                while True:
                    chunk = source.read(_COPY_CHUNK_BYTES)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > _MAX_DATABASE_BYTES:
                        raise HostMigrationError("backup database exceeds the supported closed limit")
                    hasher.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
    except HostMigrationError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError) as exc:
        raise HostMigrationError("cannot extract HOME backup database") from exc
    return hasher.hexdigest(), count


def _assert_empty_restore_target(db_path: Path) -> None:
    candidates = (
        db_path,
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
        Path(f"{db_path}-journal"),
    )
    existing = [path for path in candidates if path.exists() or path.is_symlink()]
    if existing:
        raise HostMigrationError("restore target is not empty; refusing overwrite or sidecar reuse")



def _remove_new_restore_artifacts(db_path: Path) -> None:
    failures: list[OSError] = []
    for candidate in (
        db_path,
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
        Path(f"{db_path}-journal"),
    ):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            failures.append(exc)
    if failures:
        raise HostMigrationError(
            "restored database failed validation and cleanup could not remove all new artifacts"
        ) from failures[0]

def _reject_sqlite_sidecar_symlinks(db_path: Path) -> None:
    for candidate in (
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
        Path(f"{db_path}-journal"),
    ):
        if candidate.is_symlink():
            raise HostMigrationError("SQLite sidecar path is a symlink; refusing closed backup")


def _hash_file(path: Path) -> tuple[str, int]:
    hasher = sha256()
    count = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(_COPY_CHUNK_BYTES)
                if not chunk:
                    break
                count += len(chunk)
                if count > _MAX_DATABASE_BYTES:
                    raise HostMigrationError("HOME database exceeds the supported closed limit")
                hasher.update(chunk)
    except HostMigrationError:
        raise
    except OSError as exc:
        raise HostMigrationError("cannot hash HOME database") from exc
    if count <= 0:
        raise HostMigrationError("HOME database is empty")
    return hasher.hexdigest(), count


def _read_limited(handle: BinaryIO, limit: int) -> bytes:
    raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise HostMigrationError("backup manifest exceeds the supported size")
    return raw


def _fsync_file(path: Path) -> None:
    try:
        with path.open("rb+") as handle:
            os.fsync(handle.fileno())
    except OSError as exc:
        raise HostMigrationError("could not durably flush migration artifact") from exc
