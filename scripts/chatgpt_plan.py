from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from home_memory_core.chatgpt_plan_auth import (  # noqa: E402
    DEFAULT_HOST_PATH,
    DEFAULT_PROFILE_PATH,
    ChatGPTPlanAuthError,
    list_models,
    load_profile,
    sign_in,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Connect HOME on this machine to "
            "ChatGPT plan usage."
        )
    )
    parser.add_argument(
        "command",
        choices=("login", "models", "status"),
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=DEFAULT_PROFILE_PATH,
    )
    parser.add_argument(
        "--host",
        type=Path,
        default=DEFAULT_HOST_PATH,
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "login":
            profile = sign_in(
                profile_path=args.profile,
                host_path=args.host,
            )
            print(
                "Connected with ChatGPT. "
                "ChatGPT plan usage is enabled."
            )
            print(
                f"Client registration: "
                f"{profile.client_id}"
            )
            models = list_models(
                profile=profile
            )
            print("Available models:")
            for item in models:
                print(
                    f"  {item['slug']}\t"
                    f"{item['display_name']}"
                )
            return 0

        profile = load_profile(
            path=args.profile,
        )
        if args.command == "status":
            print(
                "Connected with ChatGPT; "
                "access token is fresh and "
                "plan usage is enabled."
            )
            return 0

        models = list_models(
            profile=profile
        )
        for item in models:
            print(
                f"{item['slug']}\t"
                f"{item['display_name']}"
            )
        return 0
    except ChatGPTPlanAuthError as exc:
        print(
            f"ChatGPT plan connection error: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
