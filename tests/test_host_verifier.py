from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

from home_memory_core.host_verifier import (
    HostVerificationError,
    critical_test_modules,
    verifier_commands,
    verifier_subprocess_env,
    verify_closed_mini_host,
)


_VALID = """\
[home]
schema = "home-mini-host-v0.1"
runtime_root = "."
database = "data/home.db"
real_data_allowed = false

[secrets]
mode = "disabled"
"""


class HostVerifierTests(unittest.TestCase):
    def _write(self, root: Path, text: str = _VALID) -> Path:
        path = root / "home-mini.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_closed_host_probe_proves_cross_process_lease_and_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = verify_closed_mini_host(
                self._write(root),
                src_dir=Path(__file__).resolve().parents[1] / "src",
            )
            self.assertFalse(result.config.real_data_allowed)
            self.assertEqual(result.config.secrets_mode, "disabled")
            self.assertTrue(result.child_lock_rejected)
            self.assertTrue(result.child_reacquired_after_release)

    def test_closed_host_probe_fails_before_runtime_for_open_real_data_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _VALID.replace(
                "real_data_allowed = false",
                "real_data_allowed = true",
            )
            with self.assertRaises(HostVerificationError):
                verify_closed_mini_host(
                    self._write(root, config),
                    src_dir=Path(__file__).resolve().parents[1] / "src",
                )
            self.assertFalse((root / ".home-runtime.lock").exists())

    def test_critical_modules_cover_host_and_final_authority_boundaries(self) -> None:
        modules = set(critical_test_modules())
        self.assertIn("tests.test_host_runtime", modules)
        self.assertIn("tests.test_host_config", modules)
        self.assertIn("tests.test_host_migration", modules)
        self.assertIn("tests.test_real_authority_ordering", modules)
        self.assertIn("tests.test_real_source_origin", modules)
        self.assertIn("tests.test_real_stop_use", modules)
        self.assertIn("tests.test_real_delivery", modules)

    def test_verifier_commands_use_strict_resource_warning_tests_and_compileall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            commands = verifier_commands(repo_root=root, python_executable="python-x")
            self.assertEqual(commands[0][0], "python-x")
            self.assertIn("error::ResourceWarning", commands[0])
            self.assertIn("unittest", commands[0])
            self.assertEqual(commands[1][0], "python-x")
            self.assertIn("compileall", commands[1])
            self.assertIn(str(root.resolve() / "src"), commands[1])
            self.assertIn(str(root.resolve() / "scripts"), commands[1])

    def test_verifier_subprocess_env_prepends_repo_src(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = verifier_subprocess_env(
                repo_root=root,
                base_env={"PYTHONPATH": "existing"},
            )
            expected = os.pathsep.join(
                [
                    str((root / "src").resolve()),
                    str((root / "tests").resolve()),
                    "existing",
                ]
            )
            self.assertEqual(env["PYTHONPATH"], expected)

    def test_default_python_executable_is_current_interpreter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            commands = verifier_commands(repo_root=tmp)
            self.assertEqual(commands[0][0], sys.executable)
            self.assertEqual(commands[1][0], sys.executable)


if __name__ == "__main__":
    unittest.main()
