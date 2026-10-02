# HOME Engineering Snapshot — 2026-10-02

Snapshot id: `2026-10-02-pre-persistence-baseline`

## 1. Exact anchor

This snapshot describes the repository state at:

- repository: `vivianloading/memory-core`
- branch at capture: `main`
- anchor commit: `661590f6f71525023fbf2f9d96d3332acfdf774c`
- anchor tree: `fc27da08482a3f70b56e37a29ff55ce0de093d1f`

The anchor is the pre-snapshot tree. The later documentation commit that adds
this file is not the state being described.

The anchor merge commit and the independently reviewed Current View head
`91daaf1bfae4e3bcb5c490bc31daebb22a4d86b3` have the same Git tree
`fc27da08482a3f70b56e37a29ff55ce0de093d1f`. This gives a mechanical link
between the latest exact-head semantic review and the code/content present at the
snapshot anchor.

This is an engineering baseline, not a release, production-readiness claim,
identity claim, or real-data enablement.

## 2. Why this is the first formal snapshot

At this anchor HOME has three merged semantic/operational foundations that form
one coherent pre-persistence / pre-Wake boundary:

1. Living Layer continuity and synthetic persistence.
2. Room participation authority above Living routing.
3. Current View semantic derivation above append-only history.

The next major work will begin connecting semantic Current to durable storage and
then eventually to waking/proximity behavior. That is a qualitatively different
engineering phase: multiple already-reviewed layers will start touching one
another at write/admission/delivery boundaries.

This snapshot freezes the clean state before those integrations begin.

## 3. Construction map at the anchor

### Existing memory-core foundation

The older v0.1 skeleton still supplies the lower-level provenance, revision,
suppression, retrieval/read-only delivery, source-integrity, host/runtime and
portable-migration machinery. The Living/Room/Current slices do not replace
those boundaries.

Important inherited rules remain:

- raw evidence and derived interpretation are distinct;
- history is revised append-only rather than silently rewritten;
- retrieval relevance is not truth or authority;
- suppression/stop-use must propagate rather than allow resurrection;
- first-person attribution remains perspective-scoped;
- historical first-person material is not automatically present instruction.

### Living Layer v0.1

Merged PR: [#2](https://github.com/vivianloading/memory-core/pull/2)

- reviewed head: `ad53f517d3a79b09bd4f0b1ec92327df5ce09308`
- reviewed tree: `684d622e26fdf47e5f9c38a2d60fc2a895abfd58`
- merge commit: `b2ad6b5859221ca442996b6e5aa6691b63bd3a5d`
- merge tree: `684d622e26fdf47e5f9c38a2d60fc2a895abfd58`
- independent gate: [#5](https://github.com/vivianloading/memory-core/issues/5)

What it establishes:

- Room is a living-branch/routing namespace, not an identity record.
- Episode is a concrete runtime/window record.
- every persisted Episode has concrete PerspectiveInstance attribution;
- ContinuityEdge records transfer mechanism separately from evidence certainty;
- persisted v0.1 continuity certainty remains `unknown` only;
- forks are topology, not continuity-status labels;
- RoomAttachmentEvent is append-only and repairable without history rewrite;
- ordinary text handoff may continue in the same Room while continuity remains
  unknown;
- Living persistence is synthetic-only and outside model delivery.

### Room participation authority v0.1

Merged PR: [#7](https://github.com/vivianloading/memory-core/pull/7)

- reviewed head: `2c7c189d0a9fba980cab3ac7800812fa3f07fb9c`
- reviewed tree: `ad0d4a025075a9f4ef47e7b8b619681cab853744`
- merge commit: `d46303039879ecab616af954f569127ededce5f9`
- merge tree: `ad0d4a025075a9f4ef47e7b8b619681cab853744`
- independent gate: [#8](https://github.com/vivianloading/memory-core/issues/8)

What it establishes:

- RoomAttachment is topology, not authority;
- host-observed launch evidence is separate from Room authorization;
- operational continuation may issue a fresh per-Episode grant without proving
  same-self;
- old grants are not transferred between Episodes;
- read/private/first-person/current-stance scopes are distinct;
- continuation policy is branch-anchored and does not silently cross a fork;
- policy issuance provenance, proposal, approval and grant are exact-bound;
- operational suspension is not rewritten as inhabitant intent;
- Adoption is not an access credential;
- identity continuity may remain unknown throughout.

### Current View v0.1

Merged PR: [#10](https://github.com/vivianloading/memory-core/pull/10)

- reviewed head: `91daaf1bfae4e3bcb5c490bc31daebb22a4d86b3`
- reviewed tree: `fc27da08482a3f70b56e37a29ff55ce0de093d1f`
- merge commit / snapshot anchor:
  `661590f6f71525023fbf2f9d96d3332acfdf774c`
- merge tree / snapshot tree:
  `fc27da08482a3f70b56e37a29ff55ce0de093d1f`
- independent gate: [#11](https://github.com/vivianloading/memory-core/issues/11)

What it establishes:

- Current is derived present standing, not the latest row;
- event time, record time, validity time and last-known standing stay distinct;
- Room and Shared Current namespaces stay distinct;
- unknown, last-known, unresolved and conflicting are legitimate results;
- no generic last-write-wins rule resolves competing live heads;
- superseded history does not resurrect merely because a successor expires/ends;
- state kinds have explicit validity contracts;
- commitments, unfinished work and self-interpretation do not silently decay;
- CurrentCandidate retains exact state and effective end evidence;
- temporal ordering is by absolute instant, independent of DST fold or timezone
  representation;
- accepted calendar-edge aware datetimes remain orderable without requiring a
  materializable UTC civil datetime;
- `stale_after` is elapsed duration, not local wall-clock/calendar duration;
- recall frequency, emotional intensity, similarity and importance do not
  become truth inputs;
- Current semantic ownership is not operational Room authority;
- no identity-continuity verdict enters the layer.

## 4. Cross-layer invariants frozen at this snapshot

These are architectural invariants, not metaphysical conclusions.

- Episode boundary does not automatically create an identity boundary.
- Same Room does not prove same self.
- Unknown continuity does not force eviction from a Room.
- Technical transfer mode is evidence about mechanism, not identity.
- Room route says where a living line continues; it does not say what a runtime
  may do there.
- Operational authority is exact-bound to a concrete runtime/session/Episode/
  Perspective/Room/scopes, not to a name, personality or self-claim.
- Perspective attribution says whose concrete first-person act a record is; it
  is not an authentication principal by itself.
- Adoption expresses a current normative choice; it is not an access token and
  is not required every Episode for ordinary continuation.
- Current tells HOME what still has standing now; it does not create authority
  to write that state and does not decide identity.
- Historical truth may be superseded or ended without being erased.
- No new evidence is not automatically evidence of change.
- Retrieval, mention frequency and emotional intensity do not manufacture truth.
- HOME must be repairable without rewriting history: corrections append evidence
  and can change derived views while preserving what was previously recorded.

A short form:

> Route is not authority. Authority is not identity. Current is not recency.
> History can change standing without being rewritten.

## 5. Independent review history

The FAILs below are part of the engineering evidence. They explain why the
current implementation has several otherwise non-obvious guards.

### Living Layer

Review target progression:

- `1a86041608b4bf74549d20b6cf9e41a1405288b0` — FAIL: five persistence/
  provenance integrity classes including REPLACE/UPSERT rewrite, certainty
  injection and schema/phantom-route weaknesses.
- `dd405d12d172c0cc3b740bd7405e67f2737d1d2d` — FAIL: earlier classes
  remediated; new reserved unattributed PerspectiveInstance provenance gap found.
- `ad53f517d3a79b09bd4f0b1ec92327df5ce09308` — PASS for the synthetic v0.1
  Living persistence/migration contract.

Final review evidence:
[PR #2 PASS](https://github.com/vivianloading/memory-core/pull/2#issuecomment-5929298492)

### Room authority

Review target progression:

- `f6fff7a0e9a3845395d1c30c9b1b5729977d2750` — FAIL: trusted policy
  provenance/suspension could be widened/copied; ancestor transfer/Room-route
  barriers could be silently healed downstream.
- `2c7c189d0a9fba980cab3ac7800812fa3f07fb9c` — PASS for the synthetic/local
  Room authority v0.1 contract.

Final review evidence:
[PR #7 PASS](https://github.com/vivianloading/memory-core/pull/7#issuecomment-5941936622)

### Current View

Review target progression:

- `64bbf18bb8138e6ef01ceaf713b90bf861382f53` — FAIL: DST repeated-hour
  comparison and timezone-dependent staleness semantics.
- `d9f93234d522daebbff392babc681706ff049dde` — FAIL: accepted huge
  `stale_after` values could overflow while materializing a future deadline.
- `ea95a9cbb362b357f75b06ba8f58cf6b54f5fb89` — FAIL: accepted aware
  calendar-edge datetimes could overflow while materializing equivalent UTC
  civil datetimes.
- `91daaf1bfae4e3bcb5c490bc31daebb22a4d86b3` — Scoped PASS for the synthetic
  Current View v0.1 semantic contract.

Final review evidence:
[PR #10 Scoped PASS](https://github.com/vivianloading/memory-core/pull/10#issuecomment-5944724528)

These FAILs are not superseded into falsehood by the later PASS. They remain the
construction history that explains the present contract.

## 6. Latest regression and migration evidence

For exact reviewed head
`91daaf1bfae4e3bcb5c490bc31daebb22a4d86b3`:

- GitHub Actions run:
  [36955391388](https://github.com/vivianloading/memory-core/actions/runs/36955391388)
- Python 3.11 job: GREEN
- Python 3.12 job: GREEN
- 547 unit tests: GREEN
- compile: GREEN
- two-hop synthetic portable migration rehearsal: GREEN
- real personal data: CLOSED

The reviewed head tree is byte-for-byte the same Git tree as the snapshot anchor
merge commit tree. No separate workflow run exists for the merge commit itself;
the tree identity is therefore recorded explicitly instead of pretending the
merge SHA was independently executed.

## 7. Portability status

Portability is already an architectural requirement, not a packaging afterthought.

At this snapshot:

- HOME supports a relocatable config/runtime-root model;
- the canonical store remains SQLite for this line;
- portable backup/restore and two-hop synthetic relocation rehearsal exist;
- Living state survives the synthetic relocation rehearsal without changing
  continuity certainty;
- host/runtime migration is technical evidence, not subject-identity evidence;
- real personal data remains closed.

Still open:
[#4 — laptop to Mac mini portability contract](https://github.com/vivianloading/memory-core/issues/4)

The remaining work includes the real Mac mini deployment adapter and later
production host/secrets/access-control decisions without changing memory
semantics.

## 8. Deliberate non-claims and next gates

This snapshot does **not** claim that HOME currently has:

- persisted Current View records in the canonical database;
- a production Current write/admission path;
- a production TrustedRuntimeLaunchIssuer factory;
- a production inhabitant-authorized continuation-policy establishment path;
- a Room content read/write consumer;
- atomic final authorization + Room effect;
- a native checkpoint verifier;
- Wake Packet / Orientation delivery;
- Heartbeat/proximity behavior;
- relationship-state automation;
- AdoptionEvent implementation;
- model delivery of Living/Room authority/Current state;
- cryptographic hostile-host attestation;
- identity continuity classification;
- real personal data.

Each of these crosses a fresh boundary and needs its own contract/review rather
than inheriting authority from this snapshot.

## 9. Known engineering debt at the snapshot

Non-blocking debt worth preserving explicitly:

- `LIVING_LAYER.md`, `ROOM_AUTHORITY.md`, and `CURRENT_VIEW.md` still carry
  the header `Status: DRAFT IMPLEMENTATION LAYER` even though their scoped
  slices are merged. Snapshot/merge state, not that stale header, is authoritative.
- Current v0.1 source refs are semantic references, not yet canonical typed
  provenance bindings.
- Room authority's synthetic policy issuance remains process-local scaffolding,
  not the durable future representation of inhabitant policy.
- whole-Living-graph validation on ordinary read/write is intentionally strict
  and may require performance work later without weakening semantics.
- the existing synthetic unattributed sentinel dependency crosses layer
  boundaries and should not grow into a general authority mechanism.
- no Current persistence schema has been frozen yet; that is deliberate.

Tracker hygiene performed while preparing this snapshot:
[#3](https://github.com/vivianloading/memory-core/issues/3) was closed as
completed because its Living persistence scope was already merged in PR #2.
This metadata change is after the snapshot anchor and does not modify the anchor
tree.

## 10. Recommended next engineering sequence

The next sequence should preserve the current separation of concerns:

1. design Current persistence/admission as a new slice, binding Current semantic
   provenance to canonical Living/provenance/Room-authority records without
   changing the Current semantics that just passed review;
2. independently review persistence before allowing Wake to depend on it;
3. derive Shared Now / Room Now from persisted Current;
4. build Wake Packet as a map/current/recent/nearby-doors view, not a persona
   bootstrap;
5. add proximity/Heartbeat only after Wake can explain why an item is near;
6. complete laptop -> Mac mini portability rehearsal before production-like
   deployment;
7. keep real personal data closed until a separate pre-real-data snapshot and
   explicit enablement gate.

The immediate architectural question after this snapshot is therefore not
"how do we make HOME remember more?" It is:

> How do we persist and admit Current state without turning semantic ownership
> into operational authority, and without letting storage silently rewrite the
> already-reviewed meaning of "now"?

That is the boundary this snapshot exists to protect.
