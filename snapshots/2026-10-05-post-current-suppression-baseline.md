# HOME Engineering Snapshot — 2026-10-05

Snapshot id: `2026-10-05-post-current-suppression-baseline`

## 1. Exact anchor

This snapshot describes:

- repository: `vivianloading/memory-core`
- branch at capture: `main`
- anchor commit: `dd297511aaa3d29e30bea3e49ac15424368e00cb`
- anchor tree: `f94a7d6819d0e4d950cdf29b13307b8054c0fbcd`

The anchor is the state being described. The later documentation commit that
adds this snapshot is not the anchored state.

This is an engineering baseline, not a release, production-readiness claim,
identity claim, model-delivery authorization, or real-data enablement.

## 2. Why this boundary matters

The 2026-10-02 snapshot froze HOME before Current persistence.

At this anchor, the full synthetic/local Current substrate now spans four merged
construction slices:

1. immutable Current persistence;
2. exact Room authority-aware Current admission;
3. source suppression -> Current present-use propagation;
4. deterministic suppression historical as-of.

The next construction phase begins **present Current resolution and then Wake**.
That phase will connect already-reviewed storage/use semantics to a read path
that may eventually become model-visible, so this is a meaningful pre-resolver /
pre-Wake checkpoint.

## 3. Merged Current milestones since the prior snapshot

### Current persistence Slice 1

- PR: #15
- reviewed head: `4198361392865b1c3f800c4cf8f42f12af39154e`
- merge commit: `ede9610fd1c9a6da6fcef32044bdf7021c3964a4`
- independent gate: #20 — SCOPED PASS
- historical independent NO-GO: #16, #17, #19

What it established:

- append-only persisted Current state/end-event history;
- exact typed EvidenceRef binding;
- Room / Episode / Perspective / attachment provenance;
- no persisted `is_current` or winner;
- audit reconstruction without granting operational authority.

### Current authority-aware admission v0.1

- PR: #22
- reviewed head: `145198fdb7a60c789b6cd612e9983ac7e874e56d`
- merge commit: `be74dbed0e8686337a316d378220ccbe8c3abe71`
- independent gate: #29 — SCOPED PASS
- historical review: #23 STALE; #25/#26/#27 FAIL / NO-GO

What it established:

- Room Current writes require exact live RoomParticipationGrant authority;
- authority and effect are bound inside one ordered transaction/lease boundary;
- durable admission audit is provenance, not a credential;
- pre-existing/raw/schema-valid rows are not grandfathered into usable authority;
- Shared Current admission remains CLOSED.

### Current suppression present-use Slice 3A

- PR: #31
- reviewed head: `7ab54d4db2ae8006c967f5198ae546143f5ae513`
- merge commit: `557ea3720eba31758f518000c6f991be8293678f`
- independent gate: #37 — SCOPED PASS
- historical independent FAIL / NO-GO: #33/#34/#35/#36

What it established:

- immutable history remains auditable after stop-use;
- suppression propagates forward through Current semantic dependency;
- present-use carries exact blocking provenance;
- live admission receipts lose usability when their effect becomes suppressed;
- suppression does not implicitly resurrect a superseded parent;
- missing/damaged stop-use evidence fails closed instead of becoming permission.

### Suppression lifecycle + historical as-of Slice 3B1

- PR: #39
- reviewed head: `eeb76df2f192f3dbbc4d8586a306bdf80871cbcf`
- merge commit / snapshot anchor:
  `dd297511aaa3d29e30bea3e49ac15424368e00cb`
- independent gate: #45 — SCOPED PASS
- historical independent FAIL / NO-GO: #40/#41/#42/#43/#44

What it established:

- explicit `effective_at` vs `recorded_at`;
- explicit aware `as_of`; no ambient clock;
- later-learned stop-use cannot rewrite what HOME would have known earlier;
- legacy missing timing remains explicit `timing_unknown`;
- historical suppression projection does not weaken present-use stop;
- source-existence history is not invented when the store lacks evidence for it.

## 4. Cross-layer invariants at this anchor

- History is not present truth.
- Current is derived, not persisted as a selected winner.
- Route is not authority.
- Semantic ownership is not operational permission.
- Audit-readable is not operationally usable.
- Suppression is stop-use, not deletion, negation, or fallback authorization.
- Suppressed successor history does not resurrect a predecessor.
- Unknown evidence remains unknown rather than being guessed.
- Trust checks that authorize interpretation/use belong in the coherent database
  reality of the operation.
- Room first-person state requires concrete Episode + Perspective provenance.
- Shared semantic labels do not mint Shared operational authority.
- Technical/runtime continuity does not decide identity continuity.
- Real personal data remains CLOSED.

## 5. Latest exact-head evidence

For reviewed head
`eeb76df2f192f3dbbc4d8586a306bdf80871cbcf`:

- independent review #45: SCOPED PASS;
- review method: fresh discovery -> minimal proof -> bounded coverage sweep;
- reviewer runtime: Python 3.12.14 / SQLite 3.53.1;
- reviewer bounded run: 651 unit tests PASS plus compile and portable migration
  rehearsal;
- GitHub Actions #313: SUCCESS on Python 3.11 and 3.12 for compile, full unit
  suite and portable migration rehearsal;
- real personal data: CLOSED.

The merge commit changes only merge topology relative to its reviewed second
parent; the snapshot records both exact identities instead of pretending the
merge SHA itself received the independent verdict.

## 6. Deliberate non-claims / open boundaries

At this anchor HOME still does **not** claim:

- a production/present Current resolver above persistence + suppression;
- model delivery of Current;
- Wake Packet / Orientation delivery;
- safe Wake prose/pronoun rendering;
- restore / unsuppress or suppression reversal;
- fallback/resurrection semantics;
- Shared Current write admission/governance;
- restart-safe recreation of live Current admission receipts;
- relationship-state automation;
- Heartbeat/proximity behavior;
- identity continuity classification;
- real personal-data readiness.

## 7. Next gate

The next semantic integration question is:

> How can HOME expose present Current from complete persisted history while
> respecting present-use stop boundaries, without filtering suppressed history
> in a way that manufactures resurrection or a false winner?

That work is tracked after this anchor by Issue #46 and Draft PR #47.

Those items are **post-anchor construction metadata**. They are not part of the
tree described by this snapshot.

After Current Resolver stabilizes and receives independent exact-head review,
the intended next phase is a typed Wake substrate:

`Map -> Shared Now -> Room Now -> Recent Life -> Nearby Doors`

No prose/model delivery should precede an explicit boundary proving that
carried history is not automatically current first-person speech.
