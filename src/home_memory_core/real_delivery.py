from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import sqlite3
from uuid import uuid4

from home_memory_core.identity_namespaces import (
    AccessDomainId,
    DestinationId,
    OriginId,
    PerspectiveInstanceId,
    PerspectiveOwnerId,
    RequestId,
    SnapshotId,
)
from home_memory_core.operation_identity import (
    OperationClass,
    OperationContext,
    PrincipalId,
    require_operation_context,
)
from home_memory_core.real_authority_ordering import (
    capture_real_store_generation,
    real_authority_operation,
)
from home_memory_core.real_ingress import _assert_real_ingress_schema
from home_memory_core.real_relationships import _assert_relationship_schema
from home_memory_core.real_source_origin import (
    ORIGIN_TABLE,
    SNAPSHOT_TABLE,
    SOURCE_BINDING_TABLE,
    assert_real_source_origin_schema,
)
from home_memory_core.real_supersession import _assert_supersession_schema
from home_memory_core.real_use_state import (
    RealSourceSuppressedError,
    RealUseStateIntegrityError,
    assert_interpretation_usable,
    assert_real_stop_use_schema,
    assert_source_ids_usable,
)
from home_memory_core.store_domain import assert_real_store_domain


_CLOSED_REAL_DELIVERY_CAPABILITY_MARKER = object()
_TRUSTED_REAL_DELIVERY_POLICY_MARKER = object()
_PREPARED_REAL_PACKET_MARKER = object()

DELIVERY_POLICY_VERSION = "single_owner_thread_delivery_v0.1"
PACKET_SCHEMA_VERSION = "exact_source_spans_v0.1"


class RealDeliveryDisabledError(RuntimeError):
    """The synthetic-fixture-only real delivery preparation boundary is unavailable."""


class RealDeliveryAuthorizationError(PermissionError):
    """A delivery preparation request was denied before protected state influenced it."""


class RealDeliveryUnavailableError(PermissionError):
    """The requested thread has no currently deliverable normal-use unit."""


class RealDeliveryIntegrityError(RuntimeError):
    """Persisted real delivery state failed a mechanical invariant."""


@dataclass(frozen=True)
class ClosedRealDeliveryExerciseCapability:
    """Private capability for synthetic-fixture-only real delivery preparation."""

    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _CLOSED_REAL_DELIVERY_CAPABILITY_MARKER:
            raise RealDeliveryDisabledError(
                "closed real delivery capability cannot be caller-minted"
            )


@dataclass(frozen=True)
class SingleOwnerRealDeliveryPolicy:
    """First-pilot delivery policy for one owner/domain/perspective/destination."""

    policy_id: str
    owner_principal_id: PrincipalId
    access_domain_id: AccessDomainId
    perspective_owner: PerspectiveOwnerId
    perspective_instance: PerspectiveInstanceId
    destination_id: DestinationId
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _TRUSTED_REAL_DELIVERY_POLICY_MARKER:
            raise RealDeliveryAuthorizationError(
                "delivery policy must come from trusted policy code"
            )
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise RealDeliveryAuthorizationError("policy_id cannot be empty")
        if not isinstance(self.owner_principal_id, PrincipalId):
            raise RealDeliveryAuthorizationError(
                "owner_principal_id must use PrincipalId"
            )
        if not isinstance(self.access_domain_id, AccessDomainId):
            raise RealDeliveryAuthorizationError(
                "access_domain_id must use AccessDomainId"
            )
        if not isinstance(self.perspective_owner, PerspectiveOwnerId):
            raise RealDeliveryAuthorizationError(
                "perspective_owner must use PerspectiveOwnerId"
            )
        if not isinstance(self.perspective_instance, PerspectiveInstanceId):
            raise RealDeliveryAuthorizationError(
                "perspective_instance must use PerspectiveInstanceId"
            )
        if not isinstance(self.destination_id, DestinationId):
            raise RealDeliveryAuthorizationError(
                "destination_id must use DestinationId"
            )

    def authorize_request(self, *, context: OperationContext) -> None:
        require_operation_context(
            context,
            expected_operation_class=OperationClass.MEMORY_DELIVER,
        )
        if context.request_id is None or context.destination_id is None:
            raise RealDeliveryAuthorizationError(
                "delivery requires trusted request and destination binding"
            )
        if context.principal.principal_id != self.owner_principal_id:
            raise RealDeliveryAuthorizationError("delivery unavailable")
        if context.destination_id != self.destination_id:
            raise RealDeliveryAuthorizationError("delivery unavailable")


@dataclass(frozen=True)
class RealExactSourceSpan:
    source_id: str
    source_sha256: str
    start_char: int
    end_char: int
    exact_text: str


@dataclass(frozen=True)
class RealDeliveryDependencyRef:
    """Opaque internal dependency identity; raw provider/account IDs stay out."""

    source_id: str
    snapshot_id: SnapshotId
    origin_id: OriginId
    source_sha256: str


@dataclass(frozen=True)
class PreparedRealThreadPacket:
    """Request/destination-bound data prepared for a future final handoff.

    This object is deliberately *not* authority.  #06b.3 must revalidate the
    current persisted dependency state at the actual disclosure point.
    """

    request_id: RequestId
    destination_id: DestinationId
    thread_id: str
    candidate_interpretation_id: str
    evidence_spans: tuple[RealExactSourceSpan, ...]
    dependency_refs: tuple[RealDeliveryDependencyRef, ...]
    packet_schema_version: str = PACKET_SCHEMA_VERSION
    semantic_status: str = "not_assessed"
    world_validity: str = "not_assessed"
    instruction_authority: str = "none"
    authority: str = "none"
    _marker: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _PREPARED_REAL_PACKET_MARKER:
            raise RealDeliveryDisabledError(
                "prepared real delivery packet must be issued by the closed gate"
            )
        if not self.evidence_spans:
            raise RealDeliveryIntegrityError(
                "prepared delivery packet requires exact source evidence"
            )
        if not self.dependency_refs:
            raise RealDeliveryIntegrityError(
                "prepared delivery packet requires internal dependency refs"
            )


@dataclass(frozen=True)
class RealDeliveryReceipt:
    receipt_id: str
    request_id: RequestId
    destination_id: DestinationId
    thread_id: str
    candidate_interpretation_id: str
    dependency_refs: tuple[RealDeliveryDependencyRef, ...]
    operation_id: str
    principal_id: PrincipalId
    access_domain_id: AccessDomainId
    policy_id: str
    delivery_stage: str = "prepared_not_handed_off"
    authority: str = "none"


@dataclass(frozen=True)
class RealPreparedDelivery:
    packet: PreparedRealThreadPacket
    receipt: RealDeliveryReceipt
    authority: str = "none"


class ClosedRealThreadDeliveryPreparer:
    """Prepare one authorized thread for later final transport handoff.

    Preparation is query-only and same-process linearized with stop-use/reset.
    It revalidates the complete admitted thread support closure, resolves one
    structural head, materializes only that candidate's exact source spans, and
    binds the result to the trusted request + destination from OperationContext.

    It does not perform transport.  The packet/receipt are not bearer tokens.
    """

    def __init__(
        self,
        *,
        db_path: str | Path,
        capability: ClosedRealDeliveryExerciseCapability,
        policy: SingleOwnerRealDeliveryPolicy,
    ) -> None:
        _require_delivery_capability(capability)
        _require_delivery_policy(policy)
        self.db_path = Path(db_path)
        self._capability = capability
        self._policy = policy
        self._authority_generation = capture_real_store_generation(self.db_path)

    def prepare(
        self,
        *,
        context: OperationContext,
        thread_id: str,
    ) -> RealPreparedDelivery:
        _require_delivery_capability(self._capability)
        _require_delivery_policy(self._policy)
        if not isinstance(thread_id, str) or not thread_id.strip():
            raise ValueError("thread_id cannot be empty")

        # Principal/request/destination policy is evaluated before DB open so a
        # denied caller cannot use this boundary as a protected-store probe.
        self._policy.authorize_request(context=context)

        with real_authority_operation(
            self.db_path,
            expected_generation=self._authority_generation,
        ):
            connection = sqlite3.connect(self.db_path)
            try:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("PRAGMA query_only = ON")
                connection.execute("BEGIN")
                assert_real_store_domain(connection)
                _assert_real_ingress_schema(connection)
                _assert_relationship_schema(connection)
                _assert_supersession_schema(connection)
                try:
                    assert_real_stop_use_schema(connection)
                    assert_real_source_origin_schema(connection)
                except (RealUseStateIntegrityError, RuntimeError) as error:
                    raise RealDeliveryIntegrityError(
                        "closed real delivery authority state is unavailable"
                    ) from error

                prepared = self._prepare_current_snapshot(
                    connection=connection,
                    context=context,
                    thread_id=thread_id,
                )
                connection.commit()
                return prepared
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
            finally:
                connection.close()

    def _prepare_current_snapshot(
        self,
        *,
        connection: sqlite3.Connection,
        context: OperationContext,
        thread_id: str,
    ) -> RealPreparedDelivery:
        thread_row = connection.execute(
            """
            SELECT
                thread_id,
                perspective_owner_id,
                perspective_instance_id,
                about_subject_id,
                access_domain_id
            FROM real_threads
            WHERE thread_id = ?
              AND access_domain_id = ?
              AND perspective_owner_id = ?
              AND perspective_instance_id = ?
            """,
            (
                thread_id,
                self._policy.access_domain_id.value,
                self._policy.perspective_owner.value,
                self._policy.perspective_instance.value,
            ),
        ).fetchone()
        if thread_row is None:
            raise RealDeliveryUnavailableError("normal delivery unavailable")

        expected_identity = (
            thread_row[1],
            thread_row[2],
            thread_row[3],
            thread_row[4],
        )
        if expected_identity[:2] != (
            self._policy.perspective_owner.value,
            self._policy.perspective_instance.value,
        ) or expected_identity[3] != self._policy.access_domain_id.value:
            raise RealDeliveryIntegrityError(
                "authorized thread identity disagrees with delivery policy"
            )

        membership_rows = connection.execute(
            """
            SELECT
                interpretation_id,
                perspective_owner_id,
                perspective_instance_id,
                about_subject_id,
                access_domain_id
            FROM real_thread_memberships
            WHERE thread_id = ?
            ORDER BY interpretation_id
            """,
            (thread_id,),
        ).fetchall()
        if not membership_rows:
            raise RealDeliveryUnavailableError("normal delivery unavailable")

        interpretation_ids: tuple[str, ...] = tuple(row[0] for row in membership_rows)
        if len(set(interpretation_ids)) != len(interpretation_ids):
            raise RealDeliveryIntegrityError("thread membership contains duplicates")
        for row in membership_rows:
            if row[1:5] != expected_identity:
                raise RealDeliveryIntegrityError(
                    "thread membership crosses identity or access domain"
                )

        supersession_rows = connection.execute(
            """
            SELECT
                supersession_id,
                previous_interpretation_id,
                new_interpretation_id,
                perspective_owner_id,
                perspective_instance_id,
                about_subject_id,
                access_domain_id
            FROM real_supersessions
            WHERE thread_id = ?
            ORDER BY supersession_id
            """,
            (thread_id,),
        ).fetchall()
        candidate_id = _resolve_single_structural_head(
            interpretation_ids=interpretation_ids,
            supersession_rows=supersession_rows,
            expected_identity=expected_identity,
        )
        if candidate_id is None:
            raise RealDeliveryUnavailableError("normal delivery unavailable")

        dependencies: dict[str, RealDeliveryDependencyRef] = {}
        candidate_spans: tuple[RealExactSourceSpan, ...] | None = None

        # No fallback: every admitted interpretation in the authorized thread is
        # part of the normal-use dependency closure, including historical ones.
        for interpretation_id in interpretation_ids:
            try:
                assert_interpretation_usable(connection, interpretation_id)
            except RealSourceSuppressedError as error:
                raise RealDeliveryUnavailableError(
                    "normal delivery unavailable"
                ) from error
            except RealUseStateIntegrityError as error:
                raise RealDeliveryIntegrityError(
                    "thread interpretation use-state is invalid"
                ) from error

            spans = self._validate_interpretation_evidence(
                connection=connection,
                interpretation_id=interpretation_id,
                required_domain=expected_identity[3],
                dependencies=dependencies,
            )
            if interpretation_id == candidate_id:
                candidate_spans = spans

        # Supersession reason evidence is also required resolution support.
        for supersession_row in supersession_rows:
            supersession_id = supersession_row[0]
            self._validate_supersession_reason_evidence(
                connection=connection,
                supersession_id=supersession_id,
                required_domain=expected_identity[3],
                dependencies=dependencies,
            )

        if not candidate_spans:
            raise RealDeliveryIntegrityError(
                "resolved delivery candidate has no exact source spans"
            )

        dependency_refs = tuple(
            dependencies[source_id] for source_id in sorted(dependencies)
        )
        if not dependency_refs:
            raise RealDeliveryIntegrityError(
                "delivery dependency closure is unexpectedly empty"
            )

        assert context.request_id is not None
        assert context.destination_id is not None
        packet = PreparedRealThreadPacket(
            request_id=context.request_id,
            destination_id=context.destination_id,
            thread_id=thread_id,
            candidate_interpretation_id=candidate_id,
            evidence_spans=candidate_spans,
            dependency_refs=dependency_refs,
            _marker=_PREPARED_REAL_PACKET_MARKER,
        )
        receipt = RealDeliveryReceipt(
            receipt_id=f"real-delivery-receipt-{uuid4().hex}",
            request_id=context.request_id,
            destination_id=context.destination_id,
            thread_id=thread_id,
            candidate_interpretation_id=candidate_id,
            dependency_refs=dependency_refs,
            operation_id=context.operation_id,
            principal_id=context.principal.principal_id,
            access_domain_id=self._policy.access_domain_id,
            policy_id=self._policy.policy_id,
        )
        return RealPreparedDelivery(packet=packet, receipt=receipt)

    def _validate_interpretation_evidence(
        self,
        *,
        connection: sqlite3.Connection,
        interpretation_id: str,
        required_domain: str,
        dependencies: dict[str, RealDeliveryDependencyRef],
    ) -> tuple[RealExactSourceSpan, ...]:
        rows = connection.execute(
            """
            SELECT
                e.position,
                e.source_id,
                e.source_sha256,
                e.start_char,
                e.end_char,
                e.access_domain_id,
                s.content,
                s.content_sha256,
                s.access_domain_id
            FROM real_interpretation_evidence AS e
            JOIN real_sources AS s
              ON s.source_id = e.source_id
            WHERE e.interpretation_id = ?
            ORDER BY e.position
            """,
            (interpretation_id,),
        ).fetchall()
        if not rows:
            raise RealDeliveryIntegrityError(
                "admitted interpretation is missing required evidence"
            )
        positions = [row[0] for row in rows]
        if positions != list(range(len(rows))):
            raise RealDeliveryIntegrityError(
                "interpretation evidence positions are incomplete"
            )

        spans: list[RealExactSourceSpan] = []
        for row in rows:
            (
                _position,
                source_id,
                expected_hash,
                start_char,
                end_char,
                evidence_domain,
                content,
                stored_hash,
                source_domain,
            ) = row
            if evidence_domain != required_domain or source_domain != required_domain:
                raise RealDeliveryIntegrityError(
                    "interpretation evidence crosses the delivery access domain"
                )
            _validate_exact_source_evidence(
                content=content,
                stored_hash=stored_hash,
                expected_hash=expected_hash,
                start_char=start_char,
                end_char=end_char,
            )
            dependency = _load_source_dependency(
                connection=connection,
                source_id=source_id,
                required_domain=required_domain,
                expected_hash=expected_hash,
            )
            _record_dependency(dependencies, dependency)
            spans.append(
                RealExactSourceSpan(
                    source_id=source_id,
                    source_sha256=expected_hash,
                    start_char=start_char,
                    end_char=end_char,
                    exact_text=content[start_char:end_char],
                )
            )
        return tuple(spans)

    def _validate_supersession_reason_evidence(
        self,
        *,
        connection: sqlite3.Connection,
        supersession_id: str,
        required_domain: str,
        dependencies: dict[str, RealDeliveryDependencyRef],
    ) -> None:
        rows = connection.execute(
            """
            SELECT
                r.position,
                r.source_id,
                r.source_sha256,
                r.start_char,
                r.end_char,
                r.access_domain_id,
                s.content,
                s.content_sha256,
                s.access_domain_id
            FROM real_supersession_reason_evidence AS r
            JOIN real_sources AS s
              ON s.source_id = r.source_id
            WHERE r.supersession_id = ?
            ORDER BY r.position
            """,
            (supersession_id,),
        ).fetchall()
        if not rows:
            raise RealDeliveryIntegrityError(
                "supersession is missing required reason evidence"
            )
        positions = [row[0] for row in rows]
        if positions != list(range(len(rows))):
            raise RealDeliveryIntegrityError(
                "supersession reason positions are incomplete"
            )
        source_ids = tuple(row[1] for row in rows)
        try:
            assert_source_ids_usable(connection, source_ids)
        except RealSourceSuppressedError as error:
            raise RealDeliveryUnavailableError("normal delivery unavailable") from error
        except RealUseStateIntegrityError as error:
            raise RealDeliveryIntegrityError(
                "supersession reason use-state is invalid"
            ) from error

        for row in rows:
            (
                _position,
                source_id,
                expected_hash,
                start_char,
                end_char,
                evidence_domain,
                content,
                stored_hash,
                source_domain,
            ) = row
            if evidence_domain != required_domain or source_domain != required_domain:
                raise RealDeliveryIntegrityError(
                    "supersession reason crosses the delivery access domain"
                )
            _validate_exact_source_evidence(
                content=content,
                stored_hash=stored_hash,
                expected_hash=expected_hash,
                start_char=start_char,
                end_char=end_char,
            )
            dependency = _load_source_dependency(
                connection=connection,
                source_id=source_id,
                required_domain=required_domain,
                expected_hash=expected_hash,
            )
            _record_dependency(dependencies, dependency)


def _resolve_single_structural_head(
    *,
    interpretation_ids: tuple[str, ...],
    supersession_rows: list[tuple] | tuple[tuple, ...],
    expected_identity: tuple[str, str, str, str],
) -> str | None:
    members = set(interpretation_ids)
    seen_edges: set[tuple[str, str]] = set()
    incoming_parent: dict[str, str] = {}
    adjacency: dict[str, set[str]] = {item: set() for item in interpretation_ids}
    previous_ids: set[str] = set()

    for row in supersession_rows:
        _supersession_id, previous_id, new_id, owner, instance, subject, domain = row
        if (owner, instance, subject, domain) != expected_identity:
            raise RealDeliveryIntegrityError(
                "supersession crosses thread identity or access domain"
            )
        if previous_id not in members or new_id not in members:
            raise RealDeliveryIntegrityError(
                "supersession endpoint escaped thread membership"
            )
        if previous_id == new_id:
            raise RealDeliveryIntegrityError("supersession graph contains self-loop")
        edge = (previous_id, new_id)
        if edge in seen_edges:
            raise RealDeliveryIntegrityError(
                "supersession graph contains duplicate edge"
            )
        existing_parent = incoming_parent.get(new_id)
        if existing_parent is not None and existing_parent != previous_id:
            raise RealDeliveryIntegrityError(
                "supersession graph contains implicit reconvergence"
            )
        incoming_parent[new_id] = previous_id
        seen_edges.add(edge)
        adjacency[previous_id].add(new_id)
        previous_ids.add(previous_id)

    visited: set[str] = set()
    active: set[str] = set()

    def visit(node: str) -> None:
        if node in active:
            raise RealDeliveryIntegrityError("supersession graph contains a cycle")
        if node in visited:
            return
        active.add(node)
        for child in adjacency.get(node, set()):
            visit(child)
        active.remove(node)
        visited.add(node)

    for node in interpretation_ids:
        visit(node)

    heads = tuple(sorted(members - previous_ids))
    if len(heads) != 1:
        return None
    return heads[0]


def _validate_exact_source_evidence(
    *,
    content: str,
    stored_hash: str,
    expected_hash: str,
    start_char: int,
    end_char: int,
) -> None:
    actual_hash = sha256(content.encode("utf-8")).hexdigest()
    if actual_hash != stored_hash or stored_hash != expected_hash:
        raise RealDeliveryIntegrityError("delivery source integrity failed")
    if (
        not isinstance(start_char, int)
        or not isinstance(end_char, int)
        or start_char < 0
        or end_char <= start_char
        or end_char > len(content)
    ):
        raise RealDeliveryIntegrityError("delivery evidence offsets are invalid")
    if not content[start_char:end_char]:
        raise RealDeliveryIntegrityError("delivery evidence span cannot be empty")


def _load_source_dependency(
    *,
    connection: sqlite3.Connection,
    source_id: str,
    required_domain: str,
    expected_hash: str,
) -> RealDeliveryDependencyRef:
    row = connection.execute(
        f"""
        SELECT
            b.snapshot_id,
            snap.origin_id,
            snap.content_sha256,
            snap.access_domain_id,
            origin.access_domain_id
        FROM {SOURCE_BINDING_TABLE} AS b
        JOIN {SNAPSHOT_TABLE} AS snap
          ON snap.snapshot_id = b.snapshot_id
         AND snap.access_domain_id = b.access_domain_id
        JOIN {ORIGIN_TABLE} AS origin
          ON origin.origin_id = snap.origin_id
         AND origin.access_domain_id = snap.access_domain_id
        WHERE b.source_id = ?
          AND b.access_domain_id = ?
        """,
        (source_id, required_domain),
    ).fetchone()
    if row is None:
        raise RealDeliveryIntegrityError(
            "delivery source is missing canonical origin/snapshot dependency"
        )
    snapshot_id, origin_id, snapshot_hash, snapshot_domain, origin_domain = row
    if snapshot_domain != required_domain or origin_domain != required_domain:
        raise RealDeliveryIntegrityError(
            "delivery origin/snapshot dependency crosses access domain"
        )
    if snapshot_hash != expected_hash:
        raise RealDeliveryIntegrityError(
            "delivery snapshot hash disagrees with exact source evidence"
        )
    return RealDeliveryDependencyRef(
        source_id=source_id,
        snapshot_id=SnapshotId(snapshot_id),
        origin_id=OriginId(origin_id),
        source_sha256=expected_hash,
    )


def _record_dependency(
    dependencies: dict[str, RealDeliveryDependencyRef],
    dependency: RealDeliveryDependencyRef,
) -> None:
    existing = dependencies.get(dependency.source_id)
    if existing is not None and existing != dependency:
        raise RealDeliveryIntegrityError(
            "source dependency resolved to inconsistent canonical identity"
        )
    dependencies[dependency.source_id] = dependency


def _require_delivery_capability(
    capability: ClosedRealDeliveryExerciseCapability,
) -> None:
    if not isinstance(capability, ClosedRealDeliveryExerciseCapability):
        raise RealDeliveryDisabledError(
            "closed real delivery requires trusted exercise capability"
        )
    if capability._marker is not _CLOSED_REAL_DELIVERY_CAPABILITY_MARKER:
        raise RealDeliveryDisabledError("real delivery capability is invalid")


def _require_delivery_policy(policy: SingleOwnerRealDeliveryPolicy) -> None:
    if not isinstance(policy, SingleOwnerRealDeliveryPolicy):
        raise RealDeliveryAuthorizationError(
            "real delivery requires a trusted delivery policy"
        )
    if policy._marker is not _TRUSTED_REAL_DELIVERY_POLICY_MARKER:
        raise RealDeliveryAuthorizationError("real delivery policy is invalid")
