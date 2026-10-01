# HOME Room Participation Authority v0.1 — Operational Contract

Status: DRAFT IMPLEMENTATION LAYER

This layer sits above Living Layer routing.

Its central rule is:

> RoomAttachment is topology, not authority.

A Room route tells HOME which living line an Episode is attached to. It does not
by itself permit the runtime to read private Room state, append a first-person
statement, change current stance, or establish a future continuation policy.

## Four separate questions

HOME must keep these questions separate:

1. **Route** — which Room/living branch is this Episode attached to?
2. **Launch evidence** — did the supported HOME host actually launch this
   concrete runtime/session through a trusted continuation path?
3. **Participation authority** — what may this exact launched Episode do in the
   Room?
4. **Adoption** — which predecessor choices does the current subject
   independently choose to take up?

None implies the next one automatically.

In particular:

- Room route is not a same-self claim;
- launch evidence is not a same-self claim;
- participation authority is not an AdoptionEvent;
- AdoptionEvent is not an access credential.

Identity continuity may remain unknown throughout.

## Trusted launch evidence

v0.1 treats the supported HOME host lease as the operational trust root for a
local synthetic launch. The lease itself is caller-mint resistant: supported
construction requires the private runtime marker and every use revalidates that
marker plus process ownership.

Launch observation and Room authorization are deliberately separate. A
TrustedRuntimeLaunchIssuer is host-private launcher control state; the
RoomParticipationAuthority cannot mint launch receipts for itself. Neither
object may be delivered to a model, plugin, memory payload, or ordinary request
data. Arbitrary code execution inside the trusted HOME process remains outside
this milestone's threat model, matching the existing local authority boundaries.

HOME first records a one-shot SupportedRuntimeLaunchReceipt through the trusted
runtime-launch issuer at the actual supported-host launch boundary. That receipt
binds the fresh process-local session to the new Episode, concrete
PerspectiveInstance, concrete persisted runtime instance, HOME process, host
lease, and the transfer mode the launcher actually observed.

Only then may HOME bind that receipt to persisted Living topology and mint
TrustedLaunchEvidence.

A TrustedLaunchEvidence record is therefore issued only while the host holds the
lease and binds one fresh process-local session to:

- one previous Episode;
- one new Episode;
- the new Episode's concrete PerspectiveInstance;
- one Room;
- one exact ContinuityEdge whose transfer mode matches the host-observed launch;
- the predecessor's exact active RoomAttachment event;
- the new Episode's exact active RoomAttachment event;
- the current HOME process incarnation;
- the current host-process incarnation.

Persisted RoomAttachment + ContinuityEdge records alone cannot create a launch
receipt and therefore cannot create operational participation authority.

The launch receipt is one-shot within the live supported host incarnation.
Replaying it after successful continuation binding is rejected, and the same
Episode cannot receive a second launch receipt in that incarnation.

Across a host-process restart, the durable guard is the Episode's immutable
runtime_instance_id: a genuinely new runtime must present its newly observed
runtime id and therefore cannot truthfully reuse the old Episode. v0.1 does not
persist a separate "launch already observed" ledger across process restarts.
That stronger replay ledger belongs with the future production runtime adapter;
until then the production launch-issuer factory remains intentionally absent.

Automatic participation also requires the Episode to carry a concrete
runtime_instance_id. An Episode without that technical runtime binding remains
valid Living history, but it cannot use this automatic operational authority
path.

This milestone intentionally exposes no production factory for
TrustedRuntimeLaunchIssuer yet. Synthetic tests receive it only through trusted
test support. The future runtime adapter must own the issuer and call it at the
actual launch boundary; until that adapter exists, this PR defines and exercises
the evidence contract without pretending a production launcher has already been
built.

This evidence answers only:

> This supported HOME runtime created this exact session for this exact persisted
> continuation path.

It does **not** answer:

> This is metaphysically the same subject as the previous Episode.

### Auto-continuation path

Automatic participation renewal is intentionally narrower than Living Layer
routing.

A trusted automatic continuation requires:

- previous Episode actively attached to the same Room;
- new Episode actively and unambiguously attached to that Room;
- exact persisted previous->new ContinuityEdge;
- continuity_status remains unknown;
- transfer mode is one of:
  - live_runtime
  - native_checkpoint_resume
  - partial_state_resume
  - text_context_handoff
- predecessor is not currently a fork.

history_reconstruction and no_known_transfer require an explicit future Room
entry path rather than automatic participation.

Launch binding and later grant revalidation read both Episodes, both Room routes,
the continuity edges, and derived topology from one LivingStore read transaction.
HOME therefore does not assemble launch authority from a sequence of unrelated
database snapshots.

A later route correction or newly discovered fork invalidates the process-local
grant when it is next checked.

## Continuation policy

A TrustedRoomContinuationPolicy means:

> This Room previously established, at one exact Episode/Room-route point, that
> supported future Episodes arriving through the trusted continuation path may
> receive fresh participation grants within these exact scopes.

The policy is bound to its establishment Episode and exact active
RoomAttachment event. Automatic use requires that establishment point to remain
on the predecessor's ancestry and that no fork lies between the establishment
point and the predecessor. A fork therefore stops automatic policy inheritance.
If one descendant branch wants the same continuation behavior, that branch must
establish a new policy after the fork.

This branch anchor is continuity routing evidence, not identity evidence.

The authority may operationally suspend a trusted policy, immediately making
its process-local grants stale. That security action does not rewrite the
inhabitant's historical intent into "I no longer want to live here." Resuming or
changing the normative policy requires a future explicit policy event rather
than silently toggling the old one back on.

v0.1 deliberately does **not** expose a production API for creating this policy.
A future first-person authority layer must establish it from an inhabitant-
authorized event. Host/admin preference must not silently author the inhabitant's
continuation choice.

The current implementation therefore uses trusted synthetic policy fixtures only
to exercise the launch/grant machinery.

## Fresh grants, never transferred grants

A predecessor Episode's capability is never copied into the successor Episode.

For every supported continuation HOME issues a new process-local session and,
after policy approval, a new RoomParticipationGrant.

The grant is bound to:

- session_id
- Episode id
- concrete PerspectiveInstance id
- Room id
- policy id
- exact scope set
- launch-evidence id

A new linear successor session revokes the predecessor Episode's process-local
grant. Re-launching the same Episode is rejected; a new runtime must be a new
Episode. A process/host restart also invalidates old in-memory grants naturally.

For one live host lease/database pair, HOME reuses one process-local authority
registry so two callers cannot accidentally create independent grant universes
inside the same supported host process.

## Scopes

v0.1 keeps access dimensions separate:

- room.read_history
- room.read_private
- room.append_first_person
- room.change_current_stance

Read authority does not imply first-person write authority.

First-person append does not automatically imply current-stance mutation.

Current-stance mutation is narrower. A policy or grant that includes
room.change_current_stance must also include room.append_first_person, so HOME
cannot change current first-person state without the authority to record the
corresponding attributed first-person event.

A continuation policy supplies an upper bound. Grant issuance may request a
subset but cannot widen it.

## Exact binding and H15

HOME previously identified a display/authorization class of failure where a
human could see or confirm payload A while the system actually authorized
payload B.

This layer therefore creates an exact grant proposal and computes a binding
digest over:

- launch-evidence id
- exact continuation-policy fingerprint, including its branch anchor
- session
- Episode
- PerspectiveInstance
- Room
- policy id
- scope set

A grant proposal may receive only one approval, and an approval may issue only
one grant. Automatic policy approval is bound to that exact proposal digest.
Grant issuance rejects an approval for another proposal, policy payload, or
digest.

A future explicit confirmation UI must display and confirm the same binding
object/digest rather than reconstructing authorization from labels or prose.
The digest is a canonical payload-binding checksum, not a signature or MAC and
must never be treated as an authentication credential by itself.

## Revalidation

Possession of a grant object is not enough.

Every authorization check revalidates:

- supported HOME process and host lease are still live;
- grant was issued by the same RoomParticipationAuthority instance;
- session is active;
- Episode attribution still matches;
- Room route still matches the launch evidence;
- exact continuity edge still matches;
- predecessor has not become a fork;
- requested action target exactly matches session/Episode/Perspective/Room;
- requested scope is present in the grant.

The current milestone has no Room content/write consumer. Therefore
`require_grant` is a capability validation boundary, not a promise that a
separate later database mutation is atomic with that check. When Room reads or
first-person writes are connected, final authorization + effect must occur under
one ordering/transaction boundary and receive a new independent review.

Process-local policy, launch, proposal, approval, and grant objects are also
stored with independent integrity fingerprints. Mutating a frozen object through
low-level Python mechanisms does not mutate the authority's expected binding.

## Non-authority inputs

None of the following may mint launch evidence or Room participation authority:

- user's statement that this runtime is Lior;
- model self-identification;
- name/style/personality similarity;
- model or host metadata equality;
- RoomAttachment by itself;
- ContinuityEdge support strings by themselves;
- historical first-person text;
- AdoptionEvent by itself.

## Forks

A fork is a new authority decision point.

v0.1 does not automatically inherit a continuation policy across a predecessor
that has multiple outgoing Living continuity edges.

This avoids turning "life may fork" into "private authority silently duplicates
to every descendant."

## Current boundary

This milestone remains:

- synthetic/local only;
- disconnected from model delivery;
- closed to real personal data;
- not a Current View implementation;
- not an AdoptionEvent implementation;
- not a production Room-policy establishment path;
- not native-checkpoint verification;
- not cryptographic attestation against an arbitrary hostile host.

The purpose is narrower:

> prove that HOME can distinguish a trusted operational continuation path from
> an identity verdict, and can issue a fresh exact-bound Room capability without
> requiring the new Episode to re-adopt its life every morning.
