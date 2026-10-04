# HOME Current Persistence v0.1 — Slice 1

**Status:** implementation slice; synthetic-only; no model delivery; real personal data CLOSED.

**Physical schema marker:** `current-persistence-v0.1.1` after the Issue #16 remediation. The logical Slice 1 design remains v0.1; the marker changed because the persisted layout is intentionally incompatible with the reviewed failed draft.

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

Evidence coordinates are defined in the same domain as `EvidenceRef`: zero-based,
half-open **Python `str` code-point indices**. SQLite `length(TEXT)` is not used
as the final span authority because embedded U+0000 has different length behavior
there. The supported writer and audit path validate the Python domain directly,
while the SQLite schema requires integer coordinate storage.

Historical rows are not deleted if a source is suppressed later. This slice exposes them only through audit readers; it intentionally does not yet expose a production consumer path that could turn suppressed history back into Current. Suppression propagation belongs to the lifecycle integration slice.

## Append-only and repair semantics

State change is represented by new records and explicit supersession/end events. Existing rows cannot be updated or deleted through the supported schema, including `INSERT OR REPLACE` replacement behavior.

Current history tables use `WITHOUT ROWID`. This is intentional: a hidden SQLite
`rowid` is not allowed to become a second replacement identity that bypasses the
declared immutable primary key when `recursive_triggers` or foreign-key settings
differ.

The parent state/end-event row also seals the evidence set it was created with:
the ordered semantic `source_refs` are retained in the immutable payload and the
declared binding count is stored alongside it. Child evidence rows may fill only
those declared slots. Later insertion cannot silently make an old semantic record
wake up with a larger or different evidence set.

One `namespace + owner + key` has one stable `state_kind` across its history.
Different kinds are not allowed to appear as independent roots under the same
Current key. This does **not** collapse same-kind competing heads: conflict remains
a valid representable Current result.

Supersession must stay inside one semantic line:

```text
namespace + owner + key + state_kind
```

A correction or change may alter the current landing later, but it does not rewrite the earlier historical row.

## Room provenance

For `namespace=room` the store requires:

- an existing Room matching `owner_id`;
- an existing Episode matching `episode_id`;
- the exact concrete `PerspectiveInstance` already attributed to that Episode;
- the exact active `RoomAttachmentEvent` that routed that Episode to the Room at admission time.

The attachment id is retained as historical provenance. A later append-only route correction does not rewrite the older Current event's original route anchor.

This is provenance only. It is **not** operational permission to change Room Current state. The next admission slice must require an appropriate live Room participation grant and bind authorization to the exact write effect.

## Integrity posture

The schema is fail-closed in two ways:

1. SQL constraints/triggers block ordinary raw rewrites and cross-line writes.
2. Every supported read/write re-audits schema definitions and persisted semantic integrity.

Schema validation compares the actual SQLite table/trigger SQL against the exact expected definitions. A same-name empty trigger therefore does not satisfy the contract.

The integrity audit scans evidence tables in both directions: parent records must
have exactly their sealed number of bindings, and child bindings with no parent
are rejected even if foreign keys were disabled when the raw row was inserted.

## Raw SQL non-claim

This slice makes immutable-history rewrites and semantically invalid topology
fail closed, but it does **not** authenticate the origin of a structurally valid
new append.

A caller with arbitrary direct SQLite access can still manufacture a row set
that satisfies the storage schema. Because Slice 1 has no operational admission
authority and no production Current consumer, such a row has no right to become
trusted present-tense state merely because the audit reader can reconstruct it.

Slice 2 must therefore bind every usable append to an exact admission decision
or receipt. It must not grandfather pre-existing rows, raw-SQL rows, or
schema-valid rows into operational authority merely because they are present.

## Independent review history

Issue #16 reviewed exact head
`9408a3cbd6256298cbd9000580f9330df448f34e` and returned **FAIL / NO-GO**.
That verdict is preserved as historical design provenance and is not rewritten
by later fixes.

The independent review confirmed four blocking defects:

1. hidden `rowid` replacement paths could remove immutable history under some
   `foreign_keys` / `recursive_triggers` combinations;
2. evidence child rows could be appended after commit, changing an existing
   record's reconstructed `source_refs`;
3. fractional evidence coordinates could cross the persistence boundary and
   later fail `read_evidence()`;
4. the store accepted different `state_kind` roots under one Current key even
   though Current View rejects such history.

It also identified two residual integrity/input-domain findings: SQLite
`length(TEXT)` disagrees with Python code-point length in the presence of
U+0000, and orphan evidence rows were not reached by the original parent-driven
audit.

The remediation in subsequent heads treats these findings as changes to the
mechanical contract, not as reasons to erase the prior FAIL. A later PASS, if
earned, must bind to a new exact SHA.

### Issue #17 re-review

Issue #17 reviewed remediation head
`42764d8427ab5a1d3897f697ca7c0947e61c3e6b` and returned **FAIL / NO-GO**.

It found that the schema audit query used
`name NOT LIKE 'sqlite_%'`. In SQLite LIKE syntax, `_` is a wildcard, so
legal user objects such as `sqliteXhidden` could disappear from the audit.
A hidden secondary UNIQUE index could then provide a replacement identity and
silently suppress representable conflict heads while the audit accepted the
altered schema.

The remediation removes name-pattern filtering from the Current schema scan.
SQLite internal auto-indexes are tolerated by their actual properties
(`sql IS NULL`), while every user-defined index or unexpected trigger attached
to Current tables remains visible and rejected regardless of name.

The same review also found that the persisted duration parser used
`int(value)`, which silently coerced a malformed JSON number such as `1.9`
to one microsecond. Audit now requires the exact canonical positive decimal
string emitted by the supported writer instead of coercing alternate scalar
types or encodings.

The #17 verdict remains historical evidence for its exact SHA. Later fixes do
not rewrite it.

## Deliberate sequencing

Slice 1: persistence substrate — this document.

Slice 2: authority-aware admission.

Slice 3: suppression propagation, restore/migration replay, and historical `as_of` integrity across lifecycle operations.

Only after those boundaries survive independent exact-head review should a production Current consumer or Wake path be considered.