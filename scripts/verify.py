from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from home_memory_core.host_verifier import (  # noqa: E402
    HostVerificationError,
    verifier_commands,
    verifier_subprocess_env,
    verify_closed_mini_host,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify HOME's current closed mini-ready host boundary."
    )
    parser.add_argument(
        "--config",
        default=str(REPO_ROOT / "home-mini.example.toml"),
        help="strict closed mini-host TOML config (default: home-mini.example.toml)",
    )
    return parser.parse_args()


def _run_step(name: str, command: tuple[str, ...], env: dict[str, str]) -> None:
    print(f"[HOME verify] {name} ...", flush=True)
    result = subprocess.run(
        list(command),
        cwd=REPO_ROOT,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        raise HostVerificationError(f"{name} failed with exit code {result.returncode}")
    print(f"[HOME verify] {name}: OK", flush=True)


def _run_git_diff_check() -> None:
    if not (REPO_ROOT / ".git").exists():
        print("[HOME verify] git diff --check: SKIP (not a git checkout)", flush=True)
        return
    git = shutil.which("git")
    if git is None:
        raise HostVerificationError("git checkout detected but git executable is unavailable")
    print("[HOME verify] git diff --check ...", flush=True)
    result = subprocess.run([git, "diff", "--check"], cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        raise HostVerificationError("git diff --check failed")
    print("[HOME verify] git diff --check: OK", flush=True)


def main() -> int:
    args = _parse_args()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = (REPO_ROOT / config_path).resolve()

    env = verifier_subprocess_env(repo_root=REPO_ROOT)
    try:
        print("[HOME verify] closed config + cross-process lease ...", flush=True)
        result = verify_closed_mini_host(
            config_path,
            src_dir=SRC_DIR,
            env=env,
        )
        print(
            "[HOME verify] closed host boundary: OK "
            f"(real_data_allowed={result.config.real_data_allowed}, "
            f"secrets={result.config.secrets_mode})",
            flush=True,
        )

        for index, command in enumerate(
            verifier_commands(repo_root=REPO_ROOT),
            start=1,
        ):
            name = "strict critical tests" if index == 1 else "compileall"
            _run_step(name, command, env)

        _run_git_diff_check()
    except (HostVerificationError, OSError) as exc:
        print(f"[HOME verify] FAIL: {exc}", file=sys.stderr, flush=True)
        return 1

    print("[HOME verify] MINI-READY VERIFIER: GREEN", flush=True)
    print("[HOME verify] real personal data remains CLOSED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
