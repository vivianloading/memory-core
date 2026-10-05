# HOME Suppression As-Of v0.1 — Historical Time Slice

Status: DRAFT IMPLEMENTATION LAYER

Slice 3B1 extends the merged Slice 3A present-use boundary with deterministic
historical suppression timing.

Its purpose is narrow:

> Answer what stop-use evidence had standing at one explicit historical as-of
> instant without importing later knowledge into the earlier view.

This is not restore/unsuppress and is not the production Current resolver.

## Two suppression times

A new timed suppression records:

- `effective_at` — when the stop-use semantically begins in life;
- `recorded_at` — when HOME learned/stored that stop-use evidence.

Both must be timezone-aware.

3B1 requires:

`effective_at <= recorded_at`

A timed suppression participates in the historical view at `as_of=T` only
when both:

- `recorded_at <= T`; and
- `effective_at <= T`.

The second condition states semantic onset explicitly. With the v0.1 causal
constraint it is implied once record time is visible, but keeping both in the
contract prevents future lifecycle extensions from silently collapsing event
and record time.

The key rule is record causality:

> A stop-use learned later cannot appear in an earlier view HOME could not yet
> have known.

A retroactive `effective_at` therefore does not rewrite a historical view
before `recorded_at`.

## No ambient clock

Historical suppression projection always receives an explicit timezone-aware
`as_of`.

All comparisons use the same absolute microsecond scalar semantics as Current
View rather than local-wall ordering.

Equivalent aware timestamps with different offsets therefore select the same
historical cut.

Naive datetimes are rejected.

## Legacy Slice 3A suppression timing

Merged Slice 3A suppression rows did not persist time.

3B1 does not invent timestamps for them.

An existing legacy row:

- still blocks **present operational use** exactly as Slice 3A required;
- yields `timing_unknown` in a historical as-of projection.

This is a legitimate result.

It means:

> HOME knows the source was stopped from use, but does not possess evidence
> establishing when that stop-use entered historical standing.

Unknown is not converted to usable and is not converted to a guessed
suppression date.

## Persistence

The hardened `source_suppressions` ledger remains unchanged.

Temporal evidence is stored in a separate append-only sidecar:

`source_suppression_timing`

Each timing row is keyed by exact `suppression_id` and stores:

- effective absolute instant;
- recorded absolute instant;
- canonical aware datetime encodings for both.

The encoded datetimes and absolute scalars are cross-checked during integrity
audit.

The sidecar is `WITHOUT ROWID` and protected from UPDATE, DELETE and
replacement.

Its integrity audit also rejects user-defined indexes. This is part of the
append-only contract, not cosmetic schema tidiness: an added uniqueness
constraint can change SQLite conflict behavior and create an indirect
replacement path that the canonical guards were not designed to authorize.

Every suppression ledger row has exactly one timing sidecar row in the v0.2
schema.

- newly timed stop-use uses `timing_status='timed'` with exact temporal
  evidence;
- migrated legacy stop-use uses `timing_status='timing_unknown'` with all
  exact time fields NULL.

A missing timing row is therefore corruption, not an alternate spelling of
unknown. Historical projection and supported initialization fail closed rather
than silently turning lost timing evidence into `timing_unknown`.

## Schema completion evidence

Slice 3A used suppression schema marker:

`source-suppression-v0.1`

3B1 evolves it one-way to:

`source-suppression-v0.2`

The accepted transition is:

- exact v0.1 marker + healthy canonical Slice 3A ledger + no timing sidecar
  → install timing sidecar, write one explicit `timing_unknown` row for each
  already-existing suppression, and move marker to v0.2 in one initialization
  transaction.

Fresh stores install v0.2 directly.

Exact pre-Slice-3A legacy ledgers may still traverse the previously admitted
legacy migration and then install the 3B1 timing layer.

Once v0.2 completion evidence exists:

- missing timing sidecar fails closed;
- altered timing table or guards fail closed;
- missing/altered completion marker fails closed;
- initialization does not silently heal those states.

## Source-level historical projection

`SuppressionAsOfStore` answers one source-level question at explicit T:

- `not_suppressed_as_of`
- `suppressed_as_of`
- `timing_unknown`

For a timed suppression recorded after T, the historical answer is
`not_suppressed_as_of` even if its `effective_at` is earlier than T,
because HOME did not know that stop-use evidence at T.

For legacy untimed suppression, the answer is `timing_unknown` because the
persisted sidecar explicitly says timing was not recorded.

The source-level projection does **not** claim that the source itself was known
to HOME at T. The existing synthetic `sources` table has no persisted
`recorded_at`, so 3B1 has no evidence from which to reconstruct source
existence/visibility history. Given a currently persisted source id, this API
answers only the historical standing of its stop-use evidence.

That limitation is deliberate. Source-existence time must not be invented from
suppression time.

## Historical Current-use projection

`HistoricalCurrentUseStore` maps the same source-level time semantics onto
persisted Current effects.

It additionally distinguishes:

- `not_known_as_of` — the Current effect itself had not yet been recorded at T.

A historical list excludes effects whose Current `recorded_at` is after T.
This prevents future effect ids from entering the historical list before HOME
knew them.

Suppression dependency propagation remains the Slice 3A direction:

- direct state evidence → state;
- state → already-persisted superseding descendants;
- target state → dependent end events;
- end-event direct suppression does not propagate backward to the target state.

No historical projection removes a suppressed row and reruns Current View.
Suppression therefore does not implicitly resurrect an older superseded parent.

## Combining definite and unknown stop-use

One Current effect may depend on several sources.

If at least one dependency is definitely suppressed at T, the effect is
`suppressed_as_of`, even if another dependency has legacy unknown timing.

If no dependency is definitely suppressed at T but at least one relevant
suppression has unknown timing, the effect is `timing_unknown`.

Only when neither definite nor unknown historical stop-use blocks are present
is the effect `not_suppressed_as_of`.

Exact block provenance remains inspectable.

## Present use remains conservative

3B1 does not weaken Slice 3A.

Present-use code continues to treat **every** persisted suppression row as
blocking.

New supported suppression writes require explicit `effective_at` and
`recorded_at`; they cannot manufacture a new `timing_unknown` record.
The untimed `SuppressionRecord` shape remains only so migrated historical
evidence can be represented faithfully when read back.

Historical as-of is a read-only explanatory projection. It is not an
operational permission credential and cannot revive a present-use receipt.

## Non-goals

Slice 3B1 does not define:

- restore or unsuppress;
- deletion/reversal of stop-use history;
- production Current resolution or delivery;
- fallback/resurrection semantics;
- Shared governance expansion;
- Wake / Heartbeat;
- relationship-state behavior;
- identity continuity;
- real personal-data use.

The governing principles are:

> Later knowledge may enrich the history HOME can explain now.
> It must not be smuggled backward into what HOME would have known then.

> Unknown is not absence. If HOME claims timing is unknown, that uncertainty
> must itself be represented by durable evidence.
