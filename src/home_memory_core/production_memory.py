"""Synthetic-only protected production vertical slice; real data remains CLOSED.

Trusted host composition owns this session. No mini-host/config entry point is
made payload-capable. There are no providers, listeners, discovery or delivery.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sqlite3
from uuid import uuid4

from home_memory_core import production_schema as schema
from home_memory_core.identity_namespaces import OriginNamespaceId
from home_memory_core.operation_identity import OperationClass
from home_memory_core.production_authority import (
    ProductionAuthorityError, ProductionAuthorityRoot, ProductionLifecycle,
    ProductionScope, _ROOT_CONSTRUCTION,
)


@dataclass(frozen=True, eq=False)
class _ManualEventAdapter:
    adapter_id: str
    adapter_version: str
    origin_namespace_id: OriginNamespaceId
    session_id: str


@dataclass(frozen=True, eq=False)
class ManualEventProvenance:
    session_id: str
    store_incarnation: str
    generation: int
    origin_namespace_id: OriginNamespaceId
    ingress_adapter_id: str
    adapter_version: str
    origin_id: str
    external_object_key: str
    snapshot_id: str
    snapshot_version: int
    capture_event_id: str


@dataclass(frozen=True)
class ProductionWriteReceipt:
    source_id: str
    origin_id: str
    snapshot_id: str
    snapshot_version: int
    capture_event_id: str
    exact_replay: bool


@dataclass(frozen=True)
class ProductionSourceRead:
    source_id: str
    content: str
    content_sha256: str
    origin_id: str
    snapshot_id: str
    snapshot_version: int
    scope: ProductionScope


@dataclass(frozen=True)
class ProductionStopUseReceipt:
    source_id: str
    origin_id: str
    stopped: bool = True


class ProductionMemorySession(ProductionAuthorityRoot):
    """One fixed owner/domain/perspective; synthetic fixture content only."""

    def __init__(self, *, scope, marker):
        super().__init__(scope=scope, marker=marker)
        self._barrier_complete = False
        self._manual_adapter = None

    def _operation_classes(self):
        return frozenset({OperationClass.SOURCE_WRITE, OperationClass.SOURCE_SUPPRESS,
                          OperationClass.NORMAL_READ})

    def _bootstrap_store(self):
        if self._state is not ProductionLifecycle.BOOTSTRAPPING or self._permit.consumed:
            raise ProductionAuthorityError("production schema bootstrap is revoked")
        with self._coordinator.lock, self._lease.live_guard():
            connection = sqlite3.connect(self._path)
            try:
                connection.execute("PRAGMA foreign_keys = ON")
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    self._incarnation = schema.bootstrap(connection, self._scope)
                self._coordinator.generation += 1
                self._generation = self._coordinator.generation
                self._barrier_complete = True
            finally:
                connection.close()

    def _check_store(self):
        if not self._barrier_complete or self._generation != self._coordinator.generation:
            raise ProductionAuthorityError("production barrier/generation is not current")
        with self._transaction(write=False):
            pass

    @contextmanager
    def _transaction(self, *, write):
        # Private implementation, called only inside bootstrap/admission/drain.
        mode = "rw" if write else "ro"
        connection = sqlite3.connect(self._path.as_uri() + f"?mode={mode}", uri=True)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            if not write:
                connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            schema.assert_ready(connection, self._scope, self._incarnation)
            yield connection
            if write:
                schema.assert_ready(connection, self._scope, self._incarnation)
            connection.commit()
        except sqlite3.DatabaseError as exc:
            connection.rollback()
            raise ProductionAuthorityError("production storage integrity check failed") from exc
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _register_manual_adapter(self):
        with self._admission():
            if self._manual_adapter is not None or self._adapters:
                raise ProductionAuthorityError("only one manual-event adapter is allowed")
            adapter = _ManualEventAdapter(schema.ADAPTER_ID, schema.ADAPTER_VERSION,
                                          self._scope.origin_namespace_id, self._session_id)
            self._adapters[id(adapter)] = adapter
            self._manual_adapter = adapter

    def register_adapter(self, **kwargs):
        raise ProductionAuthorityError("only the startup-registered manual_event_v0.1 adapter exists")

    def issue_provenance(self, **kwargs):
        raise ProductionAuthorityError("use the trusted local manual-event capture path")

    def capture_manual_event(self, *, source_id=None, new_snapshot=False):
        """Host-only issuer: callers cannot supply origin/snapshot/capture identity.

        Fresh events get independent UUID identities, even for identical content.
        Recapture uses persisted identity; next snapshots have contiguous integer
        versions and immutable UUIDs. Nothing here reads source payload. Multiple
        pending next-version tokens may compete; only one version can commit.
        """
        with self._admission():
            self._require_issued(self._manual_adapter, _ManualEventAdapter, self._adapters)
            if type(new_snapshot) is not bool or (new_snapshot and source_id is None):
                raise ProductionAuthorityError("a new snapshot requires a persisted manual event")
            with self._transaction(write=False) as connection:
                if source_id is None:
                    origin_id = f"origin-{uuid4().hex}"
                    object_key = f"manual-event-{uuid4().hex}"
                    snapshot_id, version = f"snapshot-{uuid4().hex}", 1
                else:
                    _require_source_id(source_id)
                    _, origin_id, snapshot_id, version, object_key, _ = schema.source_metadata(connection, source_id)
                    schema.require_usable(connection, origin_id)
                    if new_snapshot:
                        version = connection.execute(
                            "SELECT MAX(snapshot_version) + 1 FROM production_sources WHERE origin_id = ?",
                            (origin_id,),
                        ).fetchone()[0]
                        snapshot_id = f"snapshot-{uuid4().hex}"
                provenance = ManualEventProvenance(
                    self._session_id, self._incarnation, self._generation,
                    self._scope.origin_namespace_id, schema.ADAPTER_ID, schema.ADAPTER_VERSION,
                    origin_id, object_key, snapshot_id, version, f"capture-{uuid4().hex}",
                )
                self._provenance[id(provenance)] = provenance
                return provenance

    def _require_operation_provenance(self, context, provenance):
        if context.operation_class is OperationClass.SOURCE_WRITE:
            self._require_issued(provenance, ManualEventProvenance, self._provenance)
            self._require_issued(self._manual_adapter, _ManualEventAdapter, self._adapters)
            if (provenance.session_id != self._session_id
                    or provenance.store_incarnation != self._incarnation
                    or provenance.generation != self._generation
                    or provenance.origin_namespace_id != self._scope.origin_namespace_id
                    or provenance.ingress_adapter_id != schema.ADAPTER_ID
                    or provenance.adapter_version != schema.ADAPTER_VERSION):
                raise ProductionAuthorityError("manual-event provenance is not current")
        elif provenance is not None:
            raise ProductionAuthorityError("read/stop-use validate persisted origin authority")

    def write_source(self, *, context, provenance, content):
        with self._operation_admission(
            context=context, provenance=provenance, scope=self._scope,
            expected_operation_class=OperationClass.SOURCE_WRITE,
        ):
            if type(content) is not str or not content:
                raise ProductionAuthorityError("synthetic fixture content must be nonempty text")
            digest = sha256(content.encode("utf-8")).hexdigest()
            with self._transaction(write=True) as connection:
                expected_origin = (provenance.origin_id, provenance.external_object_key,
                                   self._scope.origin_namespace_id.value, schema.ADAPTER_ID, schema.ADAPTER_VERSION)
                origin = connection.execute(
                    "SELECT * FROM production_origins WHERE external_object_key = ?",
                    (provenance.external_object_key,),
                ).fetchone()
                if origin is None:
                    if provenance.snapshot_version != 1:
                        raise ProductionAuthorityError("new origins must begin at snapshot version 1")
                    connection.execute("INSERT INTO production_origins VALUES (?, ?, ?, ?, ?)", expected_origin)
                    connection.execute("INSERT INTO production_stop_use VALUES (?, 0, NULL)", (provenance.origin_id,))
                elif origin != expected_origin:
                    raise ProductionAuthorityError("manual-event canonical origin mismatch")
                # Stop-use dominates both exact replay and any later snapshot.
                schema.require_usable(connection, provenance.origin_id)
                existing = connection.execute("""SELECT source_id, snapshot_id, content_sha256
                    FROM production_sources WHERE origin_id = ? AND snapshot_version = ?""",
                    (provenance.origin_id, provenance.snapshot_version)).fetchone()
                if existing is not None:
                    source_id, snapshot_id, old_digest = existing
                    if snapshot_id != provenance.snapshot_id or old_digest != digest:
                        raise ProductionAuthorityError("immutable snapshot replay conflict")
                    if connection.execute("SELECT content FROM production_sources WHERE source_id = ?",
                                          (source_id,)).fetchone() != (content,):
                        raise ProductionAuthorityError("immutable snapshot payload integrity mismatch")
                else:
                    next_version = connection.execute(
                        "SELECT COALESCE(MAX(snapshot_version), 0) + 1 FROM production_sources WHERE origin_id = ?",
                        (provenance.origin_id,),
                    ).fetchone()[0]
                    if provenance.snapshot_version != next_version:
                        raise ProductionAuthorityError("manual-event snapshot version is not next")
                    source_id = f"source-{uuid4().hex}"
                    connection.execute("INSERT INTO production_sources VALUES (?, ?, ?, ?, ?, ?, ?)",
                                       (source_id, provenance.origin_id, provenance.snapshot_id,
                                        provenance.snapshot_version, self._scope._metadata(), content, digest))
                capture = connection.execute(
                    "SELECT source_id, session_id FROM production_captures WHERE capture_event_id = ?",
                    (provenance.capture_event_id,),
                ).fetchone()
                if capture is None:
                    connection.execute("INSERT INTO production_captures VALUES (?, ?, ?)",
                                       (provenance.capture_event_id, source_id, self._session_id))
                elif capture != (source_id, self._session_id):
                    raise ProductionAuthorityError("manual-event capture identity conflict")
                return ProductionWriteReceipt(source_id, provenance.origin_id, provenance.snapshot_id,
                                              provenance.snapshot_version, provenance.capture_event_id,
                                              exact_replay=existing is not None)

    def read_source(self, *, context, source_id):
        with self._operation_admission(
            context=context, provenance=None, scope=self._scope,
            expected_operation_class=OperationClass.NORMAL_READ,
        ):
            _require_source_id(source_id)
            with self._transaction(write=False) as connection:
                _, origin_id, snapshot_id, version, _, _ = schema.source_metadata(connection, source_id)
                schema.require_usable(connection, origin_id)
                content, digest = connection.execute(
                    "SELECT content, content_sha256 FROM production_sources WHERE source_id = ?", (source_id,),
                ).fetchone()
                if sha256(content.encode("utf-8")).hexdigest() != digest:
                    raise ProductionAuthorityError("production source payload integrity mismatch")
                return ProductionSourceRead(source_id, content, digest, origin_id, snapshot_id, version, self._scope)

    def stop_use_source(self, *, context, source_id):
        """One-way stop-use of the source's entire manual-event origin."""
        with self._operation_admission(
            context=context, provenance=None, scope=self._scope,
            expected_operation_class=OperationClass.SOURCE_SUPPRESS,
        ):
            _require_source_id(source_id)
            with self._transaction(write=True) as connection:
                _, origin_id, _, _, _, stopped = schema.source_metadata(connection, source_id)
                if not stopped:
                    connection.execute("""UPDATE production_stop_use
                        SET stopped = 1, stop_operation_id = ? WHERE origin_id = ?""",
                        (context.operation_id, origin_id))
                return ProductionStopUseReceipt(source_id, origin_id)

    def reset_empty_store(self):
        self._require_process()
        raise ProductionAuthorityError("payload-profile reset is outside #08a.1b")

    def _reset_metadata(self):
        raise ProductionAuthorityError("payload-profile reset is outside #08a.1b")


def start_synthetic_production_memory(*, runtime_root: str | Path, db_path: str | Path,
                                      scope: ProductionScope, synthetic_only: bool = True):
    """Reviewed host-only startup barrier. This is not authorization for real data."""
    if synthetic_only is not True:
        raise ProductionAuthorityError("real personal data remains CLOSED")
    root = ProductionMemorySession(scope=scope, marker=_ROOT_CONSTRUCTION)
    try:
        root._acquire_lease(runtime_root, db_path)
        root._bootstrap_store()
        root._permit.consume()
        root._activate()
        root._register_manual_adapter()
    except BaseException:
        root._abort_bootstrap()
        raise
    return root


def _require_source_id(source_id):
    if type(source_id) is not str or not source_id.strip():
        raise ProductionAuthorityError("invalid production source identity")
