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

## Shared boundary

v0.1 refuses to infer Shared authority from:

- `namespace=shared`;
- `semantic_change_authority=shared_governance`;
- an authenticated principal alone;
- Room grants;
- historical Shared rows.

Shared Current admission must wait for a concrete Shared-governance decision
primitive with an exact effect-binding contract.

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
