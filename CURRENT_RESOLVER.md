# HOME Current Resolver v0.1 — Present Standing Integration

**Status:** DRAFT IMPLEMENTATION LAYER; synthetic/local Room Current only; process-local admission proof only; no model delivery; real personal data CLOSED.

Issue: #46

## Purpose

Current Resolver composes three distinct questions without collapsing them:

1. **Admission proof:** which persisted Room Current effects can HOME prove were actually issued through the live CurrentAdmissionAuthority in this HOME process?
2. **Semantic Current:** what standing does Current View derive from that admitted history at one explicit `as_of`?
3. **Present-use suppression:** may HOME still rely on the exact admitted effects required by that semantic answer?

The governing rules are:

> Persisted history is not automatically admitted semantic history.

> Durable admission audit is provenance, not an operational credential.

> Suppression is not semantic negation, deletion, or fallback authorization.

## Issue #50 — durable audit alone is not admission proof

Independent review #50 returned **FAIL / NO-GO** on exact head
`3da3abd49f25cc3a7af59e39cc1302d87291fb46`.

The failed head selected semantic inputs by durable membership in
`current_state_admissions` / `current_end_admissions` after structural
integrity checks.

That was insufficient. The admission binding digest is intentionally a plain
deterministic checksum, not a signature/MAC/secret-bound credential. A
storage-only row could therefore be paired with a manufactured but internally
consistent durable admission row and become operational semantic Current even
though no live admission receipt had ever been issued.

The current design fixes the boundary rather than strengthening the checksum
into an accidental credential.

### v0.1 admission proof

Current Resolver must be opened against one live `CurrentAdmissionAuthority`.

Only `CurrentAdmissionReceipt` objects that:

- were actually issued and registered by that exact live authority;
- remain bound to the exact HOME process incarnation;
- match their exact durable audit row and effect digest;

may authorize effects to enter Current semantic derivation.

The durable audit row corroborates a live receipt. It never substitutes for one.

A package-internal authority seam exposes this exact live receipt set for
resolution. That seam deliberately does **not** apply source-suppression
present-use checks, because suppression must be overlaid only after semantic
history has been derived.

## Restart boundary is explicit

v0.1 does **not** recreate live admission receipts from durable audit after
process restart.

If durable admission-shaped history relevant to the requested key exists but
the current live authority lacks matching process-local receipts, the resolver
returns:

`admission_proof_unavailable`

with the exact affected effect ids.

It does not:

- reinterpret the durable audit as authority;
- silently ignore formerly admitted history and choose a newer/older answer;
- report ordinary semantic `unknown` as if nothing had been admitted.

This is intentionally restrictive. Restart-safe Current resolution remains a
future boundary that needs authenticated durable authority semantics.

Durable admission rows are used without live receipts only in the fail-closed
direction: their presence can make resolution unavailable, but can never
authorize semantic inclusion.

## Raw unadmitted history

Persisted effects with no durable admission shape and no live receipt remain
audit/storage history only.

They cannot:

- become current;
- supersede an admitted parent;
- end an admitted state;
- manufacture a conflict.

This remains distinct from the restart case above.

## Suppression overlay

For live-receipt-backed admitted history, Current View derives semantic standing
from the complete admitted history first.

The resolver then identifies semantic dependencies and evaluates current
present-use suppression.

It MUST NOT remove suppressed admitted rows and rerun Current View.

Otherwise stop-use could manufacture:

- predecessor resurrection;
- ended-state revival;
- conflict winner selection.

A suppressed required dependency therefore produces
`blocked_unknown` with exact `CurrentSuppressionBlock` provenance and no
usable standing/current state ids.

## Result statuses

`CurrentResolverStatus` is separate from semantic `CurrentStanding`:

- `resolved` — semantic result is safe for present use;
- `blocked_unknown` — a required admitted semantic dependency is presently stopped;
- `admission_proof_unavailable` — durable admission-shaped history exists but the current process lacks exact live admission proof.

Only `resolved` exposes `usable_standing` and
`usable_current_state_ids`.

## Time and snapshot

The caller supplies one explicit timezone-aware `as_of`; no ambient clock is
read.

One resolver operation uses one coherent SQLite read snapshot covering:

- synthetic-store domain trust;
- Living schema/data integrity;
- Current persistence integrity;
- Current admission integrity;
- suppression-ledger integrity;
- durable corroboration of the live receipt set;
- semantic derivation;
- suppression decisions.

Process-local receipt registry state is sampled conservatively against that
snapshot. A receipt that cannot be corroborated by the snapshot fails closed.

## Namespace boundary

v0.1 is **Room-only**.

Shared Current operational resolution remains CLOSED until HOME has a concrete
Shared governance admission primitive. A semantic
`shared_governance` label cannot mint authority.

## Dependency set v0.1

For one resolved key:

- every semantic head candidate;
- every effective end event attached to those candidates.

State present-use already propagates suppression from supersession ancestors.

Other keys and future effects do not poison the selected present answer.

## Historical construction evidence

Author self-review had already rejected earlier exact head
`d1dc4663f4e5cfbfa150e015adf184800b2fe6b1` for omitting admission entirely.

Independent review #50 then rejected
`3da3abd49f25cc3a7af59e39cc1302d87291fb46` for treating durable admission
audit as sufficient proof.

Neither failed head is rewritten by later remediation.

## Non-goals

v0.1 does not provide:

- restart-safe recreation of admission proof;
- model/Wake delivery;
- prose rendering or pronoun choice;
- restore/unsuppress;
- suppression-driven fallback/resurrection;
- Shared governance/admission;
- relationship automation;
- Heartbeat/proximity;
- identity continuity;
- real personal data;
- merge authorization.

## Review rule

After author stabilization, freeze a new exact head and apply #18:

**Fresh discovery -> Minimal proof -> Bounded coverage sweep.**

The next independent review should reproduce the #50 manufactured-durable-audit
class and attack the live-receipt / durable-corroboration / restart boundary
without treating author tests or CI as proof.

## Issue #51 non-blocking finding — read means no create-on-open

Independent re-review #51 returned **PASS WITH NON-BLOCKING FINDINGS** on exact
head `d05a4f4f691edaba16f4548e111c5f26cbedff44`.

The finding was narrow but real: `CurrentStore._read_connection()` used an
ordinary `sqlite3.connect(path)` before enabling `query_only`. If the canonical
database file had disappeared, SQLite could create a zero-byte file at that path
before HOME failed the domain/integrity checks.

That did not mint Current or authority, but it violated a cleaner read invariant:

> **A read-only resolver must not create the database it is trying to read.**

The post-#51 remediation opens Current read connections with SQLite URI
`mode=ro`. A missing canonical database therefore fails at open time without
creating a replacement file. A resolver regression moves the canonical DB aside,
asserts the read fails, and asserts the original path remains absent.

Because this changes product code after #51, the #51 verdict remains valid only
for `d05a4f4f691edaba16f4548e111c5f26cbedff44`. The remediation head requires a
new exact-SHA narrow re-review before merge.
