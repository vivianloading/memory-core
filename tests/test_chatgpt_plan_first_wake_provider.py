import json
import unittest
from unittest.mock import patch

import first_wake_lab
from home_memory_core import openai_chatgpt_plan_adapter as plan_adapter


class ChatGPTPlanFirstWakeProviderTests(unittest.TestCase):
    def test_chatgpt_plan_provider_preserves_three_home_channels(
        self,
    ) -> None:
        raw = json.dumps(
            {
                "id": "resp_chatgpt_plan_first_wake_test",
                "model": "test-chatgpt-plan-model",
                "status": "completed",
                "error": None,
                "incomplete_details": None,
                "output": [
                    {
                        "type": "message",
                        "id": "msg_chatgpt_plan_first_wake_test",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "I can see this specific synthetic HOME "
                                    "without claiming its prior identity."
                                ),
                                "annotations": [],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )

        synthetic_token = "SYNTHETIC-CHATGPT-PLAN-ACCESS-TOKEN"
        with patch.object(
            first_wake_lab.OpenAIChatGPTPlanResponsesAdapter,
            "_post_once",
            return_value=(200, raw),
        ) as post:
            evidence = first_wake_lab.run_first_wake_lab(
                execute=True,
                model_id="test-chatgpt-plan-model",
                access_token=synthetic_token,
                provider=first_wake_lab.OPENAI_CHATGPT_PLAN_PROVIDER,
            )

        self.assertEqual(post.call_count, 1)
        self.assertTrue(evidence["execution_performed"])
        self.assertTrue(evidence["db_unchanged_during_model_run"])
        self.assertTrue(evidence["no_home_state_write_observed"])

        mapping = evidence["provider_mapping"]
        self.assertEqual(
            mapping["provider"],
            "openai-chatgpt-plan-responses",
        )
        self.assertEqual(
            [
                (
                    item["home_channel"],
                    item["provider_role"],
                    item["provider_input_index"],
                )
                for item in mapping["channel_evidence"]
            ],
            [
                ("home_policy", "developer", 0),
                ("wake_data", "user", 1),
                ("current_user_turn", "user", 2),
            ],
        )

        request = json.loads(mapping["request_json"])
        self.assertEqual(
            [item["role"] for item in request["input"]],
            ["developer", "user", "user"],
        )
        self.assertEqual(
            request["input"][2]["content"][0]["text"],
            first_wake_lab.FIRST_WAKE_USER_TURN,
        )
        self.assertFalse(request["store"])
        self.assertTrue(request["stream"])
        self.assertEqual(request["tools"], [])
        for unsupported in (
            "background",
            "conversation",
            "max_output_tokens",
            "max_tool_calls",
            "metadata",
            "moderation",
            "multi_agent",
            "prompt",
            "prompt_cache_retention",
            "safety_identifier",
            "temperature",
            "top_logprobs",
            "top_p",
            "truncation",
            "user",
        ):
            self.assertNotIn(unsupported, request)

        output = evidence["model_output"]
        self.assertEqual(output["status"], "completed_text")
        self.assertEqual(
            output["run_receipt"]["provider"],
            "openai-chatgpt-plan-responses",
        )
        self.assertEqual(
            output["run_receipt"]["provider_request_digest"],
            mapping["request_digest"],
        )
        self.assertNotIn(
            synthetic_token,
            json.dumps(
                evidence,
                ensure_ascii=False,
                sort_keys=True,
            ),
        )

    def test_sse_requires_one_terminal_response_and_returns_full_response(
        self,
    ) -> None:
        response = {
            "id": "resp_stream_test",
            "model": "test-model",
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "output": [],
        }
        stream = (
            "event: response.created\n"
            "data: {\"sequence_number\":1,\"type\":\"response.created\", "
            "\"response\":{\"id\":\"resp_stream_test\","
            "\"status\":\"in_progress\"}}\n\n"
            "event: response.completed\n"
            "data: "
            + json.dumps(
                {
                    "type": "response.completed",
                    "response": response,
                    "sequence_number": 2,
                },
                separators=(",", ":"),
            )
            + "\n\n"
            "data: [DONE]\n\n"
        )
        self.assertEqual(
            plan_adapter._terminal_response_from_sse(stream),
            response,
        )

        with self.assertRaises(
            plan_adapter.OpenAIChatGPTPlanAdapterIntegrityError
        ):
            plan_adapter._terminal_response_from_sse(
                "data: {\"type\":\"response.in_progress\","
                "\"response\":{}}\n\n"
            )

    def test_sse_rejects_multiple_terminal_responses(
        self,
    ) -> None:
        terminal = json.dumps(
            {
                "type": "response.completed",
                "sequence_number": 0,
                "response": {
                    "id": "resp_duplicate_terminal",
                    "status": "completed",
                    "output": [],
                },
            },
            separators=(",", ":"),
        )
        with self.assertRaises(
            plan_adapter.OpenAIChatGPTPlanAdapterIntegrityError
        ):
            plan_adapter._terminal_response_from_sse(
                f"data: {terminal}\n\ndata: {terminal}\n\n"
            )


if __name__ == "__main__":
    unittest.main()
