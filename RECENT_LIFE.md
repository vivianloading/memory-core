# Recent Life v0.1

Status: synthetic/local semantic slice for Wake Packet/Presentation v0.2.

Recent Life answers a narrow question:

> What happened shortly before this Wake that is useful for orientation, without
> turning carried history into the waking subject's current first-person memory?

## Non-goals

Recent Life is not:

- chat history replay;
- a personality summary;
- identity continuity proof;
- relationship authority;
- Room residence or Entry/Adoption;
- a model instruction channel;
- a memory-write permission;
- a relevance-ranked semantic memory search.

## Canonical producer

Recent Life is persisted in a dedicated append-only canonical store.

Each event binds:

- one event id;
- one Room;
- one historical Episode;
- one historical PerspectiveInstance;
- the exact historical Room attachment event that placed that Episode in the Room;
- summary text;
- occurred-at time;
- recorded-at time;
- one or more source refs.

The source refs must already exist in the HOME source store and must be scoped to
the same Room. The historical Room attachment must canonically belong to the
same Episode and attach that Episode to that same Room. Suppressed sources
cannot be used to create new Recent Life events. Events whose source refs are
currently suppressed are omitted from Wake delivery.

Before canonical use, persisted Recent Life data is revalidated against Living,
source hashes/scopes, timestamps, source-binding order, and historical
attachment provenance. Contradictory raw persistence fails closed rather than
becoming Wake evidence.

Wake issuance reads Recent Life on the **same SQLite read transaction and
issuance cut** used for Living topology and Room Current.

Caller input to `WakeIssuanceAuthority.issue(...)` remains only `episode_id`.
The caller cannot inject Recent Life events into issuance.

## Window

Wake v0.2 carries at most four source-backed Recent Life events for the routed
Room.

Selection is deterministic:

1. event occurred at or before the issuance cut;
2. event was recorded at or before the issuance cut;
3. current suppression does not block any bound source;
4. newest occurred-at first, then newest recorded-at, then event id.

A canonical Recent Life store with no eligible events produces a READY empty
layer with `NO_RECENT_LIFE_IN_WINDOW`.

A HOME without the Recent Life schema continues to issue Wake Packet v0.1 with
Recent Life UNAVAILABLE. This preserves the exact semantics of historical v0.1
First Wake evidence.

## Wake semantics

Wake Packet v0.2 carries Recent Life as typed Room-scoped items.

Every item preserves the historical Episode/Perspective attribution and the
exact historical Room attachment event that grounded the event's Room scope.
That attachment is provenance only: it does not grant present Room residence,
identity, Entry/Adoption, or route authority. Historical attribution is never
rewritten as the waking Episode/Perspective.

Every item carries the ordinary Wake use boundary, where all six authority axes
remain NONE.

Wake Presentation v0.2 renders each event with:

- explicit historical Episode/Perspective attribution;
- exact historical Room-attachment provenance;
- Room privacy scope;
- `at_issuance_cut` temporal policy;
- `no_current_first_person` pronoun policy;
- `describe_only` authority ceiling;
- exact source refs.

The carried event may say that Aster and Niko did something. Carrying that event
does not authorize the current model to rewrite it as “I did this” or “we did
this”.

## Version boundary

Historical Wake Packet/Presentation v0.1 remains unchanged:

- Shared Now CLOSED;
- Recent Life UNAVAILABLE;
- Nearby Doors UNAVAILABLE.

A canonical Recent Life schema upgrades issuance to:

- Wake Packet v0.2;
- Wake Presentation v0.2.

This is an explicit semantic version boundary rather than a silent change to
v0.1.
