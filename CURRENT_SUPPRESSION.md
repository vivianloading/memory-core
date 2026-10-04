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

## Issue #33 — missing trusted ledger must not look fresh

Independent review #33 returned **FAIL / NO-GO** on exact head
`94dd9bb1fad1e6797b0cc1d811081e4a9bc7e489`.

Fresh discovery found that `MemoryStore.initialize()` treated an absent
`source_suppressions` table as a bootstrap condition even when the database
already carried HOME's trusted synthetic-domain marker.

That meant a damaged initialized store could lose its suppression table,
re-run the supported initializer, receive a new empty ledger and guards, and
silently make previously suppressed Current history usable again. The Current
history itself remained unchanged, so this was an unauthorized present-use
resurrection rather than a historical rewrite.

The remediation makes the distinction **before** synthetic-domain
initialization can create or adopt a marker:

- an unmarked fresh database may create its first suppression ledger;
- an unmarked recognized legacy synthetic database may enter the exact legacy
  compatibility path;
- a database that already arrives with one valid synthetic HOME domain marker
  but lacks `source_suppressions` fails closed;
- real or malformed domain markers remain classified by the existing
  store-domain boundary rather than being misreported as suppression damage.

The important lesson is:

> **Absence is not bootstrap once trust has already been established.**

A trusted stop-use ledger disappearing is evidence of integrity loss, not
permission to manufacture an empty replacement.

The #33 verdict remains historical evidence for its exact SHA. Later fixes do
not rewrite it.

## Issue #34 — one-way migration needs durable completion evidence

Independent review #34 returned **FAIL / NO-GO** on exact head
`eef0afdb474ffd5227770b02ae01f66da7bc7e03`.

Issue #33 had fixed the case where a trusted suppression ledger disappeared
entirely. #34 found the deeper version: an already-upgraded store could have its
ledger replaced with the **exact** pre-Slice-3A legacy table. Because
initialization looked only at the ledger's current SQL shape, it could not tell
that this store had already completed the one-way upgrade.

That allowed a damaged store to re-enter the legacy migration path. If a
suppression row had been lost while the legacy-shaped replacement lacked
guards, supported initialization would bless the remaining empty ledger by
migrating it back to the canonical shape.

The remediation adds an independent durable completion marker:

`source_suppression_schema_marker`

with version:

`source-suppression-v0.1`

The marker is separate from the ledger, `WITHOUT ROWID`, exact-audited, and
protected from UPDATE/DELETE.

The migration state machine is now:

- no completion marker + exact pre-Slice-3A legacy ledger → one admitted
  migration, then install the completion marker;
- completion marker + canonical ledger → normal trusted reopen, with full
  marker/ledger/guard audit;
- completion marker + legacy-shaped ledger → fail closed; a completed upgrade
  cannot re-enter legacy migration;
- canonical ledger + missing completion marker → fail closed rather than
  silently manufacturing migration history;
- fresh/unmarked bootstrap creates the canonical ledger and then records
  completion.

This preserves a broader rule:

> **A one-way migration needs durable evidence that the one-way boundary has
> already been crossed. Current shape alone is not historical provenance.**

The marker is an integrity signal inside HOME's supported local-store trust
model, not a claim that arbitrary filesystem/database rewriting can be made
cryptographically impossible. If all durable evidence is externally rewritten
to an indistinguishable historical snapshot, the local database alone cannot
prove that erased history.

The #34 verdict remains historical evidence for its exact SHA. Later fixes do
not rewrite it.

## Issue #35 — integrity audit and installation need one database reality

Independent review #35 returned **FAIL / NO-GO** on exact head
`3d2b2a299a84e573a68fc33e891df60ffc155dea`.

The suppression ledger and durable migration marker were structurally strong,
but `MemoryStore.initialize()` audited them before calling Python
`sqlite3.executescript()`. That created an audit-to-install scheduling window:
another SQLite writer could remove a suppression guard and stop-use row after
the audit, then the initializer could recreate the missing guard and accept the
remaining empty ledger.

The problem was not missing schema evidence. It was **time**: the audit and the
effect of initialization did not share one continuous write-serialized
database state.

The remediation gives initialization one SQLite `BEGIN IMMEDIATE` boundary
covering:

- incoming trust/domain classification;
- admitted legacy suppression migration;
- schema and guard installation;
- suppression migration-completion marker installation;
- final ledger/marker integrity audit;
- commit.

The initialization path no longer uses `sqlite3.executescript()`, whose
transaction behavior would break that outer boundary. HOME instead executes
the schema statements individually while asserting that the outer transaction
remains active. Store-domain immutability triggers were likewise changed from
`executescript()` to individual `execute()` calls so domain setup cannot
silently end the caller's transaction.

This preserves the rule:

> **An integrity check only authorizes what remains true until the protected
> operation commits. A past check is not present authority.**

For an existing trusted store, concurrent ledger damage must therefore either
happen before initialization acquires the write boundary and be rejected by
preflight, or wait until initialization commits. It cannot occur between
preflight and final acceptance.

The #35 verdict remains historical evidence for its exact SHA. Later fixes do
not rewrite it.

## Issue #36 — wildcard syntax is not a trust boundary

Independent review #36 returned **FAIL / NO-GO** on exact head
`e16d19df8134d5798615fc88665b4c67c5624dd4`.

The unmarked-store classifier intended to ignore SQLite's internal tables with:

`name NOT LIKE 'sqlite_%'`

But SQLite `LIKE` treats `_` as a single-character wildcard. Ordinary user
tables such as `sqliteXpayload` and `sqliteApayload` were therefore hidden
from classification even though they do not begin with the literal internal
prefix `sqlite_`.

That allowed an unmarked database containing an unknown user table to appear
empty/recognized and be adopted as a synthetic HOME store.

The remediation centralizes user-table enumeration in one helper and uses:

`name NOT GLOB 'sqlite_*'`

Here `_` is literal and `*` is the intended suffix wildcard. Both synthetic
legacy classification and domain-marker creation now share this exact rule.

Regression coverage proves that user tables whose names merely match the old
LIKE pattern are visible and rejected, while SQLite's actual
`sqlite_sequence` internal table remains ignored.

The broader lesson is:

> **Pattern syntax is part of the trust model. A predicate that is only
> approximately literal is not safe enough for admission or authority
> classification.**

This defect pre-dated Slice 3A and was not introduced by the initializer
transaction remediation. It still blocks the current review target because
domain classification is a prerequisite of the supported initialization
boundary.

The #36 verdict remains historical evidence for its exact SHA. Later fixes do
not rewrite it.

## Issue #41 — present-use must establish suppression trust before permission

Independent re-review #41 returned **FAIL / NO-GO** on exact head
`d866684b1e59df26cf4b4589020f823f3af84113`.

The review confirmed the Slice 3B1 timing-index remediation, then found an
older Slice 3A boundary defect: `MemoryStore.get_source()` and
`MemoryStore.is_source_usable()` read the surviving
`source_suppressions` rows directly without first establishing that the
suppression ledger was still trustworthy.

That meant a visibly damaged synthetic store could lose a stop-use row while
also retaining evidence of damage such as a missing delete guard and orphaned
timing row. Audited paths correctly rejected the same store, but the two
source-use APIs interpreted the missing row as permission and could revive a
previously stopped source.

The remediation makes the trust dependency explicit:

- the shared present-use suppression-id lookup now audits the full suppression
  ledger before deriving permission from its rows;
- source-use reads run inside one explicit read snapshot, so source evidence,
  ledger trust and the resulting use decision belong to one database reality;
- lineage resolution input also establishes suppression-ledger trust before
  treating missing suppression joins as usable evidence;
- audit-only source reads remain distinct and can still expose persisted source
  history even when suppression integrity is damaged.

Regression coverage preserves the exact #41 class: after a supported stop,
remove the ledger delete guard and suppression row while leaving the damage
detectable. Supported source-use and derived-use paths must raise
`SuppressionLedgerIntegrityError`; they must not reinterpret corruption as
permission.

The broader rule is:

> **Absence can authorize use only after the structure that gives absence
> meaning has itself been trusted. Corruption is not permission.**

The #41 verdict remains historical evidence for its exact SHA. Later fixes do
not rewrite it.

## Issue #42 — trust checks and derived effects need one database reality

Independent re-review #42 returned **FAIL / NO-GO** on exact head
`68ff15cb2b026aaf3a318ca26b2c0603a19c6a5b`.

Issue #41 had made the shared source present-use lookup audit the suppression
ledger before treating a missing suppression row as permission. #42 found the
transactional version of the same rule: for a derived write,
**audit → permission lookup → effect commit** cannot be three moments that may
observe different database states.

The failing path was `MemoryStore.add_interpretation()`. It could complete a
healthy ledger audit without an active SQLite transaction, then observe a
later damaged ledger from which the stop row had disappeared, and finally
commit a new interpretation from evidence that should still have been blocked.

The remediation closes the class rather than only the exact call site:

- `add_interpretation()` starts `BEGIN IMMEDIATE` before suppression trust,
  evidence validation and permission lookup, and keeps that transaction
  through the derived effect commit;
- `add_supersession()` uses the same write-transaction rule because revision
  is another suppression-sensitive derived effect;
- suppression-backed present-use reads such as interpretation and
  supersession usability use explicit read snapshots so audit and permission
  inputs come from one coherent database reality;
- regression coverage injects a second local writer at the suppression decision
  point and requires the derived writer to already hold the SQLite write
  boundary. The competing ledger damage must fail rather than interleave.

This preserves the broader rule:

> **A trustworthy permission input is not enough if the effect can be committed
> against a different database reality. Trust, decision and effect must share
> the transaction boundary appropriate to that operation.**

The #42 verdict remains historical evidence for its exact SHA. Later fixes do
not rewrite it.

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
