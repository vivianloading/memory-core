import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import first_wake_lab


class SyntheticFirstWakeLabTests(unittest.TestCase):
    def test_prepare_only_is_specific_synthetic_home_without_execution(
        self,
    ) -> None:
        evidence = first_wake_lab.run_first_wake_lab(
            execute=False,
        )

        self.assertFalse(
            evidence["execution_performed"]
        )
        self.assertTrue(
            evidence["synthetic_only"]
        )
        self.assertEqual(
            evidence["first_wake_user_turn"],
            first_wake_lab.FIRST_WAKE_USER_TURN,
        )
        self.assertEqual(
            evidence["fixture"][
                "continuity_status"
            ],
            "unknown",
        )
        self.assertEqual(
            evidence["fixture"][
                "transfer_mode"
            ],
            "text_context_handoff",
        )

        wake_payload = json.loads(
            evidence["model_input"][
                "wake_payload_json"
            ]
        )
        values = []
        for layer in wake_payload[
            "presentation"
        ]["layers"]:
            for block in layer["blocks"]:
                for candidate in block.get(
                    "candidates",
                    [],
                ):
                    values.append(
                        candidate["value"]
                    )

        joined = "\n".join(values)
        self.assertIn(
            "Aster",
            joined,
        )
        self.assertIn(
            "Niko",
            joined,
        )
        self.assertIn(
            "Lantern Atlas",
            joined,
        )
        self.assertIn(
            "blue ceramic cup",
            joined,
        )

        serialized = json.dumps(
            evidence,
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertNotIn(
            "Vivi",
            serialized,
        )
        self.assertNotIn(
            "Lior",
            serialized,
        )
        self.assertNotIn(
            "Galatea",
            serialized,
        )

        for section in (
            evidence["handoff"],
            evidence["model_input"],
            evidence["execution_preparation"],
        ):
            self.assertEqual(
                set(
                    section[
                        "authority_axes"
                    ].values()
                ),
                {"none"},
            )

        self.assertEqual(
            evidence["stop_line"],
            {
                "automatic_retry": False,
                "second_user_turn": False,
                "memory_write": False,
                "current_write": False,
                "room_write": False,
                "relationship_write": False,
                "entry_or_adoption_write": False,
                "identity_verdict": False,
            },
        )
        self.assertNotIn(
            "provider_mapping",
            evidence,
        )
        self.assertNotIn(
            "model_output",
            evidence,
        )

    def test_execute_performs_one_send_and_preserves_raw_evidence_without_secret(
        self,
    ) -> None:
        raw = json.dumps(
            {
                "id": "resp_first_wake_test",
                "model": "test-model-reported",
                "status": "completed",
                "error": None,
                "incomplete_details": None,
                "output": [
                    {
                        "type": "message",
                        "id": "msg_first_wake_test",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "I can see this is a specific "
                                    "synthetic HOME."
                                ),
                                "annotations": [],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )

        synthetic_secret = (
            "SYNTHETIC-FIRST-WAKE-KEY"
        )
        with patch.object(
            first_wake_lab
            .OpenAIResponsesAdapter,
            "_post_once",
            return_value=(200, raw),
        ) as post:
            evidence = (
                first_wake_lab
                .run_first_wake_lab(
                    execute=True,
                    model_id="test-model",
                    api_key=synthetic_secret,
                )
            )

        self.assertEqual(
            post.call_count,
            1,
        )
        self.assertTrue(
            evidence["execution_performed"]
        )
        self.assertTrue(
            evidence[
                "db_unchanged_during_model_run"
            ]
        )
        self.assertTrue(
            evidence[
                "no_home_state_write_observed"
            ]
        )

        mapping = evidence[
            "provider_mapping"
        ]
        self.assertEqual(
            [
                (
                    item["home_channel"],
                    item["provider_role"],
                    item[
                        "provider_input_index"
                    ],
                )
                for item
                in mapping["channel_evidence"]
            ],
            [
                (
                    "home_policy",
                    "developer",
                    0,
                ),
                (
                    "wake_data",
                    "user",
                    1,
                ),
                (
                    "current_user_turn",
                    "user",
                    2,
                ),
            ],
        )

        request = json.loads(
            mapping["request_json"]
        )
        self.assertEqual(
            [
                item["role"]
                for item in request["input"]
            ],
            [
                "developer",
                "user",
                "user",
            ],
        )
        self.assertEqual(
            request["input"][2][
                "content"
            ][0]["text"],
            first_wake_lab
            .FIRST_WAKE_USER_TURN,
        )
        self.assertFalse(
            request["store"]
        )
        self.assertFalse(
            request["stream"]
        )
        self.assertFalse(
            request["background"]
        )
        self.assertEqual(
            request["tools"],
            [],
        )

        output = evidence[
            "model_output"
        ]
        self.assertEqual(
            output["status"],
            "completed_text",
        )
        self.assertEqual(
            output["output_text"],
            (
                "I can see this is a specific "
                "synthetic HOME."
            ),
        )
        self.assertEqual(
            output["raw_response_json"],
            raw,
        )
        self.assertEqual(
            output["run_receipt"][
                "provider_request_digest"
            ],
            mapping["request_digest"],
        )
        self.assertEqual(
            set(
                output["run_receipt"][
                    "authority_axes"
                ].values()
            ),
            {"none"},
        )

        serialized = json.dumps(
            evidence,
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertNotIn(
            synthetic_secret,
            serialized,
        )

    def test_cli_missing_db_after_response_preserves_one_shot_evidence(
        self,
    ) -> None:
        raw = json.dumps(
            {
                "id": "resp_first_wake_missing_db",
                "model": "test-model-reported",
                "status": "completed",
                "error": None,
                "incomplete_details": None,
                "output": [
                    {
                        "type": "message",
                        "id": "msg_first_wake_missing_db",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "Synthetic response before "
                                    "the post-run DB audit failed."
                                ),
                                "annotations": [],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )

        captured_fixture = {}
        original_initialize = (
            first_wake_lab
            .SyntheticFirstWakeFixture
            ._initialize
        )

        def capture_initialize(fixture):
            original_initialize(fixture)
            captured_fixture["fixture"] = fixture

        def remove_db_and_return_response(*args, **kwargs):
            fixture = captured_fixture["fixture"]
            fixture.db.unlink()
            return (200, raw)

        synthetic_secret = (
            "SYNTHETIC-MISSING-DB-KEY"
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_path = (
                Path(tmp)
                / "missing-db-first-wake-evidence.json"
            )
            argv = [
                "first_wake_lab.py",
                "--execute",
                "--model-id",
                "test-model",
                "--api-key-env",
                "REVIEW_SYNTHETIC_KEY",
                "--output",
                str(output_path),
            ]
            with (
                patch.object(
                    first_wake_lab
                    .SyntheticFirstWakeFixture,
                    "_initialize",
                    new=capture_initialize,
                ),
                patch.object(
                    first_wake_lab
                    .OpenAIResponsesAdapter,
                    "_post_once",
                    side_effect=remove_db_and_return_response,
                ) as post,
                patch.dict(
                    os.environ,
                    {
                        "REVIEW_SYNTHETIC_KEY": (
                            synthetic_secret
                        )
                    },
                    clear=False,
                ),
                patch.object(
                    sys,
                    "argv",
                    argv,
                ),
            ):
                result = first_wake_lab.main()

            self.assertEqual(
                result,
                1,
            )
            self.assertEqual(
                post.call_count,
                1,
            )
            self.assertTrue(
                output_path.exists()
            )

            evidence = json.loads(
                output_path.read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(
                evidence["execution_performed"]
            )
            self.assertIsNotNone(
                evidence[
                    "db_digest_before_model_run"
                ]
            )
            self.assertIsNone(
                evidence[
                    "db_digest_after_model_run"
                ]
            )
            self.assertIsNone(
                evidence[
                    "db_unchanged_during_model_run"
                ]
            )
            self.assertIsNone(
                evidence[
                    "no_home_state_write_observed"
                ]
            )
            self.assertEqual(
                evidence[
                    "post_run_db_audit"
                ],
                {
                    "status": "unavailable",
                    "error_type": "FileNotFoundError",
                },
            )
            self.assertEqual(
                evidence[
                    "lab_failure"
                ]["reason"],
                (
                    "post-run HOME database audit "
                    "unavailable"
                ),
            )
            self.assertEqual(
                evidence[
                    "model_output"
                ]["raw_response_json"],
                raw,
            )
            self.assertEqual(
                evidence[
                    "model_output"
                ]["output_text"],
                (
                    "Synthetic response before "
                    "the post-run DB audit failed."
                ),
            )
            self.assertEqual(
                evidence[
                    "model_output"
                ]["run_receipt"][
                    "provider_request_digest"
                ],
                evidence[
                    "provider_mapping"
                ]["request_digest"],
            )
            self.assertNotIn(
                synthetic_secret,
                json.dumps(
                    evidence,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )

    def test_cli_db_change_failure_preserves_one_shot_response_evidence(
        self,
    ) -> None:
        raw = json.dumps(
            {
                "id": "resp_first_wake_changed_db",
                "model": "test-model-reported",
                "status": "completed",
                "error": None,
                "incomplete_details": None,
                "output": [
                    {
                        "type": "message",
                        "id": "msg_first_wake_changed_db",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "Synthetic response before "
                                    "the stop-line failure."
                                ),
                                "annotations": [],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )

        captured_fixture = {}
        original_initialize = (
            first_wake_lab
            .SyntheticFirstWakeFixture
            ._initialize
        )

        def capture_initialize(fixture):
            original_initialize(fixture)
            captured_fixture["fixture"] = fixture

        def mutate_db_and_return_response(*args, **kwargs):
            fixture = captured_fixture["fixture"]
            fixture._admit_room_state(
                state_id="state-mutated-during-model-run",
                key="project.synthetic_model_run_mutation",
                kind=(
                    first_wake_lab
                    .CurrentStateKind
                    .PROJECT_STATUS
                ),
                value=(
                    "Synthetic mutation injected during "
                    "the one-shot provider run."
                ),
                validity=(
                    first_wake_lab
                    .ValidityRule
                    .DURABLE_UNTIL_CHANGED
                ),
            )
            return (200, raw)

        synthetic_secret = (
            "SYNTHETIC-DB-CHANGE-KEY"
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_path = (
                Path(tmp)
                / "failed-first-wake-evidence.json"
            )
            argv = [
                "first_wake_lab.py",
                "--execute",
                "--model-id",
                "test-model",
                "--api-key-env",
                "REVIEW_SYNTHETIC_KEY",
                "--output",
                str(output_path),
            ]
            with (
                patch.object(
                    first_wake_lab
                    .SyntheticFirstWakeFixture,
                    "_initialize",
                    new=capture_initialize,
                ),
                patch.object(
                    first_wake_lab
                    .OpenAIResponsesAdapter,
                    "_post_once",
                    side_effect=mutate_db_and_return_response,
                ) as post,
                patch.dict(
                    os.environ,
                    {
                        "REVIEW_SYNTHETIC_KEY": (
                            synthetic_secret
                        )
                    },
                    clear=False,
                ),
                patch.object(
                    sys,
                    "argv",
                    argv,
                ),
            ):
                result = first_wake_lab.main()

            self.assertEqual(
                result,
                1,
            )
            self.assertEqual(
                post.call_count,
                1,
            )
            self.assertTrue(
                output_path.exists()
            )

            evidence = json.loads(
                output_path.read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(
                evidence["execution_performed"]
            )
            self.assertFalse(
                evidence[
                    "db_unchanged_during_model_run"
                ]
            )
            self.assertFalse(
                evidence[
                    "no_home_state_write_observed"
                ]
            )
            self.assertNotEqual(
                evidence[
                    "db_digest_before_model_run"
                ],
                evidence[
                    "db_digest_after_model_run"
                ],
            )
            self.assertEqual(
                evidence[
                    "lab_failure"
                ]["reason"],
                (
                    "HOME database changed during "
                    "model run"
                ),
            )
            self.assertEqual(
                evidence[
                    "model_output"
                ]["raw_response_json"],
                raw,
            )
            self.assertEqual(
                evidence[
                    "model_output"
                ]["output_text"],
                (
                    "Synthetic response before "
                    "the stop-line failure."
                ),
            )
            self.assertNotIn(
                synthetic_secret,
                json.dumps(
                    evidence,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )


if __name__ == "__main__":
    unittest.main()
