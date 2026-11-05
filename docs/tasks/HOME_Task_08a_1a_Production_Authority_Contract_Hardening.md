# HOME Task #08a.1a — Production Authority Contract Hardening

## MODE

Implementation task, but **no real personal data**.

Do not ingest real personal data.
Do not enable external connectors, model APIs, network listeners, plugins, secrets, or real backup/restore.
Do not publish a production payload reader/writer yet.
Do not weaken the existing closed mini-host.

## PURPOSE

Create the minimum mechanical production-authority skeleton needed before any production real-data service can exist.

This task exists to close the second-eye review gaps before broader #08a.1 work.

## REQUIRED INVARIANTS

### 1. Production operation identity is current-session-bound

A production service must never accept authority merely because an object is a valid legacy/global:

- `AuthenticatedPrincipal`
- `OperationContext`
- `TrustedSourceOriginProvenance`

Production authority must prove issuance by the **currently active ProductionAuthorityRoot/session**.

Choose the smallest clean mechanism:

- production facade accepts request data and internally asks the active root to mint operation identity/provenance; or
- production-only session-bound wrappers/stamps are required and validated by exact root/session identity.

A test-minted or legacy/global context/provenance with identical visible fields must still fail.

### 2. Exercise / production separation is bidirectional

Required:

- production front rejects exercise authority;
- exercise front cannot operate on a production-owned store;
- production path cannot import or depend on `tests/_trusted_test_support.py`;
- test visibility on `PYTHONPATH`, editable installs, or current working directory must not make a production-owned store usable through the exercise path.

Do not rely only on static import-string checks.

If a persistent store profile/ownership marker is needed to enforce this cleanly, add the smallest explicit mechanism rather than inferring ownership from paths, config values, or process state.

### 3. Root lifecycle is mechanical

Implement an explicit lifecycle:

`BOOTSTRAPPING -> ACTIVE -> CLOSING -> CLOSED`

During `BOOTSTRAPPING`:

- no production operation may be minted or executed;
- no production principal/context may be published;
- no provenance issuer may be published;
- no sink may be published;
- no payload path may be reachable.

`CLOSED` is terminal.

### 4. Live host lease is part of session liveness

The production session must own a still-live single-instance host lease for its entire ACTIVE lifetime.

If the lease is released/lost:

- no new production authority may be minted;
- no production operation may execute.

Release the lease only after the production root reaches CLOSED.

Do not make the old closed mini-host API real-capable.

### 5. Unified admission / revocation contract

Define one production admission rule used by every future production operation:

- current HOME process;
- active production session;
- live host lease;
- expected same-process generation;
- expected persistent store incarnation;
- trusted current-root issuance;
- applicable principal / operation-class / domain / perspective / namespace / destination constraints.

The liveness/identity checks must be performed inside the same serialization/admission protocol used to exclude shutdown/reset/stop-use races.

Do not check liveness outside the critical section and then use protected state later.

### 6. Shutdown is linearizable

Required order:

1. atomically close admission to new production operations;
2. transition root to CLOSING;
3. drain already-admitted operations;
4. invalidate process-local issuers/grants/registries;
5. close remaining runtime resources;
6. transition root to CLOSED;
7. release host lease last.

A retained old context/grant must not be able to enter after admission closes.

If cleanup fails, the old root must never become ACTIVE again. Do not release the host lease if safe quiescence cannot be established.

### 7. Bootstrap authority is narrow and non-payload

Any bootstrap/maintenance authority introduced here may perform only explicitly enumerated empty-store/schema/metadata work.

It must not:

- read or write user payload;
- issue principals for request handling;
- mint production provenance for payload ingress;
- invoke sinks;
- expose a generic maintenance write path.

Bootstrap authority must be consumed/revoked before ACTIVE runtime authority is published.

Missing store incarnation must never behave like a wildcard.

## REQUIRED ADVERSARIAL TESTS

At minimum add tests proving:

1. test-minted principal with the exact production owner ID cannot authorize production;
2. legacy/global `create_operation_context(...)` cannot substitute for a current production-root context;
3. session-A production context fails after shutdown/restart into session B;
4. test-minted `TrustedSourceOriginProvenance` with the exact expected namespace is rejected by production;
5. current-session root/registered-adapter provenance succeeds;
6. exercise capability/policy/context/provenance cannot cross-accept into production when fields match;
7. legal exercise authority cannot read/write/maintain a production-owned store;
8. making test helpers importable does not change #7;
9. release/loss of host lease makes production authority unusable;
10. held old context racing shutdown cannot enter after the admission cutoff;
11. close/reset race has one deterministic linearization result, not timing-dependent authority leakage;
12. forked child cannot issue or use production authority;
13. bootstrap failure at each initialization stage publishes no production authority and leaves no payload path reachable;
14. CLOSED is terminal; reopening creates a fresh session/root.

Use only synthetic fixture data.

## CONFIG / STORE RULES

- preserve `home-mini-host-v0.1` behavior exactly;
- do not reinterpret `real_data_allowed=true`;
- if a new config schema is introduced, keep it strict and fail-closed;
- config is data, never authority;
- do not implement real backup/restore;
- do not add a secret-provider implementation or interface unless this task genuinely needs one.

## SCOPE LIMIT

Prefer the smallest patch that establishes these contracts.

Do **not** yet implement the full production ingress/read/discovery/relationship/supersession/delivery graph.

If satisfying this task would require a broad refactor, stop and return a design delta before coding the broad part.

## VERIFICATION

Run:

- full existing test suite;
- new #08a.1a tests;
- strict `ResourceWarning` pass for relevant modules;
- `compileall`;
- `git diff --check`;
- existing MINI-READY verifier.

The existing closed baseline must remain green.

## DELIVERABLE

Return:

- branch / commit;
- changed-file list;
- concise design note describing the authority objects and admission cutoff;
- exact test commands and results;
- any remaining blockers before #08a.1b.

## ACCEPTANCE

#08a.1a passes only if:

- production identity/provenance is current-session-bound;
- exercise/production separation is bidirectional;
- host lease is inseparable from ACTIVE session liveness;
- BOOTSTRAPPING/ACTIVE/CLOSING/CLOSED is mechanically enforced;
- shutdown admission cutoff is linearizable;
- bootstrap authority cannot reach payload;
- the closed mini-host remains unchanged;
- all verification is green.

Passing this task is **not** authorization to ingest real personal data.
