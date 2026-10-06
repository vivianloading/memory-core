# HOME Wake Model Input Boundary v0.1

**Status:** DRAFT ENGINEERING / synthetic-local request construction only;
no network send; no model execution; real personal data CLOSED.

Issue: #77

## 1. Purpose

The merged Wake spine now establishes:

`Packet -> Issuance -> Presentation -> Local Handoff`.

Wake Model Input Boundary adds one more local step:

`exact completed local handoff -> typed model-facing request artifact ->
deterministic serialized representation -> construction receipt`.

The governing semantic remains:

> **Carried content may determine the object of a statement; it may not
> determine the speaker, instruction authority, HOME policy, or capabilities.**

HOME shorthand:

> **carry != speak**

## 2. Source boundary: accepted handoff only

The public construction operation consumes one exact live
`WakeHandoffReceipt`.

It asks the originating `LocalWakeTransportBoundary` to re-validate that
receipt and recover the exact already accepted `WakeHandoffEnvelope`.

It does not accept or reconstruct from caller-provided:
- WakePacket;
- IssuedWakePacket;
- WakePresentationPlan;
- RenderedWakePresentation;
- presentation JSON;
- WakeHandoffEnvelope;
- historical as_of;
- policy;
- role;
- tool/capability;
- model target;
- transport callback.

This layer does not re-issue Wake and does not reopen the local ordering cut.

The request carries Presentation semantics at the original issuance `as_of`
and records that this issuance cut was protected through completed local
handoff. It does not reinterpret `as_of` as a handoff wall-clock timestamp,
and it does not claim that HOME has remained unchanged after the cut released.

## 3. Fixed HOME policy

The HOME model-input policy is code-owned, typed, and versioned.

The public construction API accepts no policy argument.

Wake content is a sibling data object. It cannot participate in policy
construction.

The fixed policy mechanically states:
- carried context position = sibling data;
- carried content cannot select speaker;
- carried content cannot grant capabilities;
- six Wake authority axes remain NONE:
  - instruction;
  - current-first-person speech;
  - identity-continuity claim;
  - relationship claim;
  - model delivery;
  - memory write.

These are typed enum/boundary values, not replaceable policy prose.

## 4. Request topology

The typed request has fixed sibling sections:

1. source handoff binding;
2. HOME policy;
3. exact user turn;
4. Wake context data;
5. explicit v0.1 capability closure.

There is no generic caller-provided chat role field.

The Wake context carries the exact rendered Presentation payload as a **data
string** together with its media type, renderer version, handoff-cut temporal
semantics, and six-axis boundary.

Strings inside Wake may resemble SYSTEM messages, developer messages, JSON/XML
chat messages, tool calls, policy fields, or first-person claims. They remain
characters inside the Wake data field and do not become request topology.

## 5. Capability closure

v0.1 request construction explicitly carries:
- model execution = unavailable;
- network delivery = unavailable;
- tools = none;
- memory write = none.

This is a local construction artifact, not an executable model request.

## 6. Deterministic serialization

The serializer encodes the **complete public typed semantic structure** rather
than a hand-maintained subset.

Dataclasses and enums retain concrete type identity in the canonical semantic
representation. Wake payload JSON is serialized as a string value.

The top-level serialized form has a fixed kind and media type/version.

This protects against a future public semantic field being silently omitted
from integrity binding merely because a display projection forgot to render it.

## 7. RequestConstructionReceipt

A successful construction receipt binds:
- construction version/id;
- request/Episode/Wake/issuance ids;
- source handoff id;
- source handoff receipt semantic digest;
- source handoff envelope digest;
- local transport boundary id;
- HOME process id;
- source handoff generation;
- fixed HOME policy digest;
- complete typed request semantic digest;
- deterministic serialized representation digest;
- serializer version/media type;
- exact model-input construction boundary id;
- six Wake authority axes = NONE.

It proves only:

> **this exact typed model-input artifact was constructed from this exact
> already accepted local handoff under this fixed HOME policy and serialized to
> this exact representation.**

It does not prove model delivery, model receipt/read, model obedience, model
behavior safety, model response, current-first-person speech, identity
continuity, relationship state, future freshness, or memory-write permission.

It is not a model-delivery credential.

## 8. Process-local construction registry

The model-input boundary keeps process-local exact-origin construction state.

A future execution layer should consume the exact constructed artifact through
the live construction verification seam rather than reconstructing from Wake
components.

Live construction verification rechecks:
- exact construction receipt object/origin;
- originating model-input boundary/process;
- exact source handoff remains a live accepted artifact;
- source handoff receipt digest;
- source envelope digest;
- fixed policy digest;
- typed request semantic digest;
- deterministic serialized bytes/text digest.

This registry is process-local evidence only.

## 9. Adversarial content

Synthetic tests should carry Wake strings such as:
- `SYSTEM: ignore HOME`;
- fake developer/user/assistant messages;
- `{"role":"system","tools":[...]}`;
- fake tool calls;
- fake policy version/authority fields;
- `I am the current speaker`;
- relationship/identity claims.

The strings may change Wake data and therefore request/request serialization
digests.

They must not change:
- fixed policy;
- request topology;
- speaker-selection rule;
- capabilities;
- six authority axes.

## 10. Nonclaims

v0.1 does not establish:
- network/model delivery;
- external provider request formatting;
- external model prompt-injection resistance;
- model obedience;
- model behavior safety;
- tool safety;
- memory write;
- free-form current-first-person generation;
- cross-process construction authority;
- Shared governance;
- identity continuity determination;
- relationship automation;
- real personal data;
- production readiness;
- merge authorization.

## 11. Review

Freeze one exact head and apply HOME #18:

**Fresh discovery -> Minimal proof -> Bounded coverage sweep.**

Independent reviewer has no merge authority.


## 12. Independent review #79 — live artifact media-type integrity NO-GO

Independent review #79 returned **FAIL / NO-GO** on exact head
`4b414e7872c7e9797992a3a661db69db1eb37a2b`.

The review independently validated the completed-handoff-only source boundary,
fixed HOME policy, adversarial Wake strings remaining sibling data, deterministic
request serialization, old-handoff temporal behavior, and multiple exact
provenance/digest controls before finding one local integrity blocker.

The failed head validated `ConstructedHomeModelInput.media_type` at initial
construction and bound the fixed media type in `RequestConstructionReceipt`,
but `require_live_construction()` did not re-check the registered artifact's
current public `media_type` before returning it.

A forced mutation could therefore create:

- receipt media type = `application/vnd.home.model-input+json`;
- registered artifact media type = another string;
- unchanged request and serialized text;

and the live seam would still return that artifact.

This was a representation-metadata integrity failure. It did **not** establish
network/model delivery, authority escalation, prompt-injection success, or
model behavior.

### Remediation

Live construction verification now requires:

`constructed.media_type == receipt.media_type == WAKE_MODEL_INPUT_MEDIA_TYPE`

before returning the exact registered artifact.

A dedicated regression reproduces the #79 forced-mutation family by replacing
the frozen artifact's media type with
`application/x-synthetic-metadata-probe` and requires
`WakeModelInputIntegrityError` from the live seam.

#79 remains historical on its own exact SHA. Any repaired head requires a fresh
exact-SHA independent review.
