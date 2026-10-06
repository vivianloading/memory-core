# HOME Engineering Snapshot — 2026-10-06


Snapshot id: `2026-10-06-post-wake-model-input-baseline`

## 1. Exact anchor

This snapshot describes the repository state at:

- repository: `vivianloading/memory-core`
- branch at capture: `main`
- anchor commit: `951f35763069f4e5787c173f1ecb8cc7b7ce3759`
- anchor tree: `7a58e00d41233b9b9911c51e9e0f3b153e9e66d9`
- anchor commit message: `Merge PR #78: Add Wake Model Input Boundary v0.1`
- anchor parents:
  1. prior `main`: `41f8810748ccb32999c05e626ec61464f037db88`
  2. exact reviewed PR #78 head: `41b15cb6ad72fb3ed879febd58948277e374604a`

The exact reviewed PR #78 head has the same Git tree as the anchor merge commit:

- reviewed head tree: `7a58e00d41233b9b9911c51e9e0f3b153e9e66d9`
- anchor merge tree: `7a58e00d41233b9b9911c51e9e0f3b153e9e66d9`

The later commit that may add this snapshot document to the repository is not the
state being described. The anchor remains the exact pre-snapshot tree above.

This is an engineering construction baseline. It is not a release label,
production-readiness certificate, identity verdict, relationship-state verdict,
model-behavior guarantee, or real-data enablement.

## 2. Why this snapshot exists

The previous formal engineering snapshot froze HOME before Current persistence
and before Wake.

At the present anchor, a materially different construction phase has completed.

HOME now has a reviewed local path from durable Current history and live
admission through suppression-aware Current resolution into a typed Wake, then
through exact runtime issuance, deterministic presentation, request-bound local
handoff ordering, and finally a typed model-facing input artifact.

The implemented path is:

```text
canonical history
  -> authority-aware Current admission
  -> suppression-aware Current resolution
  -> Wake Packet
  -> Wake Issuance
  -> Wake Presentation
  -> Wake Local Handoff
  -> Wake Model Input


```
The path deliberately stops before network delivery or model execution.  
That stopping point is a meaningful engineering boundary. The next step would cross from locally constructed, typed, auditable artifacts into actual model execution / provider-facing delivery semantics. This snapshot exists to freeze the local Wake spine before that boundary is crossed.  
The earlier snapshot remains append-only construction history. This snapshot does not rewrite it as if the present architecture had always existed.  
## 3. Construction map since the pre-persistence snapshot  
**3.1 Current persistence Slice 1**  
Merged PR: #15  
* reviewed head: 4198361392865b1c3f800c4cf8f42f12af39154e  
* merge commit: ede9610fd1c9a6da6fcef32044bdf7021c3964a4  
* independent gate: #20  
* final verdict: **SCOPED PASS**  
What it establishes:  
* Current state and end-event history can be persisted without persisting a preselected "present winner";  
* evidence bindings are typed and auditable;  
* state/end rows are immutable append-only history;  
* schema and data integrity are audited on supported read/write paths;  
* persisted history remains evidence for semantic Current derivation rather than a durable assertion that one state is currently true;  
* storage presence does not itself prove operational admission authority;  
* synthetic/local domain remains the supported scope.  
Historical review lineage is preserved. #16, #17 and #19 remain historical FAIL / NO-GO records on their own exact heads.  
**3.2 Room Current authority-aware admission Slice 2**  
Merged PR: #22  
* reviewed head: 145198fdb7a60c789b6cd612e9983ac7e874e56d  
* merge commit: be74dbed0e8686337a316d378220ccbe8c3abe71  
* independent gate: #29  
* final verdict: **SCOPED PASS**  
What it establishes:  
* Room Current writes require live Room participation authority;  
* admission is bound to exact Episode / Perspective / Room / scope provenance;  
* effect write and durable admission audit occur in one transaction while the relevant Room grant hold remains active;  
* a process-local live admission receipt is required for later operational use;  
* durable admission audit is corroborating history, not a credential;  
* old/raw/schema-valid Current rows are not grandfathered into operational authority;  
* Shared admission remains closed in this slice.  
Historical review lineage remains part of the construction record: #23 is stale; #25, #26 and #27 remain FAIL / NO-GO on their own exact targets.  
**3.3 Current suppression present-use Slice 3A**  
Merged PR: #31  
* reviewed head: 7ab54d4db2ae8006c967f5198ae546143f5ae513  
* merge commit: 557ea3720eba31758f518000c6f991be8293678f  
* independent gate: #37  
* final verdict: **SCOPED PASS**  
What it establishes:  
* source suppression blocks present operational use without deleting history;  
* suppression propagates from supporting evidence into dependent Current state and relevant downstream effects;  
* a suppressed successor does not cause an older predecessor to resurrect;  
* live Current admission receipt consumption rechecks present usability;  
* suppression affects present use while immutable historical records remain available for audit.  
Historical #33, #34, #35 and #36 review failures remain preserved.  
**3.4 Deterministic suppression lifecycle / historical as-of Slice 3B1**  
Merged PR: #39  
* reviewed head: eeb76df2f192f3dbbc4d8586a306bdf80871cbcf  
* merge commit: dd297511aaa3d29e30bea3e49ac15424368e00cb  
* independent gate: #45  
* final verdict: **SCOPED PASS**  
What it establishes:  
* suppression has explicit effective_at and recorded_at semantics;  
* historical queries use an explicit as_of, not ambient current time;  
* a suppression recorded later is not treated as known at an earlier historical cut;  
* legacy suppression records without typed timing remain explicitly timing_unknown;  
* present use remains conservative when suppression timing is unknown;  
* source-level and Current-level historical suppression results retain typed timing/provenance status;  
* suppression schema migration is one-way and audited;  
* suppression does not introduce restoration or fallback semantics.  
Historical #40, #41, #42, #43 and #44 FAIL / NO-GO records remain part of the construction evidence.  
**3.5 Current Resolver v0.1**  
Merged PR: #47  
* reviewed head: 77d27af25be1e0a95f6a6bc8f99f2a26156628ea  
* merge commit: 60a0152878bbc96b77c1a2ff0c7f087cb5b0a06f  
* final narrow gate: #52  
* final verdict: **SCOPED PASS**  
What it establishes:  
* semantic Current is derived from admitted history first;  
* present-use suppression is an overlay on the semantic result rather than a deletion/filter followed by re-running semantic history;  
* suppression therefore cannot make a superseded older state become Current;  
* durable admission audit is not sufficient operational admission proof;  
* exact live Current admission receipts are required for operationally usable admitted history;  
* missing live admission proof is represented explicitly rather than silently accepted;  
* the read path is read-only and does not create a missing canonical database.  
Review lineage remains explicit: author NO-GO on `d1dc4663f4e5cfbfa150e015adf184800b2fe6b1`; #50 FAIL / NO-GO on its own exact head; #51 PASS WITH NON-BLOCKING FINDINGS on predecessor `d05a4f4f691edaba16f4548e111c5f26cbedff44`; and #52 SCOPED PASS on the final read-only-open repair head above. None of those earlier verdicts is rewritten or silently extended.  
## 4. Wake spine at the anchor  
**4.1 Wake Packet v0.1**  
Merged PR: #54  
* reviewed head: b61194d09f09a903f4f17f3b2a17489ecb73d77d  
* merge commit: bed8e247eb5fed58f54952dca96dfbabbf1e0384  
* independent gate: #62  
* final verdict: **SCOPED PASS**  
Wake Packet is a typed carriage artifact with five fixed layers:  
1. Map  
2. Shared Now  
3. Room Now  
4. Recent Life  
5. Nearby Doors  
At this anchor:  
* Map is READY structural orientation for the concrete Episode;  
* Shared Now is CLOSED;  
* Room Now is available only through a valid attached Room Current path;  
* Recent Life is UNAVAILABLE;  
* Nearby Doors is UNAVAILABLE.  
Important semantics:  
* typed shape is not operational producer proof;  
* Map remains Episode-scoped even when the Episode attaches to a Room;  
* Room Now remains Room-scoped;  
* blocked / missing-proof values and inactive non-carried heads cannot leak through omission or receipt side channels;  
* Current conflict remains one conflict aggregate; no winner is selected;  
* candidate semantic identity and standing evidence are retained strongly enough to prevent relabelling into a different Room/key/standing;  
* past Perspective attribution stays past Perspective attribution;  
* identity continuity remains unassessed;  
* all six Wake authority axes are NONE:  
    * instruction authority;  
    * current-first-person speech authority;  
    * identity-continuity claim authority;  
    * relationship-claim authority;  
    * model-delivery authority;  
    * memory-write authority.  
A short form:  
**carry != speak**  
Historical review failures materially shaped the substrate:  
* #55 froze an earlier Packet target but became STALE before independent review and carries no verdict;
* #57 forced recursive type/privacy/enum/Perspective/time integrity into the typed layer;  
* #58 made aggregate conflict consistency mechanical;  
* #59 prevented one key-level conflict from being split into multiple non-conflicting items;  
* #60 preserved Current namespace / owner / key semantic identity through Wake;  
* #61 made standing re-derivable from retained validity/end evidence rather than a freely relabelled field.  
Those failures remain scoped to their own exact SHAs. #62 is the final merged Packet gate.  
**4.2 Wake Issuance v0.1**  
Merged PR: #64  
* reviewed head: 8659554b781cc7f26174950e8db39cc356c718d6  
* merge commit: d0f7b1da3986eaa2debad25b0836bde6c2182a97  
* independent gate: #67  
* final verdict: **SCOPED PASS**  
Wake Issuance turns canonical live HOME state into an exact IssuedWakePacket.  
The issuance boundary establishes:  
* public issuance input is only episode_id;  
* the issuer owns canonical runtime dependencies rather than trusting caller-provided readers;  
* Episode / continuity / route / attached Room Current are observed through one coherent read-only/query-only SQLite snapshot;  
* the issuance clock is sampled once for the cut;  
* source suppression and missing live Current admission proof withhold affected Room Now values rather than fabricating availability;  
* issuance does not write canonical HOME state;  
* one process-local origin witness binds the exact authority object and its opening dependencies;  
* issuance receipts bind exact Packet / assembly provenance;  
* a historical issuance can remain verifiably historical after HOME changes, but that verification is not present freshness.  
Two historical FAILs materially changed the design:  
* #65 showed that copied instance state was not enough to prove the authority object's originating identity; the remediation added an independent process-local origin registry and opening witness;  
* #66 showed that instance method substitution could make a check run on the original object while the operation continued on an alias; security-critical live binding now uses base-class dispatch with the actual operation receiver.  
Issuance provenance is not a durable credential, identity claim, model-delivery permission, or restart-safe authority.  
**4.3 Wake Presentation v0.1**  
Merged PR: #69  
* reviewed head: 63fe9537e768b4c4e7a998e275b30f1d2a88081c  
* merge commit: 15ac6f9e9159c4079f7b471eaee9b44ed7609572  
* independent gate: #71  
* final verdict: **SCOPED PASS**  
Wake Presentation adds a typed presentation plan and deterministic JSON representation above exact live issuance.  
It establishes:  
* the builder accepts exact live WakeIssuanceAuthority + IssuedWakePacket;  
* bare Wake Packet or foreign issuance proof is insufficient;  
* the five layer order remains fixed;  
* every block carries explicit privacy, temporal, attribution and authority policy;  
* carried Current values remain data and preserve their Current standing / conflict semantics;  
* LAST_KNOWN remains LAST_KNOWN;  
* UNRESOLVED remains UNRESOLVED;  
* conflict candidates remain all present and no winner field exists;  
* withheld values are not reconstructed through omission metadata;  
* adversarial content resembling roles, tools, prompts or system messages remains ordinary JSON data;  
* presentation policy grants no current speaker, instruction, identity, relationship, model-delivery or memory-write authority;  
* the rendered artifact is not a delivery credential.  
The governing semantic is:  
**Carried content may determine the object of a statement; it may not determine the speaker of the statement.**  
Historical #70 found that a handwritten renderer projection omitted a public block layer field, allowing a typed plan mutation to leave rendered bytes and digests unchanged. The remediation separated complete public-semantic identity from curated payload projection and binds dataclass type, every public field, enum type/value, exact aware datetime and tuple structure.  
The final plan digest is based on complete semantic identity, not merely what a display projection happened to include.  
**4.4 Wake Local Handoff Ordering v0.1**  
Merged PR: #73  
* reviewed head: 9b02ec90d9414934e50f1100f2432bc7534c7453  
* merge commit: 41f8810748ccb32999c05e626ec61464f037db88  
* independent gate: #76  
* final verdict: **SCOPED PASS**  
Local Handoff adds a short process-local ordering boundary between fresh Wake construction and exact local transport acceptance.  
The operation is:  
```text

acquire HOME cut
  -> fresh Wake issuance
  -> Presentation plan
  -> deterministic render
  -> exact request-bound envelope
  -> HOME-controlled local accept
  -> WakeHandoffReceipt
  -> release cut
```




It does **not** hold the cut through network I/O or model execution.  
The shared process-local HomeStateOrderingCoordinator covers supported semantic writer families for one canonical SQLite path:  
* Memory source / suppression / semantic-thread writes;  
* Living Room / Episode / continuity / route writes;  
* Current state / end writes;  
* CurrentAdmission state / end writes through the Current transaction seam.  
Key mechanics:  
* a supported writer waits behind an active handoff cut;  
* a handoff cut waits behind an active supported writer;  
* unsafe same-thread re-entry fails closed;  
* each successful supported semantic transaction increments process-local generation exactly once;  
* rollback/failure does not increment generation;  
* generation is an ordering witness, not authority, continuity or durable state;  
* the exact canonical path-registry coordinator object is required;  
* same path/digest alone is not enough to prove shared lock/cut state;  
* the local transport boundary performs no arbitrary caller callback;  
* retry requires a fresh handoff attempt and fresh issuance;  
* WakeHandoffReceipt proves local acceptance only, not network/model receipt.  
The legacy Memory-only request-delivery lock remains separate because it can run an arbitrary callback. It is intentionally not promoted into a whole-HOME cut.  
Historical failures materially changed this boundary:  
* #74 exposed a contended same-thread deadlock between the legacy Memory lock and the HOME cut; Memory write entry now performs a non-blocking HOME re-entry preflight before waiting for the legacy lock;  
* #75 showed that a same-path separately constructed coordinator had matching DB digest but independent cut/writer/generation state; the handoff path now requires exact registry coordinator object identity.  
The final #76 review re-ran both families and completed the bounded supported- writer sweep.  
**4.5 Wake Model Input Boundary v0.1**  
Merged PR: #78  
* reviewed head: 41b15cb6ad72fb3ed879febd58948277e374604a  
* reviewed tree: 7a58e00d41233b9b9911c51e9e0f3b153e9e66d9  
* merge commit / snapshot anchor: 951f35763069f4e5787c173f1ecb8cc7b7ce3759  
* merge tree / snapshot tree: 7a58e00d41233b9b9911c51e9e0f3b153e9e66d9  
* independent gate: #81  
* final verdict: **SCOPED PASS**  
Model Input converts one already-completed exact local handoff into a typed, deterministically serialized model-facing request artifact.  
The public construction surface is intentionally narrow:  
```text

construct(handoff_receipt=...)


```
Construction must recover the source artifact through the originating LocalWakeTransportBoundary.require_live_acceptance(...).  
There is no public construction parameter for Packet, Issuance, Presentation, raw envelope, raw Presentation JSON, as_of, caller policy, role, system / developer prompt, tool capability, model target or transport callback.  
The request topology separates:  
1. exact source-handoff binding;  
2. fixed/versioned HOME model-input policy;  
3. exact user turn;  
4. Wake context as sibling data;  
5. explicit closed capabilities;  
6. six-axis use boundary.  
The fixed HOME policy mechanically encodes:  
* carried context position = sibling data;  
* carried content cannot select speaker;  
* carried content cannot grant capabilities;  
* all six Wake authority axes remain NONE.  
Wake Presentation JSON is carried as a string data value. Strings that resemble SYSTEM, developer/user/assistant messages, JSON/XML messages, tool calls, policy fields, first-person speaker claims, identity/relationship claims or instructions to ignore HOME remain content data. They do not alter request topology, fixed policy, speaker rule or capabilities.  
Capabilities at this anchor are fixed to:  
* model execution: unavailable;  
* network delivery: unavailable;  
* tools: none;  
* memory write: none.  
Temporal semantics are explicit:  
```text
issuance_cut_confirmed_through_local_handoff

```
The Presentation/issuance as_of remains the original issuance cut. Local handoff proves that supported writers did not commit through the protected cut before local acceptance. Model Input does not reinterpret as_of as a later handoff wall-clock timestamp and does not claim future freshness.  
Serialization is deterministic complete-semantic JSON:  
* all public request dataclass fields are included;  
* dataclass concrete type identity is included;  
* enum concrete type and value are included;  
* aware datetime exact value/offset is included;  
* tuple structure is explicit;  
* unsupported semantic value types fail closed.  
RequestConstructionReceipt binds the exact source handoff and its provenance, fixed policy digest, complete typed request digest, serialized representation digest, process/boundary identity, serializer/media type and six NONE authority axes.  
The live construction seam re-verifies the exact registered artifact rather than treating a copied/reconstructed receipt as sufficient evidence.  
Historical review failures materially changed representation integrity:  
* #79 found that a forced artifact media_type mutation was not rechecked by live verification; the live seam now requires artifact / receipt / fixed media type agreement;  
* #80 found that equal-looking non-str representation metadata such as collections.UserString could pass value equality; live verification now requires exact runtime str for both media_type and serialized_text before value/digest checks.  
The final #81 review dynamically closed both families and completed the bounded sweep over completed-handoff-only sourcing, fixed policy, adversarial carried strings, deterministic complete-semantic serialization, exact receipt recomputation, origin/process binding, old-vs-fresh handoff temporal behavior, and capability absence.  
Model Input is still a local construction artifact. It is not network delivery or model execution.  
## 5. End-to-end invariants frozen at this snapshot  
The following statements are engineering invariants of the anchored tree.  
**History / Current**  
* durable history is not a persisted present winner;  
* operational Current admission requires exact live authority;  
* durable admission audit is not a credential;  
* suppression stops present use without deleting history;  
* suppression does not resurrect a superseded predecessor;  
* semantic Current is derived before present-use suppression is overlaid;  
* missing live proof is explicit and cannot be silently treated as authority.  
**Wake carriage**  
* Wake carries typed evidence and standing; it does not mint speaker authority;  
* Map route is not Room authority;  
* Room attachment is not identity evidence;  
* continuity evidence does not decide identity continuity;  
* conflict remains conflict and no Wake layer selects a winner;  
* historical first-person attribution remains attributed history rather than present first-person speech;  
* unavailable/blocked values cannot leak through receipt/omission side channels;  
* Shared Now remains closed; Recent Life and Nearby Doors remain unavailable.  
**Issuance / Presentation**  
* exact issuance provenance is not present freshness;  
* exact authority object and opening dependencies are process-bound;  
* Presentation can determine representation but not speaker authority;  
* complete semantic identity is stronger than a curated display projection;  
* renderer output and receipts are not model-delivery credentials.  
**Local handoff ordering**  
* local handoff protects one same-process supported-writer cut;  
* a locally accepted envelope corresponds to one real same-process canonical cut under the supported-writer contract;  
* the cut ends at local transport acceptance;  
* HOME does not freeze all writers through network/model execution;  
* coordinator path/digest equality is insufficient; the exact canonical registry object matters;  
* process-local generation is only an ordering witness.  
**Model-facing input**  
* only a completed exact local handoff may feed model-input construction;  
* Model Input does not silently refresh an old handoff from newer HOME state;  
* a fresh HOME state requires a fresh handoff to appear in a fresh model-input artifact;  
* HOME policy is fixed/versioned and not constructed by Wake content;  
* carried Wake content is sibling data;  
* carried data cannot select speaker or grant capabilities;  
* adversarial role/tool/policy-looking strings remain data;  
* request semantic identity includes concrete types, not only equal-looking values;  
* attested representation fields outside the typed request semantic digest also require exact runtime representation type;  
* a construction receipt proves construction and serialization, not model delivery or obedience.  
A short cross-layer form:  
**Route is not authority. Authority is not identity. Current is not recency. Suppression is not deletion. Carriage is not speech. Issuance is not freshness. Presentation is not delivery. Local handoff is not model execution. Model input is not model behavior.**  
## 6. Final exact-head review gates merged into the anchor  

| Slice | PR | Reviewed head | Independent gate | Merge commit |
| ----------------------- | --- | ---------------------------------------- | ---------------- | ---------------------------------------- |
| Current persistence | #15 | 4198361392865b1c3f800c4cf8f42f12af39154e | #20 SCOPED PASS | ede9610fd1c9a6da6fcef32044bdf7021c3964a4 |
| Current admission | #22 | 145198fdb7a60c789b6cd612e9983ac7e874e56d | #29 SCOPED PASS | be74dbed0e8686337a316d378220ccbe8c3abe71 |
| Suppression present-use | #31 | 7ab54d4db2ae8006c967f5198ae546143f5ae513 | #37 SCOPED PASS | 557ea3720eba31758f518000c6f991be8293678f |
| Suppression as-of | #39 | eeb76df2f192f3dbbc4d8586a306bdf80871cbcf | #45 SCOPED PASS | dd297511aaa3d29e30bea3e49ac15424368e00cb |
| Current Resolver | #47 | 77d27af25be1e0a95f6a6bc8f99f2a26156628ea | #52 SCOPED PASS | 60a0152878bbc96b77c1a2ff0c7f087cb5b0a06f |
| Wake Packet | #54 | b61194d09f09a903f4f17f3b2a17489ecb73d77d | #62 SCOPED PASS | bed8e247eb5fed58f54952dca96dfbabbf1e0384 |
| Wake Issuance | #64 | 8659554b781cc7f26174950e8db39cc356c718d6 | #67 SCOPED PASS | d0f7b1da3986eaa2debad25b0836bde6c2182a97 |
| Wake Presentation | #69 | 63fe9537e768b4c4e7a998e275b30f1d2a88081c | #71 SCOPED PASS | 15ac6f9e9159c4079f7b471eaee9b44ed7609572 |
| Wake Local Handoff | #73 | 9b02ec90d9414934e50f1100f2432bc7534c7453 | #76 SCOPED PASS | 41f8810748ccb32999c05e626ec61464f037db88 |
| Wake Model Input | #78 | 41b15cb6ad72fb3ed879febd58948277e374604a | #81 SCOPED PASS | 951f35763069f4e5787c173f1ecb8cc7b7ce3759 |
  
Each verdict remains scoped to its exact reviewed head and its stated nonclaims. The merge commits do not expand the review scope.  
## 7. Latest regression and migration evidence  
For the final reviewed Model Input head 41b15cb6ad72fb3ed879febd58948277e374604a:  
* GitHub Actions run number: **#438**  
* workflow run id: 37423852941  
* Python 3.11 compile: SUCCESS  
* Python 3.11 full unit suite: SUCCESS  
* Python 3.11 portable migration rehearsal: SUCCESS  
* Python 3.12 compile: SUCCESS  
* Python 3.12 full unit suite: SUCCESS  
* Python 3.12 portable migration rehearsal: SUCCESS  
Independent gate #81 additionally performed a fresh exact-head review on Python 3.12.14 with separate reviewer-authored dynamic controls. It reports:  
* #79 different-text representation mutation rejected;  
* #80 same-text non-str media_type rejected;  
* same-text non-str serialized_text rejected;  
* bounded coverage completed after minimal proof;  
* 152 bounded checks recorded in the independent sweep, plus the explicit minimal-proof controls;  
* exact source / contract copies verified against their Git-tree blobs before and after review;  
* no product code change, push, PR-state change or merge performed by the reviewer.  
The anchor merge commit itself has no separate GitHub Actions run.  
Instead, the final reviewed head and the anchor merge commit have the exact same Git tree:  
```text
7a58e00d41233b9b9911c51e9e0f3b153e9e66d9

```
This snapshot records that tree identity explicitly rather than claiming the merge SHA itself was independently executed.  
## 8. Process and portability scope  
At this anchor, several important proofs are intentionally process-local.  
Examples include:  
* Current live admission receipt registries;  
* Wake Issuance origin and exact receipt registries;  
* HOME state ordering coordinator identity / generation;  
* Wake Local Handoff acceptance registry;  
* Wake Model Input construction registry.  
Process-local proof is not a durable credential and is not cross-process synchronization.  
The implementation remains SQLite-centered for this line and continues to run the portable two-hop synthetic migration rehearsal in CI.  
The supported mini-host configuration uses a relocatable `runtime_root`; the database path is configuration-relative and must remain inside that root. Closed synthetic backup / restore validates bundle and SQLite integrity, binds the database by hash / length, and refuses unsafe overwrite.  
The current GitHub Actions workflow runs on `ubuntu-latest` for Python 3.11 and 3.12. It does **not** prove a real macOS / Mac mini relocation yet. Secret providers remain disabled in this milestone; a future destination host should re-bind secrets through an explicit provider rather than treating machine credentials as portable semantic state.  
The portable deployment contract remains open:  
#4 — Define portable HOME deployment contract for laptop to Mac mini moves  
Technical host/runtime movement remains infrastructure evidence. It is not subject-identity evidence.  
## 9. Deliberate non-claims at this snapshot  
This snapshot does **not** claim that HOME currently has:  
* actual network/model delivery of Wake Model Input;  
* provider-specific request formatting;  
* model receipt, read, obedience or response proof;  
* prompt-injection resistance of an arbitrary future model;  
* model-behavior safety;  
* tool execution authority;  
* memory-write authority from model input;  
* a safe current-first-person generation boundary after model execution;  
* cross-process Wake handoff ordering;  
* raw SQLite coordination outside supported writer paths;  
* durable/restart-safe handoff generation;  
* durable/restart-safe issuance or construction receipts;  
* restart-safe recreation of live Current admission authority;  
* Shared operational Current / Shared Now governance;  
* Recent Life producer/policy;  
* Nearby Doors producer/policy;  
* Heartbeat / proximity behavior;  
* Adoption implementation;  
* relationship-state automation;  
* identity continuity classification;  
* real personal data enablement;  
* production readiness.  
The six Wake authority axes remain NONE through Packet, Issuance, Presentation, Handoff and Model Input. That is an artifact/authority statement, not a claim that an arbitrary future model will obey the intended separation.  
## 10. Known engineering debt and next gate  
The main engineering debt at this anchor is no longer "how to get Wake state into a typed local artifact." That local spine now exists.  
The next design frontier is **provider / execution semantics**. The first slice does not need to cross into live network or model execution: a thin local typed Execution Contract / dry-run adapter is a current candidate, not a frozen design.  
Whatever implementation is chosen must not silently weaken the local guarantees frozen here.  
At minimum, a future execution boundary must answer:  
* how the exact live RequestConstructionReceipt / constructed artifact is consumed without reconstructing from older Packet/Issuance/Presentation components;  
* how fixed HOME policy and Wake sibling data are mapped into a real model API without carried data becoming system/developer/instruction authority;  
* what request-bound freshness means after the Local Handoff cut has already released;  
* what local event counts as "transport accepted", "network sent", "provider accepted", "model received" and "model execution completed";  
* how retries distinguish transport retry / provider retry / execution retry from
  a fresh semantic Wake attempt, and when freshness requires a new handoff and
  construction rather than replay of an older artifact;
* how exact provider-facing request bytes and any provider / transport
  identifiers are bound back to the exact live `RequestConstructionReceipt`
  without reconstructing policy or Wake context from older layers;
* how transport acceptance, network send, provider acceptance, model receipt,
  execution start, execution completion, cancellation, timeout and partial
  failure are represented as distinct typed events rather than collapsed into
  one ambiguous "delivered" state;
* how a provider or model response is bound to the exact request that produced
  it without turning response text or provider metadata into Current,
  first-person, identity, relationship, tool or memory-write authority;
* how any future tool or memory-write capability is admitted through a separate
  explicit authority boundary rather than inferred from model output, model
  confidence, prior handoff provenance or transport success;
* how restart / multi-process behavior is handled without promoting
  process-local handoff, construction or execution witnesses into durable
  credentials.

This snapshot deliberately does not choose those answers. It freezes the local
pre-execution contract so that future execution work can be reviewed against a
stable baseline rather than silently redefining the meaning of the artifacts
already merged.

A future execution slice should therefore begin from the exact live
`RequestConstructionReceipt` / registered constructed artifact. It should not
reconstruct a request from older Packet, Issuance, Presentation or Handoff
components and then claim equivalent provenance.

## 11. Primary code landmarks at the anchor

The following paths are the main implementation landmarks for the construction
frozen by this snapshot. This list is an orientation aid, not an exhaustive
module inventory.

**History / Living / Current**

- `src/home_memory_core/storage.py` — source persistence and suppression-backed
  storage used by the reviewed Current path;
- `src/home_memory_core/living_store.py` — Room / Episode / continuity / route
  persistence used by Wake route resolution;
- `src/home_memory_core/living_authority.py` — live Room participation authority
  used by Current admission;
- `src/home_memory_core/current_store.py` — append-only Current state / end-event
  persistence;
- `src/home_memory_core/current_admission.py` — authority-aware Room Current
  admission and process-local live admission proof;
- `src/home_memory_core/current_resolver.py` — admitted semantic Current
  derivation followed by present-use suppression overlay.

**Wake spine**

- `src/home_memory_core/wake_packet.py` — five-layer typed Wake carriage;
- `src/home_memory_core/wake_issuance.py` — exact runtime issuance and
  process-local issuance provenance;
- `src/home_memory_core/wake_presentation.py` — typed presentation plan,
  complete-semantic plan identity and deterministic JSON representation;
- `src/home_memory_core/home_state_ordering.py` — shared same-process ordering
  coordinator used by supported semantic writers and Local Handoff;
- `src/home_memory_core/wake_local_handoff.py` — fresh request-bound local
  handoff, exact local acceptance and `WakeHandoffReceipt`;
- `src/home_memory_core/wake_model_input.py` — completed-handoff-only typed
  model-input construction, fixed HOME model-input policy, deterministic
  complete-semantic serialization and `RequestConstructionReceipt`.

**Slice contracts / earlier baselines**

- `WAKE_LOCAL_HANDOFF.md` — Local Handoff v0.1 engineering contract and review
  lineage;
- `WAKE_MODEL_INPUT.md` — Model Input v0.1 engineering contract and review
  lineage;
- `snapshots/2026-10-02-pre-persistence-baseline.md` and its JSON companion —
  the earlier append-only construction baseline;
- `snapshots/README.md` — snapshot interpretation / repository convention.

## 12. Snapshot maintenance contract

This file is an append-only construction baseline for the exact anchor in
Section 1.

Capture provenance is intentionally small here: this baseline is being recorded
post-anchor through Issue #82 / PR #83. Those capture mechanics are not part of
the anchored tree. The JSON companion carries the detailed #82/#83 binding;
`snapshots/README.md` records the earlier #48 / PR #49 attempt as superseded and
never merged.

The following maintenance rules apply:

- the anchor commit and anchor tree are immutable facts of this snapshot;
- a later commit that adds or edits this snapshot file does not become the
  described anchor;
- later implementation must not cause this snapshot to be silently rewritten as
  if later mechanisms already existed at the anchor;
- exact-head review verdicts remain scoped to the exact heads they reviewed;
- historical FAIL / NO-GO records remain construction evidence even after later
  remediations pass;
- a later PASS does not retroactively convert an earlier failed head into a
  passing one;
- if a factual correction to this snapshot is ever required, record the
  correction explicitly rather than erasing review lineage;
- if derived snapshot prose conflicts with the exact anchored Git tree or the
  exact-head review artifacts, the anchored code / Git evidence and scoped
  review records control;
- future construction phases should create a later snapshot or explicit
  superseding record rather than treating this baseline as a live-state oracle.

Nothing in this snapshot grants runtime authority. Snapshot metadata is not
Current, identity evidence, Room authority, model instruction, model-delivery
permission or memory-write permission.

## 13. Baseline closure

At anchor commit
`951f35763069f4e5787c173f1ecb8cc7b7ce3759`, tree
`7a58e00d41233b9b9911c51e9e0f3b153e9e66d9`, HOME has a reviewed local Wake
spine from authority-aware Current through exact typed model-input construction.

The anchored tree can:

```text
persist / admit / resolve Current
  -> carry a typed Wake
  -> issue it from one coherent live cut
  -> present it without minting speaker authority
  -> locally hand it off under supported-writer ordering
  -> construct and attest an exact typed model-facing input artifact
```

The anchored tree cannot yet claim:

```text
network send
  -> provider acceptance
  -> model receipt
  -> model execution
  -> model behavior
```

That boundary is intentionally still unopened.

The engineering baseline frozen here is therefore:

> **HOME can carry reviewed local state into an exact model-facing artifact
> without promoting carried history into present speaker / instruction /
> identity / relationship / delivery / memory-write authority. Actual model
> execution remains a separate future gate.**

This snapshot is suitable as the regression baseline for that next gate.