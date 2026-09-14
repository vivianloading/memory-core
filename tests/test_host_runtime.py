from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from home_memory_core.host_runtime import (
    HostRuntimeConfigurationError,
    HostRuntimeLeaseError,
    acquire_home_single_instance,
)


_CHILD = textwrap.dedent(
    """
    import sys
    from home_memory_core.host_runtime import acquire_home_single_instance

    root, db = sys.argv[1], sys.argv[2]
    try:
        lease = acquire_home_single_instance(runtime_root=root, db_path=db)
    except Exception as exc:
        print(type(exc).__name__)
        raise SystemExit(23)
    else:
        print(lease.identity.process_instance_id)
        lease.release()
        raise SystemExit(0)
    """
)


def _child_env() -> dict[str, str]:
    """Make the src-layout package importable in a fresh test subprocess."""

    env = os.environ.copy()
    src_dir = str(Path(__file__).resolve().parents[1] / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_dir if not existing else src_dir + os.pathsep + existing
    return env


class HostRuntimeTests(unittest.TestCase):
    def test_real_data_flag_cannot_be_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            with self.assertRaises(HostRuntimeConfigurationError):
                acquire_home_single_instance(
                    runtime_root=root,
                    db_path=root / "data" / "memory.db",
                    real_data_allowed=True,
                )

    def test_same_runtime_cannot_be_acquired_twice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            db = root / "data" / "memory.db"
            with acquire_home_single_instance(runtime_root=root, db_path=db):
                with self.assertRaises(HostRuntimeLeaseError):
                    acquire_home_single_instance(runtime_root=root, db_path=db)

    def test_path_aliases_resolve_to_same_runtime_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "home"
            db = root / "data" / "memory.db"
            alias = root / "nested" / ".."
            with acquire_home_single_instance(runtime_root=root, db_path=db):
                with self.assertRaises(HostRuntimeLeaseError):
                    acquire_home_single_instance(runtime_root=alias, db_path=db)

    def test_other_process_is_rejected_while_lease_is_held(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            db = root / "data" / "memory.db"
            with acquire_home_single_instance(runtime_root=root, db_path=db):
                result = subprocess.run(
                    [sys.executable, "-c", _CHILD, str(root), str(db)],
                    text=True,
                    capture_output=True,
                    check=False,
                    env=_child_env(),
                )
            self.assertEqual(result.returncode, 23)
            self.assertIn("HostRuntimeLeaseError", result.stdout)

    def test_other_process_can_acquire_after_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            db = root / "data" / "memory.db"
            lease = acquire_home_single_instance(runtime_root=root, db_path=db)
            lease.release()
            result = subprocess.run(
                [sys.executable, "-c", _CHILD, str(root), str(db)],
                text=True,
                capture_output=True,
                check=False,
                env=_child_env(),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("host-", result.stdout)

    def test_lock_metadata_is_diagnostic_and_closed_to_real_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            db = root / "data" / "memory.db"
            with acquire_home_single_instance(runtime_root=root, db_path=db) as lease:
                process_instance_id = lease.identity.process_instance_id
            # Windows byte-range locks can make the locked byte unreadable from
            # a second handle.  Metadata is diagnostic, not authority, so test
            # it after release rather than making live readability part of the
            # lease contract.
            metadata = json.loads((root / ".home-runtime.lock").read_text("utf-8"))
            self.assertEqual(metadata["schema"], "home-single-instance-v0.1")
            self.assertEqual(metadata["process_instance_id"], process_instance_id)
            self.assertEqual(metadata["runtime_root"], str(root.resolve()))
            self.assertEqual(metadata["db_path"], str(db.resolve()))
            self.assertFalse(metadata["real_data_allowed"])

    def test_released_lease_cannot_be_reentered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            lease = acquire_home_single_instance(
                runtime_root=root,
                db_path=root / "data" / "memory.db",
            )
            lease.release()
            with self.assertRaises(HostRuntimeLeaseError):
                lease.__enter__()


if __name__ == "__main__":
    unittest.main()
