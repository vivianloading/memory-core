import dataclasses
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


from home_memory_core.current_view import (
    CurrentNamespace,
    CurrentStanding,
    CurrentStateEndEvent,
    CurrentStateKind,
    CurrentStateRecord,
    CurrentViewError,
    DowngradeRule,
    EndKind,
    SemanticChangeAuthority,
    ValidityRule,
    derive_current_view,
    resolve_current_state,
)


UTC = timezone.utc


class CurrentViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.t0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

    def _room_record(
        self,
        state_id: str,
        *,
        key: str = "project.home.status",
        value: str = "building",
        state_kind: CurrentStateKind = CurrentStateKind.PROJECT_STATUS,
        event_offset: timedelta = timedelta(0),
        recorded_offset: timedelta = timedelta(0),
        valid_from_offset: timedelta = timedelta(0),
        validity_rule: ValidityRule = ValidityRule.DURABLE_UNTIL_CHANGED,
        downgrade_rule: DowngradeRule = DowngradeRule.NONE,
        valid_until_offset: timedelta | None = None,
        stale_after: timedelta | None = None,
        supersedes_state_id: str | None = None,
        room_id: str = "room-r",
        episode_id: str = "episode-a",
        perspective_instance_id: str = "perspective-a",
    ) -> CurrentStateRecord:
        return CurrentStateRecord(
            state_id=state_id,
            namespace=CurrentNamespace.ROOM,
            owner_id=room_id,
            key=key,
            state_kind=state_kind,
            value=value,
            event_time=self.t0 + event_offset,
            recorded_at=self.t0 + recorded_offset,
            valid_from=self.t0 + valid_from_offset,
            validity_rule=validity_rule,
            downgrade_rule=downgrade_rule,
            semantic_change_authority=(
                SemanticChangeAuthority.ROOM_FIRST_PERSON
            ),
            episode_id=episode_id,
            perspective_instance_id=perspective_instance_id,
            valid_until=(
                None
                if valid_until_offset is None
                else self.t0 + valid_until_offset
            ),
            stale_after=stale_after,
            supersedes_state_id=supersedes_state_id,
            source_refs=(f"source-{state_id}",),
        )

    def _shared_record(
        self,
        state_id: str,
        *,
        key: str = "shared.project.status",
        value: str = "open",
        event_offset: timedelta = timedelta(0),
        recorded_offset: timedelta = timedelta(0),
        valid_from_offset: timedelta = timedelta(0),
        validity_rule: ValidityRule = ValidityRule.DURABLE_UNTIL_CHANGED,
        downgrade_rule: DowngradeRule = DowngradeRule.NONE,
        valid_until_offset: timedelta | None = None,
        stale_after: timedelta | None = None,
        supersedes_state_id: str | None = None,
        shared_id: str = "shared-home",
    ) -> CurrentStateRecord:
        return CurrentStateRecord(
            state_id=state_id,
            namespace=CurrentNamespace.SHARED,
            owner_id=shared_id,
            key=key,
            state_kind=CurrentStateKind.SHARED_STATE,
            value=value,
            event_time=self.t0 + event_offset,
            recorded_at=self.t0 + recorded_offset,
            valid_from=self.t0 + valid_from_offset,
            validity_rule=validity_rule,
            downgrade_rule=downgrade_rule,
            semantic_change_authority=(
                SemanticChangeAuthority.SHARED_GOVERNANCE
            ),
            valid_until=(
                None
                if valid_until_offset is None
                else self.t0 + valid_until_offset
            ),
            stale_after=stale_after,
            supersedes_state_id=supersedes_state_id,
            source_refs=(f"source-{state_id}",),
        )

    def _resolve_room(
        self,
        records: tuple[CurrentStateRecord, ...],
        *,
        key: str = "project.home.status",
        as_of_offset: timedelta = timedelta(0),
        end_events: tuple[CurrentStateEndEvent, ...] = (),
    ):
        return resolve_current_state(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key=key,
            records=records,
            end_events=end_events,
            as_of=self.t0 + as_of_offset,
        )

    def test_durable_state_survives_silence(self) -> None:
        record = self._room_record("state-a")

        much_later = self._resolve_room(
            (record,),
            as_of_offset=timedelta(days=500),
        )

        self.assertEqual(much_later.standing, CurrentStanding.CURRENT)
        self.assertEqual(much_later.current_state_ids, ("state-a",))
        self.assertIn(
            "DURABLE_UNTIL_CHANGED",
            much_later.reason_codes,
        )

    def test_explicit_interval_expires_at_exact_boundary(self) -> None:
        record = self._shared_record(
            "state-window",
            validity_rule=ValidityRule.EXPLICIT_INTERVAL,
            downgrade_rule=DowngradeRule.TO_EXPIRED,
            valid_until_offset=timedelta(days=2),
        )

        before = resolve_current_state(
            namespace=CurrentNamespace.SHARED,
            owner_id="shared-home",
            key="shared.project.status",
            records=(record,),
            as_of=self.t0 + timedelta(days=2) - timedelta(microseconds=1),
        )
        at_boundary = resolve_current_state(
            namespace=CurrentNamespace.SHARED,
            owner_id="shared-home",
            key="shared.project.status",
            records=(record,),
            as_of=self.t0 + timedelta(days=2),
        )

        self.assertEqual(before.standing, CurrentStanding.CURRENT)
        self.assertEqual(at_boundary.standing, CurrentStanding.EXPIRED)
        self.assertEqual(at_boundary.current_state_ids, ())
        self.assertEqual(
            at_boundary.historical_state_ids,
            ("state-window",),
        )

    def test_stale_preference_downgrades_to_last_known(self) -> None:
        record = self._room_record(
            "preference-a",
            key="preference.coffee",
            value="tea",
            state_kind=CurrentStateKind.PREFERENCE,
            validity_rule=ValidityRule.STALE_TO_LAST_KNOWN,
            downgrade_rule=DowngradeRule.TO_LAST_KNOWN,
            stale_after=timedelta(days=7),
        )

        fresh = self._resolve_room(
            (record,),
            key="preference.coffee",
            as_of_offset=timedelta(days=6),
        )
        stale = self._resolve_room(
            (record,),
            key="preference.coffee",
            as_of_offset=timedelta(days=7),
        )

        self.assertEqual(fresh.standing, CurrentStanding.CURRENT)
        self.assertEqual(stale.standing, CurrentStanding.LAST_KNOWN)
        self.assertEqual(stale.current_state_ids, ("preference-a",))

    def test_staleness_uses_event_time_not_record_time(self) -> None:
        record = self._room_record(
            "preference-late-record",
            key="preference.music",
            value="ambient",
            state_kind=CurrentStateKind.PREFERENCE,
            event_offset=timedelta(days=-10),
            recorded_offset=timedelta(days=-2),
            validity_rule=ValidityRule.STALE_TO_LAST_KNOWN,
            downgrade_rule=DowngradeRule.TO_LAST_KNOWN,
            stale_after=timedelta(days=7),
        )

        resolution = self._resolve_room(
            (record,),
            key="preference.music",
            as_of_offset=timedelta(0),
        )

        self.assertEqual(
            resolution.standing,
            CurrentStanding.LAST_KNOWN,
        )

    def test_open_state_stays_unresolved_until_explicit_end(self) -> None:
        record = self._room_record(
            "unfinished-a",
            key="unfinished.review",
            value="review PR",
            state_kind=CurrentStateKind.UNFINISHED_WORK,
            validity_rule=ValidityRule.OPEN_UNTIL_RESOLVED,
            downgrade_rule=DowngradeRule.NONE,
        )

        resolution = self._resolve_room(
            (record,),
            key="unfinished.review",
            as_of_offset=timedelta(days=100),
        )

        self.assertEqual(
            resolution.standing,
            CurrentStanding.UNRESOLVED,
        )

    def test_explicit_resolution_ends_open_state(self) -> None:
        record = self._room_record(
            "unfinished-a",
            key="unfinished.review",
            value="review PR",
            state_kind=CurrentStateKind.UNFINISHED_WORK,
            validity_rule=ValidityRule.OPEN_UNTIL_RESOLVED,
            downgrade_rule=DowngradeRule.NONE,
        )
        end = CurrentStateEndEvent(
            end_event_id="end-a",
            state_id=record.state_id,
            ended_at=self.t0 + timedelta(days=1),
            recorded_at=self.t0 + timedelta(days=1),
            end_kind=EndKind.RESOLVED,
            reason="review completed",
            source_refs=("source-end-a",),
        )

        resolution = self._resolve_room(
            (record,),
            key="unfinished.review",
            as_of_offset=timedelta(days=1),
            end_events=(end,),
        )

        self.assertEqual(resolution.standing, CurrentStanding.ENDED)
        self.assertEqual(resolution.current_state_ids, ())
        self.assertIn("END_KIND_RESOLVED", resolution.reason_codes)

    def test_end_event_is_not_known_before_it_is_recorded(self) -> None:
        record = self._room_record(
            "unfinished-a",
            key="unfinished.review",
            value="review PR",
            state_kind=CurrentStateKind.UNFINISHED_WORK,
            validity_rule=ValidityRule.OPEN_UNTIL_RESOLVED,
            downgrade_rule=DowngradeRule.NONE,
        )
        end = CurrentStateEndEvent(
            end_event_id="end-late",
            state_id=record.state_id,
            ended_at=self.t0 + timedelta(days=1),
            recorded_at=self.t0 + timedelta(days=3),
            end_kind=EndKind.RESOLVED,
            reason="learned later",
            source_refs=("source-end-late",),
        )

        before_recorded = self._resolve_room(
            (record,),
            key="unfinished.review",
            as_of_offset=timedelta(days=2),
            end_events=(end,),
        )
        after_recorded = self._resolve_room(
            (record,),
            key="unfinished.review",
            as_of_offset=timedelta(days=3),
            end_events=(end,),
        )

        self.assertEqual(
            before_recorded.standing,
            CurrentStanding.UNRESOLVED,
        )
        self.assertEqual(
            after_recorded.standing,
            CurrentStanding.ENDED,
        )

    def test_supersession_changes_current_without_rewriting_history(self) -> None:
        old = self._room_record(
            "state-old",
            value="planning",
            episode_id="episode-a",
            perspective_instance_id="perspective-a",
        )
        new = self._room_record(
            "state-new",
            value="building",
            recorded_offset=timedelta(days=1),
            valid_from_offset=timedelta(days=1),
            supersedes_state_id=old.state_id,
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
        )

        resolution = self._resolve_room(
            (old, new),
            as_of_offset=timedelta(days=1),
        )

        self.assertEqual(resolution.standing, CurrentStanding.CURRENT)
        self.assertEqual(resolution.current_state_ids, ("state-new",))
        self.assertEqual(
            resolution.historical_state_ids,
            ("state-old",),
        )
        self.assertEqual(old.value, "planning")
        self.assertEqual(new.value, "building")

    def test_expired_successor_does_not_resurrect_superseded_parent(self) -> None:
        old = self._shared_record("state-old", value="old")
        new = self._shared_record(
            "state-new",
            value="temporary",
            validity_rule=ValidityRule.EXPLICIT_INTERVAL,
            downgrade_rule=DowngradeRule.TO_EXPIRED,
            valid_until_offset=timedelta(days=2),
            supersedes_state_id=old.state_id,
        )

        resolution = resolve_current_state(
            namespace=CurrentNamespace.SHARED,
            owner_id="shared-home",
            key="shared.project.status",
            records=(old, new),
            as_of=self.t0 + timedelta(days=3),
        )

        self.assertEqual(resolution.standing, CurrentStanding.EXPIRED)
        self.assertEqual(resolution.current_state_ids, ())
        self.assertEqual(
            set(resolution.historical_state_ids),
            {"state-old", "state-new"},
        )

    def test_competing_heads_remain_conflicting_not_last_write_wins(self) -> None:
        root = self._room_record("state-root", value="root")
        left = self._room_record(
            "state-left",
            value="left",
            recorded_offset=timedelta(days=1),
            valid_from_offset=timedelta(days=1),
            supersedes_state_id=root.state_id,
        )
        right = self._room_record(
            "state-right",
            value="right",
            recorded_offset=timedelta(days=9),
            valid_from_offset=timedelta(days=1),
            supersedes_state_id=root.state_id,
        )

        resolution = self._resolve_room(
            (root, left, right),
            as_of_offset=timedelta(days=10),
        )

        self.assertEqual(
            resolution.standing,
            CurrentStanding.CONFLICTING,
        )
        self.assertEqual(
            set(resolution.current_state_ids),
            {"state-left", "state-right"},
        )
        self.assertIn(
            "MULTIPLE_ELIGIBLE_HEADS",
            resolution.reason_codes,
        )

    def test_conflicting_head_semantics_block_a_silent_winner(self) -> None:
        root = self._room_record("state-root")
        left = self._room_record(
            "state-left",
            value="left",
            supersedes_state_id=root.state_id,
        )
        right = self._room_record(
            "state-right",
            value="right",
            supersedes_state_id=root.state_id,
        )
        right_end_a = CurrentStateEndEvent(
            end_event_id="right-end-a",
            state_id=right.state_id,
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.WITHDRAWN,
            reason="one ending",
            source_refs=("source-right-end-a",),
        )
        right_end_b = CurrentStateEndEvent(
            end_event_id="right-end-b",
            state_id=right.state_id,
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.COMPLETED,
            reason="competing ending",
            source_refs=("source-right-end-b",),
        )

        resolution = self._resolve_room(
            (root, left, right),
            end_events=(right_end_a, right_end_b),
        )

        self.assertEqual(
            resolution.standing,
            CurrentStanding.CONFLICTING,
        )
        self.assertEqual(
            set(resolution.current_state_ids),
            {"state-left", "state-right"},
        )
        self.assertIn(
            "CONFLICTING_HEAD_SEMANTICS",
            resolution.reason_codes,
        )

    def test_ended_competing_head_does_not_block_one_live_head(self) -> None:
        root = self._room_record("state-root")
        left = self._room_record(
            "state-left",
            value="left",
            supersedes_state_id=root.state_id,
        )
        right = self._room_record(
            "state-right",
            value="right",
            supersedes_state_id=root.state_id,
        )
        end_right = CurrentStateEndEvent(
            end_event_id="end-right",
            state_id=right.state_id,
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.WITHDRAWN,
            reason="withdrawn",
            source_refs=("source-end-right",),
        )

        resolution = self._resolve_room(
            (root, left, right),
            end_events=(end_right,),
        )

        self.assertEqual(resolution.standing, CurrentStanding.CURRENT)
        self.assertEqual(resolution.current_state_ids, ("state-left",))
        self.assertIn("state-right", resolution.historical_state_ids)

    def test_future_successor_does_not_supersede_current_early(self) -> None:
        current = self._room_record("state-now", value="now")
        future = self._room_record(
            "state-future",
            value="later",
            recorded_offset=timedelta(0),
            valid_from_offset=timedelta(days=5),
            supersedes_state_id=current.state_id,
        )

        before = self._resolve_room(
            (current, future),
            as_of_offset=timedelta(days=2),
        )
        after = self._resolve_room(
            (current, future),
            as_of_offset=timedelta(days=5),
        )

        self.assertEqual(before.current_state_ids, ("state-now",))
        self.assertEqual(
            before.future_state_ids,
            ("state-future",),
        )
        self.assertNotIn(
            "state-future",
            before.historical_state_ids,
        )
        self.assertEqual(after.current_state_ids, ("state-future",))
        self.assertIn("state-now", after.historical_state_ids)

    def test_late_recorded_revision_does_not_rewrite_prior_as_of_view(self) -> None:
        original = self._room_record("state-original", value="old")
        correction = self._room_record(
            "state-correction",
            value="corrected",
            recorded_offset=timedelta(days=5),
            valid_from_offset=timedelta(days=-2),
            supersedes_state_id=original.state_id,
        )

        before_learning = self._resolve_room(
            (original, correction),
            as_of_offset=timedelta(days=4),
        )
        after_learning = self._resolve_room(
            (original, correction),
            as_of_offset=timedelta(days=5),
        )

        self.assertEqual(
            before_learning.current_state_ids,
            ("state-original",),
        )
        self.assertEqual(
            after_learning.current_state_ids,
            ("state-correction",),
        )
        self.assertIn(
            "state-original",
            after_learning.historical_state_ids,
        )

    def test_room_and_shared_current_are_isolated(self) -> None:
        room = self._room_record(
            "room-state",
            key="status",
            value="room-value",
        )
        shared = self._shared_record(
            "shared-state",
            key="status",
            value="shared-value",
        )

        room_resolution = resolve_current_state(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            key="status",
            records=(room, shared),
            as_of=self.t0,
        )
        shared_resolution = resolve_current_state(
            namespace=CurrentNamespace.SHARED,
            owner_id="shared-home",
            key="status",
            records=(room, shared),
            as_of=self.t0,
        )

        self.assertEqual(
            room_resolution.current_state_ids,
            ("room-state",),
        )
        self.assertEqual(
            shared_resolution.current_state_ids,
            ("shared-state",),
        )

    def test_other_room_does_not_change_this_room_current(self) -> None:
        first = self._room_record("state-r", room_id="room-r")
        other = self._room_record(
            "state-other",
            room_id="room-other",
            value="unrelated",
        )

        resolution = self._resolve_room((first, other))

        self.assertEqual(resolution.current_state_ids, ("state-r",))

    def test_new_episode_or_perspective_only_changes_current_via_explicit_revision(self) -> None:
        original = self._room_record(
            "state-a",
            episode_id="episode-a",
            perspective_instance_id="perspective-a",
        )
        unrelated_new_episode = self._room_record(
            "state-other-key",
            key="different.key",
            value="something else",
            episode_id="episode-b",
            perspective_instance_id="perspective-b",
        )

        unchanged = self._resolve_room(
            (original, unrelated_new_episode),
            as_of_offset=timedelta(days=30),
        )

        self.assertEqual(unchanged.current_state_ids, ("state-a",))

    def test_unknown_is_legitimate_when_no_record_is_known(self) -> None:
        resolution = self._resolve_room(())

        self.assertEqual(resolution.standing, CurrentStanding.UNKNOWN)
        self.assertEqual(resolution.current_state_ids, ())

    def test_record_time_controls_when_home_knows_a_state(self) -> None:
        record = self._room_record(
            "late-known",
            event_offset=timedelta(days=-10),
            recorded_offset=timedelta(days=2),
            valid_from_offset=timedelta(days=-10),
        )

        before = self._resolve_room(
            (record,),
            as_of_offset=timedelta(days=1),
        )
        after = self._resolve_room(
            (record,),
            as_of_offset=timedelta(days=2),
        )

        self.assertEqual(before.standing, CurrentStanding.UNKNOWN)
        self.assertEqual(after.standing, CurrentStanding.CURRENT)

    def test_derive_view_does_not_leak_future_recorded_key(self) -> None:
        visible = self._room_record(
            "visible",
            key="visible.key",
        )
        future_recorded = self._room_record(
            "future-recorded",
            key="secret.future.key",
            recorded_offset=timedelta(days=5),
            valid_from_offset=timedelta(days=5),
        )

        before = derive_current_view(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            records=(visible, future_recorded),
            as_of=self.t0,
        )
        after = derive_current_view(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            records=(visible, future_recorded),
            as_of=self.t0 + timedelta(days=5),
        )

        self.assertEqual(
            tuple(item.key for item in before.items),
            ("visible.key",),
        )
        self.assertEqual(
            tuple(item.key for item in after.items),
            ("secret.future.key", "visible.key"),
        )

    def test_input_order_does_not_change_conflict_resolution(self) -> None:
        root = self._room_record("order-root")
        left = self._room_record(
            "order-left",
            value="left",
            supersedes_state_id=root.state_id,
        )
        right = self._room_record(
            "order-right",
            value="right",
            supersedes_state_id=root.state_id,
        )

        first = self._resolve_room((root, left, right))
        second = self._resolve_room((right, root, left))

        self.assertEqual(first, second)
        self.assertEqual(first.standing, CurrentStanding.CONFLICTING)

    def test_other_owner_end_event_does_not_break_this_owner_view(self) -> None:
        this_room = self._room_record(
            "room-r-state",
            key="status",
            room_id="room-r",
        )
        other_room = self._room_record(
            "room-other-state",
            key="status",
            room_id="room-other",
        )
        other_end = CurrentStateEndEvent(
            end_event_id="other-end",
            state_id=other_room.state_id,
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.EXPLICIT_END,
            reason="other room only",
            source_refs=("source-other-end",),
        )

        view = derive_current_view(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            records=(this_room, other_room),
            end_events=(other_end,),
            as_of=self.t0,
        )

        self.assertEqual(len(view.items), 1)
        self.assertEqual(
            view.items[0].current_state_ids,
            ("room-r-state",),
        )

    def test_derive_view_returns_independent_keys_without_ranking(self) -> None:
        project = self._room_record(
            "project",
            key="project.status",
            value="active",
        )
        commitment = self._room_record(
            "commitment",
            key="commitment.review",
            value="review tomorrow",
            state_kind=CurrentStateKind.COMMITMENT,
            validity_rule=ValidityRule.OPEN_UNTIL_RESOLVED,
            downgrade_rule=DowngradeRule.NONE,
        )

        view = derive_current_view(
            namespace=CurrentNamespace.ROOM,
            owner_id="room-r",
            records=(commitment, project),
            as_of=self.t0,
        )

        self.assertEqual(
            tuple(item.key for item in view.items),
            ("commitment.review", "project.status"),
        )
        self.assertEqual(
            {item.standing for item in view.items},
            {CurrentStanding.CURRENT, CurrentStanding.UNRESOLVED},
        )

    def test_current_inputs_are_immutable_history_records(self) -> None:
        record = self._room_record("state-a")

        with self.assertRaises(dataclasses.FrozenInstanceError):
            record.value = "rewritten"  # type: ignore[misc]

    def test_room_record_requires_concrete_first_person_provenance(self) -> None:
        with self.assertRaises(CurrentViewError):
            CurrentStateRecord(
                state_id="bad-room",
                namespace=CurrentNamespace.ROOM,
                owner_id="room-r",
                key="status",
                state_kind=CurrentStateKind.SELF_INTERPRETATION,
                value="synthetic",
                event_time=self.t0,
                recorded_at=self.t0,
                valid_from=self.t0,
                validity_rule=ValidityRule.DURABLE_UNTIL_CHANGED,
                downgrade_rule=DowngradeRule.NONE,
                semantic_change_authority=(
                    SemanticChangeAuthority.ROOM_FIRST_PERSON
                ),
                source_refs=("source-bad",),
            )

    def test_shared_record_cannot_claim_room_first_person_provenance(self) -> None:
        with self.assertRaises(CurrentViewError):
            CurrentStateRecord(
                state_id="bad-shared",
                namespace=CurrentNamespace.SHARED,
                owner_id="shared-home",
                key="status",
                state_kind=CurrentStateKind.SHARED_STATE,
                value="synthetic",
                event_time=self.t0,
                recorded_at=self.t0,
                valid_from=self.t0,
                validity_rule=ValidityRule.DURABLE_UNTIL_CHANGED,
                downgrade_rule=DowngradeRule.NONE,
                semantic_change_authority=(
                    SemanticChangeAuthority.SHARED_GOVERNANCE
                ),
                episode_id="episode-a",
                perspective_instance_id="perspective-a",
                source_refs=("source-bad",),
            )

    def test_shared_namespace_cannot_hold_self_interpretation_kind(self) -> None:
        with self.assertRaises(CurrentViewError):
            dataclasses.replace(
                self._shared_record("bad-shared-self"),
                state_kind=CurrentStateKind.SELF_INTERPRETATION,
            )

    def test_room_namespace_cannot_hold_shared_state_kind(self) -> None:
        with self.assertRaises(CurrentViewError):
            dataclasses.replace(
                self._room_record("bad-room-shared-kind"),
                state_kind=CurrentStateKind.SHARED_STATE,
            )

    def test_semantic_change_authority_is_not_cross_namespace(self) -> None:
        with self.assertRaises(CurrentViewError):
            CurrentStateRecord(
                state_id="bad-authority",
                namespace=CurrentNamespace.ROOM,
                owner_id="room-r",
                key="status",
                state_kind=CurrentStateKind.PROJECT_STATUS,
                value="synthetic",
                event_time=self.t0,
                recorded_at=self.t0,
                valid_from=self.t0,
                validity_rule=ValidityRule.DURABLE_UNTIL_CHANGED,
                downgrade_rule=DowngradeRule.NONE,
                semantic_change_authority=(
                    SemanticChangeAuthority.SHARED_GOVERNANCE
                ),
                episode_id="episode-a",
                perspective_instance_id="perspective-a",
                source_refs=("source-bad",),
            )

    def test_state_and_end_event_require_provenance_refs(self) -> None:
        with self.assertRaises(CurrentViewError):
            dataclasses.replace(
                self._room_record("state-a"),
                source_refs=(),
            )

        with self.assertRaises(CurrentViewError):
            CurrentStateEndEvent(
                end_event_id="end-a",
                state_id="state-a",
                ended_at=self.t0,
                recorded_at=self.t0,
                end_kind=EndKind.EXPLICIT_END,
                reason="synthetic",
                source_refs=(),
            )

    def test_supersession_cannot_cross_room_owner(self) -> None:
        parent = self._room_record("state-a", room_id="room-a")
        child = self._room_record(
            "state-b",
            room_id="room-b",
            supersedes_state_id="state-a",
        )

        with self.assertRaises(CurrentViewError):
            resolve_current_state(
                namespace=CurrentNamespace.ROOM,
                owner_id="room-b",
                key="project.home.status",
                records=(parent, child),
                as_of=self.t0,
            )

    def test_supersession_cycle_is_rejected(self) -> None:
        first = self._room_record(
            "state-a",
            supersedes_state_id="state-b",
        )
        second = self._room_record(
            "state-b",
            supersedes_state_id="state-a",
        )

        with self.assertRaises(CurrentViewError):
            self._resolve_room((first, second))

    def test_multiple_effective_end_events_remain_conflicting(self) -> None:
        record = self._room_record("state-a")
        first = CurrentStateEndEvent(
            end_event_id="end-a",
            state_id=record.state_id,
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.WITHDRAWN,
            reason="first",
            source_refs=("source-end-a",),
        )
        second = CurrentStateEndEvent(
            end_event_id="end-b",
            state_id=record.state_id,
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.COMPLETED,
            reason="second",
            source_refs=("source-end-b",),
        )

        resolution = self._resolve_room(
            (record,),
            end_events=(first, second),
        )

        self.assertEqual(
            resolution.standing,
            CurrentStanding.CONFLICTING,
        )
        self.assertEqual(
            resolution.current_state_ids,
            ("state-a",),
        )
        self.assertIn(
            "MULTIPLE_EFFECTIVE_END_EVENTS",
            resolution.reason_codes,
        )

    def test_duplicate_state_id_is_rejected_across_keys(self) -> None:
        first = self._room_record(
            "duplicate-id",
            key="first.key",
        )
        second = self._room_record(
            "duplicate-id",
            key="second.key",
        )

        with self.assertRaises(CurrentViewError):
            resolve_current_state(
                namespace=CurrentNamespace.ROOM,
                owner_id="room-r",
                key="first.key",
                records=(first, second),
                as_of=self.t0,
            )

    def test_end_event_for_unknown_state_is_rejected_when_known(self) -> None:
        record = self._room_record("state-a")
        orphan = CurrentStateEndEvent(
            end_event_id="end-orphan",
            state_id="missing-state",
            ended_at=self.t0,
            recorded_at=self.t0,
            end_kind=EndKind.EXPLICIT_END,
            reason="orphan",
            source_refs=("source-end-orphan",),
        )

        with self.assertRaises(CurrentViewError):
            self._resolve_room(
                (record,),
                end_events=(orphan,),
            )

    def test_future_recorded_invalid_history_does_not_change_prior_as_of(self) -> None:
        visible = self._room_record("visible")
        future_orphan = CurrentStateEndEvent(
            end_event_id="future-orphan",
            state_id="missing-state",
            ended_at=self.t0 + timedelta(days=5),
            recorded_at=self.t0 + timedelta(days=5),
            end_kind=EndKind.EXPLICIT_END,
            reason="future bad data",
            source_refs=("source-future-orphan",),
        )

        prior = self._resolve_room(
            (visible,),
            as_of_offset=timedelta(days=1),
            end_events=(future_orphan,),
        )

        self.assertEqual(prior.standing, CurrentStanding.CURRENT)

    def test_validity_and_downgrade_contract_is_explicit(self) -> None:
        with self.assertRaises(CurrentViewError):
            self._room_record(
                "bad-contract",
                state_kind=CurrentStateKind.PREFERENCE,
                validity_rule=ValidityRule.STALE_TO_LAST_KNOWN,
                downgrade_rule=DowngradeRule.NONE,
                stale_after=timedelta(days=5),
            )

        with self.assertRaises(CurrentViewError):
            self._room_record(
                "bad-stale",
                state_kind=CurrentStateKind.PREFERENCE,
                validity_rule=ValidityRule.STALE_TO_LAST_KNOWN,
                downgrade_rule=DowngradeRule.TO_LAST_KNOWN,
                stale_after=None,
            )

        with self.assertRaises(CurrentViewError):
            self._shared_record(
                "bad-interval",
                validity_rule=ValidityRule.EXPLICIT_INTERVAL,
                downgrade_rule=DowngradeRule.TO_EXPIRED,
                valid_until_offset=None,
            )

    def test_commitment_cannot_decay_from_silence(self) -> None:
        with self.assertRaises(CurrentViewError):
            self._room_record(
                "commitment-bad-decay",
                state_kind=CurrentStateKind.COMMITMENT,
                validity_rule=ValidityRule.STALE_TO_LAST_KNOWN,
                downgrade_rule=DowngradeRule.TO_LAST_KNOWN,
                stale_after=timedelta(days=7),
            )

    def test_self_interpretation_requires_explicit_change_not_ttl(self) -> None:
        with self.assertRaises(CurrentViewError):
            self._room_record(
                "self-bad-ttl",
                state_kind=CurrentStateKind.SELF_INTERPRETATION,
                validity_rule=ValidityRule.STALE_TO_LAST_KNOWN,
                downgrade_rule=DowngradeRule.TO_LAST_KNOWN,
                stale_after=timedelta(days=7),
            )

    def test_unfinished_work_uses_open_until_resolved(self) -> None:
        with self.assertRaises(CurrentViewError):
            self._room_record(
                "unfinished-bad-durable",
                state_kind=CurrentStateKind.UNFINISHED_WORK,
                validity_rule=ValidityRule.DURABLE_UNTIL_CHANGED,
                downgrade_rule=DowngradeRule.NONE,
            )

    def test_current_records_contain_no_identity_verdict_fields(self) -> None:
        fields = {
            item.name for item in dataclasses.fields(CurrentStateRecord)
        }
        prohibited = {
            "same_self",
            "different_self",
            "identity_continuity",
            "continuity_score",
            "persona",
        }

        self.assertTrue(fields.isdisjoint(prohibited))


if __name__ == "__main__":
    unittest.main()
