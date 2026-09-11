import subprocess
import sys
import unittest
from pathlib import Path


class HomeMemoryCoreSmokeTest(unittest.TestCase):
    def test_app_wakes_up(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        app_path = project_root / "src" / "home_memory_core" / "app.py"

        result = subprocess.run(
            [sys.executable, str(app_path)],
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertEqual(
            result.stdout.strip(),
            "HOME Memory Core v0.1 is awake.",
        )


if __name__ == "__main__":
    unittest.main()