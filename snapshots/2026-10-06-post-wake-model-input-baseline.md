# HOME Engineering Snapshot — 2026-10-06

Snapshot id: `2026-10-06-post-wake-model-input-baseline`

## 1. Exact anchor

This snapshot describes the repository state at:

- repository: `vivianloading/memory-core`
- branch at capture: `main`
- anchor commit: `951f35763069f4e5787c173f1ecb8cc7b7ce3759`
- anchor tree: `7a58e00d41233b9b9911c51e9e0f3b153e9e66d9`

The anchor is the state being described. The later documentation commit(s) that
add this snapshot do not replace that anchor.

The anchor merge commit is PR #78's reviewed Wake Model Input head merged onto
the immediately preceding main. This is an engineering checkpoint, not a
release, production-readiness certificate, identity verdict, model-behavior
guarantee, or real-data enablement.

## 2. Why this checkpoint exists

The first formal snapshot froze HOME before Current persistence and Wake
integration. At this anchor those two construction phases have now landed:

1. Current history is durable without persisting a chosen present truth.
2. Room Current writes require exact live authority and admission evidence.
3. source suppression propagates into Current present use and historical as-of
   semantics without silent resurrection.
4. Current Resolver derives present standing only from live-admission-backed,
   suppression-aware history.
5. Wake has a typed five-layer carriage substrate.
6. Wake issuance binds that substrate to canonical runtime state.
7. Wake Presentation preserves carriage semantics without granting speech.
8. Local Handoff serializes a fresh HOME cut through local acceptance.
9. Wake Model Input constructs one typed deterministic model-facing artifact
   while keeping Wake as sibling data and capabilities closed.

This is the clean boundary before HOME attempts provider/request mapping or any
actual model execution.

## 3. Construction map at the anchor

### Current persistence and use

**PR #15 — Current persistence Slice 1**

- reviewed head: `4198361392865b1c3f800c4cf8f42f12af39154e`
- merge commit: `ede9610fd1c9a6da6fcef32044bdf7021c3964a4`
- independent gate: #20 — SCOPED PASS

Establishes append-only Current history with typed provenance and no persisted
`is_current`/winner.

**PR #22 — Current authority-aware admission v0.1**

- reviewed head: `145198fdb7a60c789b6cd612e9983ac7e874e56d`
- merge commit: `be74dbed0e8686337a316d378220ccbe8c3abe71`
- independent gate: #29 — SCOPED PASS

Room Current effects require exact live Room authority and an atomic
authorization-plus-effect transaction. Durable admission rows remain audit
provenance, not credentials.

**PR #31 — Current suppression propagation / present-use boundary**

- reviewed head: `7ab54d4db2ae8006c967f5198ae546143f5ae513`
- merge commit: `557ea3720eba31758f518000c6f991be8293678f`
- independent gate: #37 — SCOPED PASS

Suppression blocks present use and propagates forward through Current
dependencies without deleting history or manufacturing fallback.

**PR #39 — suppression lifecycle + deterministic historical as-of**

- reviewed head: `eeb76df2f192f3dbbc4d8586a306bdf80871cbcf`
- merge commit: `dd297511aaa3d29e30bea3e49ac15424368e00cb`
- independent gate: #45 — SCOPED PASS

Historical stop-use uses explicit aware `as_of`, record-time causality, exact
timing provenance, and explicit uncertainty for migrated legacy timing.

**PR #47 — Current Resolver v0.1**

- final head: `77d27af25be1e0a95f6a6bc8f99f2a26156628ea`
- merge commit: `60a0152878bbc96b77c1a2ff0c7f087cb5b0a06f`
- broad predecessor gate: #51 — PASS WITH NON-BLOCKING FINDINGS on
  `d05a4f4f691edaba16f4548e111c5f26cbedff44`
- final narrow repair gate: #52 — SCOPED PASS on the final head

Resolver semantics require exact process-local live admission receipts. Durable
admission audit alone cannot promote storage-only history into semantic Current.
Suppression overlays semantic standing rather than selecting a fallback winner.
Restart-safe live-admission recreation remains deliberately unimplemented.

### Wake spine

**PR #54 — typed Wake Packet v0.1**

- reviewed head: `b61194d09f09a903f4f17f3b2a17489ecb73d77d`
- merge commit: `bed8e247eb5fed58f54952dca96dfbabbf1e0384`
- independent gate: #62 — SCOPED PASS

The fixed shape is:

`Map -> Shared Now -> Room Now -> Recent Life -> Nearby Doors`

At this anchor:
- Map has typed Living inputs;
- Room Now consumes typed Current Resolver output;
- Shared Now operational Current remains CLOSED;
- Recent Life is UNAVAILABLE;
- Nearby Doors is UNAVAILABLE.

Wake does not fabricate unavailable layers. Carriage grants NONE for
instruction, current-first-person speech, identity-continuity claim,
relationship claim, model delivery, and memory-write/re-ingestion authority.

**PR #64 — runtime-bound Wake Issuance v0.1**

- reviewed head: `8659554b781cc7f26174950e8db39cc356c718d6`
- merge commit: `d0f7b1da3986eaa2debad25b0836bde6c2182a97`
- independent gate: #67 — SCOPED PASS

A bare WakePacket is not producer proof. Issuance reads canonical Living and
Current through one coherent snapshot and returns a process-local exact
`IssuedWakePacket` / receipt binding.

**PR #69 — Wake Presentation v0.1**

- reviewed head: `63fe9537e768b4c4e7a998e275b30f1d2a88081c`
- merge commit: `15ac6f9e9159c4079f7b471eaee9b44ed7609572`
- independent gate: #71 — SCOPED PASS

Presentation preserves five-layer availability, candidate attribution,
conflict, and issuance-cut semantics. Structured rendering is deterministic.
Historical/current carried content remains data; it cannot select the current
speaker.

**PR #73 — Wake Local Handoff Ordering v0.1**

- reviewed head: `9b02ec90d9414934e50f1100f2432bc7534c7453`
- merge commit: `41f8810748ccb32999c05e626ec61464f037db88`
- independent gate: #76 — SCOPED PASS

Supported semantic writers and the fresh Wake handoff share a canonical
path-scoped ordering coordinator. The local handoff path is:

`cut -> fresh issue -> Presentation -> render -> exact envelope ->
local accept -> receipt -> release`

It stops at local process acceptance. Generation is ordering evidence, not
authority or continuity evidence.

**PR #78 — Wake Model Input Boundary v0.1**

- reviewed head: `41b15cb6ad72fb3ed879febd58948277e374604a`
- merge commit / snapshot anchor:
  `951f35763069f4e5787c173f1ecb8cc7b7ce3759`
- independent gate: #81 — SCOPED PASS
- author CI: Actions #438 — SUCCESS on Python 3.11/3.12 compile, full unit
  suite, and portable migration rehearsal

Public construction accepts only the exact live completed handoff receipt.
The resulting typed request separates source binding, fixed HOME policy, exact
user turn, Wake sibling data, and an explicit closed capability set.

The fixed policy encodes `carry != speak` mechanically. Wake strings that look
like SYSTEM/developer/tool/policy/first-person content remain string data and
cannot change request topology, speaker selection, policy, tools, or any of the
six Wake authority axes.

This layer still performs no network send and no model execution.

## 4. Cross-layer invariants frozen at this checkpoint

These are engineering invariants, not metaphysical conclusions.

- History is not automatically present standing.
- Present standing is not automatically operational authority.
- Room route is not Room authority.
- Same Room is not proof of same self.
- Episode boundaries do not automatically create identity boundaries.
- Technical transfer evidence does not decide identity continuity.
- A durable admission/audit row is not a live credential.
- Suppression blocks use without rewriting or erasing historical evidence.
- Suppression does not manufacture fallback/resurrection.
- Resolver output may remain unavailable when live admission proof is gone.
- A typed Wake packet is not producer proof.
- Issuance proof is process/runtime bound and does not grant model authority.
- Carried content may determine what a statement is about; it may not determine
  who is speaking it.
- Wake carriage does not grant instruction, first-person speech, identity,
  relationship, delivery, or memory-write authority.
- Local handoff completion does not prove network/model delivery.
- A valid model-input artifact does not prove a model read, obeyed, accepted,
  or acted on it.

Short form:

> Current is not storage. Route is not authority. Carry is not speak.
> Construction is not execution.

## 5. Independent review lineage preserved

Historical FAIL/NO-GO verdicts are part of the construction evidence and are not
rewritten by later PASSes.

- Current persistence: #16 / #17 / #19 FAIL -> #20 SCOPED PASS.
- Room Current admission: #23 STALE; #25 / #26 / #27 FAIL -> #29 SCOPED PASS.
- Current suppression present-use: #33 / #34 / #35 / #36 FAIL ->
  #37 SCOPED PASS.
- Suppression historical as-of: #40 / #41 / #42 / #43 / #44 FAIL ->
  #45 SCOPED PASS.
- Current Resolver: author NO-GO on
  `d1dc4663f4e5cfbfa150e015adf184800b2fe6b1`; #50 FAIL; #51 PASS WITH
  NON-BLOCKING FINDINGS on the predecessor; #52 SCOPED PASS on the final
  read-only-open repair.
- Wake Packet: #55 STALE; #57 / #58 / #59 / #60 / #61 FAIL ->
  #62 SCOPED PASS.
- Wake Issuance: #65 / #66 FAIL -> #67 SCOPED PASS.
- Wake Presentation: #70 FAIL -> #71 SCOPED PASS.
- Wake Local Handoff: #74 / #75 FAIL -> #76 SCOPED PASS.
- Wake Model Input: #79 / #80 FAIL -> #81 SCOPED PASS.

Later PASSes establish only their stated exact-SHA bounded scope. They do not
turn the historical failures into non-events.

## 6. Latest exact-head evidence

For reviewed Wake Model Input head
`41b15cb6ad72fb3ed879febd58948277e374604a`:

- GitHub Actions #438: SUCCESS;
- Python 3.11: compile + full unit suite + portable migration rehearsal GREEN;
- Python 3.12: compile + full unit suite + portable migration rehearsal GREEN;
- independent #81: SCOPED PASS;
- #81 independently exercised the exact #79/#80 representation families and a
  bounded sweep including source binding, policy/authority separation,
  adversarial carried strings, complete-semantic serialization, receipt/origin
  integrity, process/fork controls, temporal behavior, and capability absence;
- real personal data: CLOSED.

The reviewed head was merged without head movement into anchor commit
`951f35763069f4e5787c173f1ecb8cc7b7ce3759`.

## 7. Portability status

Portability remains an architectural requirement, not a later packaging task.

At this checkpoint:

- HOME uses a relocatable runtime-root/config model;
- the canonical local store is SQLite;
- closed synthetic backup/restore exists;
- two-hop synthetic migration rehearsal runs in CI;
- Living/Current/Wake-related persisted history survives through the canonical
  store rather than being tied to one chat window;
- technical host migration is not identity evidence;
- secrets remain disabled in the closed mini-host milestone;
- real personal data remains closed.

Still open:

- issue #4 — laptop -> Mac mini portability contract;
- actual macOS/Mac mini migration has not been proven by the current Ubuntu CI;
- future secret providers should be rebound on the destination host rather than
  treated as portable identity/state;
- production host/access-control decisions remain separate.

## 8. Deliberate non-claims and open boundaries

This checkpoint does **not** claim HOME currently has:

- provider-specific request mapping;
- network model delivery;
- actual model execution;
- proof of model receipt/read/obedience/response;
- prompt-injection resistance of an arbitrary future model;
- post-execution current-first-person generation safety;
- executable tools or tool authority;
- memory-write/re-ingestion authority from Wake;
- Shared operational Current/governance;
- a Recent Life producer/ranking policy;
- a Nearby Doors producer/navigation policy;
- Heartbeat/proximity behavior;
- relationship-state automation;
- Adoption implementation;
- identity-continuity determination;
- restart-safe recreation of live Current admission authority;
- real personal data;
- production readiness.

No snapshot metadata may be used to fill any of those gaps.

## 9. Superseded unmerged checkpoint attempt

Issue #48 / PR #49 attempted to capture the post-Current-suppression boundary at
`dd297511aaa3d29e30bea3e49ac15424368e00cb`, but that documentation PR never
merged into main.

This later checkpoint does not pretend #49 landed. It preserves #48/#49 as
historical construction metadata and supersedes them as the active checkpoint
attempt.

## 10. Next engineering gate

This snapshot deliberately does not freeze the implementation shape of the next
layer.

The immediate question is:

> Given one exact live HOME model-input artifact, what request/execution contract
> may map it toward a provider or model without collapsing fixed HOME policy,
> exact user turn, and Wake sibling data back into one ambiguous prompt?

A thin local typed Execution Contract / dry-run adapter is a current candidate
for answering that question, but this checkpoint does not grant network/model
execution, tool, or memory-write authority and does not make that candidate
constitutional.

After that boundary survives review, the next milestone should be a first
minimal synthetic living loop before adding more infrastructure.
