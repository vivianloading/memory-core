# HOME Current Admission v0.1 — Authority-aware write contract

Status: DRAFT IMPLEMENTATION LAYER

This is Slice 2 above merged Current persistence Slice 1.

Its central rule is:

> History may exist without authority. A Current effect becomes admitted only
> when exact live authority and the exact committed effect cross one boundary.

## Scope

v0.1 is synthetic/local and supports **Room Current admission only**.

A Room Current state or end event requires a live
`RoomParticipationGrant` carrying `room.change_current_stance`. Existing
Room authority already requires that scope to be accompanied by
`room.append_first_person`.

Shared admission is deliberately CLOSED. The semantic label
`shared_governance` is not an authority primitive and must not be treated as
one.

Real personal data and production Current delivery remain CLOSED.

## Ordering

The admitted write holds these boundaries in this order:

1. acquire the Current SQLite `BEGIN IMMEDIATE` write transaction;
2. audit existing Current and admission persistence;
3. hold the host lease and revalidate the exact Room grant for the target
   session/Episode/PerspectiveInstance/Room/scope;
4. append the Current history effect;
5. append the exact admission audit binding in the same transaction;
6. re-audit the combined durable state;
7. commit while the Room authority lock is still held;
8. return and register the process-local `CurrentAdmissionReceipt`.

The SQLite write transaction prevents Room route corrections from interleaving
with the effect. Holding Room authority prevents process-local grant
suspension/session revocation from interleaving after the grant check but before
commit. The Room authority hold also keeps the exact host lease active until the
effect has committed or unwound, so host shutdown/release cannot remove that
trust root between authorization and commit.

## No post-hoc grandfathering

There is intentionally no supported `admit_existing_row(...)` API.

A state supersession requires the live admission receipt of the exact parent
state. An end event requires the live admission receipt of its exact target
state. Therefore a Slice 1 row, raw-SQL row, or merely schema-valid row cannot be
turned into an admitted continuation through the supported v0.1 path.

This is deliberately strict across process restart: persisted admission audit
rows remain historical evidence, but process-local receipts are not recreated
from them. A future durable authority layer must define restart-safe
authenticated admission provenance before production Current consumption can
exist.

## Audit record versus authority receipt

The durable admission tables record:

- exact effect id and effect digest;
- exact Room attachment provenance used by the Current write;
- grant id and exact grant binding digest;
- policy fingerprint / policy issuance;
- launch evidence;
- proposal and approval ids;
- session / Episode / PerspectiveInstance / Room;
- required `room.change_current_stance` scope;
- exact predecessor admission for supersession or target state admission for an
  end event.

The admission binding digest is a deterministic checksum over those fields. It
prevents accidental A/B binding drift; it is **not** a signature, MAC, or
credential.

A caller with arbitrary raw SQLite access can manufacture structurally valid
rows if it also defeats or recreates the schema constraints. That storage does
not mint the process-local receipt object registered by
`CurrentAdmissionAuthority`.

Therefore:

> durable admission audit presence != live operational credential.

## Resolver use of admission proof

Current Resolver v0.1 must not interpret durable admission-table membership as
operational admission proof.

The durable admission binding digest remains intentionally non-credential
material. For process-local resolution, the only positive proof that an effect
entered admitted semantic history is a `CurrentAdmissionReceipt` actually
issued and registered by the exact live `CurrentAdmissionAuthority`, then
corroborated against its durable audit row.

The authority exposes a package-internal receipt-snapshot seam for this purpose.
That seam validates process-local issuance and exact durable binding but does
not apply source-suppression usability. Suppression remains a separate later
resolver axis so stopped evidence cannot be deleted from semantic history and
manufacture fallback.

If the process-local receipt is gone after restart, durable audit cannot recreate
it. Resolver must fail closed / report proof unavailable rather than promote the
audit row into authority.

This preserves the existing rule:

> durable admission audit presence != live operational credential.

## Authority/effect ordering

The combined Room admission path establishes one lock order:

1. open the Current `BEGIN IMMEDIATE` write transaction;
2. enter the package-internal Room grant hold, which revalidates the exact grant;
3. append the Current effect and exact admission audit row;
4. re-audit Current and admission integrity;
5. commit before releasing the Room authority hold;
6. register and return the process-local receipt.

The Room grant hold is deliberately package-internal. It is not a general caller
capability for wrapping arbitrary database writes; exposing that shape would
allow callers to invent the opposite authority-lock -> database-lock ordering.

Admission audit reads also re-check synthetic store-domain, Living/source
upstream integrity, Current schema/data integrity, and admission schema/data
integrity from one read transaction. Exact admission provenance must not remain
apparently valid on top of a damaged upstream history.

A crash or process restart after durable commit but before/after receipt
registration can leave durable audit provenance without a live receipt. That
fails closed: durable audit presence alone never recreates operational
authority.

## Shared boundary

v0.1 refuses to infer Shared authority from:

- `namespace=shared`;
- `semantic_change_authority=shared_governance`;
- an authenticated principal alone;
- Room grants;
- historical Shared rows.

Shared Current admission must wait for a concrete Shared-governance decision
primitive with an exact effect-binding contract.

## Issue #25 — fork-inherited live authority

Independent review #25 returned **FAIL / NO-GO** on exact head
`6d1f25cc94255c3d564456359953125ca985cf92`.

Fresh discovery found that `CurrentAdmissionReceipt` validation relied on the
live authority's in-memory registry, receipt object identity, marker identity,
fingerprint, and durable audit binding, but did not separately assert the HOME
process incarnation. Under POSIX `fork()`, a child inherits that entire memory
world. The inherited Current admission authority therefore accepted the
inherited original receipt even though HOME's process-boundary contract says a
fork child does not inherit valid process-local authority.

Room participation authority already failed closed in the same child because
its live-host path checks the HOME process boundary.

The remediation binds each `CurrentAdmissionAuthority` to the exact HOME
process incarnation in which it was created and checks that boundary before
admission work or live-receipt validation, including internal predecessor
receipt checks. The durable admission row remains unchanged: process identity
belongs to live operational authority, not historical audit provenance.

Lesson:

> **Process-local is not established by object identity alone.**
> Any capability registry that can survive memory inheritance must also bind
> itself to the process incarnation that is allowed to interpret that registry.

The #25 verdict remains historical evidence for its exact SHA. Later fixes do
not rewrite it.

## Issue #26 — leased database binding

Independent review #26 returned **FAIL / NO-GO** on exact head
`18881898853e78e498e259ff85d57d577b5c3c43`.

Fresh discovery found that Current admission verified same-database binding only
when the authority was opened, then retained caller-owned `CurrentStore` and
`CurrentAdmissionStore` objects as later connection targets. Because their
`db_path` configuration is mutable and may also be relative, the operational
Current effect could drift away from the database protected by the Room
authority's host lease.

The independent proof demonstrated both:
- explicit public `db_path` mutation from leased database A to unleased clone B;
- unchanged relative `Path("home.db")` configuration whose meaning changed
  only because process cwd moved from A's directory to B's directory.

In both cases the Room grant still revalidated against A while the supported
Current admission operation wrote effect + admission audit to B and minted a
live receipt there.

The remediation makes the host lease identity's canonical database path the
operational trust root. A Current admission authority now:
- records that exact canonical path when opened;
- keeps caller-owned Current/admission stores only as binding evidence;
- uses internally owned stores pinned to the canonical leased path for every
  operational connection;
- revalidates caller-store path resolution before each public admission or
  live-receipt operation, so later configuration/cwd drift fails closed;
- keeps internal connection targets pinned even if cwd changes after the check.

This preserves the authority/effect rule:

> **The authority that authorizes an effect and the database that receives the
> effect must share one immutable trust root.**

A route, grant, or lease attached to database A cannot authorize an effect in a
structurally identical database B.

The #26 verdict remains historical evidence for its exact SHA. Later fixes do
not rewrite it.

## Issue #27 — authorization reader must share the leased trust root

Independent review #27 returned **FAIL / NO-GO** on exact head
`a41c31f42316d4d65ad524b8aa996e6e92c7a2a5`.

Issue #26 pinned Current/admission effect connections to the host lease's
canonical database, but Room authority still retained the caller-owned
`LivingStore` as its operational lineage reader. Its live-host path check and
the later continuation snapshot read were separate operations. A concurrent
change to that public store's `db_path` could therefore make grant
revalidation read structurally similar database B while the authorized Current
effect committed to leased database A.

The independent proof made A stale by introducing a continuity fork while a
pre-fork clone B remained linear. By switching only the caller-owned
`LivingStore.db_path` during lineage read, the supported admission path
accepted lineage from B and committed the effect to A.

The remediation extends the lease-rooted binding to the authorization reader:
`RoomParticipationAuthority` now creates and owns an internal
`LivingStore` pinned to the lease identity's canonical database path. The
caller-owned LivingStore is used only to establish the open-time binding and is
not retained as the later operational reader.

The resulting rule is stronger than a path pre-check:

> **Authorization evidence must be read from the same immutable trust root that
> will receive the authorized effect.**

Checking that a mutable reader points to A and then later reading from that
reader is not equivalent to binding the read to A.

The #27 verdict remains historical evidence for its exact SHA. Later fixes do
not rewrite it.

## Deliberate non-claims

This slice does not provide:

- a production Current resolver or delivery path;
- Wake / Heartbeat behavior;
- real personal data;
- restart-safe recreation of live admission receipts;
- Shared-governance admission;
- identity continuity adjudication.

When this implementation stabilizes, review it using HOME's staged method:
**fresh discovery → minimal proof → bounded coverage sweep**.