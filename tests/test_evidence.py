import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from home_memory_core.evidence import create_evidence_ref, read_evidence
from home_memory_core.source import create_source_record


class EvidenceRefTest(unittest.TestCase):
    def test_evidence_points_to_exact_source_text(self) -> None:
        content = "今天我们开始建新的 HOME。以后慢慢长大。"

        source = create_source_record(
            source_id="message-003",
            content=content,
            authored_by="vivi",
            scope="shared",
        )

        exact_text = "开始建新的 HOME"
        start = content.index(exact_text)
        end = start + len(exact_text)

        evidence = create_evidence_ref(
            source=source,
            start_char=start,
            end_char=end,
        )

        self.assertEqual(
            read_evidence(source=source, evidence=evidence),
            exact_text,
        )

    def test_evidence_rejects_wrong_source_snapshot(self) -> None:
        original = create_source_record(
            source_id="message-004",
            content="这是原来的话。",
            authored_by="lior",
            scope="shared",
        )

        evidence = create_evidence_ref(
            source=original,
            start_char=0,
            end_char=len(original.content),
        )

        changed = create_source_record(
            source_id="message-004",
            content="这是被偷偷改过的话。",
            authored_by="lior",
            scope="shared",
        )

        with self.assertRaises(ValueError):
            read_evidence(source=changed, evidence=evidence)


if __name__ == "__main__":
    unittest.main()