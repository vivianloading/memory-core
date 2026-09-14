from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping, Sequence

from home_memory_core.host_config import HostConfigError, HomeMiniHostConfig, load_home_mini_host_config
from home_memory_core.host_runtime import HostRuntimeLeaseError
from home_memory_core.host_startup import start_home_mini_host


class HostVerificationError(RuntimeError):
    """The supported mini-ready verification could not prove its closed contract."""


@dataclass(frozen=True)
class HostVerificationResult:
    config: HomeMiniHostConfig
    child_lock_rejected: bool
    child_reacquired_after_release: bool


_CHILD_STARTUP = r"""
import sys
from home_memory_core.host_runtime import HostRuntimeLeaseError
from home_memory_core.host_startup import start_home_mini_host

config_path = sys.argv[1]
try:
    with start_home_mini_host(config_path):
        pass
except HostRuntimeLeaseError:
    raise SystemExit(23)
except Exception as exc:
    print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
    raise SystemExit(24)
else:
    raise SystemExit(0)
"""


def verify_closed_mini_host(
    config_path: str | Path,
    *,
    src_dir: str | Path | None = None,
    python_executable: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> HostVerificationResult:
    """Verify the current closed mini-host boundary without opening HOME data.

    This probe is intentionally narrow. It validates the strict non-secret
    configuration and proves that the supported startup path owns one OS-backed
    runtime lease across processes. It does not open or initialize the configured
    database, and it never enables real personal data or a secret provider.
    """

    try:
        config = load_home_mini_host_config(config_path)
    except HostConfigError as exc:
        raise HostVerificationError("closed mini-host config validation failed") from exc

    if config.real_data_allowed:
        raise HostVerificationError("real personal data must remain disabled")
    if config.secrets_mode != "disabled":
        raise HostVerificationError("secret providers must remain disabled")

    child_env = _child_env(src_dir=src_dir, base_env=env)
    executable = str(python_executable or sys.executable)

    try:
        with start_home_mini_host(config.config_path):
            held = _run_child_startup(
                executable=executable,
                config_path=config.config_path,
                env=child_env,
            )
            if held.returncode != 23:
                raise HostVerificationError(
                    "cross-process single-instance probe did not fail closed while lease was held"
                )
    except HostRuntimeLeaseError as exc:
        raise HostVerificationError(
            "mini-host runtime is already owned; stop the supported HOME host before verification"
        ) from exc

    released = _run_child_startup(
        executable=executable,
        config_path=config.config_path,
        env=child_env,
    )
    if released.returncode != 0:
        detail = _compact_child_detail(released)
        raise HostVerificationError(
            "cross-process single-instance probe could not reacquire after release"
            + (f": {detail}" if detail else "")
        )

    return HostVerificationResult(
        config=config,
        child_lock_rejected=True,
        child_reacquired_after_release=True,
    )


def critical_test_modules() -> tuple[str, ...]:
    """Focused closed-boundary tests used by the mini-ready verifier."""

    return (
        "tests.test_host_runtime",
        "tests.test_host_config",
        "tests.test_real_authority_ordering",
        "tests.test_real_source_origin",
        "tests.test_real_stop_use",
        "tests.test_real_delivery",
    )


def verifier_commands(
    *,
    repo_root: str | Path,
    python_executable: str | Path | None = None,
) -> tuple[tuple[str, ...], ...]:
    """Return deterministic verifier subprocess commands for the current repo."""

    root = Path(repo_root).resolve()
    executable = str(python_executable or sys.executable)
    modules = critical_test_modules()
    return (
        (
            executable,
            "-W",
            "error::ResourceWarning",
            "-m",
            "unittest",
            *modules,
            "-v",
        ),
        (
            executable,
            "-m",
            "compileall",
            "-q",
            str(root / "src"),
            str(root / "scripts"),
        ),
    )


def verifier_subprocess_env(
    *,
    repo_root: str | Path,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a subprocess environment for the repo's src-layout tests.

    Older HOME test modules intentionally import the trusted test support as a
    top-level test helper, matching unittest discovery. Include both ``src``
    and ``tests`` so the verifier behaves the same way on Windows and macOS.
    """

    root = Path(repo_root).resolve()
    child_env = dict(base_env or os.environ)
    prefixes = [str(root / "src"), str(root / "tests")]
    existing = child_env.get("PYTHONPATH")
    if existing:
        prefixes.append(existing)
    child_env["PYTHONPATH"] = os.pathsep.join(prefixes)
    return child_env


def _run_child_startup(
    *,
    executable: str,
    config_path: Path,
    env: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [executable, "-c", _CHILD_STARTUP, str(config_path)],
        text=True,
        capture_output=True,
        check=False,
        env=dict(env),
    )


def _child_env(
    *,
    src_dir: str | Path | None,
    base_env: Mapping[str, str] | None,
) -> dict[str, str]:
    child_env = dict(base_env or os.environ)
    if src_dir is None:
        return child_env

    source = str(Path(src_dir).resolve())
    existing = child_env.get("PYTHONPATH")
    child_env["PYTHONPATH"] = source if not existing else source + os.pathsep + existing
    return child_env


def _compact_child_detail(result: subprocess.CompletedProcess[str]) -> str:
    parts: list[str] = []
    if result.stdout.strip():
        parts.append(result.stdout.strip())
    if result.stderr.strip():
        parts.append(result.stderr.strip())
    detail = " | ".join(parts)
    return detail[-500:]
