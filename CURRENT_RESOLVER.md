# HOME Current Resolver v0.1 — Present Standing Integration

**Status:** DRAFT IMPLEMENTATION LAYER; synthetic/local only; no model delivery; real personal data CLOSED.

Issue: #46

## Purpose

Current View already defines the semantic meaning of present standing.
Current persistence stores its immutable inputs. Current present-use classifies
whether persisted effects may still participate in operational use after source
stop-use.

The resolver joins those layers without collapsing them.

> **Semantic standing answers what the history means. Present-use eligibility
> answers whether HOME may rely on the effects that make that answer true now.**

Suppression is therefore not a semantic edit, deletion, negation, or fallback
instruction.

## Core rule: overlay, never filter-and-rerun

The resolver MUST NOT remove suppressed state/end rows and rerun Current View.

Filtering first would manufacture new semantics. In particular:

- suppressing a superseding child could make its predecessor look current again;
- suppressing an end event could make its target look current again;
- suppressing one conflict participant could silently choose the other as a
  winner.

Those are semantic changes. Stop-use alone has no authority to assert them.

The resolver instead:

1. derives Current semantic standing from the complete trusted history known at
   the explicit `as_of`;
2. identifies the exact persisted effects on which that semantic answer depends;
3. overlays present-use eligibility for those effects;
4. exposes the semantic answer only when every required effect remains usable;
5. otherwise returns an explicit blocked/unknown operational result with exact
   suppression provenance.

The complete semantic resolution remains available inside the typed decision for
audit/debugging. A later delivery boundary MUST NOT present a blocked semantic
resolution as current model context.

## Time

The resolver accepts an explicit timezone-aware `as_of`.

No ambient clock is read.

`as_of` controls Current semantic time: record visibility, validity intervals,
staleness and effective end events.

Suppression eligibility is intentionally **present-use** eligibility from the
current canonical stop-use ledger. Historical questions about what stop-use HOME
knew at an earlier time belong to `SuppressionAsOfStore` /
`HistoricalCurrentUseStore`, not this resolver.

A caller that wants "now" must supply its explicit current instant.

## Coherent read boundary

One resolution uses one SQLite read snapshot.

Inside that snapshot HOME must establish:

- synthetic-store domain trust;
- Living schema/data integrity;
- Current schema/data integrity;
- canonical suppression-ledger integrity.

History reconstruction, semantic derivation and present-use decisions all occur
against that same database reality.

A past trust check is not sufficient.

## Result axes

The resolver keeps semantic standing separate from operational usability.

`CurrentResolverStatus`:

- `resolved` — every effect required by the semantic answer is presently usable;
- `blocked_unknown` — at least one required effect is stopped from present use.

`CurrentStanding` remains unchanged and continues to mean semantic standing.

A `blocked_unknown` result has no usable standing/value for downstream delivery,
even though its `semantic_resolution` remains inspectable internally.

## Dependency set v0.1

For one key at one `as_of`, the conservative dependency set is:

- every semantic head candidate returned by Current View;
- every effective end event attached to those candidate heads.

State present-use evaluation already carries inherited suppression from
supersession ancestors. Therefore a head whose lineage depends on a stopped
ancestor is blocked without separately making every historical ancestor a
top-level dependency.

Effects that cannot affect this key's semantic answer do not block it merely
because they are suppressed:

- other keys;
- historical non-head effects outside the selected head lineage;
- future effects not participating at the explicit `as_of`.

This rule is deliberately conservative around ambiguity. If suppression touches
an effect that participates in conflict/end/current derivation, v0.1 returns
`blocked_unknown`; it does not simplify the semantic problem by deleting that
effect.

## No resurrection

Examples:

### Suppressed successor

History:

A -> B

B is the semantic head. If B becomes suppressed:

- A does not become current;
- B remains the semantic head in audit history;
- present resolver status becomes `blocked_unknown`.

### Suppressed end event

History:

A -> END(A)

If the effective end event becomes suppressed:

- HOME does not assert A is current again;
- HOME also may not rely on the stopped end evidence;
- present resolver status becomes `blocked_unknown`.

### Suppressed conflict participant

If semantic Current View has two eligible heads A and B and B becomes
suppressed:

- HOME does not choose A;
- the historical conflict is not rewritten;
- present resolver status becomes `blocked_unknown`.

## Provenance

Every blocked result carries exact `CurrentSuppressionBlock` provenance from
the existing present-use layer:

- source_ref;
- source_id;
- suppression_id;
- origin effect kind;
- origin effect id.

Duplicate inherited blocks may be deduplicated for presentation only when every
field is identical. Provenance must not be weakened to an opaque boolean.

## What resolved means

`resolved` does not mean `CurrentStanding.CURRENT`.

A safe semantic result can legitimately be:

- current;
- last_known;
- unresolved;
- expired;
- ended;
- conflicting;
- no_current;
- unknown.

`resolved` only means HOME can rely on the exact effects needed to state that
semantic result under the present-use boundary.

## Non-goals

Current Resolver v0.1 does not provide:

- model/Wake delivery;
- prose rendering or pronoun choice;
- restore/unsuppress;
- deletion/reversal of stop-use;
- implicit fallback/resurrection;
- Shared write admission/governance expansion;
- relationship automation;
- Heartbeat/proximity;
- identity continuity;
- real personal data;
- merge authorization.

## Review rule

After author stabilization, freeze one exact head and apply #18:

**Fresh discovery -> Minimal proof -> Bounded coverage sweep.**

Independent review should attack the dependency set, snapshot/trust ordering and
all ways suppression might accidentally manufacture a different semantic answer.
