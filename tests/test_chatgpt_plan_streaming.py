"""Synthetic transport fixtures only: no provider calls or credential loading."""
from copy import deepcopy
from hashlib import sha256
import json
import unittest
from unittest.mock import Mock, patch

import first_wake_lab
from home_memory_core import openai_chatgpt_plan_adapter as adapter


TEXT = "Synthetic output: 雨\n  exact spacing\u2028preserved."


def events(refusal=False):
    ptype, field = ("refusal", "refusal") if refusal else ("output_text", "text")
    empty = {"type": ptype, field: ""}
    if not refusal:
        empty["annotations"] = []
    final = {**empty, field: TEXT}
    initial = {"id": "msg_synthetic", "type": "message", "role": "assistant",
               "status": "in_progress", "content": []}
    item = {**initial, "status": "completed", "content": [final]}
    loc = {"item_id": initial["id"], "output_index": 0, "content_index": 0}
    response = {"id": "resp_synthetic", "model": "test-model", "status": "completed",
                "error": None, "incomplete_details": None, "output": [],
                "usage": {"input_tokens": 100, "output_tokens": 171,
                          "output_tokens_details": {"reasoning_tokens": 83}, "total_tokens": 271}}
    return [
        {"type": "response.created", "response": {**response, "status": "in_progress"}},
        {"type": "response.output_item.added", "output_index": 0, "item": initial},
        {"type": "response.content_part.added", **loc, "part": empty},
        {"type": f"response.{ptype}.delta", **loc, "delta": TEXT[:10]},
        {"type": f"response.{ptype}.delta", **loc, "delta": TEXT[10:]},
        {"type": f"response.{ptype}.done", **loc, field: TEXT},
        {"type": "response.content_part.done", **loc, "part": final},
        {"type": "response.output_item.done", "output_index": 0, "item": item},
        {"type": "response.completed", "response": response},
    ]


def stream(values):
    return "".join("event: " + e["type"] + "\ndata: " + json.dumps(
        {"sequence_number": i, **e}, ensure_ascii=False) + "\n\n" for i, e in enumerate(values))


def run_mocked(raw):
    connection = Mock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = raw.encode("utf-8")
    with patch.object(adapter.http.client, "HTTPSConnection", return_value=connection):
        evidence = first_wake_lab.run_first_wake_lab(
            execute=True, model_id="test-model", access_token="SYNTHETIC-ONLY",
            provider=adapter.OPENAI_CHATGPT_PLAN_PROVIDER)
    assert connection.request.call_count == 1
    connection.close.assert_called_once()
    return evidence


class StreamingTests(unittest.TestCase):
    def test_empty_terminal_output_reconstructs_exact_home_text_and_evidence(self):
        values = events()
        raw = stream(values)
        evidence = run_mocked(raw)
        output = evidence["model_output"]
        self.assertEqual(output["status"], "completed_text")
        self.assertEqual(output["output_text"], TEXT)
        normalized = json.loads(output["raw_response_json"])
        captured = normalized["_home_stream_evidence"]
        self.assertEqual(captured["raw_sse"], raw)
        self.assertEqual(captured["raw_sse_sha256"], sha256(raw.encode()).hexdigest())
        self.assertEqual(normalized["usage"]["output_tokens"], 171)
        self.assertEqual(values[-1]["response"]["output"], [])
        self.assertEqual(output["raw_response_digest"], sha256(output["raw_response_json"].encode()).hexdigest())
        self.assertTrue(evidence["db_unchanged_during_model_run"])
        self.assertTrue(evidence["no_home_state_write_observed"])

    def test_streamed_items_require_created_anchor(self):
        for refusal in (False, True):
            for first_sequence in (0, 7):
                for prefix in ("missing", "in_progress", "late_created"):
                    with self.subTest(refusal=refusal, first_sequence=first_sequence,
                                      prefix=prefix):
                        values = events(refusal=refusal)
                        created = values.pop(0)
                        if prefix == "in_progress":
                            values.insert(0, {**created, "type": "response.in_progress"})
                        elif prefix == "late_created":
                            values.insert(1, created)
                        for i, event in enumerate(values, first_sequence):
                            event["sequence_number"] = i
                        raw = stream(values)
                        with self.assertRaisesRegex(
                            adapter.OpenAIChatGPTPlanAdapterIntegrityError,
                            "streamed item requires prior response.created",
                        ):
                            adapter._terminal_response_from_sse(raw)
                        output = run_mocked(raw)["model_output"]
                        self.assertEqual(output["status"], "rejected_response")
                        self.assertIsNone(output["output_text"])
                        self.assertIsNone(output["refusal_text"])
                        captured = json.loads(output["raw_response_json"])["_home_stream_evidence"]
                        self.assertEqual(captured["raw_sse"], raw)
                        self.assertEqual(captured["raw_sse_sha256"], sha256(raw.encode()).hexdigest())
                        self.assertEqual(captured["validation"], "rejected")

    def test_terminal_only_response_needs_no_created_anchor(self):
        for refusal in (False, True):
            with self.subTest(refusal=refusal):
                values = events(refusal=refusal)
                terminal = values[-1]
                terminal["response"]["output"] = [values[-2]["item"]]
                terminal["sequence_number"] = 7
                raw = stream([terminal])
                self.assertEqual(adapter._terminal_response_from_sse(raw), terminal["response"])
                output = run_mocked(raw)["model_output"]
                self.assertEqual(output["refusal_text" if refusal else "output_text"], TEXT)

    def test_refusal(self):
        evidence = run_mocked(stream(events(refusal=True)))
        self.assertEqual(evidence["model_output"]["refusal_text"], TEXT)
        self.assertIsNone(evidence["model_output"]["output_text"])

    def test_repeated_terminal_output_is_checked_not_appended(self):
        values = events()
        values[-1]["response"]["output"] = [deepcopy(values[-2]["item"])]
        result = adapter._terminal_response_from_sse(stream(values))
        self.assertEqual(result, values[-1]["response"])

    def test_reasoning_item_precedes_assistant_without_becoming_text(self):
        values = events()
        initial = {"id": "reason_synthetic", "type": "reasoning", "summary": []}
        for e in values:
            if "output_index" in e:
                e["output_index"] = 1
        values[1:1] = [
            {"type": "response.output_item.added", "output_index": 0, "item": initial},
            {"type": "response.output_item.done", "output_index": 0, "item": initial},
        ]
        output = run_mocked(stream(values))["model_output"]
        self.assertEqual(output["output_text"], TEXT)

    def test_multiple_messages_and_parts_preserve_index_order(self):
        values = events()
        # Add a second part to the first message, then a second message.
        extra = deepcopy(values[2:7])
        for e in extra:
            e["content_index"] = 1
        values[7]["item"]["content"].append(deepcopy(values[6]["part"]))
        values[7:7] = extra
        second = deepcopy(events()[1:8])
        for e in second:
            e["output_index"] = 1
            if "item_id" in e:
                e["item_id"] = "msg_second"
            if "item" in e:
                e["item"]["id"] = "msg_second"
        values[-1:-1] = second
        self.assertEqual(run_mocked(stream(values))["model_output"]["output_text"], TEXT * 3)

    def test_reasoning_summary_is_validated_but_not_assistant_output(self):
        values = events()
        for e in values:
            if "output_index" in e:
                e["output_index"] = 1
        initial = {"id": "reason_synthetic", "type": "reasoning", "summary": []}
        loc = {"item_id": "reason_synthetic", "output_index": 0, "summary_index": 0}
        part = {"type": "summary_text", "text": "Synthetic summary"}
        summary = [
            {"type": "response.output_item.added", "output_index": 0, "item": initial},
            {"type": "response.reasoning_summary_part.added", **loc,
             "part": {"type": "summary_text", "text": ""}},
            {"type": "response.reasoning_summary_text.delta", **loc, "delta": part["text"]},
            {"type": "response.reasoning_summary_text.done", **loc, "text": part["text"]},
            {"type": "response.reasoning_summary_part.done", **loc, "part": part},
            {"type": "response.output_item.done", "output_index": 0,
             "item": {**initial, "summary": [part]}},
        ]
        values[1:1] = summary
        self.assertEqual(run_mocked(stream(values))["model_output"]["output_text"], TEXT)
        values[3]["delta"] = "conflicting summary"
        with self.assertRaises(adapter.OpenAIChatGPTPlanAdapterIntegrityError):
            adapter._terminal_response_from_sse(stream(values))

    def test_failure_and_incomplete_never_promote_partial_stream(self):
        for status in ("failed", "incomplete"):
            with self.subTest(status=status):
                values = events()
                values[-1]["type"] = "response." + status
                values[-1]["response"]["status"] = status
                if status == "failed":
                    values[-1]["response"]["error"] = {"code": "server_error", "message": "synthetic"}
                else:
                    values[-1]["response"]["incomplete_details"] = {"reason": "max_output_tokens"}
                values = values[:4] + values[-1:]
                result = adapter._terminal_response_from_sse(stream(values))
                self.assertEqual(result, values[-1]["response"])
                output = run_mocked(stream(values))["model_output"]
                self.assertNotEqual(output["status"], "completed_text")
                self.assertIsNone(output["output_text"])

    def test_malformed_streams_fail_closed(self):
        mutations = {
            "wrong id": lambda v: v[3].update(item_id="wrong"),
            "bool index": lambda v: v[3].update(content_index=True),
            "unknown index": lambda v: v[3].update(output_index=2),
            "sequence replay": lambda v: v[4].update(sequence_number=3),
            "sequence gap": lambda v: v[4].update(sequence_number=6),
            "missing sequence": lambda v: v[4].update(sequence_number=None),
            "wrong text done": lambda v: v[5].update(text="invented"),
            "wrong part": lambda v: v[6]["part"].update(text="invented"),
            "wrong item": lambda v: v[7]["item"].update(id="other"),
            "wrong terminal": lambda v: v[-1]["response"].update(output=[{"type": "message"}]),
            "wrong response id": lambda v: v[-1]["response"].update(id="other"),
            "status mismatch": lambda v: v[-1]["response"].update(status="incomplete"),
            "duplicate part done": lambda v: v.insert(7, deepcopy(v[6])),
            "duplicate text done": lambda v: v.insert(6, deepcopy(v[5])),
            "duplicate item": lambda v: v.insert(2, deepcopy(v[1])),
            "missing item done": lambda v: v.pop(7),
            "missing part done": lambda v: v.pop(6),
            "missing text done": lambda v: v.pop(5),
            "missing delta": lambda v: v.pop(4),
            "missing terminal": lambda v: v.pop(),
            "late delta": lambda v: v.append(deepcopy(v[3])),
            "duplicate terminal": lambda v: v.append(deepcopy(v[-1])),
            "unknown event": lambda v: v[3].update(type="response.unknown"),
            "wrong role": lambda v: v[1]["item"].update(role="user"),
            "initial text": lambda v: v[2]["part"].update(text="hidden"),
            "error event": lambda v: v.insert(4, {"type": "error", "message": "synthetic"}),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                values = deepcopy(events())
                mutate(values)
                with self.assertRaises(adapter.OpenAIChatGPTPlanAdapterIntegrityError):
                    adapter._terminal_response_from_sse(stream(values))

    def test_sse_framing_and_json(self):
        raw = stream(events())
        for bad in (raw.rstrip(), raw.replace("event: response.created", "event: wrong", 1),
                    "data: [DONE]\n\n" + raw, raw + "data: [DONE]\n\ndata: [DONE]\n\n",
                    raw.replace('"sequence_number": 0', '"sequence_number": 0, "sequence_number": 0', 1),
                    raw.replace('"sequence_number": 0', '"sequence_number": NaN', 1)):
            with self.subTest(raw=bad[:80]):
                with self.assertRaises(adapter.OpenAIChatGPTPlanAdapterIntegrityError):
                    adapter._terminal_response_from_sse(bad)
        self.assertEqual(adapter._terminal_response_from_sse(raw),
                         adapter._terminal_response_from_sse(raw.replace("\n", "\r\n") + "data: [DONE]\r\n\r\n"))

    def test_invalid_stream_retains_raw_evidence_in_rejected_artifact(self):
        raw = stream(events()[:-1])
        output = run_mocked(raw)["model_output"]
        self.assertEqual(output["status"], "rejected_response")
        self.assertIsNone(output["output_text"])
        captured = json.loads(output["raw_response_json"])["_home_stream_evidence"]
        self.assertEqual(captured["validation"], "rejected")
        self.assertEqual(captured["raw_sse"], raw)


if __name__ == "__main__":
    unittest.main()
