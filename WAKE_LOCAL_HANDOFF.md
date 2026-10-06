# HOME Wake Local Handoff Ordering v0.1

**Status:** DRAFT ENGINEERING / same-process synthetic-local ordering only;
no network send; no model execution; real personal data CLOSED.

Issue: #72

## 1. Purpose

Wake Packet says what may be carried.

Wake Issuance proves one exact carried artifact came from the live canonical HOME
runtime.

Wake Presentation constrains how that artifact may be represented without
upgrading carriage into speaker authority.

Wake Local Handoff Ordering answers a fourth question:

> **Can HOME locally accept one exact rendered Wake from one canonical state cut
> without a supported semantic writer committing through the cut?**

The governing invariant is:

> **A locally handed-off Wake must come from one canonical HOME cut that no
> supported HOME semantic writer can commit through between fresh issuance and
> exact local transport acceptance.**

## 2. Local handoff is not model delivery

v0.1 intentionally ends at one short process-local acceptance point.

The cut contains:

`acquire cut -> fresh issue -> presentation -> deterministic render ->
request-bound envelope -> local accept -> handoff receipt -> release cut`

The cut does **not** contain:

- network I/O;
- model execution;
- arbitrary caller callback;
- user-provided code.

Actual network/model work may happen later, after the cut has released.

Therefore the v0.1 receipt is named `WakeHandoffReceipt`, not a delivery
receipt.

## 3. Shared path-scoped coordinator

All supported canonical HOME semantic writers for one resolved SQLite path use
one process-local `HomeStateOrderingCoordinator`.

v0.1 supported writer families:

- MemoryStore ordinary semantic/source/suppression writes;
- LivingStore Room/Episode/continuity/route writes;
- CurrentStore state/end writes;
- CurrentAdmission writes through the CurrentStore transaction path.

Enforcement belongs at canonical write-transaction entry, not only at individual
public method names.

Schema/bootstrap installation, raw SQLite access, and direct private-method
bypass are outside this supported-writer contract.

The coordinator is bound to the live HOME process incarnation. Reuse from a
fork/inherited process fails closed. This is still not cross-process
coordination: a separately started process has its own coordinator/generation.

## 4. Writer/cut ordering

For one coordinator/path:

- at most one supported writer transaction is active;
- at most one delivery cut is active;
- a writer waits while another thread owns the cut;
- a cut waits while another thread owns a writer transaction.

Same-thread unsafe re-entry fails closed:

- writer attempted while that thread owns the delivery cut;
- nested delivery cut;
- delivery cut attempted while that thread owns a writer transaction;
- nested supported writer transaction.

This rule intentionally does not use re-entrant locking semantics to turn these
cases into accidental permission.

MemoryStore retains its older Memory-only request-delivery RLock for the legacy
`RequestBoundDeliveryBoundary`. That legacy boundary still invokes an
arbitrary callback, so it must **not** become a whole-HOME cut.

Memory semantic writes acquire the legacy Memory lock before the HOME writer
permit. Therefore a slow legacy Memory callback cannot indirectly hold a HOME
writer permit while waiting. Living/Current writers remain free to proceed
while only the legacy Memory callback boundary is active.

## 5. Generation

The coordinator holds a monotonically increasing process-local
`generation`.

Each successful supported semantic write transaction increments generation
exactly once.

Rollback/failure does not increment it.

Writer permits are released even if opening the SQLite write connection fails;
connection-open failure cannot strand the path in a permanently active writer
state.

A delivery cut captures the current generation. No supported writer may commit
until that cut releases, so generation must remain stable through local
acceptance.

Generation is only a process-local ordering witness.

It is **not**:

- authority;
- identity;
- continuity;
- durable history;
- restart-safe state;
- cross-process synchronization.

## 6. Fresh operation only

Public Wake handoff accepts only request-time input:

- request_id;
- episode_id;
- user_input.

It does not accept a caller-provided:

- IssuedWakePacket;
- WakePresentationPlan;
- RenderedWakePresentation;
- request envelope;
- historical `as_of`.

Every handoff attempt performs fresh Wake issuance while holding the cut.

A retry is a new handoff attempt and therefore obtains:

- a fresh issuance;
- a fresh wake id;
- a fresh envelope;
- a fresh one-shot handoff nonce.

## 7. Request-bound envelope

The HOME-controlled envelope binds:

- request id;
- Episode id;
- exact user input;
- exact rendered Wake Presentation artifact;
- Wake id;
- issuance id;
- rendered payload digest;
- presentation plan digest;
- one-shot handoff nonce.

The envelope is local process data, not a model request.

It contains no chat role, tool authority, system prompt, transport callback, or
current-first-person authority.

## 8. Local acceptance boundary

`LocalWakeTransportBoundary` performs one short HOME-controlled acceptance.

It validates the exact request-bound envelope, consumes its nonce once, and
registers exact process-local acceptance.

No arbitrary callback executes during this acceptance.

v0.1 exposes no network sender and no model execution path.

## 9. WakeHandoffReceipt

The receipt binds at least:

- handoff id;
- request id;
- Episode id;
- Wake id;
- issuance id;
- coordinator generation;
- envelope digest;
- rendered payload digest;
- presentation plan digest;
- local acceptance status.

It proves only:

> **this exact request-bound rendered envelope was accepted by this
> process-local local transport boundary inside this coordinator generation.**

It does not prove:

- network send;
- model receipt;
- model read;
- model obedience;
- model response;
- current first-person speech;
- identity continuity;
- relationship state;
- future freshness.

It is not an authority credential.

## 10. Failure and retry

If fresh issuance, presentation, rendering, envelope construction, or local
acceptance fails, no successful handoff receipt is returned.

A nonce accepted by the local boundary cannot be accepted again.

A later retry must begin from the public handoff entry and fresh issuance; old
Wake/Presentation/Rendered artifacts are not injectable through that API.

## 11. Temporal claim

The handoff cut proves one exact local acceptance happened against one
generation-stable supported-writer cut.

After the cut releases, HOME may continue to change.

The receipt therefore does **not** claim that the accepted envelope remains
latest forever or that a later network/model consumer sees the newest HOME
state.

## 12. Initial adversarial contract

Synthetic/local defensive validation must include:

- route writer blocks behind an active cut;
- representative Living continuity/Episode/Room writer blocks;
- Current/CurrentAdmission writer blocks;
- Memory source-suppression writer blocks;
- representative Memory semantic writer blocks;
- same-thread writer inside cut fails closed;
- nested cut fails closed;
- cut-inside-writer fails closed;
- successful write increments generation exactly once;
- rollback/failed write does not increment;
- writer committed before cut is visible to fresh issuance;
- writer waiting behind cut commits only after local acceptance/release;
- generation is stable from cut acquisition through local acceptance;
- no arbitrary callback is invoked inside cut;
- the legacy Memory-only callback guard does not freeze Living/Current writers;
- connection-open failure releases the HOME writer permit;
- process-incarnation drift/fork reuse fails closed;
- public handoff accepts no prebuilt issuance/presentation/render;
- repeated handoff attempts produce fresh wake/issuance/envelope nonce;
- accepted nonce cannot be accepted again;
- no model/network capability appears.

## 13. Nonclaims

v0.1 does not establish:

- cross-process ordering;
- raw SQLite coordination;
- durable generation;
- network delivery;
- model input/control safety;
- model behavior safety;
- free-form prose safety;
- current first-person speech authority;
- identity continuity;
- relationship automation;
- Shared governance;
- real personal data;
- production readiness;
- merge authorization.

## 14. Review

Freeze one exact head and apply HOME #18:

**Fresh discovery -> Minimal proof -> Bounded coverage sweep.**

Independent review may issue an exact-SHA verdict but has no merge authority.


## 15. Current implementation shape

The author implementation uses one global in-process coordinator registry keyed
by resolved canonical SQLite path.

MemoryStore, LivingStore, and CurrentStore instances for the same path therefore
share one exact `HomeStateOrderingCoordinator` object.

CurrentAdmission durable writes participate through
`CurrentStore._write_transaction()`; admission keeps its original semantic
ordering by committing while the Room grant hold is still active, then
registering the process-local admission receipt before releasing the writer
operation.

The coordinator uses a non-reentrant condition/state protocol rather than one
shared RLock:

- `acquire_writer()` waits behind another thread's active cut;
- `acquire_cut()` waits behind another thread's active writer;
- same-thread writer/cut nesting fails closed;
- successful commit records generation while the writer permit is still held;
- permit/cut release wakes waiting operations.

MemoryStore additionally retains its historical Memory-only RLock. Ordinary
Memory writes acquire that legacy lock before the HOME writer permit. This
preserves old RequestBoundDeliveryBoundary semantics without allowing its
arbitrary callback to become a whole-HOME cut.

`WakeLocalHandoffAuthority.handoff()` exposes only
`request_id / episode_id / user_input`. It performs fresh issuance,
Presentation planning/rendering, exact envelope construction, process-local
acceptance, and receipt issuance under one HOME cut.

`LocalWakeTransportBoundary` has no network/model callback. It binds exact
origin object identity, HOME process incarnation, one-shot nonce, exact accepted
envelope digest, and exact receipt digest.

The accepted envelope remains retrievable only as evidence of the already
completed local acceptance. Neither that retrieval nor the receipt grants
permission to perform a future network/model delivery.


## 16. Independent review #74 — contended Memory re-entry NO-GO

Independent review #74 returned **FAIL / NO-GO** on exact head
`5cf37e52f6ad96a28d07a1ed9d1f811caf917c06`.

The failed head preserved legacy Memory lock ordering as:

`legacy Memory RLock -> HOME writer permit`.

That ordering was intentional for ordinary cross-thread Memory writers: a writer
waiting behind a slow legacy Memory callback must not hold a whole-HOME writer
permit.

However, #74 demonstrated a contended same-thread deadlock:

1. a Wake handoff thread owned the active HOME cut;
2. a second Memory writer acquired the legacy Memory RLock and then waited at
   HOME `acquire_writer()` for the cut;
3. the cut-owning thread attempted an ordinary Memory write;
4. it blocked waiting for the legacy RLock before reaching HOME's same-thread
   re-entry rejection;
5. the waiting Memory writer could not proceed until the cut released.

No writer was shown committing through the cut. The blocker was failure to fail
closed and loss of cut progress.

### Remediation

Memory canonical write entry now performs a **non-blocking HOME same-thread
writer re-entry preflight before waiting for the legacy Memory lock**.

The preflight:

- checks only whether the current thread already owns the active HOME cut or
  supported writer operation;
- fails closed immediately on unsafe same-thread re-entry;
- does not acquire a writer permit;
- does not wait for another thread's cut/writer;
- does not serialize or grant authority.

Ordinary cross-thread Memory writer ordering remains:

`non-blocking preflight -> legacy Memory RLock -> HOME writer permit`.

Therefore a writer waiting behind a slow legacy Memory callback still does not
hold the HOME permit.

A dedicated regression creates the exact #74 contention family: one thread owns
the cut, another Memory writer holds the legacy RLock while waiting at the HOME
gate, and the cut owner attempts a Memory write. The cut-owner write must reject
promptly with `HomeStateOrderingReentryError` before waiting for the legacy
lock, after which cut release allows the waiting writer to complete.

#74 remains historical on its own exact SHA. Any repaired head requires a fresh
exact-SHA independent review.


## 17. Independent review #75 — noncanonical coordinator identity NO-GO

Independent review #75 returned **FAIL / NO-GO** on exact head
`2b71b9728df38f43df4d28dcbbd3a7e44809ef93`.

The #74 contended Memory re-entry family passed independently and the bounded
sweep completed. The new blocker was a distinct coordinator-identity gap.

The failed head allowed public construction of another
`HomeStateOrderingCoordinator` for the same resolved canonical DB path.
That object had the same database-binding digest but independent process-local:

- condition state;
- active cut;
- writer permit;
- generation.

Ordinary Memory/Living/Current writers remained bound to the path registry's
canonical coordinator. A manually constructed Wake handoff authority/boundary
could instead bind to the same-path twin and successfully perform local
acceptance. Such a receipt therefore proved a cut on the wrong mutex state.

The blocker was **shared coordinator object identity**, not path/digest
equivalence.

### Remediation

The ordering layer now exposes a canonical-identity requirement that accepts
only the exact live coordinator object currently registered for its resolved
canonical DB path.

Wake Local Handoff applies that requirement at multiple operational boundaries:

- `LocalWakeTransportBoundary` construction;
- `WakeLocalHandoffAuthority` construction;
- every public `handoff()` entry;
- live local-acceptance verification.

A same-path manually constructed coordinator is rejected even when its DB
binding digest matches exactly.

The ordinary factory remains:

`home_state_coordinator_for_path(canonical_path)`

and valid Wake handoff construction uses that exact returned object.

This requirement is process-local object identity. It does not turn the
coordinator id or DB digest into durable authority, identity, or cross-process
synchronization.

Author regression coverage constructs a same-path twin coordinator, confirms
matching DB digest but distinct object/id, confirms boundary and authority
construction reject it, then confirms the canonical factory path still
successfully hands off and records the registry coordinator id.

#75 remains historical on its own exact SHA. The repaired head requires a fresh
exact-SHA independent review.
