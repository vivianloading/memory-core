from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from home_memory_core.host_config import HomeMiniHostConfig, load_home_mini_host_config
from home_memory_core.host_runtime import HomeSingleInstanceLease, acquire_home_single_instance


@dataclass
class HomeMiniHostSession:
    """One supported closed HOME mini-host startup session.

    Holding this object means the process owns the OS-backed single-instance
    lease for the canonical runtime. It grants no memory, model, connector, or
    real-data authority.
    """

    config: HomeMiniHostConfig
    _lease: HomeSingleInstanceLease
    _closed: bool = False

    @property
    def identity(self):
        return self._lease.identity

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._lease.release()
        self._closed = True

    def __enter__(self) -> HomeMiniHostSession:
        if self._closed:
            raise RuntimeError("closed HOME mini-host session cannot be reused")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def start_home_mini_host(config_path: str | Path) -> HomeMiniHostSession:
    """Start the closed supported mini-host boundary from strict TOML config.

    Configuration is validated before any runtime directory is created. The
    single-instance lease is then acquired before callers are given the
    canonical database path. This function deliberately does not open the
    database or resolve any secret provider.
    """

    config = load_home_mini_host_config(config_path)
    lease = acquire_home_single_instance(
        runtime_root=config.runtime_root,
        db_path=config.db_path,
        real_data_allowed=config.real_data_allowed,
    )
    return HomeMiniHostSession(config=config, _lease=lease)
