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

The first snapshot is the pre-persistence / pre-Wake semantic baseline after
Living continuity, Room participation authority, and Current View v0.1 were
merged into main.
