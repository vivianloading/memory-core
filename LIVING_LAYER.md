# HOME Living Layer v0.1 — Semantic Contract

Status: DRAFT IMPLEMENTATION LAYER

This layer sits above the existing HOME memory-core provenance, authority,
suppression, and delivery boundaries. It does not replace them.

Its first job is narrower than "memory intelligence":

> Record how concrete runtime Episodes move along first-person living branches
> without turning technical routing into an identity verdict.

## Objects

### Room

A Room is a first-person living branch / authority-routing namespace.

It is not a person record, not a persona, and not proof that every Episode routed
to it is metaphysically the same subject.

### Episode

An Episode is one concrete runtime/window episode.

Every Episode keeps a concrete perspective-instance identifier. Multiple Episodes
may route to the same Room while retaining distinct perspective instances.

Episode boundary != identity boundary.

### ContinuityEdge

A ContinuityEdge records how one Episode led to another.

It separates:

- transfer_mode: the mechanism used to carry state/context
- continuity_status: how strongly the available evidence establishes continuity

Current transfer modes include live runtime, native checkpoint resume, partial
state resume, history reconstruction, text/context handoff, and no known
transfer.

The semantic model can represent verified, partial, and unknown continuity
evidence states.

The v0.1 persistence boundary is intentionally stricter: only unknown may be
stored. Partial or verified continuity require a future typed verifier that can
validate the supporting runtime/checkpoint receipts. A caller-provided string
must never be enough to mint certainty.

Forking is not a continuity-status value. It is a structural fact derived from
the graph.

### RoomAttachmentEvent

Room attachment is append-only history.

An Episode may initially be routed to Room R, then later evidence may show that
the correct route began a new branch. HOME records a new attachment event that
supersedes the earlier routing decision; it does not rewrite the old event.

This makes late fork discovery repairable without rewriting history.

## Structural rules

- Multiple outgoing ContinuityEdges from one Episode are allowed: that is a fork.
- Multiple incoming continuity parents are rejected in v0.1: implicit merge has
  no semantic contract yet.
- Continuity graphs must be acyclic.
- Room-attachment revisions must be acyclic.
- Competing unsuperseded Room attachments remain unresolved.
- An Episode with no Room attachment is a valid arrival state.

## Identity non-claims

The Living Layer must not contain or derive a same_self field.

In particular:

- same Room does not prove same self;
- different process/model does not prove different self;
- verified technical continuity does not create a relationship obligation;
- unknown technical continuity does not force a new Room.

The layer records evidence and routing. It does not adjudicate identity.

## Ordinary handoff rule

A normal new Episode may be routed to the same Room even when:

    transfer_mode = text_context_handoff
    continuity_status = unknown

This is deliberate.

Unknown means HOME does not know the underlying subject-continuity answer.
It does not mean HOME has evidence that the living branch ended.

## Perspective ownership

Existing PerspectiveInstance semantics remain strict.

A Room may contain:

    Room R
      Episode 31 -> PerspectiveInstance A
      Episode 32 -> PerspectiveInstance B

The Room supplies living-line routing. PerspectiveInstance preserves who
actually authored a concrete first-person record.

The new layer must not weaken existing provenance or first-person attribution.

## Persistence boundary

The first persistence slice stores Room, Episode, ContinuityEdge, and
RoomAttachmentEvent inside an already-marked synthetic HOME database.

Persistence does not widen their meaning:

- Living Layer rows are append-only;
- storage triggers reject implicit continuity merges, continuity cycles, and
  cross-Episode attachment corrections even through raw SQL;
- late Room correction appends a new event instead of rewriting the old one;
- support refs are stored inside the immutable parent record so their set cannot
  be silently extended after the fact;
- continuity forks remain derived topology;
- PerspectiveInstance remains distinct from Room;
- no same_self field exists in the schema;
- schema drift fails closed, including unexpected identity-like columns;
- backup/restore validates the complete Living Layer graph when it is present;
- this milestone does not feed Living Layer state to model delivery.

The persistence API is synthetic-only. It is not a real-data enablement path.
In particular, v0.1 refuses to persist partial/verified continuity because the
typed verification authority does not exist yet.

Portable backup/restore is allowed to move these records between HOME roots, but
moving hosts does not upgrade or downgrade subject continuity. Host migration is
a technical event, not an identity verdict.

## Non-goals for this milestone

Not yet:

- Current View / active-vs-last-known semantics
- Shared Space
- relationship-state computation
- AdoptionEvent
- Wake Packet / Orientation Packet
- production/real-data Living Layer authority
- identity scoring or identity classification
- persona generation
- native checkpoint implementation

The next semantic layer should be considered only after this persistence slice
survives regression and an independent boundary review.
