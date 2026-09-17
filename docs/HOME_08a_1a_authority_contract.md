# HOME #08a.1a — production authority contract

Base: `main` at `bb88cc40e2b6d2d4200b657800644e3dfd4efe1c`.
Branch: `codex/home-08a-1a-authority-hardening`.

This is a non-payload contract skeleton. Real personal data remains CLOSED.
All validation uses synthetic fixture identifiers, temporary stores and data.
No production reader/writer, external adapter implementation, sink, model API,
listener, secret provider, plugin, or real backup/restore is introduced.

## Authority objects and persistent ownership

The trusted host exclusively owns `ProductionAuthorityRoot`. Its bootstrap
factory is a host composition entry point, not a request endpoint or an
authentication mechanism. Configuration and `ProductionScope` describe exact
constraints; possession of those values never grants operation authority.

The root registers the exact object identities of its `ProductionPrincipal`,
`ProductionOperationContext`, `ProductionAdapter` and `ProductionProvenance`.
Production admission requires membership in those current-root registries.
Legacy/global identity markers, exercise capabilities/policies and copies with
identical fields cannot satisfy this test. Adapter registration here is only a
metadata issuer contract; no connector runs. There is no exported issuer that
can mint independently of the live root.

The persistent `home_store_domain` row uses the explicit `production-contract`
ownership profile, a nonempty incarnation, and the exact serialized scope.
This is distinct from the existing `real` exercise profile. Existing exercise
read/write/schema/bootstrap/reset paths reject it through their shared domain
check, even in a fresh process with test helpers on PYTHONPATH and tests as cwd.
There is no conversion from exercise/synthetic stores into production stores.
Production opens only a marker-only database and rejects missing incarnation,
wrong scope, other ownership, and additional payload tables. The bootstrap
permit can only initialize/validate that metadata and is consumed before ACTIVE.

Only `check_contract` is enabled, using `OperationClass.AUDIT_READ` strictly for
this metadata check. All payload operation classes remain disabled. The receipt
contains session, operation and store-incarnation identifiers, never payload.

## Admission and cutoff

`_operation_admission` is the combined protocol for future production operations.
It checks current HOME process, ACTIVE root, live OS-backed lease, same-process
generation, persistent incarnation, exact current-root issuance, and principal,
operation-class, domain, perspective, namespace and destination constraints.
Protected work stays within the protocol. Root-only issuance uses the same
liveness and store serialization protocol.

Lock order is store coordinator -> lease guard -> lifecycle condition. The
coordinator is the existing per-store lock used by exercise writes, stop-use
and reset. Lease release is serialized against admitted work. The admission
point is the state/store check under the lifecycle condition while holding the
coordinator and lease guard. An early state check is only a fast denial; a
queued context is checked again at actual admission.

Shutdown atomically changes ACTIVE to CLOSING under the lifecycle condition;
that transition is the admission cutoff. It releases that condition before
waiting for the coordinator, so already-admitted work drains without deadlock.
It then clears every issuance registry, closes remaining resources, sets CLOSED,
and releases the lease last. A retained context cannot enter after the cutoff.
Cleanup failure never reactivates the root and retains the lease when quiescence
or resource cleanup has not completed. Same-thread reentry/shutdown is denied.
Failed roots are retained in a process-local quarantine so garbage collection
cannot silently release a lease after an unpublished bootstrap cleanup failure.

`reset_empty_store` participates in the same cutoff. It closes the root and
rotates only the empty metadata incarnation; it is not a payload deletion or
backup/restore API. The first close/reset cutoff wins and all concurrent callers
observe its disposition. CLOSED has no transition back to ACTIVE; reopening
creates a new root/session and advances the same-process generation.

The supported root releases its private lease only after CLOSED. Simulated
out-of-band release, closed handles and replaced lock files deny subsequent
minting and operation admission. As in the existing host boundary, arbitrary
Python mutation, direct SQL or direct OS unlocking outside the supported APIs
is outside the in-process trust model.

## Verification

Environment: Linux, Python 3.12.14. Commands run from the repository root.
Baseline before changes: 362 existing tests passed.

| Check | Exact command | Result |
| --- | --- | --- |
| Full suite | `PYTHONPATH=src python -m unittest discover -s tests -v` | 389 tests, OK |
| #08a.1a adversarial suite | `PYTHONPATH=src:tests python -m unittest test_production_authority -v` | 27 tests, OK |
| Strict relevant modules | `PYTHONPATH=src:tests python -W error::ResourceWarning -m unittest test_production_authority test_host_runtime test_host_config test_store_domain test_real_authority_ordering test_real_ingress test_real_normal_read test_real_source_origin test_real_stop_use test_real_delivery -v` | 161 tests, OK; no ResourceWarning output |
| Compilation | `python -m compileall -q src tests scripts` | Exit 0 |
| Patch whitespace | `git diff --check` and `git diff --cached --check` | Exit 0 |
| Existing closed verifier | `python scripts/verify.py` | 128 critical tests, MINI-READY VERIFIER: GREEN; real personal data CLOSED |

The new suite covers all fourteen required adversarial categories. Additional
cases check copied production objects, every scope dimension, disabled payload
operation classes, admission queued before cutoff, lease-release serialization,
same-thread reentry, cleanup failure, missing incarnation, lock-file replacement,
and six SQL bootstrap failure points with rollback/handle-closure assertions.
An isolated subprocess actively prohibits test-helper imports while exercising
production bootstrap, issuance, metadata admission and shutdown.

The existing mini-host config schema, startup API, `real_data_allowed=true`
rejection and existing MINI-READY verifier are unchanged. No broad refactor was
needed: existing-code changes are confined to lease liveness serialization and
recognition of the new persistent ownership value.

## Before #08a.1b

The principal issuer currently proves trusted host/root possession only. A real
request-facing authentication binding, real-data GO, and the complete production
service graph require separate review and authorization. Future operations must
use the combined admission contract and explicitly extend the closed operation
allowlist; they must not reuse exercise/global identity or adopt exercise stores.
The marker-only profile intentionally rejects payload schemas until a later
reviewed schema contract is introduced. Windows-specific OS lease behavior was
not executed in this Linux validation environment. No merge is performed.
