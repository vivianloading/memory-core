# HOME Current View v0.1 — Semantic Contract

Status: DRAFT IMPLEMENTATION LAYER

Current View sits above append-only HOME history.

Its job is not to decide who someone is, and not to rank memories by emotional
importance. Its job is narrower:

> Derive what still has standing to participate in life at an explicit point in
> time, without rewriting the past.

The core rule is:

> Current is not the latest row. Current is a historical state that still has
> standing now under an explicit validity contract.

## Four times / statuses that must not collapse

HOME keeps these concepts separate:

- event time — when the underlying event, choice or state belongs in life;
- record time — when HOME learned or stored the record;
- validity time — when the state is eligible to participate in Current View;
- last-known standing — a downgrade state when evidence is old but there is no
  evidence of change.

A late-recorded correction must not rewrite what HOME would have known at an
earlier as-of time. A future-valid state may be known without becoming current
early.

## Namespaces

Current View v0.1 has two semantic namespaces:

- Room — first-person living-line state;
- Shared — common-world state.

They are intentionally separate.

A Room current-state record requires concrete Episode and PerspectiveInstance
provenance. That preserves who actually authored the first-person source event.
It does not claim that two Episodes are the same metaphysical subject.

A Shared record cannot claim Room first-person provenance.

Semantic ownership metadata is not an operational access credential. The Room
participation authority layer decides whether a runtime may act in a Room;
Current View only derives standing from already-admitted history.

## Append-only inputs

A CurrentStateRecord is immutable historical input.

A later record may supersede an earlier record by id, but the earlier record is
not deleted or rewritten.

Supersession cannot cross namespace, owner or key.

Multiple children of one historical record are allowed. They are competing
heads, not an invitation to choose the newest write.

A CurrentStateEndEvent is also append-only evidence. It can explicitly end a
state without altering the historical assertion itself.

## Explicit validity rules

Every state declares one validity rule and a compatible downgrade rule.

### durable_until_changed

The state remains current until explicit supersession or an explicit end event.

Silence, inactivity, a new window, a new Episode, a model change, a host change,
or time passing does not expire it.

### explicit_interval

The state is current on the half-open interval:

    valid_from <= as_of < valid_until

At valid_until it becomes expired.

### stale_to_last_known

The state is current while fresh.

At:

    event_time + stale_after

it becomes last_known rather than false, deleted or silently replaced.

This is useful for things like preferences where old evidence may become less
certain without becoming evidence of the opposite.

### open_until_resolved

The state remains unresolved until an explicit end/resolution event or
supersession occurs.

Open does not mean bedside-worthy. It only means the matter is not semantically
closed.

## Resolution outcomes

For one namespace / owner / key, Current View may return:

- current
- last_known
- unresolved
- expired
- ended
- conflicting
- no_current
- unknown

Unknown is legitimate.

Conflicting is legitimate.

No generic last-write-wins rule exists.

If multiple effective unsuperseded heads still have present standing, Current
View returns conflicting and exposes all candidate ids.

If a successor later expires or ends, an older superseded parent does not
resurrect. Historical supersession remains history.

## History, future and now

CurrentResolution separates:

- current_state_ids — states eligible to participate now;
- historical_state_ids — known effective history that no longer participates;
- future_state_ids — known records whose valid_from is still in the future.

A record whose recorded_at is later than as_of is not known in that historical
view at all.

This lets HOME answer historical as-of questions without importing knowledge
from the future.

## First-person provenance

Room current state carries:

- Room owner id;
- source Episode id;
- source PerspectiveInstance id;
- source references.

The source Episode and PerspectiveInstance are attribution evidence only.

They do not become authentication principals, and they do not prove identity
continuity.

A later Episode may explicitly supersede an earlier current-state record while
identity continuity remains unknown.

## Source provenance

Every current-state record and explicit end event requires at least one source
reference.

Current View is therefore a derived evidence layer. It must not invent present
state from retrieval frequency, emotional intensity, similarity or prose
plausibility.

The v0.1 source_refs field is a semantic reference only; production integration
must bind it to the existing typed provenance/suppression domains rather than
treating opaque strings as authority.

## Deterministic as-of evaluation

Current derivation always receives an explicit timezone-aware as_of timestamp.

The resolver must not read the ambient wall clock.

The same history plus the same as_of value produces the same semantic result.

This is required for:

- historical replay;
- tests;
- migration;
- audit;
- Wake reconstruction later.

## What silence means

No new evidence is not the same as evidence of change.

Therefore:

- durable state remains current through silence;
- open state remains unresolved through silence;
- stale-to-last-known state downgrades only because its explicit rule says so;
- explicit-interval state expires only because its explicit validity interval
  says so.

Current View has no generic inactivity decay.

## What Current View is not

Current View is not:

- identity classification;
- a continuity score;
- a persona/trait profile;
- a Room access-control system;
- an AdoptionEvent;
- relationship-state automation;
- a retrieval ranking signal;
- a Wake Packet;
- a Heartbeat/proximity policy;
- a model delivery path.

In particular, it does not turn often-recalled material into truth and does not
turn emotionally intense material into permanence.

## Relationship to Room authority

Room participation authority answers:

> May this exact launched runtime perform this operation in this Room?

Current View answers:

> Given admitted history, what state still has semantic standing at this as-of
> time?

Neither answer implies the other.

Future Room-current write integration must require operational Room authority at
the write boundary. This semantic module must not be used as a substitute for
that gate.

## v0.1 implementation boundary

This first slice is deliberately semantic and synthetic-only.

It provides immutable typed records plus deterministic derivation.

It does not yet persist Current View records into the canonical HOME database.
That persistence layer should be added only after the semantic contract survives
regression and adversarial review, so storage does not freeze a mistaken
definition of current.

Real personal data remains CLOSED.

## Design sentence

> 没有新证据，不等于已经改变；没有新证据，也不永远等于“我确定现在仍然如此”。

Current View exists to represent that middle honestly.
