import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from home_memory_core.evidence import EvidenceRef, create_evidence_ref, read_evidence
from home_memory_core.source import SourceRecord, create_source_record


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


    def test_read_evidence_rejects_source_record_with_self_inconsistent_hash(self) -> None:
        source = SourceRecord(
            source_id="message-manual",
            content="new",
            authored_by="vivi",
            scope="shared",
            content_sha256="cba06b5736faf67e54b07b561eae94395e774c517a7d910a54369e1263ccfbd4",  # sha256("old")
        )
        evidence = EvidenceRef(
            source_id="message-manual",
            source_sha256=source.content_sha256,
            start_char=0,
            end_char=3,
        )

        with self.assertRaises(ValueError):
            read_evidence(source=source, evidence=evidence)

    def test_read_evidence_rejects_range_outside_current_source_content(self) -> None:
        source = create_source_record(
            source_id="message-range",
            content="abc",
            authored_by="vivi",
            scope="shared",
        )
        evidence = EvidenceRef(
            source_id=source.source_id,
            source_sha256=source.content_sha256,
            start_char=0,
            end_char=99,
        )

        with self.assertRaises(ValueError):
            read_evidence(source=source, evidence=evidence)



if __name__ == "__main__":
    unittest.main()