from dataclasses import dataclass
from uuid import uuid4

from home_memory_core.interpretation import (
    InterpretationRecord,
    SYNTHETIC_UNATTRIBUTED_INSTANCE_ID,
)


@dataclass(frozen=True)
class InterpretationThread:
    thread_id: str
    question: str
    perspective_owner: str
    perspective_instance_id: str
    about_subject: str
    scope: str


@dataclass(frozen=True)
class ThreadAdmissionRecord:
    admission_id: str
    thread_id: str
    interpretation_id: str
    perspective_instance_id: str
    admitted_by_instance_id: str


@dataclass(frozen=True)
class ThreadTopology:
    thread_id: str
    interpretation_ids: frozenset[str]
    supersession_edges: frozenset[tuple[str, str]]


def create_interpretation_thread(
    *,
    question: str,
    perspective_owner: str,
    perspective_instance_id: str,
    about_subject: str,
    scope: str,
) -> InterpretationThread:
    values = {
        "question": question,
        "perspective_owner": perspective_owner,
        "perspective_instance_id": perspective_instance_id,
        "about_subject": about_subject,
        "scope": scope,
    }

    for field_name, value in values.items():
        if not value.strip():
            raise ValueError(f"{field_name} cannot be empty")

    if perspective_instance_id == SYNTHETIC_UNATTRIBUTED_INSTANCE_ID:
        raise ValueError(
            "a real interpretation thread needs a concrete "
            "perspective instance"
        )

    return InterpretationThread(
        thread_id=f"thread-{uuid4().hex}",
        question=question,
        perspective_owner=perspective_owner,
        perspective_instance_id=perspective_instance_id,
        about_subject=about_subject,
        scope=scope,
    )


def create_thread_admission(
    *,
    thread: InterpretationThread,
    interpretation: InterpretationRecord,
    admitted_by_instance_id: str,
) -> ThreadAdmissionRecord:
    if not admitted_by_instance_id.strip():
        raise ValueError("admitted_by_instance_id cannot be empty")

    if interpretation.perspective_owner != thread.perspective_owner:
        raise ValueError(
            "thread admission must stay within "
            "the thread perspective owner"
        )

    if (
        interpretation.perspective_instance_id
        != thread.perspective_instance_id
    ):
        raise ValueError(
            "thread admission must stay within "
            "the thread perspective instance"
        )

    if interpretation.about_subject != thread.about_subject:
        raise ValueError(
            "thread admission must stay about "
            "the thread subject"
        )

    if interpretation.scope != thread.scope:
        raise ValueError(
            "thread admission must stay within "
            "the thread scope"
        )

    return ThreadAdmissionRecord(
        admission_id=f"admission-{uuid4().hex}",
        thread_id=thread.thread_id,
        interpretation_id=interpretation.interpretation_id,
        perspective_instance_id=thread.perspective_instance_id,
        admitted_by_instance_id=admitted_by_instance_id,
    )
