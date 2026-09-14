from __future__ import annotations

import os
from uuid import uuid4


class HomeProcessIsolationError(RuntimeError):
    """A HOME runtime object was used from a forked/inherited process."""


_ORIGIN_PID = os.getpid()
_PROCESS_INSTANCE_ID = f"process-{uuid4().hex}"


def require_home_process() -> None:
    """Fail closed if this module state was inherited across ``fork``.

    HOME's current authority coordinators, delivery registries, capabilities, and
    host leases are process-local by design. A fork child inherits Python memory
    without inheriting a valid HOME process incarnation, so it must not reuse
    any of those objects. Fresh spawned/executed processes import this module
    again and receive their own process identity.
    """

    if os.getpid() != _ORIGIN_PID:
        raise HomeProcessIsolationError(
            "HOME process-local authority cannot be reused after fork"
        )


def current_home_process_instance_id() -> str:
    require_home_process()
    return _PROCESS_INSTANCE_ID


def home_process_origin_pid() -> int:
    return _ORIGIN_PID
