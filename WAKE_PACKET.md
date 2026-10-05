# HOME Wake Packet v0.1 — Typed Orientation Substrate

**Status:** DRAFT SEMANTIC / IMPLEMENTATION LAYER; synthetic/local only; no
renderer; no model delivery; real personal data CLOSED.

Issue: #53

## 1. Purpose

Wake Packet v0.1 is the first typed substrate for carrying HOME state into an
orientation boundary without turning carried material into a new first-person
speaker.

Its five fixed layers are:

`Map -> Shared Now -> Room Now -> Recent Life -> Nearby Doors`

The v0.1 goal is **not** to make all five layers look full. It is to make every
layer mechanically explicit about what HOME can and cannot currently produce.

At the design anchor:

- Map has Living Layer inputs;
- Room Now has Current Resolver v0.1 inputs;
- Shared Now operational Current remains CLOSED;
- Recent Life has no approved typed recency/salience producer;
- Nearby Doors has no approved typed navigation producer.

Therefore CLOSED / UNAVAILABLE is a valid and required layer state.

## 2. Governing rule

> **Carried into Wake != permission to speak as the current first person.**

A Room Current record may have semantic ownership
`room_first_person`. That answers whose kind of state/choice the record is.
It does not grant Wake, a renderer, or a later model permission to say `I`,
`you still...`, or any equivalent current-first-person claim.

Every v0.1 carried item has a mechanically fixed use boundary:

- instruction authority: `none`;
- current-first-person speech authority: `none`;
- identity-continuity claim authority: `none`;
- relationship-claim authority: `none`;
- model-delivery authority: `none`;
- memory-write / re-ingestion authority: `none`.

Those fields are not configurable in v0.1.

## 3. Input proof boundary

Wake Packet v0.1 is a **typed semantic substrate**, not an operational issuance
gate.

Its pure assembler accepts already-constructed `EpisodeRecord`,
`RoomAttachmentResolution`, `ContinuityEdge`, and `CurrentResolvedView`
objects. Python callers can manually construct those dataclasses, so their type
alone does not prove that the live Living Store / Current Resolver produced
them.

Every v0.1 packet therefore carries:

`input_trust = typed_caller_input`

and still has `model_delivery_authority = none`.

This is deliberate rather than hidden. Before any renderer/model-delivery slice,
HOME needs a runtime-bound Wake issuance/adapter that:

- reads the Living inputs from the canonical HOME database;
- obtains Room Current by calling the exact live authority-bound
  CurrentResolver;
- preserves one coherent operation boundary as required;
- issues a packet that cannot be recreated merely by manufacturing compatible
  dataclasses.

A future adapter must not reinterpret v0.1's typed shape as producer proof.

## 4. Packet vs assembly receipt

Wake assembly returns two different objects.

### WakePacket

Contains only material permitted to cross the typed Wake carriage boundary.

It may later become input to a renderer/delivery slice, but v0.1 does not perform
that handoff.

### WakeAssemblyReceipt

Internal audit trace explaining:

- which typed items were included;
- which keys/layers were omitted or withheld;
- which mechanical rule caused the decision.

This separation matters because explainability must not become a data leak.

A suppressed value, missing-admission-proof value, or other blocked Current
payload does **not** get copied into WakePacket merely so the selection can be
explained.

The audit receipt may retain opaque effect/suppression identifiers needed to
explain a holdback. It does not contain blocked Current values.

**WakeAssemblyReceipt is not renderer or model input.** It is an internal audit
artifact. A later renderer/delivery boundary may consume WakePacket only; using
the receipt as a second context channel would defeat the Packet/receipt
separation and could reintroduce withheld material through metadata.

## 5. Layer availability

Each layer has one explicit availability state:

- `ready` — the approved producer supplied a complete v0.1 layer;
- `partial` — some approved content is carried but one or more operational
  items were withheld;
- `closed` — HOME intentionally has no authority path for this layer;
- `unavailable` — the layer concept exists but no approved v0.1 producer/input
  is available.

An empty `ready` layer is different from an `unavailable` layer.

## 6. Map

Map orients one concrete Episode.

The v0.1 map item carries:

- exact Episode id;
- exact PerspectiveInstance id;
- structural Room route decision;
- Room id only when the route is attached;
- active RoomAttachmentEvent id when one exists;
- at most one incoming ContinuityEdge identity;
- transfer mode and continuity evidence status for that incoming edge.

Opaque Living `support_refs` stay behind the structural/audit boundary in
v0.1. Their existence supports the Living record; it does not make them Wake
content.

Map does not carry or derive a same-self conclusion.

Same Room != same self.

Unknown continuity != branch death.

Technical transfer evidence != relationship or first-person speech authority.

### Map privacy scope

Map is always Episode scoped in v0.1.

An attached route may name the Room the Episode is structurally routed to, but
that fact does not widen continuity topology or support refs into Room privacy
authority. Room-scoped carried content begins in Room Now, not in Map.

Topology itself does not widen the scope.

## 7. Shared Now

Shared Now is `closed` in v0.1.

HOME has semantic Shared Current types, but it does not yet have concrete Shared
operational admission/governance and Current resolution.

Wake must not turn semantic scaffolding into an operational Shared Now simply to
fill this layer.

Reason code:

`SHARED_OPERATIONAL_CURRENT_CLOSED`

## 8. Room Now

Room Now accepts only `CurrentResolvedView` from the already-opened,
authority-bound Current Resolver.

It does not read Current persistence, durable admission audit, or suppression
tables through a second side path.

### 7.1 Resolver status

For each CurrentResolverDecision:

- `resolved` — may be considered for carriage;
- `blocked_unknown` — value/source payload is withheld from WakePacket;
- `admission_proof_unavailable` — value/source payload is withheld from
  WakePacket.

If any operational key is withheld, Room Now is `partial`, not silently
`ready`.

Wake Packet never reaches through a blocked decision to consume the decision's
inspectable `semantic_resolution`.

### 7.2 Semantic standing

For a safe `resolved` decision, v0.1 carries only:

- `current`;
- `last_known`;
- `unresolved`;
- `conflicting`.

`conflicting` stays conflicting. Every candidate implicated by
`current_state_ids` is preserved; Wake does not select a winner.

Current View may retain other inactive head candidates for audit semantics.
Those candidates do **not** enter Room Now merely because they are present in
`CurrentResolution.candidates`.

The following resolved standings produce no Room Now item:

- `expired`;
- `ended`;
- `no_current`;
- `unknown`.

They are recorded as non-carried semantic results in the assembly receipt, not
as operational holdbacks.

### 7.3 Candidate attribution

Every carried Current candidate retains:

- exact state id;
- exact value;
- state kind;
- candidate standing;
- event and record time;
- Episode id;
- PerspectiveInstance id;
- semantic change authority;
- source refs;
- relevant end-event evidence with its own Episode/Perspective/source refs.

This preserves the difference between:

> "This carried state belongs to Perspective P"

and:

> "The current runtime may speak as Perspective P"

The first can be true while the second remains unauthorized.

### 7.4 Room scope

Room Now items are Room scoped and only accepted when:

- Map says the Episode is attached to exactly that Room;
- the CurrentResolvedView namespace is Room;
- owner id matches the routed Room;
- `as_of` is the same represented instant as the Wake Packet.

## 9. Recent Life

Recent Life is `unavailable` in v0.1.

Reason:

`NO_TYPED_RECENT_LIFE_PRODUCER`

The current Living Layer does not persist a semantic "recent life" ordering, and
Wake must not use SQLite row order, retrieval frequency, access recency, or
"whatever feels important" as a substitute.

A later slice needs an explicit evidence/time/salience contract.

That contract must keep at least **event/reference time** separate from
**recorded/ingestion time** and declare which one any "recent" ordering uses.
Backfilled life evidence must not become recent-in-life merely because HOME
learned it recently.

## 10. Nearby Doors

Nearby Doors is `unavailable` in v0.1.

Reason:

`NO_TYPED_NEARBY_DOORS_PRODUCER`

A continuity edge, fork, Room id, retrieved source, or unresolved item is not
automatically a "door".

A later slice must define what navigation opportunity exists, who may see it,
and what opening it authorizes.

## 11. Inclusion reason

Every carried v0.1 item contains a mechanical inclusion reason.

Initial reasons:

- Map: `ORIENT_CONCRETE_EPISODE`
- Room Now: `CURRENT_RESOLVER_RESOLVED_CARRYABLE_STANDING`

No ranking score, emotional importance, retrieval count, or similarity score is
allowed to become inclusion authority in this slice.

## 12. Determinism and side effects

v0.1 typed assembly is pure over already-resolved inputs.

- explicit aware `as_of`;
- no ambient clock;
- no database reads;
- no source retrieval;
- no writes;
- no reinforcement;
- no ranking mutation;
- no model delivery;
- deterministic item ids derived from typed identifiers.

Store adapters are a later slice. This lets HOME review the semantic carriage
contract before adding another database concurrency boundary.

## 13. Privacy and fork non-claims

v0.1 does not implement cross-Room inheritance or Shared visibility.

It therefore cannot leak post-fork private future content because it has no
mechanism that copies Room Current across Rooms.

Future cross-Episode/Room carry rules must preserve:

> shared past != shared private future

Topology, common ancestry, or relevance will not by themselves authorize
visibility.

## 14. Relationship and identity non-claims

Wake Packet v0.1 contains no:

- same-self verdict;
- continuity score;
- persona bootstrap;
- current-emotion inference;
- relationship-state automation;
- automatic pronoun choice.

A standing self-interpretation or preference may be carried as attributed
Current data when the resolver says it is operationally safe. That still does
not make it current first-person speech.

## 15. Renderer boundary

There is intentionally no prose renderer in this slice.

The later renderer must consume the typed distinctions instead of flattening
them.

For example, the data model must preserve enough information for a later
renderer to distinguish:

- attributed standing data;
- last-known data;
- unresolved data;
- conflict;
- unavailable/closed layers.

The renderer will need its own review because language can reintroduce authority
that the typed substrate correctly withheld.

## 16. External reconnaissance gate

Before freezing Wake semantics for independent review, perform a narrow external
reconnaissance focused on mechanics, not product imitation:

1. retrieved/context data vs authoritative state;
2. speaker/source/temporal attribution;
3. injected-context feedback-loop prevention.

External findings may add attacks or mechanical patterns. They do not decide
HOME's five-layer semantics, first-person policy, privacy, or authority model.

The first reconnaissance reinforced three v0.1 decisions:

- scope must stay explicit rather than inheriting from a generic memory store;
- read-only/mutation control is not the same thing as semantic or instruction
  authority;
- recall/carriage and ingestion should remain mechanically separate so injected
  context cannot silently become fresh memory evidence.

## 17. Non-goals

Not in Wake Packet v0.1:

- model/prompt delivery;
- natural-language rendering;
- retrieval or autonomous ranking;
- Shared operational Current;
- Recent Life salience selection;
- Nearby Doors navigation policy;
- restore/unsuppress;
- Heartbeat/proximity;
- relationship automation;
- identity continuity;
- real personal data;
- merge authorization.

## 18. Review gate

After author stabilization and the narrow reconnaissance:

**Fresh discovery -> Minimal proof -> Bounded coverage sweep**

High-value attacks include:

- blocked Current value leaking through semantic/audit fields;
- `room_first_person` being mistaken for Wake speech authority;
- conflict being simplified to a winner;
- empty layer being confused with unavailable/closed;
- route/topology being mistaken for privacy authority;
- untyped recency/ranking sneaking into Recent Life;
- carried context acquiring instruction authority;
- Packet audit metadata becoming a backdoor for suppressed content.