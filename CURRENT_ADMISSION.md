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
