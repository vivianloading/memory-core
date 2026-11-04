# ChatGPT-plan Responses stream capture

The adapter previously ignored non-terminal SSE events and returned only the
terminal response object. A completed response with `output=[]` therefore lost
any assistant output delivered earlier in the stream. Token usage cannot recover
text and is never used as evidence that text exists.

The parser follows the documented Responses SSE event shapes:
https://developers.openai.com/api/reference/resources/responses/streaming-events

Supported reconstruction requires output-item added/done events, content-part
added/done events, and output-text or refusal delta/done events. Exact text must
agree at delta, text-done, part-done, and item-done levels. Message IDs, assistant
roles, contiguous output/content indexes, unique item IDs, and contiguous integer
sequence numbers are checked. Before any streamed item, `response.created` must
establish the Response ID, which must match the terminal Response ID. A surviving
stream suffix without that anchor is rejected even if its sequence numbers are
contiguous; `response.in_progress` alone cannot substitute for the anchor.
Repeated text chunks with distinct sequence numbers
are legitimate; replayed sequence numbers are rejected. Multiple messages and
parts preserve index order. Reasoning summary/text parts use their corresponding
part/text events and never become assistant text. Reasoning items with no visible
parts (including encrypted content) may be carried through item snapshots; HOME's
existing reasoning validation still applies.

A nonempty terminal output must exactly match the streamed item snapshots. An
empty terminal output may use the validated completed items. No text is inferred
from usage, done snapshots without their deltas, or partial streams. Existing
terminal-only responses remain supported and pass through HOME's normal output
validation. Failed and incomplete terminal responses are returned without
reconstruction, even if a partial message was streaming. Event/status mismatches,
unknown event families, conflicting snapshots, sequence gaps, unclosed successful
streams, and events after termination fail closed. Tools, audio, nonempty
annotations/logprobs, SSE id/retry fields, and undocumented event variants are
intentionally unsupported on this bounded route. This may reject additional
provider variants rather than silently accepting them.

For every decoded successful-HTTP stream, the serialized response passed to HOME
contains `_home_stream_evidence` with a version, the exact decoded `raw_sse`, its
SHA-256 over UTF-8, and validation outcome. The original terminal object (including
its empty output) remains verbatim inside that SSE. The top-level output is a
**derived validated view**, not a claim that the provider repeated those items in
the terminal event. HOME's `raw_response_json` and its digest cover this entire
adapter envelope. On parser failure, an envelope with the non-provider status
`stream_integrity_error` retains SSE plus the validation reason; the unchanged
HOME boundary rejects it as `rejected_response`. Network/read/UTF-8 failures keep
the existing transport-error behavior; this change cannot preserve bytes that
were not successfully read and decoded.

The first failed Synthetic Recent Life Wake remains historical evidence of a
transport/evidence-capture failure, not a behavioral model result. This change
neither reads nor modifies that run, reconstructs its lost text, nor authorizes
another Wake. Regression fixtures are synthetic and all HTTP is mocked. HOME
policy, Wake, Current, Recent Life, relationship, identity, Entry/Adoption, and
write boundaries are unchanged.

The public Responses schema supports the implemented shapes, but it does not
establish which exact sequence the ChatGPT-plan route emitted in the historical
run. No real provider call was made to resolve that uncertainty.
