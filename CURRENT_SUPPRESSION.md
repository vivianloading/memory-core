# HOME Current Suppression v0.1 — Present-Use Boundary

Status: DRAFT IMPLEMENTATION LAYER

This slice sits above immutable Current persistence and Room Current admission.

Its job is deliberately narrow:

> Preserve historical Current evidence while preventing suppressed source
> lineage from participating in present or future operational use.

This is not a Current resolver, an unsuppress mechanism, or historical replay.

## Core distinction

HOME keeps these facts separate:

1. the Current effect was historically recorded;
2. the Current effect was admitted through valid authority at that time;
3. the effect is still permitted to participate in present use now.

Source suppression changes (3).

It does not rewrite (1) or (2).

A state or end event therefore remains available through audit APIs after one
of its source bindings is suppressed.

The durable Current row, evidence bindings, Room attachment provenance, and
admission audit row are not deleted or rewritten.

## Explicit present-use decisions

Slice 3A derives one read-only decision for each persisted Current effect:

- `usable`
- `suppressed`

A suppressed decision exposes the exact blocking provenance:

- source_ref;
- source_id;
- suppression_id.

The projection is snapshot-scoped and read-only.

Suppression propagates **forward through already-persisted Current dependency**:

- a state's direct evidence can block that state;
- a blocked state also blocks every persisted superseding descendant that
  semantically depends on it;
- a blocked target state also blocks persisted end events that depend on that
  target;
- an end event's own suppression does not propagate backward into its target
  state.

Inherited blocks retain the exact source_ref/source_id/suppression_id and the
origin effect id/kind that introduced the blocked evidence. This makes the
reason inspectable instead of reducing lineage stop-use to one opaque boolean.

It does not silently drop effects from history.

## Suppression is not resurrection

A suppressed successor does not automatically make an older superseded parent
current again.

That would conflate two unrelated operations:

- stopping use of evidence;
- asserting that an older semantic state has regained standing.

Slice 3A therefore does not call the Current resolver with suppressed rows
removed.

Future Current resolution must consume present-use eligibility explicitly and
define any resulting `unknown`, `no_current`, or conflict semantics without
manufacturing historical resurrection.

## Operational receipt propagation

A live CurrentAdmissionReceipt is process-local operational authority tied to
one exact persisted effect.

If that effect later depends on a suppressed source, the receipt remains a
historical fact but loses present operational usability.

The live receipt boundary therefore rechecks Current present-use eligibility.

Consequences:

- a suppressed parent receipt cannot authorize a later supersession;
- a suppressed target receipt cannot authorize a later end event;
- public live-receipt validation fails closed after source suppression;
- durable admission audit remains readable and unchanged.

For effect-producing admission operations, the usability check happens inside
the same SQLite transaction that will write the new effect. Current admission
uses `BEGIN IMMEDIATE`, while source suppression is also a write, so stop-use
cannot commit between predecessor/target authorization and effect commit.

Read-only public receipt validation is only a snapshot claim. A later effect
must revalidate inside its own effect transaction.

## Suppression ledger

Synthetic `source_suppressions` is one-way in this slice.

The supported schema installs and audits append-only guards against:

- UPDATE;
- DELETE;
- INSERT OR REPLACE of an existing suppression.

Present-use decisions fail closed if those guards or the suppression ledger
shape are altered.

The suppression ledger is also `WITHOUT ROWID`. HOME previously learned on
Current persistence that append-only triggers which guard only semantic keys can
still be bypassed by an implicit SQLite rowid replacement channel. Slice 3A does
not repeat that mistake.

`MemoryStore.initialize()` accepts exactly one historical suppression-table
shape for upgrade: the pre-Slice-3A schema already present on `main`. It
migrates that exact shape to `WITHOUT ROWID` while preserving every suppression
record. Unknown or modified look-alike schemas are not normalized or repaired;
they fail closed.

An already-upgraded `WITHOUT ROWID` ledger must also arrive at
`MemoryStore.initialize()` with all append-only guards intact. Initialization
does not silently recreate a missing/altered guard, because doing so could hide
a prior window in which stop-use history was mutable. Fresh databases and the
one exact legacy migration are the only paths that install these guards.

This does not claim that arbitrary programs with direct filesystem/SQLite
control are transformed into authorized HOME callers. It ensures the supported
HOME boundary can mechanically detect when its stop-use ledger is no longer a
trustworthy basis for use decisions.

## Historical audit remains distinct

Audit reads intentionally continue to reconstruct suppressed Current history.

This is necessary for:

- provenance inspection;
- review;
- debugging;
- later historical replay work.

"Can be audited" does not mean "may be used now."

## No historical suppression as-of yet

The legacy synthetic suppression record has no persisted suppression timestamp.

Slice 3A therefore makes only a present-use claim.

It does not answer:

> Was this source already suppressed at historical time T?

That requires a future lifecycle event model with explicit recorded time and
deterministic as-of semantics.

Until then, suppression is evaluated as current operational stop-use only.

## No restore / unsuppress yet

Slice 3A defines no supported restore or unsuppress operation.

Future restore semantics must not be implemented as deleting the suppression
row. They will require their own explicit authority, provenance, lifecycle and
replay rules.

## Boundaries / non-claims

This slice is synthetic/local only.

It does not authorize:

- real personal data;
- Shared Current governance;
- production Current resolution or delivery;
- Wake / Heartbeat;
- relationship-state behavior;
- identity continuity;
- historical suppression replay;
- restore / unsuppress;
- merge.

The guiding rule is:

> Past existence is historical fact.
> Present use is a separate permission.
> Stop-use revokes the latter without falsifying the former.
