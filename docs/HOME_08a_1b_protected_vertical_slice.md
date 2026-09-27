# HOME #08a.1b — first protected production vertical slice

Status: implementation and Linux verification complete; **Windows acceptance completed**
on the actual HOME Windows checkout, as reported by the user on 2026-09-28.
The Windows acceptance blocker is closed; main-reviewer review remains separate.
Real personal data remains CLOSED. All exercised content is synthetic fixture text.

Base branch: `codex/home-08a-1a-authority-hardening`.
Exact base commit: `0eefb5847d6fa26e8fa30dcad503613786387b01`.
Implementation branch: `codex/home-08a-1b-protected-vertical-slice`.
No merge is performed; this branch is based on 1a, not the older main.

## Scope and changed files

| File | Change |
| --- | --- |
| `src/home_memory_core/production_authority.py` | Narrow hooks for the root's closed operation allowlist and provenance validation; extract private ownership-row validation while preserving the marker-only front's schema restriction. |
| `src/home_memory_core/production_schema.py` | Exact production payload profile, atomic bootstrap, immutable origin/source/capture state, one-way stop-use, per-operation authority validation. |
| `src/home_memory_core/production_memory.py` | Synthetic-only startup barrier, one registered manual-event adapter, protected source ingress/read/stop-use. |
| `tests/test_production_memory.py` | 36 adversarial tests for the vertical slice and startup failures. |
| `docs/HOME_08a_1b_protected_vertical_slice.md` | Design, Linux verification, completed Windows acceptance and #08a.1c blockers. |

There are no relationships, supersession decisions, discovery, model/session
delivery, external providers, connectors, listeners, plugins, secrets, or real
backup/restore. Payload-profile reset is explicitly unavailable. Existing
exercise domain checks, the closed mini-host config/startup and MINI-READY
verifier are unchanged. No broad refactor was needed.

## Startup and authority

`start_synthetic_production_memory` is a trusted local host composition entry,
not a request endpoint or a change to `start_home_mini_host`. It rejects any
`synthetic_only` value other than literal `True` before filesystem creation.
This flag is an explicit mode restriction, not a content classifier or authority
proof. The trusted host owns the root and all fixture inputs; untrusted request
code must not receive the root/issuer. No real-data enablement is added.

Startup holds the live host lease and stays BOOTSTRAPPING. A new empty DB or an
exact 1a marker-only DB is initialized in one transaction. The persistent
`production-contract` ownership/scope/incarnation row is preserved; a separate
`production-manual-event-synthetic-v0.1` schema profile seals the payload schema.
Origin, stop-use, source and capture schemas are installed and verified before
the profile is committed. The bootstrap permit is consumed before ACTIVE, and
the single manual-event adapter is registered before the session is returned.
Partial initialization publishes no payload authority. Unknown objects, missing
tables/triggers/profile rows, and incomplete payload-bearing authority state
are refused without repair or relabeling.

The only enabled payload classes are SOURCE_WRITE, SOURCE_SUPPRESS and NORMAL_READ.
Every operation uses 1a's combined `_operation_admission`: current HOME process,
ACTIVE session, live lease, generation, persistent incarnation, exact root-issued
object identity, operation class and the fixed principal/domain/perspective/
namespace/destination constraints. Legacy, exercise, copied and stale objects
fail. The 1a marker-only front still enables only its metadata contract check.

Each protected transaction repeats exact schema/profile/ownership and persisted
origin/stop-use validation before payload access. Writes also validate complete
authority state before commit. Missing stop-use state is never interpreted as
usable. Source reads use SQLite `mode=ro` and `query_only=ON`; reads do not mutate
memory or return search/discovery results.

## Manual-event and stop-use semantics

The only registered adapter is `manual_event_v0.1`, version `0.1`, pinned to the
store's `OriginNamespaceId`. `capture_manual_event` is a host-only issuer: it
generates caller-independent origin/external-object, snapshot and capture UUIDs.
Issued provenance also binds session, store incarnation and generation. Caller
metadata cannot supply these identities or replace current-root registration.

Each immutable snapshot has a UUID and a contiguous integer version starting at
1. Recapture derives identity from the exact persisted source and gets a fresh
capture identity. Explicit next snapshots preserve the canonical origin and get
a new snapshot UUID/version. Competing pending tokens for the same version
cannot both commit. Older versions remain independently addressable; this does
not implement supersession. The content hash is solely integrity data: distinct
manual events with identical fixture text remain distinct origins.

First ingress atomically records origin, explicit usable stop-use state, source
snapshot and capture. Exact replay resolves by canonical origin and snapshot,
then verifies content integrity; it does not derive identity from the hash.
Stop-use is irreversible for the entire canonical origin and all its snapshots.
Both exact replay and held next-snapshot tokens are rejected after suppression,
before reading/writing payload. Restart preserves the suppression and requires
fresh current-session objects. A new independent manual event is not an implicit
relabeling or reactivation of an existing origin.

The 1a shutdown cutoff is retained: CLOSING atomically closes admission, admitted
work drains under the shared coordinator, registries/resources are cleared,
CLOSED is terminal, and lease release is last. A queued-but-not-admitted context
is rechecked after the cutoff. Stop-use and reads/writes share this serialization.
Failed cleanup retains the 1a quarantined root/lease behavior.

## Executed Linux verification

Environment: Linux x86_64, Python 3.12.14. Commands run from the repository root.
Baseline at the exact 1a commit: 389 tests passed.

| Exact command | Result |
| --- | --- |
| `PYTHONPATH=src python -m unittest discover -s tests -v` | 425 tests, OK |
| `PYTHONPATH=src:tests python -m unittest test_production_memory -v` | 36 tests, OK |
| `PYTHONPATH=src:tests python -W error::ResourceWarning -m unittest test_production_memory test_production_authority test_host_runtime test_host_config test_store_domain test_real_authority_ordering test_real_ingress test_real_normal_read test_real_source_origin test_real_stop_use test_real_delivery -v` | 197 tests, OK; no ResourceWarning/unraisable-exception output |
| `python -m compileall -q src tests scripts` | Exit 0 |
| `git diff --check` and `git diff --cached --check` | Exit 0 |
| `python scripts/verify.py` | 128 critical tests, OK; MINI-READY VERIFIER: GREEN; real personal data CLOSED |

Coverage includes all nineteen required categories: pre-barrier denial and each
new schema-stage failure; valid ingress; legacy/test/copied/exercise/stale
authority rejection; bidirectional store separation; absent/damaged origin and
stop-use schema/state; suppression against normal read/replay/new snapshots;
shutdown cutoff; restart persistence; wrong incarnation; fork rejection; and
exclusively synthetic fixture inputs. Additional tests cover commit rollback,
query-only reads, live-lease contention/loss, source-scope corruption, content
integrity, and stop-use/read serialization. An isolated subprocess actively
blocks all test imports while executing the synthetic vertical slice and emits
no payload to stdout. No tests, logs or temporary stores ingest real content.

## Completed Windows acceptance — actual HOME Windows checkout

Commit under test: `8b9db5bed83ca488f83d8134eed67c32214d6d28`.

The user confirmed completion on the actual HOME Windows checkout and supplied
the following results on 2026-09-28 (Asia/Shanghai). These are user-reported
Windows results, not a Windows run performed by this Linux environment. This
follow-up changes acceptance documentation only; implementation logic is unchanged.

| Windows check | Reported result |
| --- | --- |
| Targeted production/host suite | 81 tests OK, skipped=4 |
| Full suite | 425 tests OK, skipped=8 |
| `compileall` | OK |
| `git diff --check` | OK |
| MINI-READY verifier | 128 tests OK, skipped=5 |
| Verifier status | `MINI-READY VERIFIER: GREEN` |
| Real-data boundary | `real personal data remains CLOSED` |

Skipped tests are retained explicitly and are not counted as executed passes.
The user did not supply the Python version, individual skip reasons or a raw
command transcript; none are inferred. The previously documented PowerShell
acceptance procedure is preserved below as a reproduction reference, not as
an independently verified transcript of the Windows run:

```powershell
git status --short
git log -1 --format="%H %s"
python --version
$env:PYTHONPATH = "src;tests"
python -W error::ResourceWarning -m unittest test_host_runtime test_host_config test_production_authority test_production_memory -v
python -m unittest discover -s tests -v
python -m compileall -q src tests scripts
git diff --check
python scripts/verify.py
```

The reported Windows acceptance covers the required production/host suites and
existing MINI-READY verifier. Real personal data remains CLOSED; acceptance
does not authorize real-data ingestion or a merge.

## Before #08a.1c

1. Complete main-reviewer review of this branch; Windows acceptance above is completed.
2. Any broader service graph or real request authentication binding needs its own
   scoped task; this slice proves trusted host/root possession only.
3. Real personal data, providers, payload reset/restore and delivery remain
   closed. Passing this synthetic slice is not authorization to enable them.
