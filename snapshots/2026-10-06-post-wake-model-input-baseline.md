# HOME Engineering Snapshot — 2026-10-06

Snapshot id: `2026-10-06-post-wake-model-input-baseline`

## 1. Exact anchor

This snapshot describes the repository state at:

- repository: `vivianloading/memory-core`
- branch at capture: `main`
- anchor commit: `951f35763069f4e5787c173f1ecb8cc7b7ce3759`
- anchor tree: `7a58e00d41233b9b9911c51e9e0f3b153e9e66d9`
- anchor commit message: `Merge PR #78: Add Wake Model Input Boundary v0.1`

The anchor merge commit has parents:

1. prior main: `41f8810748ccb32999c05e626ec61464f037db88`
2. exact reviewed PR #78 head:
   `41b15cb6ad72fb3ed879febd58948277e374604a`

The reviewed head and the anchor merge commit have the same Git tree:

`7a58e00d41233b9b9911c51e9e0f3b153e9e66d9`

This mechanically links the latest independent exact-head review to the bytes
present at the snapshot anchor.

No separate GitHub Actions run exists for the merge commit itself. The latest
author CI evidence is Actions #438 on the exact reviewed head. The snapshot
records that distinction instead of treating the merge SHA as independently
executed.

This is an engineering baseline, not a release, production-readiness
certificate, identity verdict, relationship-state verdict, model-safety
certificate, or real-data enablement.

## 2. Why this snapshot exists

The prior formal snapshot,
`2026-10-02-pre-persistence-baseline`, froze HOME before Current persistence
and before Wake.

At this anchor, HOME has crossed two large engineering phases:

1. Current moved from pure semantic derivation into durable synthetic/local
   history, authority-aware admission, suppression-aware present/historical use,
   and a live resolver.
2. Wake moved from a typed carriage substrate through runtime-bound issuance,
   deterministic presentation, same-process local handoff ordering, and finally
   into a typed model-facing input artifact.

The resulting spine is:

`Current history -> Current admission/use -> Current resolver -> Wake Packet ->
Wake Issuance -> Wake Presentation -> Local Handoff -> Model Input`

The important stopping point is equally explicit:

`Model Input != network/model execution`

No network send, provider request, or model invocation exists at this anchor.

This snapshot therefore freezes the **post-Wake-Model-Input /
pre-model-execution** engineering boundary.

## 3. Construction map at the anchor

### 3.1 Inherited semantic foundations

The earlier Living Layer, Room participation authority, and Current View
semantic core remain in force.

The most important inherited separations are unchanged:

- Room route is not authority.
- Authority is not identity.
- Perspective attribution is not authentication.
- Adoption is not a credential.
- Current is present standing, not raw recency.
- Technical continuity evidence is not a same-self verdict.
- Same Room does not prove same self.
- Episode boundaries do not automatically create identity boundaries.
- Historical material may remain true as history without being current.
- Retrieval relevance, emotional intensity, similarity, and repetition do not
  manufacture present truth or authority.

The 2026-10-02 snapshot remains the canonical construction record for those
foundations.

### 3.2 Current persistence Slice 1

Merged PR: [#15](https://github.com/vivianloading/memory-core/pull/15)

- reviewed head: `4198361392865b1c3f800c4cf8f42f12af39154e`
- reviewed tree: `3edef0d46e53e7629d1b3246969890e69e49608f`
- merge commit: `ede9610fd1c9a6da6fcef32044bdf7021c3964a4`
- merge tree: `3edef0d46e53e7629d1b3246969890e69e49608f`
- independent gate: [#20](https://github.com/vivianloading/memory-core/issues/20)
- gate result: **SCOPED PASS**

What it establishes:

- Current history is persisted append-only rather than as one mutable "current"
  row.
- persisted state and end-event history retain explicit temporal fields and
  ordered evidence bindings;
- storage preserves candidate/evidence history without persisting a semantic
  winner;
- Current semantic derivation remains responsible for standing;
- structurally valid storage presence does not authenticate write origin;
- schema/data auditing fails closed on the reviewed immutable-history and
  canonical-encoding boundaries;
- synthetic/local only; real personal data remains closed.

### 3.3 Room Current authority-aware admission Slice 2

Merged PR: [#22](https://github.com/vivianloading/memory-core/pull/22)

- reviewed head: `145198fdb7a60c789b6cd612e9983ac7e874e56d`
- reviewed tree: `a70e3c12b850b4d4e7f5088ef494c00eb5ca4599`
- merge commit: `be74dbed0e8686337a316d378220ccbe8c3abe71`
- merge tree: `a70e3c12b850b4d4e7f5088ef494c00eb5ca4599`
- independent gate: [#29](https://github.com/vivianloading/memory-core/issues/29)
- gate result: **SCOPED PASS**

What it establishes:

- operational admission is Room Current only; Shared admission remains closed;
- a durable admission audit row is provenance, not a credential;
- live process-local admission receipts are required for operational use;
- admission is bound to exact Room participation authority, session, Episode,
  Perspective, Room, effect, and source evidence;
- supersession/end admission requires the exact live predecessor/target receipt;
- effect write, admission audit, commit, and live receipt registration preserve
  the reviewed authority/transaction ordering;
- lost process-local admission authority after restart is not reconstructed from
  durable audit.

### 3.4 Current suppression present-use Slice 3A

Merged PR: [#31](https://github.com/vivianloading/memory-core/pull/31)

- reviewed head: `7ab54d4db2ae8006c967f5198ae546143f5ae513`
- reviewed tree: `719731e7cfa53014c32a1d9eafe161854adf7d25`
- merge commit: `557ea3720eba31758f518000c6f991be8293678f`
- merge tree: `719731e7cfa53014c32a1d9eafe161854adf7d25`
- independent gate: [#37](https://github.com/vivianloading/memory-core/issues/37)
- gate result: **SCOPED PASS**

What it establishes:

- source suppression blocks present use without deleting audit history;
- source/state/end dependency blocking propagates in the reviewed direction;
- a blocked successor does not cause an older semantic state to resurrect;
- live admission receipts become unusable when their supporting source is no
  longer usable;
- present-use permission requires a trusted suppression ledger rather than
  treating missing suppression rows as permission by default;
- restore/unsuppress remains outside this slice.

### 3.5 Suppression lifecycle as-of Slice 3B1

Merged PR: [#39](https://github.com/vivianloading/memory-core/pull/39)

- reviewed head: `eeb76df2f192f3dbbc4d8586a306bdf80871cbcf`
- reviewed tree: `f94a7d6819d0e4d950cdf29b13307b8054c0fbcd`
- merge commit: `dd297511aaa3d29e30bea3e49ac15424368e00cb`
- merge tree: `f94a7d6819d0e4d950cdf29b13307b8054c0fbcd`
- independent gate: [#45](https://github.com/vivianloading/memory-core/issues/45)
- gate result: **SCOPED PASS**

What it establishes:

- suppression records distinguish `effective_at` from `recorded_at`;
- historical projections are explicit-`as_of` rather than ambient-clock
  queries;
- later-learned stop evidence is not silently projected into an earlier
  knowledge cut;
- legacy suppression without timing remains timing-unknown for historical use
  and conservatively blocked for present use;
- timing evidence is append-only and schema-audited;
- source and Current historical-use decisions preserve explicit uncertainty;
- no restore/unsuppress behavior is introduced.

### 3.6 Current Resolver v0.1

Merged PR: [#47](https://github.com/vivianloading/memory-core/pull/47)

- reviewed head: `77d27af25be1e0a95f6a6bc8f99f2a26156628ea`
- reviewed tree: `a6c2ad1ed78b0d03cef9909b0f4ddb0583f45e94`
- merge commit: `60a0152878bbc96b77c1a2ff0c7f087cb5b0a06f`
- merge tree: `a6c2ad1ed78b0d03cef9909b0f4ddb0583f45e94`
- independent final gate: [#52](https://github.com/vivianloading/memory-core/issues/52)
- gate result: **SCOPED PASS**

What it establishes:

- semantic Current is derived from full admitted history before the present-use
  suppression overlay;
- suppression is not implemented by deleting blocked rows and re-running
  history, so an older state does not become current merely because a newer one
  became unusable;
- only exact live `CurrentAdmissionAuthority` receipts authorize semantic
  inclusion;
- durable admission audit can make resolution unavailable but cannot authorize
  a value;
- missing live proof fails closed;
- Current read connections are SQLite `mode=ro`; a missing canonical database
  is not silently recreated by a read;
- resolver scope remains Room Current; Shared is closed.

### 3.7 Wake Packet v0.1

Merged PR: [#54](https://github.com/vivianloading/memory-core/pull/54)

- reviewed head: `b61194d09f09a903f4f17f3b2a17489ecb73d77d`
- reviewed tree: `7012d340876cb7edaebd08977df55c0ea95cac0c`
- merge commit: `bed8e247eb5fed58f54952dca96dfbabbf1e0384`
- merge tree: `7012d340876cb7edaebd08977df55c0ea95cac0c`
- independent gate: [#62](https://github.com/vivianloading/memory-core/issues/62)
- gate result: **SCOPED PASS**

What it establishes:

- Wake has five fixed layers:
  `Map -> Shared Now -> Room Now -> Recent Life -> Nearby Doors`;
- v0.1 explicitly allows CLOSED / UNAVAILABLE layers;
- Shared Now remains CLOSED;
- Recent Life and Nearby Doors have no approved producers and remain
  UNAVAILABLE;
- Map is Episode-scoped;
- Room Now is Room-scoped;
- blocked Current values do not leak into Packet or assembly explanations;
- conflicts preserve all candidates and do not manufacture a winner;
- historical Perspective attribution remains historical Perspective
  attribution;
- identity continuity remains `not_assessed`;
- six authority axes are mechanically NONE;
- typed Packet assembly is a semantic substrate, not producer authentication or
  model-delivery authority.

The central invariant is:

> **Carried into Wake != permission to speak as the current first person.**

### 3.8 Wake Issuance v0.1

Merged PR: [#64](https://github.com/vivianloading/memory-core/pull/64)

- reviewed head: `8659554b781cc7f26174950e8db39cc356c718d6`
- reviewed tree: `910951a6866590779dbc298831876b08c9a5e874`
- merge commit: `d0f7b1da3986eaa2debad25b0836bde6c2182a97`
- merge tree: `910951a6866590779dbc298831876b08c9a5e874`
- independent gate: [#67](https://github.com/vivianloading/memory-core/issues/67)
- gate result: **SCOPED PASS**

What it establishes:

- issuance reads canonical Living + Current under one coherent read snapshot;
- callers supply only Episode identity, not prebuilt route/Current inputs;
- attached Room Current is resolved through the exact live authority-bound
  resolver;
- issuance receipts bind exact authority/process/database/wake/episode/as-of and
  Packet/assembly digests;
- issuer origin and opening dependencies are exact-object/process bound;
- historical issuance provenance is not current freshness;
- issuance grants no instruction, first-person, identity, relationship,
  model-delivery, or memory-write authority.

### 3.9 Wake Presentation v0.1

Merged PR: [#69](https://github.com/vivianloading/memory-core/pull/69)

- reviewed head: `63fe9537e768b4c4e7a998e275b30f1d2a88081c`
- reviewed tree: `da6d15927fd0d30710f606855c70de6edaf67b64`
- merge commit: `15ac6f9e9159c4079f7b471eaee9b44ed7609572`
- merge tree: `da6d15927fd0d30710f606855c70de6edaf67b64`
- independent gate: [#71](https://github.com/vivianloading/memory-core/issues/71)
- gate result: **SCOPED PASS**

What it establishes:

- Presentation requires exact live-issued Wake provenance;
- the five layers retain fixed order and typed policy metadata;
- Map and Room data keep explicit attribution and privacy scope;
- Room Current candidates retain state/value/standing/Episode/Perspective/source
  provenance;
- conflicts preserve all candidates and contain no winner field;
- complete public typed semantics, including concrete dataclass/enum identity,
  are bound independently of the curated JSON projection;
- deterministic JSON rendering is data projection, not model execution;
- arbitrary carried strings remain values rather than role/tool/prompt
  capabilities;
- temporal wording is standing at the issuance cut, not unqualified eternal
  currentness;
- Presentation adds no current-first-person, instruction, identity,
  relationship, model-delivery, or memory-write authority.

The governing rule is:

> **Carried content may determine the object of a statement; it may not determine
> the speaker of the statement.**

### 3.10 Wake Local Handoff Ordering v0.1

Merged PR: [#73](https://github.com/vivianloading/memory-core/pull/73)

- reviewed head: `9b02ec90d9414934e50f1100f2432bc7534c7453`
- reviewed tree: `98abb8e8ea8f93f20c6fd22369f742f17f751883`
- merge commit: `41f8810748ccb32999c05e626ec61464f037db88`
- merge tree: `98abb8e8ea8f93f20c6fd22369f742f17f751883`
- independent gate: [#76](https://github.com/vivianloading/memory-core/issues/76)
- gate result: **SCOPED PASS**

What it establishes:

- one path-scoped, process-local HOME state coordinator orders supported
  Memory/Living/Current semantic writers against a short local Wake handoff cut;
- ordinary supported writers enter the coordinator at canonical transaction
  seams rather than relying on a public-method decorator convention;
- successful supported semantic transactions increment a process-local
  generation once; rollback/failure does not;
- same-thread writer/cut re-entry fails closed;
- canonical coordinator object identity, not merely path/digest equality, is
  required;
- legacy Memory callback ordering remains separate and does not become a
  whole-HOME callback-held cut;
- public Wake handoff performs fresh issuance/presentation/rendering internally;
- local acceptance has no arbitrary caller callback, network I/O, or model
  execution;
- `WakeHandoffReceipt` proves exact process-local local acceptance under one
  stable supported-writer cut;
- the receipt does not prove network delivery, model receipt/read, model
  behavior, or future freshness.

The v0.1 synchronization claim is same-process and supported-writer only. Raw
SQLite/private bypasses and separately started processes are outside the
ordering guarantee.

### 3.11 Wake Model Input Boundary v0.1

Merged PR: [#78](https://github.com/vivianloading/memory-core/pull/78)

- reviewed head: `41b15cb6ad72fb3ed879febd58948277e374604a`
- reviewed tree: `7a58e00d41233b9b9911c51e9e0f3b153e9e66d9`
- merge commit / snapshot anchor:
  `951f35763069f4e5787c173f1ecb8cc7b7ce3759`
- merge tree / snapshot tree:
  `7a58e00d41233b9b9911c51e9e0f3b153e9e66d9`
- independent gate: [#81](https://github.com/vivianloading/memory-core/issues/81)
- gate result: **SCOPED PASS**

What it establishes:

- public construction consumes only an exact live `WakeHandoffReceipt`;
- it does not accept Packet/Issuance/Presentation/raw envelope/raw payload,
  caller policy, role, tools, historical `as_of`, model target, or callback;
- the source artifact is recovered through the originating Local Handoff live
  verification seam;
- HOME model-input policy is fixed/versioned typed structure and is not derived
  from Wake content;
- Wake Presentation JSON is carried as sibling string data;
- exact user input remains a separate user-turn field;
- capability closure is:
  model execution unavailable, network delivery unavailable, tools NONE,
  memory write NONE;
- six Wake authority axes remain concrete NONE;
- deterministic serialization covers complete public typed request semantics,
  including concrete dataclass/enum type identity and aware datetime
  representation;
- the upstream handoff envelope digest remains owned by the upstream handoff
  layer rather than being redefined by a downstream canonicalizer;
- `RequestConstructionReceipt` binds the source handoff, policy, typed request,
  deterministic representation, process/local-boundary/model-input-boundary
  provenance, serializer/media type, and authority boundary;
- live verification rejects copied/foreign/mutated provenance;
- public representation fields `media_type` and `serialized_text` must
  remain exact runtime `str` before value/digest checks;
- an old completed handoff remains an old cut even after HOME later changes;
  constructing model input does not silently re-issue or refresh Wake;
- the layer introduces no network sender, provider client, model invoke path,
  system/developer/chat-role constructor, executable tool grant, transport
  callback, or memory-write operation.

Temporal semantics are:

`issuance_cut_confirmed_through_local_handoff`

This means Presentation's issuance `as_of` remained protected through the
completed local handoff cut. It is not a handoff wall-clock timestamp and is not
a claim of freshness after the cut released.

## 4. Cross-layer invariants frozen at this snapshot

These are implementation/architecture invariants, not metaphysical conclusions.

- **History != Current.** Durable history may remain readable after its present
  standing or present usability changes.
- **Storage presence != authority.** A structurally valid row or durable audit
  record cannot create live admission authority.
- **Current != latest row.** Current standing is derived from semantic history,
  validity, ends, conflicts, admission proof, and present-use policy.
- **Suppression != deletion.** Stop-use prevents present use without erasing the
  audit record.
- **Suppression != resurrection.** Blocking a newer state does not make an older
  state regain standing.
- **Historical projection != present permission.** Explicit as-of reasoning and
  present-use authorization are separate.
- **Route != authority.** Living attachment does not authorize Room
  participation or Current mutation.
- **Authority != identity.** Operational grants do not decide same-self.
- **Perspective != authentication.** First-person attribution and runtime
  authorization remain separate.
- **Carry != speak.** A value may be carried as data without gaining current
  first-person or instruction authority.
- **Presentation != delivery.** Structured rendering is not a model request.
- **Local handoff != network delivery.** Exact process-local acceptance is not
  proof that a model received or read anything.
- **Model input != model execution.** A typed model-facing artifact is not an
  invocation and does not prove model obedience.
- **Digest equality != shared authority state.** Process-local coordination
  depends on exact canonical coordinator/origin binding where the contract says
  so.
- **Value equality != typed exactness.** Public typed representation metadata
  must satisfy both runtime type and value/integrity bindings.
- **Downstream evidence does not redefine upstream evidence.** A later layer may
  rely on an upstream verified digest without silently changing that digest's
  canonicalization contract.

A short form:

> Route is not authority. Authority is not identity. Current is not recency.
> Suppression is not resurrection. Carry is not speak. Handoff is not delivery.
> Model input is not model execution.

## 5. Independent review history after the 2026-10-02 snapshot

Historical FAIL / NO-GO verdicts remain engineering evidence. Later PASSes do
not rewrite them.

### Current persistence

- #16 — FAIL / NO-GO at
  `9408a3cbd6256298cbd9000580f9330df448f34e`
- #17 — FAIL / NO-GO at
  `42764d8427ab5a1d3897f697ca7c0947e61c3e6b`
- #19 — FAIL / NO-GO at
  `464dac091b8623aa3d3b6923b9b41c398d61cdb7`
- #20 — SCOPED PASS at
  `4198361392865b1c3f800c4cf8f42f12af39154e`

The failed heads materially hardened immutable-history storage, schema audit,
evidence encoding, state-kind consistency, and exact datetime representation.

### Current admission

- #23 — stale review target
- #25 — FAIL / NO-GO at
  `6d1f25cc94255c3d564456359953125ca985cf92`
- #26 — FAIL / NO-GO at
  `18881898853e78e498e259ff85d57d577b5c3c43`
- #27 — FAIL / NO-GO at
  `a41c31f42316d4d65ad524b8aa996e6e92c7a2a5`
- #29 — SCOPED PASS at
  `145198fdb7a60c789b6cd612e9983ac7e874e56d`

These failures hardened process isolation, leased database binding, canonical
Living trust-root reads, and admission transaction ordering.

### Current suppression and historical timing

Slice 3A:

- #33 — FAIL / NO-GO at
  `94dd9bb1fad1e6797b0cc1d811081e4a9bc7e489`
- #34 — FAIL / NO-GO at
  `eef0afdb474ffd5227770b02ae01f66da7bc7e03`
- #35 — FAIL / NO-GO at
  `3d2b2a299a84e573a68fc33e891df60ffc155dea`
- #36 — FAIL / NO-GO at
  `e16d19df8134d5798615fc88665b4c67c5624dd4`
- #37 — SCOPED PASS at
  `7ab54d4db2ae8006c967f5198ae546143f5ae513`

Slice 3B1 / accumulated trust boundary:

- #40 — FAIL / NO-GO at
  `4900a6159b4c7f1bd3b5cc5da1793e6db9552931`
- #41 — FAIL / NO-GO at
  `d866684b1e59df26cf4b4589020f823f3af84113`
- #42 — FAIL / NO-GO at
  `68ff15cb2b026aaf3a318ca26b2c0603a19c6a5b`
- #43 — FAIL / NO-GO at
  `710e1bf54d4433835b22ea3ff72c095d2364990f`
- #44 — FAIL / NO-GO at
  `4431db8ffba16bf5ddbebf04c7c4814cc67825fd`
- #45 — SCOPED PASS at
  `eeb76df2f192f3dbbc4d8586a306bdf80871cbcf`

These reviews hardened append-only timing evidence, index/trigger/schema trust,
one-database-reality transaction boundaries, store-domain admission, and the
rule that absence of a stop row is permission only after suppression trust is
established.

### Current resolver

- author self-review rejected
  `d1dc4663f4e5cfbfa150e015adf184800b2fe6b1` for omitting admission;
- #50 — FAIL / NO-GO at
  `3da3abd49f25cc3a7af59e39cc1302d87291fb46` for treating durable admission
  audit as semantic admission proof;
- #51 — PASS WITH NON-BLOCKING FINDING at
  `d05a4f4f691edaba16f4548e111c5f26cbedff44`; the finding was read-side
  create-on-open;
- #52 — SCOPED PASS at
  `77d27af25be1e0a95f6a6bc8f99f2a26156628ea` after read-only-open
  remediation.

### Wake Packet

- #55 — stale review target
- #57 — FAIL / NO-GO at
  `3cf6a41dc98ccaf15958d16604576d823c5c9447`
- #58 — FAIL / NO-GO at
  `34acfe30d0d021220cb7691ec39b64d693b7a55f`
- #59 — FAIL / NO-GO at
  `0ea9ac64c1ea7225304014447db656b2f86745e2`
- #60 — FAIL / NO-GO at
  `3f4cb30c897a33805131a5eaab9a083a85dc2f2d`
- #61 — FAIL / NO-GO at
  `ff495957eb14ed9e0400d351495904e3347767ff`
- #62 — SCOPED PASS at
  `b61194d09f09a903f4f17f3b2a17489ecb73d77d`

These failures hardened provenance/privacy representation, aggregate conflict
semantics, Room/key identity preservation, standing/evidence consistency, and
temporal cut integrity.

### Wake Issuance

- #65 — FAIL / NO-GO at
  `941b11af3bcddee3257943b6c40745747697db4f`
- #66 — FAIL / NO-GO at
  `1529219d06f9217d67346a9e51b1ede7a48b014a`
- #67 — SCOPED PASS at
  `8659554b781cc7f26174950e8db39cc356c718d6`

These failures hardened exact issuer/origin identity, operation-receiver
binding, and opening-state dependency binding.

### Wake Presentation

- #70 — FAIL / NO-GO at
  `5c467fb34b7137372bfc9f6de441960d8cc67b49`
- #71 — SCOPED PASS at
  `63fe9537e768b4c4e7a998e275b30f1d2a88081c`

The failure established that curated rendering payload equality was not enough:
complete public typed semantics must be bound independently of display
projection.

### Wake Local Handoff Ordering

- #74 — FAIL / NO-GO at
  `5cf37e52f6ad96a28d07a1ed9d1f811caf917c06`
- #75 — FAIL / NO-GO at
  `2b71b9728df38f43df4d28dcbbd3a7e44809ef93`
- #76 — SCOPED PASS at
  `9b02ec90d9414934e50f1100f2432bc7534c7453`

The failures hardened contended same-thread Memory re-entry and the requirement
that handoff use the exact canonical path-registry coordinator object, not a
same-path lookalike.

### Wake Model Input

- #79 — FAIL / NO-GO at
  `4b414e7872c7e9797992a3a661db69db1eb37a2b`
- #80 — FAIL / NO-GO at
  `e8ab5910d95f535c1c7266e34b8707b354f642c1`
- #81 — SCOPED PASS at
  `41b15cb6ad72fb3ed879febd58948277e374604a`

The failures hardened exact live representation metadata: first value agreement
for `media_type`, then runtime-type agreement for both `media_type` and
`serialized_text`.

## 6. Latest exact-head evidence

Latest independently reviewed head:

`41b15cb6ad72fb3ed879febd58948277e374604a`

Independent gate:

[#81 — SCOPED PASS](https://github.com/vivianloading/memory-core/issues/81)

Author CI on that exact head:

- GitHub Actions run #438 / run id `37423852941`
- Python 3.11 compile: GREEN
- Python 3.11 full unit suite: GREEN
- Python 3.11 portable migration rehearsal: GREEN
- Python 3.12 compile: GREEN
- Python 3.12 full unit suite: GREEN
- Python 3.12 portable migration rehearsal: GREEN
- real personal data: CLOSED

Independent #81 evidence additionally reported:

- exact-head source/contract blobs verified against the Git tree;
- #79/#80 representation failures independently reproduced as historical
  controls and rejected on the final head;
- 152 bounded-sweep check records plus the minimal proof controls;
- completed-handoff-only source validation;
- fixed policy / six-NONE authority validation;
- adversarial carried strings remaining data;
- deterministic complete-semantic serialization;
- independent digest recomputation;
- old-handoff-vs-fresh-handoff temporal behavior;
- exact-origin/process/fork controls;
- no network/model execution capability in the new layer.

The reviewed head tree equals the snapshot anchor tree exactly.

## 7. Wake spine at the anchor

The merged Wake spine is:

`WakePacket`
-> `IssuedWakePacket`
-> `WakePresentationPlan / RenderedWakePresentation`
-> `WakeHandoffEnvelope / WakeHandoffReceipt`
-> `HomeModelInputRequest / ConstructedHomeModelInput`

Each transition narrows a different question:

- Packet: what typed material may be carried.
- Issuance: whether the carried packet came from the live canonical HOME
  runtime/state boundary.
- Presentation: how carried material is represented without upgrading it into a
  current speaker.
- Local Handoff: whether the exact rendered artifact was accepted under one
  stable same-process supported-writer cut.
- Model Input: whether one exact accepted handoff became one exact typed,
  deterministic, non-executable model-facing data artifact under fixed HOME
  policy.

No layer in this spine grants model execution.

## 8. Portability and process scope

Portable deployment remains an architectural requirement.

At this anchor:

- canonical HOME state remains SQLite-based for this line;
- portable migration rehearsal remains part of author CI;
- the reviewed head passes the existing portable migration rehearsal on Python
  3.11 and 3.12;
- host migration remains technical evidence, not identity evidence;
- process-local admission/issuance/handoff/model-input registries intentionally
  do not survive restart as live authority;
- Wake Local Handoff ordering is same-process only;
- a separately started process has its own coordinator/generation;
- raw SQLite/private bypasses are outside the supported-writer ordering claim.

Open portability tracker:

[#4 — Define portable HOME deployment contract for laptop to Mac mini moves](https://github.com/vivianloading/memory-core/issues/4)

Issue #4 remains open at the snapshot anchor.

## 9. Deliberate non-claims and open boundaries

This snapshot does **not** claim that HOME currently has:

- network delivery of Wake/model input;
- provider-specific request construction;
- model execution or invocation;
- proof that an external model will obey HOME's data/instruction separation;
- prompt-injection resistance of an arbitrary future model;
- model response provenance;
- model tools;
- model-triggered memory write;
- current-first-person generation safety after execution;
- cross-process Wake handoff ordering;
- durable/restart-safe handoff or model-input authority receipts;
- raw-SQLite coordination against unsupported writers;
- restore/unsuppress semantics;
- Shared Current admission/governance;
- a Shared Now producer;
- Recent Life producer;
- Nearby Doors producer;
- relationship-state automation;
- identity continuity determination;
- production inhabitant-policy establishment;
- real personal data;
- production readiness.

The six Wake/model-input authority axes remain NONE:

- instruction authority;
- current-first-person speech authority;
- identity-continuity claim authority;
- relationship-claim authority;
- model-delivery authority;
- memory-write authority.

Real personal data remains CLOSED.

## 10. Known engineering boundaries worth preserving

The following are intentional boundaries, not accidental omissions:

- durable admission audit cannot recreate a live admission receipt;
- resolver cannot infer admission from durable storage membership;
- a suppressed value is not deleted and an older value does not resurrect;
- historical suppression timing is explicit evidence and cannot be silently
  healed;
- Wake Packet assembly receipts are not a second model-context channel;
- old issuance is historical provenance, not present freshness;
- Presentation policy metadata proves what HOME granted to the artifact, not
  what an arbitrary future model will obey;
- Local Handoff ends before network/model work;
- Local Handoff's generation is process-local ordering evidence only;
- Model Input consumes an already completed handoff and does not reopen the
  ordering cut;
- Model Input construction does not refresh an old handoff from newer HOME
  state;
- deterministic model-input serialization is local evidence, not a provider
  request;
- model-input construction receipts are process-local exact-construction
  evidence, not delivery credentials.

## 11. Snapshot interpretation

This snapshot records what the code at the exact anchor can truthfully claim.

It must not be used as:

- identity evidence;
- Room participation authority;
- Current truth by itself;
- model instruction authority;
- model-delivery authority;
- relationship-state authority;
- real-data permission;
- production-readiness certification.

Historical FAILs remain part of the construction record because they explain
why the final implementation contains several otherwise non-obvious guards.

Future work may add new layers, but it must not silently rewrite this snapshot
to make those layers appear to have existed at this anchor.
