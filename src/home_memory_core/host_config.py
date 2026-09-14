from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any


CONFIG_SCHEMA = "home-mini-host-v0.1"
_MAX_CONFIG_BYTES = 64 * 1024


class HostConfigError(RuntimeError):
    """The mini-host configuration is unsafe, malformed, or unsupported."""


@dataclass(frozen=True)
class HomeMiniHostConfig:
    """Strict non-secret configuration for the supported HOME mini host.

    This milestone intentionally accepts no secret values and no real-data
    enablement. Future integrations must open explicit secret providers rather
    than smuggling credentials into this file.
    """

    config_path: Path
    runtime_root: Path
    db_path: Path
    real_data_allowed: bool = False
    secrets_mode: str = "disabled"


def load_home_mini_host_config(config_path: str | Path) -> HomeMiniHostConfig:
    """Load one strict, non-secret HOME mini-host TOML file.

    Relative runtime paths are anchored to the configuration file directory.
    The database must remain inside the canonical runtime root so the supported
    startup path cannot accidentally pair one database with multiple unrelated
    runtime leases.
    """

    path = _canonical_config_path(config_path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise HostConfigError(f"cannot stat HOME host config: {path}") from exc
    if size > _MAX_CONFIG_BYTES:
        raise HostConfigError("HOME host config is unexpectedly large")

    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise HostConfigError(f"cannot load HOME host config: {path}") from exc

    _require_exact_keys(raw, {"home", "secrets"}, where="top level")
    home = _require_table(raw.get("home"), where="home")
    secrets = _require_table(raw.get("secrets"), where="secrets")

    _require_exact_keys(
        home,
        {"schema", "runtime_root", "database", "real_data_allowed"},
        where="home",
    )
    _require_exact_keys(secrets, {"mode"}, where="secrets")

    schema = _require_string(home["schema"], field="home.schema")
    if schema != CONFIG_SCHEMA:
        raise HostConfigError("unsupported HOME host config schema")

    real_data_allowed = home["real_data_allowed"]
    if type(real_data_allowed) is not bool:
        raise HostConfigError("home.real_data_allowed must be a boolean")
    if real_data_allowed:
        raise HostConfigError(
            "mini-host configuration remains closed to real personal data"
        )

    secrets_mode = _require_string(secrets["mode"], field="secrets.mode")
    if secrets_mode != "disabled":
        raise HostConfigError(
            "mini-host secret providers remain disabled in this milestone"
        )

    base = path.parent
    runtime_value = _require_string(home["runtime_root"], field="home.runtime_root")
    database_value = _require_string(home["database"], field="home.database")

    runtime_input = Path(runtime_value).expanduser()
    if not runtime_input.is_absolute():
        runtime_input = base / runtime_input
    runtime_root = _canonical_path(runtime_input, field="home.runtime_root")

    database_input = Path(database_value)
    if database_input.is_absolute():
        raise HostConfigError(
            "home.database must be relative to home.runtime_root"
        )
    db_path = _canonical_path(runtime_root / database_input, field="home.database")
    if not _is_within(db_path, runtime_root):
        raise HostConfigError(
            "home.database must remain inside the canonical runtime root"
        )

    return HomeMiniHostConfig(
        config_path=path,
        runtime_root=runtime_root,
        db_path=db_path,
        real_data_allowed=False,
        secrets_mode="disabled",
    )


def _canonical_config_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HostConfigError(f"HOME host config does not exist: {path}") from exc
    if not resolved.is_file():
        raise HostConfigError(f"HOME host config is not a file: {resolved}")
    return resolved


def _canonical_path(value: Path, *, field: str) -> Path:
    try:
        return value.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise HostConfigError(f"cannot canonicalize {field}") from exc


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _require_table(value: Any, *, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HostConfigError(f"{where} must be a TOML table")
    return value


def _require_exact_keys(
    value: dict[str, Any],
    expected: set[str],
    *,
    where: str,
) -> None:
    actual = set(value)
    if actual != expected:
        unexpected = sorted(actual - expected)
        missing = sorted(expected - actual)
        details: list[str] = []
        if unexpected:
            details.append(f"unexpected={unexpected}")
        if missing:
            details.append(f"missing={missing}")
        raise HostConfigError(
            f"unsupported HOME host config keys at {where}: " + ", ".join(details)
        )


def _require_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise HostConfigError(f"{field} must be a string")
    if not value.strip() or "\x00" in value:
        raise HostConfigError(f"{field} must be a non-empty safe string")
    return value
