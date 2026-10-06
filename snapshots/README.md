# HOME Engineering Snapshots

Engineering snapshots are append-only construction baselines.

A snapshot records what HOME could truthfully claim at one exact repository
state before crossing a meaningful engineering boundary. It is not a release
label, an identity verdict, a production-readiness certificate, or a substitute
for the exact-head reviews that produced the state.

## Rules

- Every snapshot names one exact anchor commit and tree.
- The anchor is the state being described. The later commit that adds the
  snapshot document does not replace that anchor.
- Historical FAILs remain part of the snapshot record when they materially
  changed the design.
- Review PASS/GO language is scoped exactly as the original review scoped it.
- A snapshot must distinguish implemented behavior from deliberate non-claims
  and future gates.
- Old snapshots are not silently edited to make later architecture look as if
  it had always existed. Corrections append a new snapshot or an explicit
  correction record.
- Snapshot metadata must never be used as identity evidence, Room authority,
  Current truth, model instruction authority, or real-data permission.

## Canonical snapshots

1. `2026-10-02-pre-persistence-baseline`
   - anchor: `661590f6f71525023fbf2f9d96d3332acfdf774c`
   - clean semantic boundary after Living continuity, Room participation
     authority, and Current View v0.1; before Current persistence / Wake.

2. `2026-10-06-post-wake-model-input-baseline`
   - anchor: `951f35763069f4e5787c173f1ecb8cc7b7ce3759`
   - clean engineering boundary after Current persistence/admission/suppression/
     resolver and Wake Packet -> Issuance -> Presentation -> Local Handoff ->
     Model Input; before provider/model execution.

Issue #48 / PR #49 was an intermediate post-Current-suppression capture attempt
that never merged. It remains historical construction metadata and is not a
canonical snapshot on `main`.
