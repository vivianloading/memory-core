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
    HomeHostRuntimeIdentity,
    HomeSingleInstanceLease,
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

    def test_home_single_instance_lease_cannot_be_caller_minted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            db = root / "data" / "memory.db"
            db.parent.mkdir(parents=True, exist_ok=True)
            fake_lock = db.parent / "fake.lock"
            handle = fake_lock.open("a+b", buffering=0)
            try:
                identity = HomeHostRuntimeIdentity(
                    runtime_root=root.resolve(),
                    db_path=db.resolve(),
                    process_instance_id="host-forged",
                    owner_pid=os.getpid(),
                    lock_path=fake_lock.resolve(),
                    real_data_allowed=False,
                )
                with self.assertRaises(HostRuntimeLeaseError):
                    HomeSingleInstanceLease(
                        identity=identity,
                        handle=handle,
                        _marker=object(),
                    )
            finally:
                handle.close()

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


    def test_nested_runtime_roots_cannot_lock_same_canonical_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            outer = base / "pilot"
            db = outer / "data" / "home.db"
            inner = outer / "data"
            with acquire_home_single_instance(runtime_root=outer, db_path=db):
                result = subprocess.run(
                    [sys.executable, "-c", _CHILD, str(inner), str(db)],
                    text=True,
                    capture_output=True,
                    check=False,
                    env=_child_env(),
                )
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertIn("HostRuntimeLeaseError", result.stdout)

    @unittest.skipUnless(hasattr(os, "fork"), "fork isolation is POSIX-only")
    def test_forked_child_cannot_release_parent_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            db = root / "data" / "memory.db"
            lease = acquire_home_single_instance(runtime_root=root, db_path=db)
            pid = os.fork()
            if pid == 0:  # pragma: no cover - child process assertion
                try:
                    lease.release()
                except HostRuntimeLeaseError:
                    os._exit(0)
                except BaseException:
                    os._exit(2)
                else:
                    os._exit(3)

            _, status = os.waitpid(pid, 0)
            self.assertEqual(os.waitstatus_to_exitcode(status), 0)
            # The child must not have unlocked the parent's file description.
            result = subprocess.run(
                [sys.executable, "-c", _CHILD, str(root), str(db)],
                text=True,
                capture_output=True,
                check=False,
                env=_child_env(),
            )
            self.assertEqual(result.returncode, 23, result.stderr)
            lease.release()

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
            lock_path = db.parent / ".home-runtime.lock"
            metadata = json.loads(lock_path.read_text("utf-8"))
            self.assertEqual(metadata["schema"], "home-single-instance-v0.1")
            self.assertEqual(metadata["process_instance_id"], process_instance_id)
            self.assertEqual(metadata["owner_pid"], os.getpid())
            self.assertEqual(metadata["lock_path"], str(lock_path.resolve()))
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
