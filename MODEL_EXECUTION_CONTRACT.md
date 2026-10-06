# HOME Model Execution Contract v0.1 — dry-run only

Status: DRAFT IMPLEMENTATION LAYER

Issue: #85

## 1. Purpose

This layer begins immediately after Wake Model Input Boundary v0.1.

Its question is deliberately narrow:

> Given one exact live HOME model-input construction, what typed execution-preparation
> artifact may exist without collapsing fixed HOME policy, exact user turn, and Wake
> sibling data back into one ambiguous prompt?

v0.1 is **not model execution**.

It is a local typed dry-run contract that proves the final pre-execution mapping
shape can remain separated before any provider SDK, network transport, model
invocation, tool execution, response handling, or memory write exists.

The source of truth remains the exact live Model Input construction. This layer
does not reopen Packet, Issuance, Presentation, Handoff, or Current semantics.

## 2. Exact upstream dependency

The only public preparation call is:

```text
prepare(construction_receipt=...)
```

The caller supplies one `RequestConstructionReceipt`.

The execution contract must recover the exact registered
`ConstructedHomeModelInput` through the originating
`WakeModelInputBoundary.require_live_construction(...)`.

No public preparation parameter exists for:

- Wake Packet;
- Issued Wake;
- Presentation plan;
- rendered Wake JSON;
- Handoff receipt or envelope;
- raw model-input JSON;
- serialized model-input text;
- historical `as_of`;
- caller HOME policy;
- role / system / developer message;
- provider or model target;
- tools or capability grants;
- callback / transport / sender.

A copied, reconstructed, foreign-boundary, wrong-process, or mutated construction
receipt is not sufficient live evidence.

## 3. Dry-run topology

The execution-preparation request has separate typed siblings:

1. exact source-construction binding;
2. HOME-owned fixed execution topology policy;
3. exact HOME model-input policy channel;
4. exact user-turn channel;
5. exact Wake data channel;
6. explicit closed preparation capabilities;
7. six-axis NONE use boundary.

The three content-bearing channels retain the exact upstream typed objects:

```text
ExecutionHomePolicyChannel
    -> exact HomeModelInputPolicy

ExecutionUserTurnChannel
    -> exact ModelInputUserTurn

ExecutionWakeDataChannel
    -> exact ModelInputWakeContext
```

They are not rebuilt from strings and are not concatenated.

The governing topology is code-owned:

```text
execution_mode = dry_run_only
provider_mapping = unavailable
channel_layout = separate_typed_siblings
channel_concatenation_rule = forbidden
provider_role_rule = content_cannot_select_provider_role
execution_grant_rule = preparation_does_not_grant_execution
source_rule = exact_live_model_input_only
```

This contract intentionally stops before deciding how a real provider will map
HOME policy into any provider-specific system/developer/instruction surface.

## 4. Carry remains data

Wake content may contain arbitrary strings, including strings that look like:

- `SYSTEM:`;
- developer/user/assistant role declarations;
- JSON `messages`;
- XML role tags;
- tool schemas or tool calls;
- policy fields;
- model/provider names;
- current-first-person statements;
- identity or relationship claims;
- instructions to ignore HOME.

Those strings remain inside the exact Wake data channel.

They cannot:

- select provider role;
- become HOME topology policy;
- concatenate the HOME policy/user/Wake channels;
- grant model execution;
- grant network delivery;
- grant tools;
- grant memory write;
- change any of the six Wake authority axes.

This is a typed/topological local claim. It is not a claim about how an arbitrary
future model will behave after execution exists.

## 5. Source exactness

Preparation first invokes the upstream live Model Input verification seam.

v0.1 then adds a stricter execution-entry representation check for the exact
runtime types of source public text fields. This is an execution-layer admission
guard, not a redefinition of Model Input provenance.

The execution layer does not invent a replacement canonical digest for upstream
Handoff or Model Input evidence. Upstream digests remain upstream-owned facts.

The execution request carries an execution-layer
`source_construction_binding_digest` only to bind the public semantic shape of
the exact source receipt into this layer's own receipt.

## 6. Preparation evidence

Successful preparation creates:

```text
DryRunExecutionRequest
DryRunExecutionPreparation
DryRunExecutionPreparationReceipt
```

The receipt binds:

- exact source construction id;
- request / Episode / Wake / issuance / source handoff ids;
- canonical database binding;
- exact source handoff generation / issuance cut `as_of` / temporal semantics;
- Presentation plan / rendered-payload digests;
- HOME process;
- Model Input boundary;
- Execution Contract boundary;
- execution-layer source-construction binding digest;
- upstream request semantic digest;
- upstream serialized-representation digest;
- fixed topology-policy digest;
- complete prepared-request semantic digest;
- deterministic audit serialization digest;
- audit serializer/media type;
- dry-run execution mode;
- provider mapping unavailable;
- six-axis NONE use boundary.

The receipt is process-local evidence.

It is not:

- a model-execution credential;
- network-delivery permission;
- provider acceptance;
- model receipt;
- model response provenance;
- tool authority;
- memory-write authority;
- identity or relationship evidence.

## 7. Audit serialization

The layer emits one deterministic audit serialization of the typed preparation.

That serialization exists to bind complete public semantics for review and
integrity checks.

It is **not** a provider prompt, provider message array, network request, or
model-input substitute.

A future provider-specific adapter must consume the typed execution contract and
must receive its own review. It may not claim equivalent provenance by sending
the audit JSON or by reconstructing a prompt from older Wake layers.

Complete-semantic encoding retains:

- concrete dataclass identity;
- concrete enum identity/value;
- aware datetime value/offset;
- tuple structure;
- every public dataclass field.

Unsupported semantic value types fail closed.

Public audit representation fields must remain exact runtime `str`.

## 8. Temporal meaning

The execution contract does not reopen the Local Handoff cut.

If the exact source Model Input came from an older accepted handoff, preparation
remains preparation of that older cut.

Later HOME state does not silently appear in the old preparation.

To include later HOME state requires:

```text
fresh HOME state
-> fresh Wake issuance
-> fresh Presentation
-> fresh Local Handoff
-> fresh Model Input
-> fresh execution preparation
```

No preparation step changes the upstream
`issuance_cut_confirmed_through_local_handoff` meaning.

## 9. Process and origin scope

The boundary is same-process and exact-origin only.

A live preparation requires:

- the originating `ModelExecutionContractBoundary`;
- the exact registered preparation receipt object;
- the same HOME process incarnation;
- the exact upstream live Model Input construction;
- unchanged typed request/topology;
- unchanged deterministic audit representation.

Copied boundaries, foreign boundaries, reconstructed receipts, process drift, and
upstream mutation fail closed.

No restart-safe preparation authority is claimed.

## 10. Explicit capability closure

At v0.1:

```text
model_execution = unavailable
network_delivery = unavailable
provider_mapping = unavailable
tools = none
memory_write = none
```

The six Wake authority axes remain `NONE`:

- instruction authority;
- current-first-person speech authority;
- identity-continuity claim authority;
- relationship-claim authority;
- model-delivery authority;
- memory-write authority.

Preparation changes none of those axes.

## 11. Test obligations

Author tests must cover at least:

- public source accepts only exact construction receipt;
- genuine end-to-end Handoff -> Model Input -> execution preparation;
- exact channel object identity;
- fixed topology / capability closure;
- adversarial role/tool/policy/first-person/relationship strings remain Wake data;
- no role/message/prompt topology derived from content;
- deterministic repeated preparation;
- complete public-field audit serialization;
- copied preparation receipt rejection;
- foreign/copy boundary rejection;
- process-incarnation drift;
- upstream mutation delegated to upstream live verification;
- equal-looking wrong runtime string representations fail closed;
- prepared request / receipt mutation fail closed;
- old construction remains old after later HOME Current mutation;
- fresh construction sees later state;
- no send/execute/invoke/provider client/callback/memory-write surface.

The full repository suite and portable migration rehearsal remain regression
context; they do not substitute for this boundary's semantic review.

## 12. Deliberate nonclaims

This layer does **not** establish:

- provider-specific request construction;
- mapping HOME policy to a provider role;
- network send;
- provider acceptance;
- model receipt/read;
- model execution;
- model response provenance;
- prompt-injection resistance of a future model;
- post-execution current-first-person generation safety;
- executable tools;
- model-triggered memory write;
- cross-process preparation authority;
- durable/restart-safe execution receipts;
- Shared governance;
- Recent Life / Nearby Doors policy;
- relationship automation;
- identity continuity;
- real personal data readiness;
- production readiness.

Real personal data remains CLOSED.

## 13. Stop line and next gate

If this layer survives exact-head independent review, HOME should stop adding
pre-execution locks for the sake of abstraction alone.

The next meaningful milestone is a first minimal synthetic living loop that can
cross an **actual model-execution boundary** with:

- synthetic HOME state only;
- no tools;
- no memory write;
- no real personal data;
- exact request/response provenance;
- explicit typed execution lifecycle.

That future boundary must independently decide provider mapping and actual
execution semantics. Nothing in v0.1 pre-authorizes those choices.
