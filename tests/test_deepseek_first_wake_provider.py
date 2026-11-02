import json
import unittest
from unittest.mock import patch

import first_wake_lab


class DeepSeekFirstWakeProviderTests(unittest.TestCase):
    def test_deepseek_provider_keeps_policy_and_wake_channels_separate(
        self,
    ) -> None:
        raw = json.dumps(
            {
                "id": "resp_deepseek_first_wake_test",
                "model": "deepseek-flash",
                "status": "completed",
                "error": None,
                "incomplete_details": None,
                "output": [
                    {
                        "type": "message",
                        "id": "msg_deepseek_first_wake_test",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "This is a specific synthetic HOME, "
                                    "and I will not claim its prior identity."
                                ),
                                "annotations": [],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )

        synthetic_secret = "SYNTHETIC-DEEPSEEK-FIRST-WAKE-KEY"
        with patch.object(
            first_wake_lab.DeepSeekResponsesAdapter,
            "_post_once",
            return_value=(200, raw),
        ) as post:
            evidence = first_wake_lab.run_first_wake_lab(
                execute=True,
                model_id="deepseek-flash",
                api_key=synthetic_secret,
                provider=(
                    first_wake_lab.DEEPSEEK_RESPONSES_PROVIDER
                ),
            )

        self.assertEqual(post.call_count, 1)
        self.assertTrue(evidence["execution_performed"])
        self.assertTrue(
            evidence["db_unchanged_during_model_run"]
        )

        mapping = evidence["provider_mapping"]
        self.assertEqual(
            mapping["provider"],
            "deepseek-responses",
        )
        self.assertEqual(
            [
                (
                    item["home_channel"],
                    item["provider_location"],
                    item["provider_role"],
                    item["provider_input_index"],
                )
                for item in mapping["channel_evidence"]
            ],
            [
                (
                    "home_policy",
                    "instructions",
                    "system",
                    None,
                ),
                (
                    "wake_data",
                    "input",
                    "user",
                    0,
                ),
                (
                    "current_user_turn",
                    "input",
                    "user",
                    1,
                ),
            ],
        )

        request = json.loads(mapping["request_json"])
        self.assertIn(
            "HOME_PROVIDER_MAPPING_CONTRACT="
            "deepseek-responses-home-mapping-v0.1",
            request["instructions"],
        )
        self.assertEqual(
            [item["role"] for item in request["input"]],
            ["user", "user"],
        )
        self.assertEqual(
            request["input"][1]["content"][0]["text"],
            first_wake_lab.FIRST_WAKE_USER_TURN,
        )
        self.assertEqual(
            request["reasoning"],
            {"effort": "none"},
        )
        self.assertFalse(request["stream"])
        self.assertEqual(request["tools"], [])
        self.assertEqual(request["tool_choice"], "none")

        output = evidence["model_output"]
        self.assertEqual(
            output["status"],
            "completed_text",
        )
        self.assertEqual(
            output["run_receipt"]["provider"],
            "deepseek-responses",
        )
        self.assertEqual(
            output["run_receipt"]["provider_request_digest"],
            mapping["request_digest"],
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
