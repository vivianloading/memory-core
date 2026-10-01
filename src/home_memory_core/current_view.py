from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class CurrentViewError(ValueError):
    """Current View input or topology violates the semantic contract."""


class CurrentNamespace(StrEnum):
    ROOM = "room"
    SHARED = "shared"


class CurrentStateKind(StrEnum):
    PROJECT_STATUS = "project_status"
    PREFERENCE = "preference"
    COMMITMENT = "commitment"
    SELF_INTERPRETATION = "self_interpretation"
    SHARED_STATE = "shared_state"
    UNFINISHED_WORK = "unfinished_work"


class SemanticChangeAuthority(StrEnum):
    """Semantic ownership metadata, never an operational access credential."""

    ROOM_FIRST_PERSON = "room_first_person"
    SHARED_GOVERNANCE = "shared_governance"


class ValidityRule(StrEnum):
    DURABLE_UNTIL_CHANGED = "durable_until_changed"
    EXPLICIT_INTERVAL = "explicit_interval"
    STALE_TO_LAST_KNOWN = "stale_to_last_known"
    OPEN_UNTIL_RESOLVED = "open_until_resolved"


class DowngradeRule(StrEnum):
    NONE = "none"
    TO_LAST_KNOWN = "to_last_known"
    TO_EXPIRED = "to_expired"


class CurrentStanding(StrEnum):
    CURRENT = "current"
    LAST_KNOWN = "last_known"
    UNRESOLVED = "unresolved"
    EXPIRED = "expired"
    ENDED = "ended"
    CONFLICTING = "conflicting"
    NO_CURRENT = "no_current"
    UNKNOWN = "unknown"


class EndKind(StrEnum):
    RESOLVED = "resolved"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    WITHDRAWN = "withdrawn"
    EXPLICIT_END = "explicit_end"


_ELIGIBLE_STANDINGS = frozenset(
    {
        CurrentStanding.CURRENT,
        CurrentStanding.LAST_KNOWN,
        CurrentStanding.UNRESOLVED,
    }
)

_EXPECTED_DOWNGRADE = {
    ValidityRule.DURABLE_UNTIL_CHANGED: DowngradeRule.NONE,
    ValidityRule.EXPLICIT_INTERVAL: DowngradeRule.TO_EXPIRED,
    ValidityRule.STALE_TO_LAST_KNOWN: DowngradeRule.TO_LAST_KNOWN,
    ValidityRule.OPEN_UNTIL_RESOLVED: DowngradeRule.NONE,
}

_ALLOWED_VALIDITY_BY_KIND = {
    CurrentStateKind.PROJECT_STATUS: frozenset(
        {ValidityRule.DURABLE_UNTIL_CHANGED}
    ),
    CurrentStateKind.PREFERENCE: frozenset(
        {
            ValidityRule.DURABLE_UNTIL_CHANGED,
            ValidityRule.STALE_TO_LAST_KNOWN,
        }
    ),
    CurrentStateKind.COMMITMENT: frozenset(
        {ValidityRule.OPEN_UNTIL_RESOLVED}
    ),
    CurrentStateKind.SELF_INTERPRETATION: frozenset(
        {ValidityRule.DURABLE_UNTIL_CHANGED}
    ),
    CurrentStateKind.SHARED_STATE: frozenset(
        {
            ValidityRule.DURABLE_UNTIL_CHANGED,
            ValidityRule.EXPLICIT_INTERVAL,
            ValidityRule.OPEN_UNTIL_RESOLVED,
        }
    ),
    CurrentStateKind.UNFINISHED_WORK: frozenset(
        {ValidityRule.OPEN_UNTIL_RESOLVED}
    ),
}


@dataclass(frozen=True)
class CurrentStateRecord:
    """One immutable historical assertion that may have present standing.

    event_time says when the underlying event/choice/state belongs in life.
    recorded_at says when HOME learned/stored this record.
    valid_from and the validity rule determine when it may participate in
    Current View.

    semantic_change_authority describes whose kind of choice/state this is.
    It is not an operational write capability and must never be used as one.
    """

    state_id: str
    namespace: CurrentNamespace
    owner_id: str
    key: str
    state_kind: CurrentStateKind
    value: str
    event_time: datetime
    recorded_at: datetime
    valid_from: datetime
    validity_rule: ValidityRule
    downgrade_rule: DowngradeRule
    semantic_change_authority: SemanticChangeAuthority
    episode_id: str | None = None
    perspective_instance_id: str | None = None
    valid_until: datetime | None = None
    stale_after: timedelta | None = None
    supersedes_state_id: str | None = None
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("state_id", "owner_id", "key", "value"):
            _require_text(field_name, getattr(self, field_name))
        if not isinstance(self.namespace, CurrentNamespace):
            raise CurrentViewError("namespace must use CurrentNamespace")
        if not isinstance(self.state_kind, CurrentStateKind):
            raise CurrentViewError("state_kind must use CurrentStateKind")
        if not isinstance(self.validity_rule, ValidityRule):
            raise CurrentViewError("validity_rule must use ValidityRule")
        if not isinstance(self.downgrade_rule, DowngradeRule):
            raise CurrentViewError("downgrade_rule must use DowngradeRule")
        if not isinstance(
            self.semantic_change_authority,
            SemanticChangeAuthority,
        ):
            raise CurrentViewError(
                "semantic_change_authority must use SemanticChangeAuthority"
            )

        _require_aware("event_time", self.event_time)
        _require_aware("recorded_at", self.recorded_at)
        _require_aware("valid_from", self.valid_from)
        if self.valid_until is not None:
            _require_aware("valid_until", self.valid_until)

        expected_authority = (
            SemanticChangeAuthority.ROOM_FIRST_PERSON
            if self.namespace is CurrentNamespace.ROOM
            else SemanticChangeAuthority.SHARED_GOVERNANCE
        )
        if self.semantic_change_authority is not expected_authority:
            raise CurrentViewError(
                "semantic change authority does not match Current namespace"
            )
        if (
            self.namespace is CurrentNamespace.SHARED
            and self.state_kind is CurrentStateKind.SELF_INTERPRETATION
        ):
            raise CurrentViewError(
                "Shared current state cannot be first-person self interpretation"
            )
        if (
            self.namespace is CurrentNamespace.ROOM
            and self.state_kind is CurrentStateKind.SHARED_STATE
        ):
            raise CurrentViewError(
                "Room current state cannot claim shared-state kind"
            )

        if self.namespace is CurrentNamespace.ROOM:
            if self.episode_id is None or self.perspective_instance_id is None:
                raise CurrentViewError(
                    "Room current state requires Episode and PerspectiveInstance provenance"
                )
            _require_text("episode_id", self.episode_id)
            _require_text(
                "perspective_instance_id",
                self.perspective_instance_id,
            )
        elif (
            self.episode_id is not None
            or self.perspective_instance_id is not None
        ):
            raise CurrentViewError(
                "Shared current state cannot claim Room first-person provenance"
            )

        _validate_source_refs(
            field_name="source_refs",
            source_refs=self.source_refs,
        )

        if self.validity_rule not in _ALLOWED_VALIDITY_BY_KIND[
            self.state_kind
        ]:
            raise CurrentViewError(
                "validity_rule is not allowed for this state_kind"
            )

        expected_downgrade = _EXPECTED_DOWNGRADE[self.validity_rule]
        if self.downgrade_rule is not expected_downgrade:
            raise CurrentViewError(
                "downgrade_rule does not match validity_rule"
            )

        if self.validity_rule is ValidityRule.EXPLICIT_INTERVAL:
            if self.valid_until is None:
                raise CurrentViewError(
                    "explicit interval requires valid_until"
                )
            if self.valid_until <= self.valid_from:
                raise CurrentViewError(
                    "valid_until must be after valid_from"
                )
            if self.stale_after is not None:
                raise CurrentViewError(
                    "explicit interval cannot also use stale_after"
                )
        elif self.valid_until is not None:
            raise CurrentViewError(
                "valid_until is only valid for explicit_interval"
            )

        if self.validity_rule is ValidityRule.STALE_TO_LAST_KNOWN:
            if (
                self.stale_after is None
                or not isinstance(self.stale_after, timedelta)
                or self.stale_after <= timedelta(0)
            ):
                raise CurrentViewError(
                    "stale_to_last_known requires positive stale_after"
                )
        elif self.stale_after is not None:
            raise CurrentViewError(
                "stale_after is only valid for stale_to_last_known"
            )

        if self.supersedes_state_id is not None:
            _require_text(
                "supersedes_state_id",
                self.supersedes_state_id,
            )
            if self.supersedes_state_id == self.state_id:
                raise CurrentViewError("state cannot supersede itself")



@dataclass(frozen=True)
class CurrentStateEndEvent:
    """Append-only evidence that explicitly ended one historical state."""

    end_event_id: str
    state_id: str
    ended_at: datetime
    recorded_at: datetime
    end_kind: EndKind
    reason: str
    semantic_change_authority: SemanticChangeAuthority
    episode_id: str | None = None
    perspective_instance_id: str | None = None
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "end_event_id",
            "state_id",
            "reason",
        ):
            _require_text(field_name, getattr(self, field_name))
        _require_aware("ended_at", self.ended_at)
        _require_aware("recorded_at", self.recorded_at)
        if not isinstance(self.end_kind, EndKind):
            raise CurrentViewError("end_kind must use EndKind")
        if not isinstance(
            self.semantic_change_authority,
            SemanticChangeAuthority,
        ):
            raise CurrentViewError(
                "end semantic_change_authority must use SemanticChangeAuthority"
            )
        if (
            self.semantic_change_authority
            is SemanticChangeAuthority.ROOM_FIRST_PERSON
        ):
            if self.episode_id is None or self.perspective_instance_id is None:
                raise CurrentViewError(
                    "Room end event requires Episode and PerspectiveInstance provenance"
                )
            _require_text("episode_id", self.episode_id)
            _require_text(
                "perspective_instance_id",
                self.perspective_instance_id,
            )
        elif (
            self.episode_id is not None
            or self.perspective_instance_id is not None
        ):
            raise CurrentViewError(
                "Shared end event cannot claim Room first-person provenance"
            )
        _validate_source_refs(
            field_name="source_refs",
            source_refs=self.source_refs,
        )


@dataclass(frozen=True)
class CurrentCandidate:
    """Exact historical state/end evidence plus derived as-of standing."""

    record: CurrentStateRecord
    end_events: tuple[CurrentStateEndEvent, ...]
    standing: CurrentStanding
    reason_codes: tuple[str, ...]

    @property
    def state_id(self) -> str:
        return self.record.state_id

    @property
    def value(self) -> str:
        return self.record.value


@dataclass(frozen=True)
class CurrentResolution:
    namespace: CurrentNamespace
    owner_id: str
    key: str
    standing: CurrentStanding
    current_state_ids: tuple[str, ...]
    historical_state_ids: tuple[str, ...]
    future_state_ids: tuple[str, ...]
    candidates: tuple[CurrentCandidate, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class CurrentView:
    as_of: datetime
    namespace: CurrentNamespace
    owner_id: str
    items: tuple[CurrentResolution, ...]


def resolve_current_state(
    *,
    namespace: CurrentNamespace,
    owner_id: str,
    key: str,
    records: tuple[CurrentStateRecord, ...],
    end_events: tuple[CurrentStateEndEvent, ...] = (),
    as_of: datetime,
) -> CurrentResolution:
    """Derive one key's present standing without last-write-wins shortcuts."""

    _require_aware("as_of", as_of)
    _require_text("owner_id", owner_id)
    _require_text("key", key)
    if not isinstance(namespace, CurrentNamespace):
        raise CurrentViewError("namespace must use CurrentNamespace")

    known_global = tuple(
        record
        for record in records
        if record.recorded_at <= as_of
    )
    known_end_global = tuple(
        event
        for event in end_events
        if event.recorded_at <= as_of
    )
    _validate_global_ids(
        records=known_global,
        end_events=known_end_global,
    )

    relevant = tuple(
        record
        for record in known_global
        if (
            record.namespace is namespace
            and record.owner_id == owner_id
            and record.key == key
        )
    )

    known = relevant
    known_end_events = known_end_global
    _validate_current_graph(records=known)
    if not known:
        return CurrentResolution(
            namespace=namespace,
            owner_id=owner_id,
            key=key,
            standing=CurrentStanding.UNKNOWN,
            current_state_ids=(),
            historical_state_ids=(),
            future_state_ids=(),
            candidates=(),
            reason_codes=("NO_RECORD_KNOWN_AS_OF",),
        )

    effective = tuple(
        record
        for record in known
        if record.valid_from <= as_of
    )
    if not effective:
        return CurrentResolution(
            namespace=namespace,
            owner_id=owner_id,
            key=key,
            standing=CurrentStanding.UNKNOWN,
            current_state_ids=(),
            historical_state_ids=(),
            future_state_ids=tuple(
                sorted(record.state_id for record in known)
            ),
            candidates=(),
            reason_codes=("KNOWN_ONLY_FOR_FUTURE_VALIDITY",),
        )

    future_ids = tuple(
        sorted(
            record.state_id
            for record in known
            if record.valid_from > as_of
        )
    )
    effective_ids = {record.state_id for record in effective}
    superseded_ids = {
        record.supersedes_state_id
        for record in effective
        if (
            record.supersedes_state_id is not None
            and record.supersedes_state_id in effective_ids
        )
    }
    head_records = tuple(
        record
        for record in effective
        if record.state_id not in superseded_ids
    )

    end_by_state = _effective_end_events(
        records=known,
        end_events=known_end_events,
        as_of=as_of,
    )
    candidates = tuple(
        _candidate_for(
            record=record,
            end_events=end_by_state.get(record.state_id, ()),
            as_of=as_of,
        )
        for record in sorted(
            head_records,
            key=lambda item: item.state_id,
        )
    )

    conflict_candidates = tuple(
        candidate
        for candidate in candidates
        if candidate.standing is CurrentStanding.CONFLICTING
    )
    if conflict_candidates:
        implicated = tuple(
            candidate.state_id
            for candidate in candidates
            if (
                candidate.standing in _ELIGIBLE_STANDINGS
                or candidate.standing is CurrentStanding.CONFLICTING
            )
        )
        historical = tuple(
            sorted(
                record.state_id
                for record in effective
                if record.state_id not in set(implicated)
            )
        )
        return CurrentResolution(
            namespace=namespace,
            owner_id=owner_id,
            key=key,
            standing=CurrentStanding.CONFLICTING,
            current_state_ids=implicated,
            historical_state_ids=historical,
            future_state_ids=future_ids,
            candidates=candidates,
            reason_codes=(
                "CONFLICTING_HEAD_SEMANTICS",
                *tuple(
                    sorted(
                        {
                            reason
                            for candidate in conflict_candidates
                            for reason in candidate.reason_codes
                        }
                    )
                ),
            ),
        )

    eligible = tuple(
        candidate
        for candidate in candidates
        if candidate.standing in _ELIGIBLE_STANDINGS
    )
    eligible_ids = {
        candidate.state_id
        for candidate in eligible
    }
    historical_ids = tuple(
        sorted(
            record.state_id
            for record in effective
            if record.state_id not in eligible_ids
        )
    )

    if len(eligible) > 1:
        return CurrentResolution(
            namespace=namespace,
            owner_id=owner_id,
            key=key,
            standing=CurrentStanding.CONFLICTING,
            current_state_ids=tuple(
                candidate.state_id
                for candidate in eligible
            ),
            historical_state_ids=historical_ids,
            future_state_ids=future_ids,
            candidates=candidates,
            reason_codes=("MULTIPLE_ELIGIBLE_HEADS",),
        )

    if len(eligible) == 1:
        candidate = eligible[0]
        return CurrentResolution(
            namespace=namespace,
            owner_id=owner_id,
            key=key,
            standing=candidate.standing,
            current_state_ids=(candidate.state_id,),
            historical_state_ids=historical_ids,
            future_state_ids=future_ids,
            candidates=candidates,
            reason_codes=candidate.reason_codes,
        )

    inactive_standings = {
        candidate.standing
        for candidate in candidates
    }
    if len(candidates) == 1:
        only = candidates[0]
        return CurrentResolution(
            namespace=namespace,
            owner_id=owner_id,
            key=key,
            standing=only.standing,
            current_state_ids=(),
            historical_state_ids=tuple(
                sorted(record.state_id for record in effective)
            ),
            future_state_ids=future_ids,
            candidates=candidates,
            reason_codes=only.reason_codes,
        )

    reason_codes = (
        "NO_ELIGIBLE_HEAD",
        *tuple(
            sorted(
                f"HEAD_{standing.value.upper()}"
                for standing in inactive_standings
            )
        ),
    )
    return CurrentResolution(
        namespace=namespace,
        owner_id=owner_id,
        key=key,
        standing=CurrentStanding.NO_CURRENT,
        current_state_ids=(),
        historical_state_ids=tuple(
            sorted(record.state_id for record in effective)
        ),
        future_state_ids=future_ids,
        candidates=candidates,
        reason_codes=reason_codes,
    )


def derive_current_view(
    *,
    namespace: CurrentNamespace,
    owner_id: str,
    records: tuple[CurrentStateRecord, ...],
    end_events: tuple[CurrentStateEndEvent, ...] = (),
    as_of: datetime,
) -> CurrentView:
    """Derive all known keys for one Room or Shared owner."""

    _require_aware("as_of", as_of)
    _require_text("owner_id", owner_id)
    if not isinstance(namespace, CurrentNamespace):
        raise CurrentViewError("namespace must use CurrentNamespace")

    known_global = tuple(
        record
        for record in records
        if record.recorded_at <= as_of
    )
    known_end_global = tuple(
        event
        for event in end_events
        if event.recorded_at <= as_of
    )
    _validate_global_ids(
        records=known_global,
        end_events=known_end_global,
    )

    matching = tuple(
        record
        for record in records
        if (
            record.namespace is namespace
            and record.owner_id == owner_id
        )
    )
    keys = tuple(
        sorted(
            {
                record.key
                for record in matching
                if record.recorded_at <= as_of
            }
        )
    )
    items = tuple(
        resolve_current_state(
            namespace=namespace,
            owner_id=owner_id,
            key=key,
            records=records,
            end_events=end_events,
            as_of=as_of,
        )
        for key in keys
    )
    return CurrentView(
        as_of=as_of,
        namespace=namespace,
        owner_id=owner_id,
        items=items,
    )


def _candidate_for(
    *,
    record: CurrentStateRecord,
    end_events: tuple[CurrentStateEndEvent, ...],
    as_of: datetime,
) -> CurrentCandidate:
    if len(end_events) > 1:
        return CurrentCandidate(
            record=record,
            end_events=end_events,
            standing=CurrentStanding.CONFLICTING,
            reason_codes=("MULTIPLE_EFFECTIVE_END_EVENTS",),
        )
    if len(end_events) == 1:
        end_event = end_events[0]
        return CurrentCandidate(
            record=record,
            end_events=end_events,
            standing=CurrentStanding.ENDED,
            reason_codes=(
                "EXPLICIT_END_EVENT",
                f"END_KIND_{end_event.end_kind.value.upper()}",
            ),
        )

    if record.validity_rule is ValidityRule.DURABLE_UNTIL_CHANGED:
        return CurrentCandidate(
            record=record,
            end_events=end_events,
            standing=CurrentStanding.CURRENT,
            reason_codes=("DURABLE_UNTIL_CHANGED",),
        )

    if record.validity_rule is ValidityRule.EXPLICIT_INTERVAL:
        assert record.valid_until is not None
        if as_of >= record.valid_until:
            return CurrentCandidate(
                record=record,
                end_events=end_events,
                standing=CurrentStanding.EXPIRED,
                reason_codes=("EXPLICIT_VALIDITY_INTERVAL_ENDED",),
            )
        return CurrentCandidate(
            record=record,
            end_events=end_events,
            standing=CurrentStanding.CURRENT,
            reason_codes=("WITHIN_EXPLICIT_VALIDITY_INTERVAL",),
        )

    if record.validity_rule is ValidityRule.STALE_TO_LAST_KNOWN:
        assert record.stale_after is not None
        stale_at = record.event_time + record.stale_after
        if as_of >= stale_at:
            return CurrentCandidate(
                record=record,
                end_events=end_events,
                standing=CurrentStanding.LAST_KNOWN,
                reason_codes=("STALE_TO_LAST_KNOWN",),
            )
        return CurrentCandidate(
            record=record,
            end_events=end_events,
            standing=CurrentStanding.CURRENT,
            reason_codes=("FRESH_WITHIN_STALENESS_WINDOW",),
        )

    if record.validity_rule is ValidityRule.OPEN_UNTIL_RESOLVED:
        return CurrentCandidate(
            record=record,
            end_events=end_events,
            standing=CurrentStanding.UNRESOLVED,
            reason_codes=("OPEN_UNTIL_EXPLICITLY_RESOLVED",),
        )

    raise CurrentViewError("unsupported validity rule")


def _effective_end_events(
    *,
    records: tuple[CurrentStateRecord, ...],
    end_events: tuple[CurrentStateEndEvent, ...],
    as_of: datetime,
) -> dict[str, tuple[CurrentStateEndEvent, ...]]:
    record_ids = {record.state_id for record in records}
    effective: dict[str, list[CurrentStateEndEvent]] = {}

    for event in end_events:
        if event.state_id not in record_ids:
            continue
        if event.recorded_at > as_of or event.ended_at > as_of:
            continue
        effective.setdefault(event.state_id, []).append(event)

    return {
        state_id: tuple(
            sorted(
                events,
                key=lambda item: item.end_event_id,
            )
        )
        for state_id, events in effective.items()
    }


def _validate_global_ids(
    *,
    records: tuple[CurrentStateRecord, ...],
    end_events: tuple[CurrentStateEndEvent, ...],
) -> None:
    record_ids: set[str] = set()
    for record in records:
        if record.state_id in record_ids:
            raise CurrentViewError("duplicate state_id")
        record_ids.add(record.state_id)

    end_ids: set[str] = set()
    record_by_id = {
        record.state_id: record
        for record in records
    }
    for event in end_events:
        if event.end_event_id in end_ids:
            raise CurrentViewError("duplicate end_event_id")
        end_ids.add(event.end_event_id)
        target = record_by_id.get(event.state_id)
        if target is None:
            raise CurrentViewError(
                "end event references unknown state"
            )
        if (
            event.semantic_change_authority
            is not target.semantic_change_authority
        ):
            raise CurrentViewError(
                "end event semantic authority does not match target state"
            )


def _validate_current_graph(
    *,
    records: tuple[CurrentStateRecord, ...],
) -> None:
    record_by_id: dict[str, CurrentStateRecord] = {}
    for record in records:
        if record.state_id in record_by_id:
            raise CurrentViewError("duplicate state_id")
        record_by_id[record.state_id] = record

    state_kinds = {
        record.state_kind
        for record in records
    }
    if len(state_kinds) > 1:
        raise CurrentViewError(
            "one Current key cannot change state_kind across history"
        )

    parent_by_child: dict[str, str] = {}
    children_by_parent: dict[str, set[str]] = {}
    for record in records:
        parent_id = record.supersedes_state_id
        if parent_id is None:
            continue
        parent = record_by_id.get(parent_id)
        if parent is None:
            raise CurrentViewError(
                "superseded state is missing from current-state history"
            )
        if (
            parent.namespace is not record.namespace
            or parent.owner_id != record.owner_id
            or parent.key != record.key
        ):
            raise CurrentViewError(
                "supersession cannot cross namespace, owner, or key"
            )
        parent_by_child[record.state_id] = parent_id
        children_by_parent.setdefault(parent_id, set()).add(
            record.state_id
        )

    for state_id in record_by_id:
        seen: set[str] = set()
        current = state_id
        while current in parent_by_child:
            if current in seen:
                raise CurrentViewError(
                    "current-state supersession graph contains a cycle"
                )
            seen.add(current)
            current = parent_by_child[current]

    _ = children_by_parent


def _validate_source_refs(
    *,
    field_name: str,
    source_refs: tuple[str, ...],
) -> None:
    if not isinstance(source_refs, tuple) or not source_refs:
        raise CurrentViewError(
            f"{field_name} must be a non-empty tuple"
        )
    for source_ref in source_refs:
        _require_text("source_ref", source_ref)
    if len(set(source_refs)) != len(source_refs):
        raise CurrentViewError(
            f"{field_name} cannot contain duplicates"
        )


def _require_aware(field_name: str, value: datetime) -> None:
    if not isinstance(value, datetime):
        raise CurrentViewError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise CurrentViewError(f"{field_name} must be timezone-aware")


def _require_text(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CurrentViewError(f"{field_name} cannot be empty")
