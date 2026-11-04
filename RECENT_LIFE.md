# Recent Life v0.1

Status: synthetic/local read-only Wake projection.

Recent Life answers one narrow question:

> Which already-authorized Room Current changes happened recently enough to
> help orientation, without turning carried history into the waking subject's
> current first-person memory?

## Core decision

Recent Life v0.1 is **not a second memory store** and has no write API.

It does not accept caller-created:
- summaries;
- event times;
- record times;
- Room routes;
- Episode/Perspective attribution;
- source IDs as loose provenance.

Instead, Wake projects Recent Life only from Room Current state records that
already crossed the existing live `CurrentAdmissionAuthority` boundary in the
same HOME process and canonical SQLite snapshot.

This deliberately reuses an authority path HOME already trusts rather than
creating a new event-authority system inside Recent Life.

## Producer

The canonical producer is:

`live_admitted_room_current_history`

For one routed Room and one Wake issuance cut it:

1. obtains the exact live Current admission receipts from the bound
   `CurrentResolver`;
2. reads only Current state records backed by those exact live receipts;
3. keeps only Room records owned by the Wake-routed Room;
4. requires the record's exact historical Episode/Perspective attribution;
5. requires the exact Room attachment recorded when Current admission happened;
6. re-resolves that Episode's Room attachment at the Wake cut and withholds the
   event if the historical attachment has since been superseded/corrected;
7. applies Current present-use suppression before carriage;
8. keeps only records whose **event time**, not ingestion time, falls inside
   the canonical Recent Life horizon;
9. carries the exact Current evidence bindings, including source snapshot hash
   and character locator.

No durable Current admission row is sufficient by itself. The corresponding
process-local live admission receipt must still exist.

## Time policy

Recent Life v0.1 uses:

- event time as the recency ordering/eligibility time;
- recorded time only as an as-of visibility guard;
- a fixed seven-day horizon;
- a maximum of four items.

Formally, an item is eligible only when:

`as_of - 7 days <= event_time <= as_of`

and:

`recorded_at <= as_of`

Selection order is deterministic:

1. newest event time;
2. newest recorded time;
3. state id.

A state learned today about an event eight days ago does **not** become recent
merely because it was recorded today.

A Room with no eligible item produces a READY empty Recent Life layer with:

`NO_RECENT_LIFE_IN_WINDOW`

## Provenance

Each carried Recent Life item retains:

- Current state id;
- live Current admission id;
- Room id;
- historical Episode id;
- historical PerspectiveInstance id;
- the exact Room attachment event recorded by Current admission;
- Current key and state kind;
- Current value as the carried description;
- Current event time;
- Current recorded time;
- exact `EvidenceRef` values:
  - source id;
  - source SHA-256 snapshot;
  - start character;
  - end character.

Recent Life does not write a new summary over those sources. The carried
description is the already-admitted Current value whose provenance and
authority were established upstream.

## Late Room correction

Room attachment history is not treated as permanent privacy authority.

If Current state S was admitted while Episode E was attached to Room A, and
Living later supersedes that attachment so E resolves elsewhere, S remains
historical Current evidence but is no longer automatically eligible for
Recent Life delivery into Room A.

v0.1 does not auto-rescope it into another Room.

That requires a future explicit re-scope contract.

This is intentionally conservative:

> shared/history evidence may remain, but a superseded route cannot keep
> authorizing private future delivery.

## Wake semantics

Recent Life is enabled explicitly on a Wake issuer by the one canonical
`RECENT_LIFE_POLICY_V0_1` object.

Without that policy, Wake behavior remains exactly v0.1:

- Shared Now CLOSED;
- Recent Life UNAVAILABLE;
- Nearby Doors UNAVAILABLE.

With the policy, Wake Packet/Presentation become v0.2 and may carry Recent Life.

Each Recent Life item still has all six Wake authority axes fixed to NONE.

Wake Presentation renders each item with:

- Room privacy scope;
- explicit historical Episode/Perspective attribution;
- exact Current admission / attachment provenance;
- exact EvidenceRef provenance;
- `at_issuance_cut` temporal policy;
- `no_current_first_person` pronoun policy;
- `describe_only` authority ceiling.

Therefore:

> “This Room's admitted history says A happened recently.”

does not become:

> “I remember doing A.”

## Non-goals

Recent Life v0.1 does not yet support:

- arbitrary life-event writes;
- chat-history replay;
- automatic summarization;
- historical backfill as Recent Life;
- model-generated Recent Life;
- relevance ranking;
- emotional salience ranking;
- Shared-space Recent Life;
- cross-Room inheritance;
- route-based automatic re-scoping;
- identity continuity;
- relationship authority;
- Room residence / Entry / Adoption;
- real personal data.

A future arbitrary-event producer must establish its own typed observation /
event-time / exact-evidence admission authority. It may not reuse this read-only
projection as permission to accept caller-supplied event prose or timestamps.
