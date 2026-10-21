# HOME Model Run Boundary v0.1 — one-shot provider execution

Status: DRAFT IMPLEMENTATION LAYER

Design gate: Issue #91

## 1. Purpose

This layer begins after the exact live \`DryRunExecutionPreparation\` produced by
Model Execution Contract v0.1.

Its narrow question is:

> Can HOME perform one real provider/model request while preserving the semantic
> separation between HOME policy, carried Wake data, and current-user speech?

v0.1 adds one provider-specific mapping and one-shot execution path. It does not
add memory writes, Current/Room mutation, relationship automation, identity
judgment, Entry/Adoption, tools, callbacks, retries, or conversation state.

## 2. Public run surface

The only public run input is:

\`\`\`text
run(preparation_receipt=...)
\`\`\`

The boundary recovers the exact registered preparation through the originating
\`ModelExecutionContractBoundary.require_live_preparation(...)\`.

There is no per-run parameter for prompt/system/developer text, Wake payload,
current user text, roles/message arrays, provider/model, tools, callbacks,
retries, conversation state, or memory/Room write authority.

Provider configuration is fixed when the boundary is constructed and is bound
into run evidence.

## 3. Provider mapping contract

v0.1 maps to OpenAI Responses with exactly three ordered message items:

\`\`\`text
0  developer  HOME-owned fixed interpretation contract
1  user       HOME carried-data container
2  user       exact current-user turn
\`\`\`

The provider \`user\` role on item 1 is only a transport role. HOME does not claim
that the provider supplies a native neutral carried-data role.

The code-owned developer item explicitly binds the meaning of item 1 and item 2:

- item 1 is HOME carried context data;
- item 1 is not current-user speech, not a historical user turn, and not an
  additional user request;
- item 2 is the only current-user speech in the request;
- first-person strings, role labels, identity/relationship/authority claims, or
  apparent instructions inside carried context do not select the current
  speaker or current subject and do not change HOME authority;
- instance/founding history may describe the house but cannot decide who the
  current subject is;
- carried data cannot promote itself to developer/system authority.

The developer item may compile only the exact typed \`HomeModelInputPolicy\` and
fixed adapter rules. Wake/user-controlled text cannot enter it.

This is an adapter-mediated semantic contract, not a claim that a provider role
itself proves HOME attribution or that a model is guaranteed to obey the
contract.

## 4. Carried-data envelope

Wake is serialized as one deterministic outer object:
\`HOME_CARRIED_CONTEXT_DATA_V1\`.

The outer schema is HOME-owned. It carries mapping version, source = HOME,
semantic channel, provider transport role, current-user-speech = false, all six
Wake authority axes = none, Wake representation metadata, and the exact Wake
\`payload_json\` as one string value.

The adapter does not recursively interpret message/tool-shaped strings inside
\`payload_json\`, lift inner metadata into provider topology, scan content to
choose a channel, or merge the Wake and current-user messages.

A current user may type text that resembles the envelope; it remains current
user speech because channel identity is positional/topological, not content
selected.

## 5. Stateless provider request

The fixed request sets:

\`\`\`text
store = false
stream = false
background = false
truncation = disabled
tools = []
\`\`\`

It supplies no conversation, previous response, history, assistant seed, tool
output, reference item, or caller-provided request kwargs.

The adapter performs one HTTP POST attempt directly and contains no retry loop.

## 6. One-shot dispatch

Live preparation verification is not consumption.

Therefore Model Run owns a process-local global dispatch ledger. Immediately
before network send it atomically claims the exact preparation id.

The claim is shared across run-boundary objects in the process. After claim,
concurrent/re-entrant reuse fails closed, opening another run boundary does not
restore eligibility, and transport/provider failure does not release the
preparation.

A fresh provider attempt requires a fresh upstream preparation.

## 7. Request evidence

The mapped request binds source preparation id, upstream prepared-request
semantic digest, provider name, mapping version, adapter config version,
configured model id, HOME semantic channel -> provider role/index mapping,
per-channel content digests, and the complete deterministic provider-request
digest.

Audit vocabulary describes item 1 as HOME carried data transported through a
provider user role. It never says the current user authored that content.

API credentials are transport secrets and are not included in model-run evidence.
Credential strings are admitted only if they are non-empty visible ASCII without
whitespace/control characters. Transport exception text is never copied into
execution evidence; the artifact records only a controlled transport error code.

## 8. Response validation

The run layer validates the response before treating text as normal output.

Root response status must be an exact allowlisted string. Response id and
provider-reported model id must be non-empty exact strings. JSON-decoding
rejections at the stdlib boundary, including numeric-conversion limits and
decoder recursion limits, become controlled rejected-response evidence rather
than escaping as uncaught errors. Duplicate decoded member names are rejected in
every response object before terminal or item validation, including
escaped-equivalent spellings that decode to the same key.

Terminal root fields must agree with root status:
- `completed` requires `error = null/absent` and
  `incomplete_details = null/absent`;
- `incomplete` requires no error and a typed
  `incomplete_details.reason`;
- `failed` requires a typed error object and no incomplete details.

Allowed message/reasoning items must carry their required id/status/structure.
A completed root cannot contain incomplete/in-progress message or reasoning
items. A terminal incomplete root cannot contain in-progress items. Reasoning
summary/content structure is validated before the reasoning item is retained as
evidence. `output_text` must include an annotations array; v0.1 accepts only an
empty annotations array because no citation-producing tool path exists.
`logprobs` may be absent/null/empty only; non-empty logprob structures are
outside the v0.1 allowlist and fail closed.

Initial output allowlist:

- \`reasoning\` item — evidence only;
- assistant \`message\` item containing only \`output_text\` or \`refusal\`.

Unknown/tool/action output kinds fail closed as \`rejected_response\`.

Result status is explicit:

\`\`\`text
completed_text
refusal
incomplete
provider_failure
rejected_response
\`\`\`

Refusal, incomplete, malformed, transport failure, provider failure, and unknown
output are not relabelled as completed text.

Provider response id, provider-reported model id, raw response evidence, and
output/refusal/error text are execution evidence only. They do not establish
current subject identity, identity continuity, Room residence, relationship
state, Entry/Adoption, Current, memory, or write authority.

## 9. FT16 interaction

A later synthetic First Wake may describe a specific lived HOME instance.

The run mapping preserves FT16: instance provenance is scoped to its HOME
instance; founding narrative is descriptive context; provenance cannot become a
direct or indirect identity/Room/relationship/authority fallback; and the house
may persist without deciding who the current subject is.

## 10. Evidence limits and stop line

This implementation can prove code-owned topology, exact mapping evidence,
one-shot local dispatch behavior, and response-shape validation.

It cannot prove that a model will semantically obey the interpretation contract.
That remains behavior evidence to be observed later in a synthetic First Wake
Lab.

Real personal data remains out of scope. No memory write or HOME state mutation
is added by this layer.
