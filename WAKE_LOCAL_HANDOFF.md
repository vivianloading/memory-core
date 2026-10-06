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

Schema/bootstrap installation, raw SQLite access, direct private-method bypass,
and another process are outside this contract.

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

## 5. Generation

The coordinator holds a monotonically increasing process-local
`generation`.

Each successful supported semantic write transaction increments generation
exactly once.

Rollback/failure does not increment it.

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
