# Wake Packet v0.1 — Narrow External Reconnaissance

**Date:** 2026-10-05  
**Issue:** #53  
**Role:** attack material / mechanical comparison only; not HOME design authority.

This reconnaissance was intentionally run **after** HOME's first Wake Packet
contract existed. It did not ask "which memory product should HOME copy?" It
asked three narrow mechanical questions:

1. how systems separate retrieved/context material from durable/current state;
2. how they preserve scope/source/time attribution;
3. how recall/injected context is kept from silently becoming new memory input.

## LangGraph — scope is a first-class mechanical distinction

LangGraph separates thread-scoped checkpoint state from cross-thread long-term
stores, and long-term memories live in explicit namespaces.

Useful mechanical lesson for HOME:

- scope should be represented structurally, not inferred from retrieval;
- "available across threads" is an explicit store/namespace choice.

HOME keeps the stronger rule that scope still does not imply authority.

Reference:
https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/persistence.mdx

## Graphiti — event time and ingestion time are different clocks

Graphiti entity edges keep temporal fields such as `valid_at`, `invalid_at`,
`created_at`, and episode/reference linkage. Its saga code also distinguishes
a processing watermark from the latest episode event/reference time.

Useful mechanical lesson for HOME Recent Life:

- "HOME learned this recently" and "this happened recently in life" are not the
  same ordering;
- any future recency producer should declare which clock it uses.

This reinforces HOME's existing event_time / recorded_at distinction rather than
adding a new metaphysical interpretation.

References:
https://github.com/getzep/graphiti/blob/main/graphiti_core/edges.py
https://github.com/getzep/graphiti/blob/main/graphiti_core/graphiti.py

## Letta — read-only is about mutation, not semantic authority

Letta memory blocks may be always visible in agent context and may be marked
read-only. Read-only prevents the agent from updating the block, while the block
still remains context and can be used for persona, human details, policy, state,
or other coordination.

Useful mechanical lesson for HOME:

- storage mutability and behavioral/semantic authority are orthogonal;
- Wake must carry explicit instruction/speech/identity/relationship authority
  rather than assuming "read-only data" is harmless;
- attachment/access control is useful, but attachment itself must not become
  first-person or relationship authority.

Reference:
https://docs.letta.com/v1-sdk/memory/memory-blocks

## Cloudflare Agent Memory — recall and ingestion can be separate paths

Cloudflare's Agent Memory guide exposes recall separately and explicitly tells
the model to treat recalled memories as context rather than guaranteed truth.
Its ingestion example reads session history from a cursor and filters the batch
to user/assistant message roles before calling ingest.

Useful mechanical lesson for HOME:

- carriage/recall should not itself acquire memory-write authority;
- future HOME delivery should preserve a machine-readable origin so Wake-injected
  material can be excluded from ordinary conversation ingestion;
- an ingestion cursor/source filter is a useful implementation pattern, but HOME
  still needs its own provenance/authority checks.

Reference:
https://github.com/cloudflare/cloudflare-docs/blob/production/src/content/docs/agent-memory/get-started.mdx

## Mem0 — explicit entity scope and metadata are useful but not sufficient

Mem0's add-memory interface requires at least one entity scope such as user,
agent, app, or run and accepts metadata. Its additive pipeline can retain
memories without overwriting prior ones.

Useful mechanical lesson for HOME:

- explicit scope + metadata belongs on the record, not only in retrieval logic;
- additive history is compatible with preserving old states.

HOME does **not** adopt "entity id" as proof of perspective, Room authority, or
current standing.

Reference:
https://github.com/mem0ai/mem0/blob/main/docs/api-reference/memory/add-memories.mdx

## Net design delta for HOME

The reconnaissance does not change the five Wake layers.

It strengthens these gates:

1. Map remains Episode-scoped even when it names an attached Room.
2. Room Now remains Room-scoped and resolver-only.
3. WakeUseBoundary now explicitly denies memory-write / re-ingestion authority.
4. Future Recent Life must distinguish event/reference time from ingest/recorded
   time; row order/access time is not a valid substitute.
5. A future renderer/delivery slice must preserve Wake origin and non-authority
   metadata so ordinary ingestion can exclude injected Wake context.
6. Read-only storage is never accepted as proof that context is semantically
   non-authoritative.

No external source changed HOME's standing first-person, privacy, Shared,
relationship, or identity rules.
