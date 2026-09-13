from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import sqlite3
from uuid import uuid4

from home_memory_core.identity_namespaces import (
    AccessDomainId,
    PerspectiveInstanceId,
    PerspectiveOwnerId,
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
from home_memory_core.real_supersession import _assert_supersession_schema
from home_memory_core.real_use_state import (
    RealSourceSuppressedError,
    RealUseStateIntegrityError,
    assert_interpretation_usable,
    assert_real_stop_use_schema,
    assert_source_ids_usable,
)
from home_memory_core.store_domain import assert_real_store_domain


_CLOSED_REAL_DISCOVERY_CAPABILITY_MARKER = object()
_TRUSTED_REAL_DISCOVERY_POLICY_MARKER = object()

QUERY_RULE = "literal_unicode_scalar_substring_v0.1"
ELIGIBILITY_RULE = "authorized_current_thread_evidence_v0.1"
ORDERING_RULE = "thread_id_ascending_v0.1"
DEFAULT_MAX_THREAD_MATCHES = 64


class RealDiscoveryDisabledError(RuntimeError):
    """The synthetic-fixture-only real discovery boundary is unavailable."""


class RealDiscoveryAuthorizationError(PermissionError):
    """A discovery request was denied before protected state could influence it."""


class RealDiscoveryQueryError(ValueError):
    """The exact literal discovery query violates the closed v0.1 contract."""


class RealDiscoveryIntegrityError(RuntimeError):
    """Persisted real discovery state failed a mechanical invariant."""


@dataclass(frozen=True)
class ClosedRealDiscoveryExerciseCapability:
    """Private capability for synthetic-fixture-only real discovery tests."""

    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _CLOSED_REAL_DISCOVERY_CAPABILITY_MARKER:
            raise RealDiscoveryDisabledError(
                "closed real discovery capability cannot be caller-minted"
            )


@dataclass(frozen=True)
class SingleOwnerRealDiscoveryPolicy:
    """Closed first-pilot discovery policy.

    Discovery is mechanically limited to one trusted authenticated principal,
    one access domain, and one trusted derived perspective binding.  Policy is
    evaluated before HOME opens the database for candidate discovery.
    """

    policy_id: str
    owner_principal_id: PrincipalId
    access_domain_id: AccessDomainId
    perspective_owner: PerspectiveOwnerId
    perspective_instance: PerspectiveInstanceId
    _marker: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._marker is not _TRUSTED_REAL_DISCOVERY_POLICY_MARKER:
            raise RealDiscoveryAuthorizationError(
                "discovery policy must come from trusted policy code"
            )
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise RealDiscoveryAuthorizationError("policy_id cannot be empty")
        if not isinstance(self.owner_principal_id, PrincipalId):
            raise RealDiscoveryAuthorizationError(
                "owner_principal_id must use PrincipalId"
            )
        if not isinstance(self.access_domain_id, AccessDomainId):
            raise RealDiscoveryAuthorizationError(
                "access_domain_id must use AccessDomainId"
            )
        if not isinstance(self.perspective_owner, PerspectiveOwnerId):
            raise RealDiscoveryAuthorizationError(
                "perspective_owner must use PerspectiveOwnerId"
            )
        if not isinstance(self.perspective_instance, PerspectiveInstanceId):
            raise RealDiscoveryAuthorizationError(
                "perspective_instance must use PerspectiveInstanceId"
            )

    def authorize_request(self, *, context: OperationContext) -> None:
        require_operation_context(
            context,
            expected_operation_class=OperationClass.DISCOVERY_READ,
        )
        if context.principal.principal_id != self.owner_principal_id:
            raise RealDiscoveryAuthorizationError("discovery unavailable")


@dataclass(frozen=True)
class RealDiscoveryReceipt:
    discovery_id: str
    exact_query_input: str
    query_rule_version: str
    eligible_domain_rule_version: str
    result_status: str
    complete_for_rule: bool
    deterministic_ordering_rule: str
    matched_thread_ids: tuple[str, ...]
    max_thread_matches: int
    operation_id: str
    principal_id: PrincipalId
    access_domain_id: AccessDomainId
    policy_id: str
    authority: str = "none"


@dataclass(frozen=True)
class RealDiscoveryResult:
    status: str
    complete_for_rule: bool
    thread_ids: tuple[str, ...] | None
    receipt: RealDiscoveryReceipt
    authority: str = "none"


class ClosedRealAuthorizedDiscovery:
    """Exact source-linked discovery after authorization/current-use filtering.

    This is not delivery and does not search interpretation text, thread
    question text, supersession reason text, or full source payloads outside
    exact evidence spans.  It deliberately has no ranking, FTS, embeddings, or
    query expansion.

    The operation is linearized inside HOME's same-process real-authority
    coordinator.  A suppression that commits before this operation enters its
    critical section is observed; a suppression that begins afterward waits
    until this discovery operation has completed its persisted-state read.
    """

    def __init__(
        self,
        *,
        db_path: str | Path,
        capability: ClosedRealDiscoveryExerciseCapability,
        policy: SingleOwnerRealDiscoveryPolicy,
        max_thread_matches: int = DEFAULT_MAX_THREAD_MATCHES,
    ) -> None:
        _require_discovery_capability(capability)
        _require_discovery_policy(policy)
        if not isinstance(max_thread_matches, int) or max_thread_matches <= 0:
            raise RealDiscoveryQueryError(
                "max_thread_matches must be a positive integer"
            )
        self.db_path = Path(db_path)
        self._capability = capability
        self._policy = policy
        self._max_thread_matches = max_thread_matches
        self._authority_generation = capture_real_store_generation(self.db_path)

    def search(
        self,
        *,
        context: OperationContext,
        query: str,
    ) -> RealDiscoveryResult:
        _require_discovery_capability(self._capability)
        _require_discovery_policy(self._policy)
        _validate_literal_query(query)

        # Authenticate/authorize the closed pilot before opening the database,
        # so a denied principal cannot use discovery as a store-existence probe.
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
                except RealUseStateIntegrityError as error:
                    raise RealDiscoveryIntegrityError(
                        "closed real stop-use state is unavailable"
                    ) from error

                result = self._search_current_snapshot(
                    connection=connection,
                    context=context,
                    query=query,
                )
                connection.commit()
                return result
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
            finally:
                connection.close()

    def _search_current_snapshot(
        self,
        *,
        connection: sqlite3.Connection,
        context: OperationContext,
        query: str,
    ) -> RealDiscoveryResult:
        policy_domain = self._policy.access_domain_id.value
        policy_owner = self._policy.perspective_owner.value
        policy_instance = self._policy.perspective_instance.value

        # Authorization domain and perspective filtering happen in SQL before
        # any candidate list, count, ordering, limit, or payload match is formed.
        thread_rows = connection.execute(
            """
            SELECT
                thread_id,
                perspective_owner_id,
                perspective_instance_id,
                about_subject_id,
                access_domain_id
            FROM real_threads
            WHERE access_domain_id = ?
              AND perspective_owner_id = ?
              AND perspective_instance_id = ?
            ORDER BY thread_id
            """,
            (policy_domain, policy_owner, policy_instance),
        ).fetchall()

        matched_thread_ids: list[str] = []

        for thread_row in thread_rows:
            thread_id, owner_id, instance_id, subject_id, domain_id = thread_row
            if (
                owner_id != policy_owner
                or instance_id != policy_instance
                or domain_id != policy_domain
                or not isinstance(subject_id, str)
                or not subject_id.strip()
            ):
                raise RealDiscoveryIntegrityError(
                    "authorized thread identity is internally inconsistent"
                )

            eligible_interpretation_ids = self._eligible_thread_interpretations(
                connection=connection,
                thread_id=thread_id,
                thread_identity=thread_row[1:],
            )
            if eligible_interpretation_ids is None:
                # Conservative no-fallback rule: if any admitted interpretation
                # or supersession reason in this authorized thread is currently
                # unusable, the whole thread cannot enter normal discovery.
                continue
            if not eligible_interpretation_ids:
                continue

            if self._thread_matches_query(
                connection=connection,
                thread_id=thread_id,
                interpretation_ids=eligible_interpretation_ids,
                query=query,
            ):
                matched_thread_ids.append(thread_id)
                # N+1: never publish a partial prefix when the cap is exceeded.
                if len(matched_thread_ids) > self._max_thread_matches:
                    return self._too_many_result(context=context, query=query)

        ordered = tuple(sorted(matched_thread_ids))
        return self._complete_result(
            context=context,
            query=query,
            thread_ids=ordered,
        )

    def _eligible_thread_interpretations(
        self,
        *,
        connection: sqlite3.Connection,
        thread_id: str,
        thread_identity: tuple[str, str, str, str],
    ) -> tuple[str, ...] | None:
        owner_id, instance_id, subject_id, domain_id = thread_identity
        membership_rows = connection.execute(
            """
            SELECT
                memberships.interpretation_id,
                memberships.perspective_owner_id,
                memberships.perspective_instance_id,
                memberships.about_subject_id,
                memberships.access_domain_id,
                interpretations.perspective_owner_id,
                interpretations.perspective_instance_id,
                interpretations.about_subject_id,
                interpretations.access_domain_id
            FROM real_thread_memberships AS memberships
            JOIN real_interpretations AS interpretations
              ON interpretations.interpretation_id = memberships.interpretation_id
            WHERE memberships.thread_id = ?
            ORDER BY memberships.interpretation_id
            """,
            (thread_id,),
        ).fetchall()

        interpretation_ids: list[str] = []
        for row in membership_rows:
            interpretation_id = row[0]
            copied_identity = row[1:5]
            interpretation_identity = row[5:9]
            if copied_identity != thread_identity or interpretation_identity != thread_identity:
                raise RealDiscoveryIntegrityError(
                    "authorized thread membership crosses identity or access domain"
                )
            try:
                assert_interpretation_usable(connection, interpretation_id)
            except RealSourceSuppressedError:
                return None
            except RealUseStateIntegrityError as error:
                raise RealDiscoveryIntegrityError(
                    "authorized interpretation use state is invalid"
                ) from error
            interpretation_ids.append(interpretation_id)

        # Existing supersession reason evidence is part of the thread's current
        # normal-use support. A suppressed reason blocks discovery of the thread
        # rather than silently reviving an older interpretation path.
        supersession_rows = connection.execute(
            """
            SELECT
                supersession_id,
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

        for supersession_row in supersession_rows:
            supersession_id = supersession_row[0]
            if supersession_row[1:5] != thread_identity:
                raise RealDiscoveryIntegrityError(
                    "authorized supersession crosses identity or access domain"
                )
            reason_rows = connection.execute(
                """
                SELECT
                    position,
                    source_id,
                    source_sha256,
                    start_char,
                    end_char,
                    access_domain_id
                FROM real_supersession_reason_evidence
                WHERE supersession_id = ?
                ORDER BY position
                """,
                (supersession_id,),
            ).fetchall()
            if not reason_rows:
                raise RealDiscoveryIntegrityError(
                    "authorized supersession has no reason evidence"
                )
            positions = [row[0] for row in reason_rows]
            if positions != list(range(len(reason_rows))):
                raise RealDiscoveryIntegrityError(
                    "authorized supersession reason positions are incomplete"
                )
            source_ids = tuple(row[1] for row in reason_rows)
            try:
                assert_source_ids_usable(connection, source_ids)
            except RealSourceSuppressedError:
                return None
            except RealUseStateIntegrityError as error:
                raise RealDiscoveryIntegrityError(
                    "authorized supersession reason use state is invalid"
                ) from error
            for reason_row in reason_rows:
                self._validate_exact_evidence_row(
                    connection=connection,
                    source_id=reason_row[1],
                    expected_hash=reason_row[2],
                    start_char=reason_row[3],
                    end_char=reason_row[4],
                    expected_domain=reason_row[5],
                    required_domain=domain_id,
                )

        return tuple(interpretation_ids)

    def _thread_matches_query(
        self,
        *,
        connection: sqlite3.Connection,
        thread_id: str,
        interpretation_ids: tuple[str, ...],
        query: str,
    ) -> bool:
        placeholders = ",".join("?" for _ in interpretation_ids)
        rows = connection.execute(
            f"""
            SELECT
                memberships.thread_id,
                evidence.interpretation_id,
                evidence.position,
                evidence.source_id,
                evidence.source_sha256,
                evidence.start_char,
                evidence.end_char,
                evidence.access_domain_id,
                sources.content,
                sources.content_sha256,
                sources.access_domain_id
            FROM real_thread_memberships AS memberships
            JOIN real_interpretation_evidence AS evidence
              ON evidence.interpretation_id = memberships.interpretation_id
            JOIN real_sources AS sources
              ON sources.source_id = evidence.source_id
            WHERE memberships.thread_id = ?
              AND evidence.interpretation_id IN ({placeholders})
            ORDER BY evidence.interpretation_id, evidence.position
            """,
            (thread_id, *interpretation_ids),
        ).fetchall()

        evidence_by_interpretation: dict[str, list[tuple]] = {
            interpretation_id: [] for interpretation_id in interpretation_ids
        }
        for row in rows:
            evidence_by_interpretation.setdefault(row[1], []).append(row)

        for interpretation_id in interpretation_ids:
            interpretation_rows = evidence_by_interpretation.get(interpretation_id, [])
            if not interpretation_rows:
                raise RealDiscoveryIntegrityError(
                    "authorized interpretation has no discovery evidence"
                )
            positions = [row[2] for row in interpretation_rows]
            if positions != list(range(len(interpretation_rows))):
                raise RealDiscoveryIntegrityError(
                    "authorized interpretation evidence positions are incomplete"
                )
            for row in interpretation_rows:
                if row[0] != thread_id:
                    raise RealDiscoveryIntegrityError(
                        "authorized evidence escaped its thread"
                    )
                source_id = row[3]
                expected_hash = row[4]
                start_char = row[5]
                end_char = row[6]
                evidence_domain = row[7]
                content = row[8]
                stored_hash = row[9]
                source_domain = row[10]

                if evidence_domain != self._policy.access_domain_id.value:
                    raise RealDiscoveryIntegrityError(
                        "authorized evidence crosses the discovery access domain"
                    )
                if source_domain != evidence_domain:
                    raise RealDiscoveryIntegrityError(
                        "authorized evidence source domain is inconsistent"
                    )
                actual_hash = sha256(content.encode("utf-8")).hexdigest()
                if actual_hash != stored_hash or stored_hash != expected_hash:
                    raise RealDiscoveryIntegrityError(
                        "authorized discovery source integrity failed"
                    )
                if (
                    not isinstance(start_char, int)
                    or not isinstance(end_char, int)
                    or start_char < 0
                    or end_char <= start_char
                    or end_char > len(content)
                ):
                    raise RealDiscoveryIntegrityError(
                        "authorized discovery evidence offsets are invalid"
                    )
                exact_span = content[start_char:end_char]
                if query in exact_span:
                    return True
        return False

    def _validate_exact_evidence_row(
        self,
        *,
        connection: sqlite3.Connection,
        source_id: str,
        expected_hash: str,
        start_char: int,
        end_char: int,
        expected_domain: str,
        required_domain: str,
    ) -> None:
        if expected_domain != required_domain:
            raise RealDiscoveryIntegrityError(
                "authorized reason evidence crosses the thread access domain"
            )
        row = connection.execute(
            """
            SELECT content, content_sha256, access_domain_id
            FROM real_sources
            WHERE source_id = ?
            """,
            (source_id,),
        ).fetchone()
        if row is None:
            raise RealDiscoveryIntegrityError(
                "authorized reason source is missing"
            )
        content, stored_hash, source_domain = row
        if source_domain != required_domain:
            raise RealDiscoveryIntegrityError(
                "authorized reason source domain is inconsistent"
            )
        actual_hash = sha256(content.encode("utf-8")).hexdigest()
        if actual_hash != stored_hash or stored_hash != expected_hash:
            raise RealDiscoveryIntegrityError(
                "authorized reason source integrity failed"
            )
        if (
            not isinstance(start_char, int)
            or not isinstance(end_char, int)
            or start_char < 0
            or end_char <= start_char
            or end_char > len(content)
        ):
            raise RealDiscoveryIntegrityError(
                "authorized reason evidence offsets are invalid"
            )

    def _complete_result(
        self,
        *,
        context: OperationContext,
        query: str,
        thread_ids: tuple[str, ...],
    ) -> RealDiscoveryResult:
        receipt = RealDiscoveryReceipt(
            discovery_id=f"real-discovery-{uuid4().hex}",
            exact_query_input=query,
            query_rule_version=QUERY_RULE,
            eligible_domain_rule_version=ELIGIBILITY_RULE,
            result_status="ok",
            complete_for_rule=True,
            deterministic_ordering_rule=ORDERING_RULE,
            matched_thread_ids=thread_ids,
            max_thread_matches=self._max_thread_matches,
            operation_id=context.operation_id,
            principal_id=context.principal.principal_id,
            access_domain_id=self._policy.access_domain_id,
            policy_id=self._policy.policy_id,
        )
        return RealDiscoveryResult(
            status="ok",
            complete_for_rule=True,
            thread_ids=thread_ids,
            receipt=receipt,
        )

    def _too_many_result(
        self,
        *,
        context: OperationContext,
        query: str,
    ) -> RealDiscoveryResult:
        receipt = RealDiscoveryReceipt(
            discovery_id=f"real-discovery-{uuid4().hex}",
            exact_query_input=query,
            query_rule_version=QUERY_RULE,
            eligible_domain_rule_version=ELIGIBILITY_RULE,
            result_status="too_many_matches",
            complete_for_rule=False,
            deterministic_ordering_rule=ORDERING_RULE,
            matched_thread_ids=(),
            max_thread_matches=self._max_thread_matches,
            operation_id=context.operation_id,
            principal_id=context.principal.principal_id,
            access_domain_id=self._policy.access_domain_id,
            policy_id=self._policy.policy_id,
        )
        return RealDiscoveryResult(
            status="too_many_matches",
            complete_for_rule=False,
            thread_ids=None,
            receipt=receipt,
        )


def _require_discovery_capability(
    capability: ClosedRealDiscoveryExerciseCapability,
) -> None:
    if not isinstance(capability, ClosedRealDiscoveryExerciseCapability):
        raise RealDiscoveryDisabledError(
            "closed real discovery requires trusted exercise capability"
        )
    if capability._marker is not _CLOSED_REAL_DISCOVERY_CAPABILITY_MARKER:
        raise RealDiscoveryDisabledError("closed real discovery capability is invalid")


def _require_discovery_policy(policy: SingleOwnerRealDiscoveryPolicy) -> None:
    if not isinstance(policy, SingleOwnerRealDiscoveryPolicy):
        raise RealDiscoveryAuthorizationError(
            "closed real discovery requires trusted policy"
        )
    if policy._marker is not _TRUSTED_REAL_DISCOVERY_POLICY_MARKER:
        raise RealDiscoveryAuthorizationError("real discovery policy is invalid")


def _validate_literal_query(query: str) -> None:
    if not isinstance(query, str):
        raise RealDiscoveryQueryError("query must be a string")
    if query == "":
        raise RealDiscoveryQueryError("query cannot be empty")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in query):
        raise RealDiscoveryQueryError(
            "query must contain valid Unicode scalar values"
        )
