# HOME Current Resolver v0.1 — Present Standing Integration

**Status:** DRAFT IMPLEMENTATION LAYER; synthetic/local Room Current only; no model delivery; real personal data CLOSED.

Issue: #46

## Purpose

Current View defines semantic present standing. Current persistence stores its
immutable inputs. Current admission records which Room effects actually crossed
the live authority boundary. Current present-use records whether those admitted
effects may still be used after source stop-use.

The resolver composes those layers without collapsing them.

Two distinctions are essential:

> **Persisted history is not automatically admitted semantic history.**

and:

> **Suppression is not semantic negation, deletion, or fallback authorization.**

## Order of operations

For one explicit timezone-aware `as_of`, inside one coherent SQLite read
snapshot, v0.1:

1. establishes synthetic-domain, Living, Current persistence, Current admission
   and suppression-ledger integrity;
2. reconstructs the subset of persisted Room Current state/end effects that have
   exact durable admission audit records;
3. derives ordinary Current View semantics from that **admitted history**;
4. identifies the exact admitted effects on which the semantic answer depends;
5. overlays present-use suppression eligibility for those effects;
6. exposes the semantic answer only when every dependency remains usable;
7. otherwise returns explicit `blocked_unknown` with exact stop-use provenance.

This ordering is deliberate.

## Admission filtering is allowed; suppression filtering is not

Admission and suppression answer different questions.

### Unadmitted persisted rows

A structurally valid persisted row that never crossed Current admission is
storage/audit history only. It never acquired operational semantic standing.

Therefore it is excluded **before** Current View derivation.

Examples:

- a raw/unadmitted child cannot supersede an admitted parent for present Current;
- a raw/unadmitted competing head cannot manufacture a Current conflict;
- a raw/unadmitted end event cannot end an admitted state.

This is not resurrection. The excluded effect was never admitted into the
operational semantic history.

Durable admission audit is used here only as evidence that the historical effect
crossed authority when it was created. It is **not** a credential for a new
write and does not recreate a process-local CurrentAdmissionReceipt.

### Suppressed admitted rows

An admitted effect did participate in semantic history. Later stop-use does not
erase that fact or authorize a replacement semantic assertion.

Therefore the resolver MUST NOT delete/filter suppressed admitted rows and rerun
Current View.

Filtering suppressed history could:

- revive a superseded predecessor;
- revive a state whose end event was stopped;
- choose a winner from a historical conflict.

v0.1 instead keeps the admitted semantic answer intact for audit and marks its
present operational result `blocked_unknown` when a required dependency is
suppressed.

## Namespace boundary

Current Resolver v0.1 is **Room-only**.

Shared Current admission remains CLOSED because HOME has no concrete Shared
operational governance primitive yet. A semantic label such as
`shared_governance` cannot mint authority.

Requests for `CurrentNamespace.SHARED` fail closed. Shared semantic/persisted
history does not become operational Current merely because it exists.

## Time

The resolver accepts an explicit timezone-aware `as_of`; it never reads the
ambient clock.

`as_of` controls Current semantic time: record visibility, validity intervals,
staleness and effective end events.

Suppression eligibility is intentionally **present-use** eligibility from the
current canonical stop-use ledger. Historical questions about what stop-use HOME
knew at an earlier time belong to `SuppressionAsOfStore` /
`HistoricalCurrentUseStore`.

A caller that wants "now" must supply its explicit current instant.

## Coherent read boundary

One resolver call uses one SQLite read snapshot.

Inside that snapshot HOME establishes:

- synthetic-store domain trust;
- Living schema/data integrity;
- Current persistence schema/data integrity;
- Current admission schema/data integrity;
- canonical suppression-ledger integrity.

Admission classification, semantic derivation and present-use decisions therefore
belong to one database reality.

## Result axes

`CurrentResolverStatus` is separate from `CurrentStanding`:

- `resolved` — all admitted effects required by the semantic answer remain
  presently usable;
- `blocked_unknown` — at least one required admitted effect is stopped from use.

`CurrentStanding` retains its semantic meaning.

A blocked decision exposes no `usable_standing` or
`usable_current_state_ids`. Its complete semantic answer is kept only as
`audit_resolution` for inspection and later review; a delivery boundary must
not present that audit object as current model context.

A safe `resolved` result can itself have semantic standing current,
last_known, unresolved, expired, ended, conflicting, no_current, or unknown.

## Dependency set v0.1

For one admitted key at one `as_of`, the conservative dependency set is:

- every semantic head candidate returned by Current View;
- every effective end event attached to those candidate heads.

State present-use evaluation already carries inherited stop-use from admitted
supersession ancestors.

Other keys, future effects and persisted-but-unadmitted effects do not enter the
dependency set.

If suppression touches a participating conflict/end/current effect, v0.1 returns
`blocked_unknown`; it does not simplify the semantic problem by deleting that
effect.

## Exact blocking provenance

Every blocked result retains exact existing `CurrentSuppressionBlock`
provenance:

- source_ref;
- source_id;
- suppression_id;
- origin effect kind;
- origin effect id.

Identical inherited blocks may be deduplicated for presentation only.

## Non-goals

Current Resolver v0.1 does not provide:

- model/Wake delivery;
- prose rendering or pronoun choice;
- restore/unsuppress;
- deletion/reversal of stop-use;
- suppression-driven fallback/resurrection;
- Shared Current admission/governance;
- restart-safe recreation of live admission receipts;
- relationship automation;
- Heartbeat/proximity;
- identity continuity;
- real personal data;
- merge authorization.

## Review rule

After author stabilization, freeze one exact head and apply #18:

**Fresh discovery -> Minimal proof -> Bounded coverage sweep.**

Independent review should attack both sides of the boundary:

- unadmitted persistence must never become operational Current;
- suppression must never manufacture a different semantic answer.
