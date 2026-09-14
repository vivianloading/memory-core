from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from home_memory_core.host_config import HostConfigError, load_home_mini_host_config
from home_memory_core.host_runtime import HostRuntimeLeaseError
from home_memory_core.host_startup import start_home_mini_host


_VALID = """\
[home]
schema = "home-mini-host-v0.1"
runtime_root = "."
database = "data/home.db"
real_data_allowed = false

[secrets]
mode = "disabled"
"""


class HostConfigTests(unittest.TestCase):
    def _write(self, root: Path, text: str = _VALID) -> Path:
        path = root / "home-mini.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_valid_config_resolves_runtime_and_database_from_config_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_home_mini_host_config(self._write(root))
            self.assertEqual(config.runtime_root, root.resolve())
            self.assertEqual(config.db_path, (root / "data" / "home.db").resolve())
            self.assertFalse(config.real_data_allowed)
            self.assertEqual(config.secrets_mode, "disabled")

    def test_real_data_flag_is_explicitly_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = _VALID.replace("real_data_allowed = false", "real_data_allowed = true")
            with self.assertRaises(HostConfigError):
                load_home_mini_host_config(self._write(root, text))

    def test_plaintext_secret_cannot_be_smuggled_as_extra_home_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = _VALID.replace(
                'real_data_allowed = false',
                'real_data_allowed = false\napi_key = "do-not-accept"',
            )
            with self.assertRaises(HostConfigError):
                load_home_mini_host_config(self._write(root, text))

    def test_secret_values_or_refs_are_not_accepted_yet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = _VALID.replace(
                'mode = "disabled"',
                'mode = "disabled"\ngmail_password = "secret"',
            )
            with self.assertRaises(HostConfigError):
                load_home_mini_host_config(self._write(root, text))

    def test_secret_provider_cannot_be_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = _VALID.replace('mode = "disabled"', 'mode = "environment"')
            with self.assertRaises(HostConfigError):
                load_home_mini_host_config(self._write(root, text))

    def test_database_must_be_relative_to_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            absolute = (root / "other.db").resolve().as_posix()
            text = _VALID.replace('database = "data/home.db"', f'database = "{absolute}"')
            with self.assertRaises(HostConfigError):
                load_home_mini_host_config(self._write(root, text))

    def test_database_cannot_escape_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = _VALID.replace('database = "data/home.db"', 'database = "../outside.db"')
            with self.assertRaises(HostConfigError):
                load_home_mini_host_config(self._write(root, text))

    def test_startup_acquires_the_single_instance_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._write(root)
            with start_home_mini_host(path) as first:
                self.assertEqual(first.identity.db_path, (root / "data" / "home.db").resolve())
                with self.assertRaises(HostRuntimeLeaseError):
                    start_home_mini_host(path)
            with start_home_mini_host(path) as second:
                self.assertFalse(second.closed)

    def test_closed_session_cannot_be_reentered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = start_home_mini_host(self._write(root))
            session.close()
            with self.assertRaises(RuntimeError):
                session.__enter__()


if __name__ == "__main__":
    unittest.main()
