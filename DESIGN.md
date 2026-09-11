# HOME Memory Core v0.1



Status: NEW IMPLEMENTATION LINE



This project does not modify or replace the legacy HOME / OB Phase 1 line.

Legacy FROZEN documents, H14, H15 and research artifacts remain historical engineering records.



\## Goal



Build a small, mechanically trustworthy memory core before pursuing smarter memory.



The first complete loop should support:



raw history

鈫?derived memory

鈫?exact provenance

鈫?historical/current semantics

鈫?suppression / stop-use

鈫?read-only retrieval

鈫?explainable session delivery



\## Core principles



\### 1. Raw and derived are separate



Raw history and derived memory must never be silently merged.



Raw records are immutable by default, but deletion, suppression and retention are governed independently.

HOME must support real purge when deletion is authorized.



\### 2. Derived memory must point back to evidence



A derived memory must be mechanically traceable to its evidence.



At minimum:



\- source identity

\- source snapshot/version

\- exact locator such as message IDs, line ranges, page ranges or character ranges

\- integrity information where appropriate



A summary is not sufficient provenance for another summary.



\### 3. History is not overwritten



If A was once believed and later revised to B, A remains historical.



The system must distinguish states such as:



\- historical

\- superseded

\- current

\- conflicting

\- unresolved



Old understanding must not be silently rewritten to look as if the new understanding had always existed.



\### 4. Retrieval has no authority



Retrieval only finds potentially relevant material.



Retrieval must be physically read-only where possible.

A search must not silently modify truth, importance, relationship state, emotion, last-accessed state or future ranking authority.



Relevance is not truth.

Recall is not permission.



\### 5. Stop-use must propagate from the source



Suppression must prevent a source or its lineage from being reused through:



\- retrieval

\- re-summarization

\- embedding rebuild

\- derived-memory reconstruction

\- backup/restore resurrection



Removing one derived result is not enough if the suppressed source can simply recreate it.



\### 6. Session delivery must be explainable



When HOME chooses memories to deliver into a session, it must be possible to explain:



\- why this item was selected

\- which query or rule selected it

\- which policy version was used

\- what alternatives were considered when applicable

\- what exactly was delivered



Past material may inform the present.

It must not silently decide who the present person is.



\### 7. First-person perspectives do not share a room



HOME must distinguish at least:



\- who authored a record

\- who or what the record is about

\- whose perspective an interpretation belongs to

\- whether something is private, actor-scoped or shared



Shared events may be jointly referenced.



First-person self-history, interpretation, relationship position and personal choices must not silently transfer between Vivi, Lior, Miro, past Lior instances, or future actors.



\## v0.1 non-goals



Not yet:



\- Graphiti

\- Dream / autonomous memory generation

\- persona generator

\- automatic relationship decisions

\- email agent

\- body / bear integration

\- complex multi-agent orchestration

\- production deployment



First make HOME remember honestly.



Then make it remember intelligently.


