import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from home_memory_core.source import create_source_record


class SourceRecordTest(unittest.TestCase):
    def test_source_record_preserves_raw_content_and_identity(self) -> None:
        record = create_source_record(
            source_id="message-001",
            content="今天我们开始建新的 HOME。",
            authored_by="vivi",
            scope="shared",
        )

        self.assertEqual(record.source_id, "message-001")
        self.assertEqual(record.content, "今天我们开始建新的 HOME。")
        self.assertEqual(record.authored_by, "vivi")
        self.assertEqual(record.scope, "shared")
        self.assertEqual(len(record.content_sha256), 64)

    def test_source_record_is_immutable(self) -> None:
        record = create_source_record(
            source_id="message-002",
            content="HOME Memory Core v0.1 is awake.",
            authored_by="lior",
            scope="shared",
        )

        with self.assertRaises(FrozenInstanceError):
            record.content = "偷偷改掉原文"


if __name__ == "__main__":
    unittest.main()