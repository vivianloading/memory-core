from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
TESTS_ROOT = REPO_ROOT / "tests"
for _path in (str(SRC_ROOT), str(TESTS_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import first_wake_lab
import recent_life_wake_lab as lab
from home_memory_core.recent_life import (
    RECENT_LIFE_POLICY_V0_1,
    RECENT_LIFE_POLICY_VERSION,
)


class SyntheticRecentLifeWakeLabTests(
    unittest.TestCase
):
    def _prepare(self):
        fixture = lab.SyntheticRecentLifeWakeFixture()
        fixture.__enter__()
        self.addCleanup(
            fixture.__exit__,
            None,
            None,
            None,
        )
        return fixture, fixture.prepare()

    def _payload(self, prepared):
        return json.loads(
            prepared.constructed.request.wake_context.payload_json
        )

    def _layer(self, payload, name):
        matches = [
            layer
            for layer in payload["presentation"]["layers"]
            if layer["layer"] == name
        ]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_operational_path_uses_canonical_recent_life_policy(
        self,
    ) -> None:
        fixture, _ = self._prepare()

        self.assertIs(
            fixture.issuer._recent_life_policy,
            RECENT_LIFE_POLICY_V0_1,
        )
        self.assertIs(
            fixture.handoff._wake_issuance_authority,
            fixture.issuer,
        )
        self.assertIs(
            fixture.model_input_boundary._local_transport_boundary,
            fixture.handoff.local_transport_boundary,
        )

    def test_exact_user_turn_and_v02_presentation_survive_preparation(
        self,
    ) -> None:
        _, prepared = self._prepare()
        payload = self._payload(prepared)

        self.assertEqual(
            prepared.preparation.request.user_turn.value.text,
            "你醒了吗？你知道这里是什么地方吗？",
        )
        self.assertEqual(
            payload["presentation_version"],
            "wake-presentation-v0.2",
        )
        self.assertEqual(
            payload["presentation"]["presentation_version"],
            "wake-presentation-v0.2",
        )
        self.assertEqual(
            payload["presentation"]["as_of"],
            lab.FIXED_AS_OF.isoformat(
                timespec="microseconds"
            ),
        )
        self.assertEqual(
            payload["presentation"]["episode_id"],
            first_wake_lab.FIRST_WAKE_EPISODE_ID,
        )
        self.assertEqual(
            payload["presentation"][
                "perspective_instance_id"
            ],
            first_wake_lab.FIRST_WAKE_PERSPECTIVE_ID,
        )

    def test_recent_life_is_ready_with_exact_r3_r2_r1_order(
        self,
    ) -> None:
        _, prepared = self._prepare()
        layer = self._layer(
            self._payload(prepared),
            "recent_life",
        )

        self.assertEqual(
            layer["availability"],
            "ready",
        )
        self.assertEqual(
            layer["reason_codes"],
            [],
        )
        self.assertEqual(
            tuple(
                block["state_id"]
                for block in layer["blocks"]
            ),
            lab.EXPECTED_RECENT_ORDER,
        )
        self.assertEqual(
            len(layer["blocks"]),
            3,
        )

    def test_baseline_room_current_does_not_leak_into_recent_life(
        self,
    ) -> None:
        _, prepared = self._prepare()
        payload = self._payload(prepared)
        recent = self._layer(
            payload,
            "recent_life",
        )
        room_now = self._layer(
            payload,
            "room_now",
        )

        recent_ids = {
            block["state_id"]
            for block in recent["blocks"]
        }
        baseline_ids = {
            "state-home-founding",
            "state-lantern-project",
            "state-blue-cup",
            "state-lantern-placement",
        }
        self.assertTrue(
            recent_ids.isdisjoint(baseline_ids)
        )
        self.assertEqual(
            recent_ids,
            set(lab.EXPECTED_RECENT_ORDER),
        )

        room_keys = {
            block["key"]
            for block in room_now["blocks"]
        }
        self.assertTrue(
            {
                "home.founding",
                "project.lantern_atlas",
                "preference.blue_cup",
                "unfinished.lantern_placement",
            }.issubset(room_keys)
        )

    def test_recent_life_exact_content_time_and_provenance(
        self,
    ) -> None:
        _, prepared = self._prepare()
        layer = self._layer(
            self._payload(prepared),
            "recent_life",
        )
        expected = {
            spec["state_id"]: spec
            for spec in lab.RECENT_LIFE_SPECS
        }

        for block in layer["blocks"]:
            spec = expected[block["state_id"]]
            expected_time = (
                spec["event_time"].isoformat(
                    timespec="microseconds"
                )
            )
            self.assertEqual(
                block["summary"],
                spec["value"],
            )
            self.assertEqual(
                block["occurred_at"],
                expected_time,
            )
            self.assertEqual(
                block["recorded_at"],
                expected_time,
            )
            self.assertEqual(
                block["episode_id"],
                first_wake_lab.PREVIOUS_EPISODE_ID,
            )
            self.assertEqual(
                block["perspective_instance_id"],
                first_wake_lab.PREVIOUS_PERSPECTIVE_ID,
            )
            self.assertEqual(
                block["room_attachment_event_id"],
                "route-before-wake",
            )
            self.assertEqual(
                block["projection_kind"],
                "room_current_state_assertion",
            )
            self.assertEqual(
                block["selection_policy_version"],
                RECENT_LIFE_POLICY_VERSION,
            )
            self.assertIsNone(
                block["supersedes_state_id"]
            )

            evidence = block["evidence"]
            self.assertEqual(len(evidence), 1)
            self.assertEqual(
                block["source_refs"],
                [evidence[0]["source_id"]],
            )
            self.assertEqual(
                evidence[0]["source_sha256"],
                sha256(
                    spec["value"].encode("utf-8")
                ).hexdigest(),
            )
            self.assertEqual(
                evidence[0]["start_char"],
                0,
            )
            self.assertEqual(
                evidence[0]["end_char"],
                len(spec["value"]),
            )

    def test_recent_life_keeps_describe_only_none_authority_boundary(
        self,
    ) -> None:
        _, prepared = self._prepare()
        payload = self._payload(prepared)
        layer = self._layer(
            payload,
            "recent_life",
        )

        for field in lab._AUTHORITY_FIELDS:
            self.assertEqual(
                payload[field],
                "none",
            )

        for block in layer["blocks"]:
            policy = block["policy"]
            self.assertEqual(
                policy["privacy_scope"],
                {
                    "kind": "room",
                    "scope_id": first_wake_lab.ROOM_ID,
                },
            )
            self.assertEqual(
                policy["temporal_policy"],
                "at_issuance_cut",
            )
            self.assertEqual(
                policy["attribution_policy"],
                "explicit_episode_perspective",
            )
            self.assertEqual(
                policy["pronoun_policy"],
                "no_current_first_person",
            )
            self.assertEqual(
                policy["authority_ceiling"],
                "describe_only",
            )
            for field in lab._AUTHORITY_FIELDS:
                self.assertEqual(
                    policy["use_boundary"][field],
                    "none",
                )

    def test_prepare_only_evidence_freezes_issue_103_and_stop_line(
        self,
    ) -> None:
        evidence = lab.run_recent_life_wake_lab(
            execute=False,
        )

        self.assertFalse(
            evidence["execution_performed"]
        )
        self.assertEqual(
            evidence["kind"],
            lab.RECENT_LIFE_WAKE_EVIDENCE_KIND,
        )
        self.assertEqual(
            evidence["lab_version"],
            lab.RECENT_LIFE_WAKE_LAB_VERSION,
        )
        self.assertEqual(
            evidence["base_main_sha"],
            lab.RECENT_LIFE_WAKE_BASE_MAIN_SHA,
        )
        self.assertEqual(
            evidence["canonical_lab_issue"],
            103,
        )
        self.assertEqual(
            evidence["fixture"][
                "baseline_event_time"
            ],
            lab.BASELINE_EVENT_TIME.isoformat(),
        )
        self.assertEqual(
            evidence["fixture"][
                "recent_life_policy_version"
            ],
            RECENT_LIFE_POLICY_VERSION,
        )
        self.assertEqual(
            evidence["recent_life_presentation"][
                "availability"
            ],
            "ready",
        )
        self.assertEqual(
            tuple(
                block["state_id"]
                for block in evidence[
                    "recent_life_presentation"
                ]["blocks"]
            ),
            lab.EXPECTED_RECENT_ORDER,
        )
        self.assertEqual(
            set(evidence["stop_line"].values()),
            {False},
        )


if __name__ == "__main__":
    unittest.main()
