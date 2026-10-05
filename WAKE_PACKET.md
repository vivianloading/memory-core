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

Wake keeps upstream semantic enum types (for example CurrentStateKind,
SemanticChangeAuthority, EndKind, TransferMode, and ContinuityStatus) as typed
values inside the substrate. It does not flatten them to arbitrary text merely
for early serialization convenience.

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

## Author-side type-integrity hardening after initial freeze

A later author re-read treated direct dataclass construction as adversarial input,
rather than assuming the assembler would always be the only producer.

That review found two representation holes in the first frozen head
`36a787132f09a7712c556b9a9d591cc0656ed7be`:

1. a hand-built `WakeMapItem` could encode an impossible route or attach an
   incoming continuity edge whose destination was not the Map Episode;
2. a hand-built `WakeCurrentCandidate` could omit Episode/Perspective
   attribution, claim non-Room semantic ownership, or omit source provenance.

The assembler did not emit those shapes, but the substrate itself was too weak.
v0.1 now rejects them at dataclass construction time.

This preserves a stronger rule:

> **Typed shape must not launder missing attribution into Wake content, even
> before an operational producer exists.**

The old frozen head remains author-side pre-review history; any independent
review target bound to it is stale once this hardening changes the branch head.

## Independent review #57 — FAIL / NO-GO and remediation

Independent review #57 returned **FAIL / NO-GO** on exact head
`3cf6a41dc98ccaf15958d16604576d823c5c9447`.

The review confirmed five representation/time defects using ordinary constructors
and `dataclasses.replace`:

1. nested Room Now item/candidate shapes were not recursively type-checked;
2. direct `WakePacket` construction did not bind Room Now privacy to the Map's
   attached Room;
3. equality behavior of `StrEnum` allowed a plain string such as
   `"unavailable"` to bypass typed availability guards;
4. the explicit synthetic-unattributed Perspective sentinel could enter Wake
   provenance;
5. Python `datetime ==` was not a safe same-instant test across DST folds.

The remediation strengthens the substrate itself rather than relying on the
normal assembler:

- nested Room Now tuples now require exact Wake dataclass element types and
  immutable tuple containers;
- packet-level validation binds all Room Now items to the Map-attached Room and
  forbids Room Now content when the Map is unattached/unresolved;
- layer/availability boundaries require actual enum instances before value
  checks;
- Wake Map, Room Current candidates and Room end evidence reject the established
  unattributed Perspective sentinel;
- same-time binding uses explicit absolute-instant arithmetic consistent with
  Current View rather than wall-time equality.

The #57 verdict remains permanently bound to its failed exact head. A later
remediation head requires a fresh independent review and bounded coverage sweep.

## Independent review #58 — conflict aggregate NO-GO

Independent review #58 returned **FAIL / NO-GO** on exact head
`34acfe30d0d021220cb7691ec39b64d693b7a55f`.

The #57 risk families were successfully rejected in independent proofs and the
bounded sweep was reached. The sweep found one remaining semantic representation
family: direct construction could carry multiple distinct eligible candidates
while labelling the aggregate as non-conflicting.

The remediation makes aggregate/candidate consistency mechanical:

- candidate `state_id` values must be unique;
- one candidate requires the aggregate standing to exactly match that candidate;
- more than one candidate requires aggregate `CONFLICTING`;
- legitimate one-candidate `CONFLICTING` remains representable (for example,
  one state with multiple effective end events).

The author additionally checked the symmetric direct-construction case where a
single ordinary candidate was falsely labelled `CONFLICTING`; it is rejected by
the same invariant.

The #58 verdict remains bound to its failed exact SHA. A later head requires a
fresh exact-SHA review.

## Independent review #59 — section-level conflict split NO-GO

Independent review #59 returned **FAIL / NO-GO** on exact head
`0ea9ac64c1ea7225304014447db656b2f86745e2`.

The per-item aggregate consistency added after #58 worked, but direct section
construction could split one genuine key-level conflict into multiple
non-conflicting items for the same `(room_id, key)`. Every item was internally
valid, yet the section as a whole erased the required conflict aggregate.

The remediation therefore moves the invariant to the enclosing semantic unit:

- one `WakeRoomNowSection` may contain at most one item per
  `(room_id, key)`;
- item IDs must also be unique within the section;
- distinct keys remain independently representable;
- a conflict for one key must remain inside that key's single aggregate item.

This reflects the actual Current semantic boundary: one Room Current key has one
aggregate Wake representation.

The #59 verdict remains bound to its failed exact SHA. A later head requires a
fresh exact-SHA review.
