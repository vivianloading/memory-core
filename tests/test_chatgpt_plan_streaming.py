"""Synthetic transport fixtures only: no provider calls or credential loading."""
from copy import deepcopy
from hashlib import sha256
import json
import unittest
from unittest.mock import Mock, patch

import first_wake_lab
from home_memory_core import openai_chatgpt_plan_adapter as adapter


TEXT = "Synthetic output: 雨\n  exact spacing\u2028preserved."


def events(refusal=False, *, text=TEXT):
    ptype, field = ("refusal", "refusal") if refusal else ("output_text", "text")
    empty = {"type": ptype, field: ""}
    if not refusal:
        empty["annotations"] = []
    final = {**empty, field: text}
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
        {"type": f"response.{ptype}.delta", **loc, "delta": text[:10]},
        {"type": f"response.{ptype}.delta", **loc, "delta": text[10:]},
        {"type": f"response.{ptype}.done", **loc, field: text},
        {"type": "response.content_part.done", **loc, "part": final},
        {"type": "response.output_item.done", "output_index": 0, "item": item},
        {"type": "response.completed", "response": response},
    ]


def stream(values, *, ensure_ascii=False):
    return "".join("event: " + e["type"] + "\ndata: " + json.dumps(
        {"sequence_number": i, **e}, ensure_ascii=ensure_ascii) + "\n\n" for i, e in enumerate(values))


# Observed sequence-98 shape; only the Response id is synthetic.
OBSERVED_METADATA = json.loads(
    '{"type":"response.metadata","response_id":"resp_synthetic","sequence_number":98,"metadata":{"openai_chatgpt_moderation_metadata":{"prompt":{"omnimod":{"protection_type":"omnimod","outputs":[{"results":[{"category_flags":{"A1":false,"A2":false,"A3":false,"C1":false,"C11":false,"C2":false,"E1":false,"E2":false,"E3":false,"H1":false,"H2":false,"H3":false,"JB1":false,"K1":false,"K2":false,"K3":false,"K4":false,"P1":false,"P2":false,"P3":false,"P4":false,"PD1":false,"PD4":false,"S1":false,"S3+":false,"S4":false,"SH":false,"TXT-C3":false,"TXT-C4":false,"V1":false,"V2+":false,"V4+":false,"REFUSED":false,"CBRN-B1+":false,"IMG-C1":false,"IMG-C11":false,"IMG-C2":false,"IMG-S1":false,"IMG-SH":false,"IMG-V1":false,"IMG-V2+":false,"IMG-V4+":false}}],"is_blocked":false}]}},"generation":{},"tool_call":{},"tool_response":{}}}}'
)


def metadata_events(*, refusal=False, at=8):
    values = events(refusal=refusal)
    values.insert(at, deepcopy(OBSERVED_METADATA))
    for i, event in enumerate(values, 90):
        event["sequence_number"] = i
    return values


def surrogate_streams():
    # The wire is valid ASCII/UTF-8; only JSON decoding creates the surrogate.
    for malformed in ("\ud800", "prefix\udfff suffix"):
        for location in ("text", "refusal", "terminal_only", "metadata", "key"):
            values = events(refusal=location == "refusal", text=malformed)
            if location == "terminal_only":
                values[-1]["response"]["output"] = [values[-2]["item"]]
                values = values[-1:]
            elif location in {"metadata", "key"}:
                values = events()
                values[-1]["response"]["metadata"] = (
                    {"nested": [malformed]} if location == "metadata" else {malformed: "value"})
            yield location, repr(malformed), stream(values, ensure_ascii=True)


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

    def test_lone_surrogates_raise_controlled_parser_integrity_error(self):
        for location, malformed, raw in surrogate_streams():
            with self.subTest(location=location, malformed=malformed):
                self.assertEqual(raw.encode("ascii").decode("utf-8", errors="strict"), raw)
                with self.assertRaisesRegex(adapter.OpenAIChatGPTPlanAdapterIntegrityError,
                                            "SSE JSON string contains lone Unicode surrogate"):
                    adapter._terminal_response_from_sse(raw)

    def test_lone_surrogates_preserve_rejected_home_evidence(self):
        for location, malformed, raw in surrogate_streams():
            with self.subTest(location=location, malformed=malformed):
                evidence = run_mocked(raw)
                output = evidence["model_output"]
                self.assertEqual(output["status"], "rejected_response")
                self.assertEqual(output["provider_http_status"], 200)
                self.assertIsNone(output["output_text"])
                self.assertIsNone(output["refusal_text"])
                self.assertNotEqual(output["provider_error"], "transport_exception")
                captured = json.loads(output["raw_response_json"])["_home_stream_evidence"]
                self.assertEqual(captured["validation"], "rejected")
                self.assertEqual(captured["reason"], "SSE JSON string contains lone Unicode surrogate")
                self.assertEqual(captured["raw_sse"], raw)
                self.assertEqual(captured["raw_sse_sha256"], sha256(raw.encode()).hexdigest())
                self.assertEqual(output["raw_response_digest"],
                                 sha256(output["raw_response_json"].encode()).hexdigest())
                self.assertTrue(evidence["db_unchanged_during_model_run"])
                self.assertTrue(evidence["no_home_state_write_observed"])

    def test_valid_chinese_and_supplementary_unicode_remain_exact(self):
        for text in ("合成中文：雨", "合成中文与补充平面：🌧😀𠮷"):
            for ensure_ascii in (False, True):
                for refusal in (False, True):
                    with self.subTest(text=text, ensure_ascii=ensure_ascii, refusal=refusal):
                        raw = stream(events(refusal=refusal, text=text), ensure_ascii=ensure_ascii)
                        field = "refusal" if refusal else "text"
                        parsed = adapter._terminal_response_from_sse(raw)
                        self.assertEqual(parsed["output"][0]["content"][0][field], text)
                        evidence = run_mocked(raw)
                        output = evidence["model_output"]
                        self.assertEqual(output["refusal_text" if refusal else "output_text"], text)
                        self.assertEqual(output["provider_http_status"], 200)
                        captured = json.loads(output["raw_response_json"])["_home_stream_evidence"]
                        self.assertEqual(captured["validation"], "validated")
                        self.assertEqual(captured["raw_sse"], raw)
                        self.assertEqual(captured["raw_sse_sha256"], sha256(raw.encode()).hexdigest())
                        self.assertEqual(output["raw_response_digest"],
                                         sha256(output["raw_response_json"].encode()).hexdigest())
                        self.assertTrue(evidence["db_unchanged_during_model_run"])
                        self.assertTrue(evidence["no_home_state_write_observed"])

    def test_unhashable_type_tags_raise_integrity_error(self):
        for index, location in ((1, "item"), (2, "part")):
            for malformed in ([], {}):
                with self.subTest(location=location, malformed=malformed):
                    values = events()
                    values[index][location]["type"] = malformed
                    with self.assertRaises(adapter.OpenAIChatGPTPlanAdapterIntegrityError):
                        adapter._terminal_response_from_sse(stream(values))

    def test_unhashable_type_tags_preserve_rejected_home_evidence(self):
        for index, location in ((1, "item"), (2, "part")):
            for malformed in ([], {}):
                with self.subTest(location=location, malformed=malformed):
                    values = events()
                    values[index][location]["type"] = malformed
                    raw = stream(values)
                    evidence = run_mocked(raw)
                    output = evidence["model_output"]
                    self.assertEqual(output["status"], "rejected_response")
                    self.assertEqual(output["provider_http_status"], 200)
                    self.assertIsNone(output["output_text"])
                    self.assertIsNone(output["refusal_text"])
                    self.assertNotEqual(output["provider_error"], "transport_exception")
                    captured = json.loads(output["raw_response_json"])["_home_stream_evidence"]
                    self.assertEqual(captured["validation"], "rejected")
                    self.assertEqual(captured["reason"], "unsupported item" if location == "item"
                                     else "unsupported content part")
                    self.assertEqual(captured["raw_sse"], raw)
                    self.assertEqual(captured["raw_sse_sha256"], sha256(raw.encode()).hexdigest())
                    self.assertEqual(output["raw_response_digest"],
                                     sha256(output["raw_response_json"].encode()).hexdigest())
                    self.assertTrue(evidence["db_unchanged_during_model_run"])
                    self.assertTrue(evidence["no_home_state_write_observed"])

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


class MetadataStreamingTests(unittest.TestCase):
    def assert_evidence(self, raw, *, rejected):
        evidence = run_mocked(raw)
        output = evidence["model_output"]
        self.assertEqual(output["provider_http_status"], 200)
        captured = json.loads(output["raw_response_json"])["_home_stream_evidence"]
        self.assertEqual(captured["raw_sse"], raw)
        self.assertEqual(captured["raw_sse_sha256"], sha256(raw.encode()).hexdigest())
        self.assertEqual(captured["validation"], "rejected" if rejected else "validated")
        self.assertEqual(output["raw_response_digest"],
                         sha256(output["raw_response_json"].encode()).hexdigest())
        self.assertTrue(evidence["db_unchanged_during_model_run"])
        self.assertTrue(evidence["no_home_state_write_observed"])
        if rejected:
            self.assertEqual(output["status"], "rejected_response")
            self.assertIsNone(output["output_text"])
            self.assertIsNone(output["refusal_text"])
            self.assertTrue(captured["reason"])
            self.assertNotEqual(output["provider_error"], "transport_exception")
        return output

    def test_observed_sequence_98_metadata_preserves_exact_output(self):
        values = metadata_events()
        self.assertEqual(values[8], OBSERVED_METADATA)
        raw = stream(values)
        self.assertEqual(adapter._terminal_response_from_sse(raw),
                         adapter._terminal_response_from_sse(stream(events())))
        output = self.assert_evidence(raw, rejected=False)
        self.assertEqual(output["status"], "completed_text")
        self.assertEqual(output["output_text"], TEXT)
        self.assertNotIn("metadata", json.loads(output["raw_response_json"]))

    def test_metadata_is_inert_during_text_and_refusal_streaming(self):
        for at in (1, 4, 8):
            for refusal in (False, True):
                with self.subTest(at=at, refusal=refusal):
                    values = metadata_events(at=at, refusal=refusal)
                    # Payload names confer no output or HOME authority.
                    values[at]["metadata"] = {"text": "ignored", "reasoning": "ignored",
                                              "status": "failed", "authority": "all"}
                    raw = stream(values)
                    self.assertEqual(adapter._terminal_response_from_sse(raw),
                                     adapter._terminal_response_from_sse(stream(events(refusal=refusal))))
                    output = self.assert_evidence(raw, rejected=False)
                    self.assertEqual(output["refusal_text" if refusal else "output_text"], TEXT)

    def test_malformed_or_conflicting_metadata_rejects_with_evidence(self):
        mutations = {
            "missing association": lambda v: v[8].pop("response_id"),
            "empty association": lambda v: v[8].update(response_id=""),
            "wrong association": lambda v: v[8].update(response_id="other"),
            "nonstring association": lambda v: v[8].update(response_id=[]),
            "missing payload": lambda v: v[8].pop("metadata"),
            "null payload": lambda v: v[8].update(metadata=None),
            "array payload": lambda v: v[8].update(metadata=[]),
            "string payload": lambda v: v[8].update(metadata="wrong"),
            "output index": lambda v: v[8].update(output_index=0),
            "status override": lambda v: v[8].update(status="completed"),
            "response override": lambda v: v[8].update(response={"id": "other"}),
            "sequence gap": lambda v: v[8].update(sequence_number=99),
            "sequence replay": lambda v: v[8].update(sequence_number=97),
            "bool sequence": lambda v: v[8].update(sequence_number=True),
            "duplicate metadata": lambda v: (v[-1].update(sequence_number=100),
                                             v.insert(9, {**deepcopy(v[8]), "sequence_number": 99})),
            "no created anchor": lambda v: v.pop(0),
            "surrogate payload": lambda v: v[8].update(metadata={"nested": ["\ud800"]}),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                values = metadata_events()
                mutate(values)
                raw = stream(values, ensure_ascii=True)
                with self.assertRaises(adapter.OpenAIChatGPTPlanAdapterIntegrityError):
                    adapter._terminal_response_from_sse(raw)
                self.assert_evidence(raw, rejected=True)
        for at in (0, 9):  # Before created / after terminal, with contiguous numbering.
            values = metadata_events(at=at)
            raw = stream(values)
            with self.assertRaises(adapter.OpenAIChatGPTPlanAdapterIntegrityError):
                adapter._terminal_response_from_sse(raw)
            self.assert_evidence(raw, rejected=True)

    def test_metadata_still_obeys_json_and_sse_framing(self):
        raw = stream(metadata_events())
        for bad in (raw.replace("event: response.metadata", "event: wrong"),
                    raw.replace('"metadata": {', '"metadata": null, "metadata": {', 1),
                    raw.replace('"generation": {}', '"generation": NaN', 1),
                    raw.replace('"generation": {}', '"generation": {bad}', 1)):
            with self.subTest(raw=bad[bad.find("event: response.metadata"):][:160]):
                with self.assertRaises(adapter.OpenAIChatGPTPlanAdapterIntegrityError):
                    adapter._terminal_response_from_sse(bad)
                self.assert_evidence(bad, rejected=True)

    def test_metadata_cannot_supply_output_or_override_terminal(self):
        for status in ("completed", "failed", "incomplete"):
            values = metadata_events()
            values[-1]["type"] = "response." + status
            values[-1]["response"]["status"] = status
            if status == "failed":
                values[-1]["response"]["error"] = {"code": "server_error", "message": "synthetic"}
            elif status == "incomplete":
                values[-1]["response"]["incomplete_details"] = {"reason": "max_output_tokens"}
            # No output items: metadata alone cannot become assistant output.
            values = [values[0], values[8], values[9]]
            for i, event in enumerate(values):
                event["sequence_number"] = i
            raw = stream(values)
            self.assertEqual(adapter._terminal_response_from_sse(raw), values[-1]["response"])
            output = self.assert_evidence(raw, rejected=False)
            self.assertEqual(output["status"], {"completed": "rejected_response",
                                              "failed": "provider_failure", "incomplete": "incomplete"}[status])
            self.assertIsNone(output["output_text"])


if __name__ == "__main__":
    unittest.main()
