# HOME Current Persistence v0.1 — Slice 1

**Status:** implementation slice; synthetic-only; no model delivery; real personal data CLOSED.

## Purpose

Persist the immutable historical inputs consumed by `Current View` without turning persistence into a new source of present truth.

The store persists `CurrentStateRecord` and `CurrentStateEndEvent` history. It does **not** persist `is_current`, a selected winner, a cached `CurrentView`, relationship conclusions, identity conclusions, or a first-person voice.

> **Persistence preserves the evidence from which Current can be derived. It does not own the answer to what is current.**

## Boundary of this slice

This first slice deliberately separates storage from admission authority.

It provides:

- append-only Current state history;
- append-only end-event history;
- exact typed evidence binding for every semantic `source_ref`;
- mechanical Room / Episode / Perspective provenance checks;
- same-line supersession checks;
- exact schema / trigger integrity checks;
- audit readers that reconstruct the persisted semantic records and evidence.

It does not provide:

- `RoomParticipationGrant` admission;
- Shared governance admission;
- authorization/effect atomicity;
- suppression-aware Current consumption;
- Wake / Heartbeat / relationship automation;
- real personal data.

A later slice must add operational admission without changing these stored semantics.

## Typed source binding

`CurrentStateRecord.source_refs` and `CurrentStateEndEvent.source_refs` are semantic labels. They are not accepted as provenance by themselves.

At persistence time every label must be bound, in the same order, to one exact `EvidenceRef`:

```text
source_ref
  -> source_id
  -> source_sha256
  -> [start_char, end_char)
```

The source must already exist in the HOME source store, its hash/range must match, and it must not already be suppressed when the new Current history is written.

Historical rows are not deleted if a source is suppressed later. This slice exposes them only through audit readers; it intentionally does not yet expose a production consumer path that could turn suppressed history back into Current. Suppression propagation belongs to the lifecycle integration slice.

## Append-only and repair semantics

State change is represented by new records and explicit supersession/end events. Existing rows cannot be updated or deleted through the supported schema, including `INSERT OR REPLACE` replacement behavior.

Supersession must stay inside one semantic line:

```text
namespace + owner + key + state_kind
```

A correction or change may alter the current landing later, but it does not rewrite the earlier historical row.

## Room provenance

For `namespace=room` the store requires:

- an existing Room matching `owner_id`;
- an existing Episode matching `episode_id`;
- the exact concrete `PerspectiveInstance` already attributed to that Episode.

This is provenance only. It is **not** operational permission to change Room Current state. The next admission slice must require an appropriate live Room participation grant and bind authorization to the exact write effect.

## Integrity posture

The schema is fail-closed in two ways:

1. SQL constraints/triggers block ordinary raw rewrites and cross-line writes.
2. Every supported read/write re-audits schema definitions and persisted semantic integrity.

Schema validation compares the actual SQLite table/trigger SQL against the exact expected definitions. A same-name empty trigger therefore does not satisfy the contract.

## Deliberate sequencing

Slice 1: persistence substrate — this document.

Slice 2: authority-aware admission.

Slice 3: suppression propagation, restore/migration replay, and historical `as_of` integrity across lifecycle operations.

Only after those boundaries survive independent exact-head review should a production Current consumer or Wake path be considered.