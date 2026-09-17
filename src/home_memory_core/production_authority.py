"""Non-payload production authority contract; real personal data remains CLOSED.

This module has no ingress, payload reader/writer, sink, connector, or model API.
The trusted host owns the root; request code may receive only issued objects.
Scope/config values and even copied issued objects are never issuance proof.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
import sqlite3
from threading import Condition, RLock, get_ident
from uuid import uuid4

from home_memory_core.host_runtime import acquire_home_single_instance
from home_memory_core.identity_namespaces import (
    AccessDomainId, DestinationId, OriginNamespaceId, PerspectiveInstanceId,
    PerspectiveOwnerId, RequestId,
)
from home_memory_core.operation_identity import OperationClass, PrincipalId
from home_memory_core.process_boundary import current_home_process_instance_id
from home_memory_core.real_authority_ordering import _coordinator_for_path
from home_memory_core.store_domain import PRODUCTION_STORE_DOMAIN


class ProductionAuthorityError(PermissionError):
    """A production contract operation failed closed."""


class ProductionLifecycle(StrEnum):
    BOOTSTRAPPING = "BOOTSTRAPPING"
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class ShutdownDisposition(StrEnum):
    CLOSE = "close"
    RESET_EMPTY_METADATA = "reset_empty_metadata"


@dataclass(frozen=True)
class ProductionScope:
    """Exact constraints, not authority. There are no wildcard values."""

    owner_principal_id: PrincipalId
    access_domain_id: AccessDomainId
    perspective_owner: PerspectiveOwnerId
    perspective_instance: PerspectiveInstanceId
    origin_namespace_id: OriginNamespaceId
    destination_id: DestinationId

    def __post_init__(self):
        for name, kind in (
            ("owner_principal_id", PrincipalId),
            ("access_domain_id", AccessDomainId),
            ("perspective_owner", PerspectiveOwnerId),
            ("perspective_instance", PerspectiveInstanceId),
            ("origin_namespace_id", OriginNamespaceId),
            ("destination_id", DestinationId),
        ):
            if type(getattr(self, name)) is not kind:
                raise ProductionAuthorityError(f"invalid production constraint: {name}")

    def _metadata(self):
        return json.dumps({k: v.value for k, v in vars(self).items()}, sort_keys=True)


@dataclass(frozen=True, eq=False)
class ProductionPrincipal:
    principal_id: PrincipalId
    principal_kind: str
    trust_source: str
    session_id: str


@dataclass(frozen=True, eq=False)
class ProductionOperationContext:
    operation_id: str
    principal: ProductionPrincipal
    operation_class: OperationClass
    request_id: RequestId
    scope: ProductionScope
    session_id: str
    generation: int
    store_incarnation: str


@dataclass(frozen=True, eq=False)
class ProductionProvenance:
    """Metadata-only provenance proof; it cannot authorize payload ingress."""

    origin_namespace_id: OriginNamespaceId
    external_object_key: str
    ingress_adapter_id: str
    session_id: str


@dataclass(frozen=True, eq=False)
class ProductionAdapter:
    """A registered metadata issuer, with no external connector implementation."""

    adapter_id: str
    origin_namespace_id: OriginNamespaceId
    session_id: str


@dataclass(frozen=True)
class ContractReceipt:
    session_id: str
    operation_id: str
    store_incarnation: str


class _BootstrapPermit:
    """One-shot empty-store metadata initialization; no runtime minting methods."""

    def __init__(self):
        self.consumed = False

    def consume(self):
        if self.consumed:
            raise ProductionAuthorityError("bootstrap permit is already consumed")
        self.consumed = True


_ROOT_CONSTRUCTION = object()
# Failed cleanup must retain the OS handle even if the caller drops the root or
# bootstrap never returned it. GC must not silently release an unquiesced lease.
_FAILED_ROOTS: dict[str, ProductionAuthorityRoot] = {}


class ProductionAuthorityRoot:
    """Host-private owner of one session and its single-instance lease.

    Lock order: store coordinator -> lease guard -> lifecycle condition.
    Shutdown takes the lifecycle condition only to close admission, releases it,
    then takes the coordinator to drain. It never waits for the coordinator
    while holding the lifecycle condition. No callback is exposed by this API.
    """

    def __init__(self, *, scope, marker):
        if marker is not _ROOT_CONSTRUCTION or type(scope) is not ProductionScope:
            raise ProductionAuthorityError("root requires trusted contract bootstrap")
        self._scope = scope
        self._process = current_home_process_instance_id()
        self._session_id = f"production-{uuid4().hex}"
        self._condition = Condition(RLock())
        self._state = ProductionLifecycle.BOOTSTRAPPING
        self._lease = None
        self._coordinator = None
        self._path = None
        self._generation = None
        self._incarnation = None
        self._permit = _BootstrapPermit()
        self._principals = {}
        self._contexts = {}
        self._adapters = {}
        self._provenance = {}
        self._admitted_thread = None
        self._shutdown_disposition = None
        self._shutdown_failed = False

    def _require_process(self):
        if current_home_process_instance_id() != self._process:
            raise ProductionAuthorityError("production root belongs to another process")

    @property
    def state(self):
        self._require_process()
        with self._condition:
            return self._state

    @property
    def session_id(self):
        self._require_process()
        return self._session_id

    def _acquire_lease(self, runtime_root, db_path):
        self._lease = acquire_home_single_instance(
            runtime_root=runtime_root, db_path=db_path, real_data_allowed=False,
        )
        self._path = self._lease.identity.db_path
        self._coordinator = _coordinator_for_path(self._path)

    def _bootstrap_store(self):
        if self._state is not ProductionLifecycle.BOOTSTRAPPING or self._permit.consumed:
            raise ProductionAuthorityError("bootstrap authority is revoked")
        with self._coordinator.lock, self._lease.live_guard():
            connection = sqlite3.connect(self._path)
            try:
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    tables = _user_tables(connection)
                    if not tables:
                        # One explicit ownership row. No payload schema is installed.
                        connection.execute("""CREATE TABLE home_store_domain (
                            marker_key TEXT PRIMARY KEY CHECK(marker_key = 'store_domain'),
                            domain TEXT NOT NULL CHECK(domain = 'production-contract'),
                            incarnation TEXT NOT NULL CHECK(length(incarnation) > 0),
                            scope TEXT NOT NULL
                        )""")
                        connection.execute(
                            "INSERT INTO home_store_domain VALUES (?, ?, ?, ?)",
                            ("store_domain", PRODUCTION_STORE_DOMAIN,
                             uuid4().hex, self._scope._metadata()),
                        )
                        for action in ("UPDATE OF marker_key, domain, scope", "DELETE"):
                            name = "update" if action.startswith("UPDATE") else "delete"
                            connection.execute(f"""CREATE TRIGGER production_no_{name}
                                BEFORE {action} ON home_store_domain BEGIN
                                SELECT RAISE(ABORT, 'production ownership is immutable');
                                END""")
                    self._incarnation = _read_metadata(connection, self._scope)
                self._coordinator.generation += 1
                self._generation = self._coordinator.generation
            finally:
                connection.close()

    def _activate(self):
        with self._coordinator.lock, self._lease.live_guard(), self._condition:
            if self._state is not ProductionLifecycle.BOOTSTRAPPING:
                raise ProductionAuthorityError("CLOSED is terminal; create a fresh root")
            if not self._permit.consumed:
                raise ProductionAuthorityError("bootstrap authority must be consumed")
            self._check_store()
            self._state = ProductionLifecycle.ACTIVE

    def _check_store(self):
        if self._generation != self._coordinator.generation:
            raise ProductionAuthorityError("stale same-process store generation")
        connection = sqlite3.connect(self._path.as_uri() + "?mode=ro", uri=True)
        try:
            if not self._incarnation or _read_metadata(connection, self._scope) != self._incarnation:
                raise ProductionAuthorityError("missing or stale persistent store incarnation")
        finally:
            connection.close()

    @contextmanager
    def _admission(self):
        # Check fork before touching any possibly inherited locked primitive.
        self._require_process()
        with self._condition:
            if self._state is not ProductionLifecycle.ACTIVE:
                raise ProductionAuthorityError("production admission is closed")
            if self._admitted_thread == get_ident():
                raise ProductionAuthorityError("production admission cannot re-enter")
        with self._coordinator.lock, self._lease.live_guard():
            with self._condition:
                # This is the admission point, shared with the shutdown cutoff.
                # The early check above is only a fast denial, never authorization.
                self._require_process()
                if self._state is not ProductionLifecycle.ACTIVE:
                    raise ProductionAuthorityError("production admission is closed")
                self._check_store()
                self._admitted_thread = get_ident()
            try:
                yield
            finally:
                with self._condition:
                    self._admitted_thread = None

    @staticmethod
    def _require_issued(value, kind, registry):
        if type(value) is not kind or registry.get(id(value)) is not value:
            raise ProductionAuthorityError("authority was not issued by this current root")

    def issue_owner(self):
        with self._admission():
            principal = ProductionPrincipal(
                self._scope.owner_principal_id, "local_owner",
                "production-contract-root", self._session_id,
            )
            self._principals[id(principal)] = principal
            return principal

    def issue_operation(self, *, principal, request_id,
                        operation_class=OperationClass.AUDIT_READ):
        with self._admission():
            self._require_issued(principal, ProductionPrincipal, self._principals)
            if type(request_id) is not RequestId or operation_class is not OperationClass.AUDIT_READ:
                raise ProductionAuthorityError("only metadata contract checks are enabled")
            context = ProductionOperationContext(
                uuid4().hex, principal, operation_class, request_id, self._scope,
                self._session_id, self._generation, self._incarnation,
            )
            self._contexts[id(context)] = context
            return context

    def register_adapter(self, *, adapter_id, origin_namespace_id):
        with self._admission():
            if (type(adapter_id) is not str or not adapter_id.strip()
                    or origin_namespace_id != self._scope.origin_namespace_id):
                raise ProductionAuthorityError("invalid metadata adapter registration")
            adapter = ProductionAdapter(adapter_id, origin_namespace_id, self._session_id)
            self._adapters[id(adapter)] = adapter
            return adapter

    def issue_provenance(self, *, adapter, external_object_key):
        with self._admission():
            self._require_issued(adapter, ProductionAdapter, self._adapters)
            if type(external_object_key) is not str or not external_object_key.strip():
                raise ProductionAuthorityError("empty provenance metadata key")
            provenance = ProductionProvenance(
                adapter.origin_namespace_id, external_object_key,
                adapter.adapter_id, self._session_id,
            )
            self._provenance[id(provenance)] = provenance
            return provenance

    def check_contract(self, *, context, provenance, scope):
        """Admit a metadata-only check. No payload or sink is reachable here."""
        with self._operation_admission(context=context, provenance=provenance, scope=scope):
            return ContractReceipt(self._session_id, context.operation_id, self._incarnation)

    @contextmanager
    def _operation_admission(self, *, context, provenance, scope):
        """Mandatory combined admission rule for future production operations.

        Keep protected work inside this protocol; never preflight and use later.
        The separate root-only issuance paths use the same liveness protocol.
        """
        with self._admission():
            self._require_issued(context, ProductionOperationContext, self._contexts)
            self._require_issued(context.principal, ProductionPrincipal, self._principals)
            self._require_issued(provenance, ProductionProvenance, self._provenance)
            if (type(scope) is not ProductionScope or scope != self._scope
                    or context.scope != scope
                    or context.principal.principal_id != scope.owner_principal_id
                    or context.operation_class is not OperationClass.AUDIT_READ
                    or context.session_id != self._session_id
                    or context.generation != self._generation
                    or context.store_incarnation != self._incarnation
                    or provenance.session_id != self._session_id
                    or provenance.origin_namespace_id != scope.origin_namespace_id):
                raise ProductionAuthorityError("production operation constraints do not match")
            yield

    def close(self):
        return self._shutdown(ShutdownDisposition.CLOSE)

    def reset_empty_store(self):
        """Terminal empty-metadata reset, not payload deletion or backup/restore.

        The first close/reset cutoff wins. Concurrent callers observe the same
        disposition. Reset rotates only the incarnation of this marker-only DB.
        """
        return self._shutdown(ShutdownDisposition.RESET_EMPTY_METADATA)

    def _shutdown(self, disposition):
        self._require_process()
        with self._condition:
            if self._admitted_thread == get_ident():
                raise ProductionAuthorityError("cannot shut down from an admitted operation")
            while self._state is ProductionLifecycle.CLOSING and not self._shutdown_failed:
                self._condition.wait()
            if self._shutdown_failed:
                raise ProductionAuthorityError("cleanup failed; root closed to admission, lease retained")
            if self._state is ProductionLifecycle.CLOSED:
                return self._shutdown_disposition
            if self._state is not ProductionLifecycle.ACTIVE:
                raise ProductionAuthorityError("unpublished root cannot accept runtime shutdown")
            self._shutdown_disposition = disposition
            self._state = ProductionLifecycle.CLOSING  # Atomic admission cutoff.
            self._condition.notify_all()
        try:
            with self._coordinator.lock:  # Drain the already admitted operation.
                self._invalidate_issuance()
                if disposition is ShutdownDisposition.RESET_EMPTY_METADATA:
                    with self._lease.live_guard():
                        self._reset_metadata()
                self._close_runtime_resources()
                with self._condition:
                    self._state = ProductionLifecycle.CLOSED
                self._lease.release()  # Last: after resources and CLOSED.
        except BaseException:
            with self._condition:
                self._shutdown_failed = True
                _FAILED_ROOTS[self._session_id] = self
                self._condition.notify_all()
            raise
        with self._condition:
            self._condition.notify_all()
        return disposition

    def _invalidate_issuance(self):
        for registry in (self._principals, self._contexts, self._adapters, self._provenance):
            registry.clear()

    def _close_runtime_resources(self):
        # All SQLite handles are operation-local and closed before the drain.
        # No sink, connector, secret provider, or other runtime resource exists.
        pass

    def _reset_metadata(self):
        self._check_store()
        connection = sqlite3.connect(self._path)
        try:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                if _read_metadata(connection, self._scope) != self._incarnation:
                    raise ProductionAuthorityError("stale reset incarnation")
                connection.execute(
                    "UPDATE home_store_domain SET incarnation = ? WHERE marker_key = 'store_domain'",
                    (uuid4().hex,),
                )
            self._coordinator.generation += 1
        finally:
            connection.close()

    def _abort_bootstrap(self):
        with self._condition:
            self._state = ProductionLifecycle.CLOSING
        self._permit.consumed = True
        self._invalidate_issuance()
        # No runtime authority was published and initialization has unwound all
        # operation-local handles. If cleanup raises, retain the lease.
        try:
            self._close_runtime_resources()
            with self._condition:
                self._state = ProductionLifecycle.CLOSED
            if self._lease is not None:
                self._lease.release()
        except BaseException:
            with self._condition:
                self._shutdown_failed = True
                _FAILED_ROOTS[self._session_id] = self
                self._condition.notify_all()
            raise


def start_production_authority_contract(*, runtime_root: str | Path,
                                       db_path: str | Path, scope: ProductionScope):
    """Trusted host bootstrap for synthetic contract tests, never real-data GO.

    Returns only after the narrow bootstrap permit is revoked. This does not
    change home-mini-host-v0.1 or interpret config as runtime authority.
    """
    root = ProductionAuthorityRoot(scope=scope, marker=_ROOT_CONSTRUCTION)
    try:
        root._acquire_lease(runtime_root, db_path)
        root._bootstrap_store()
        root._permit.consume()
        root._activate()
    except BaseException:
        root._abort_bootstrap()
        raise
    return root


def _user_tables(connection):
    return {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    )}


def _read_metadata(connection, scope):
    if _user_tables(connection) != {"home_store_domain"}:
        raise ProductionAuthorityError("production contract requires a marker-only store")
    try:
        rows = connection.execute(
            "SELECT marker_key, domain, incarnation, scope FROM home_store_domain"
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise ProductionAuthorityError("missing production store incarnation/profile") from exc
    if (len(rows) != 1 or rows[0][0] != "store_domain"
            or rows[0][1] != PRODUCTION_STORE_DOMAIN
            or type(rows[0][2]) is not str or not rows[0][2].strip()
            or rows[0][3] != scope._metadata()):
        raise ProductionAuthorityError("invalid production store incarnation/profile/constraints")
    return rows[0][2]
