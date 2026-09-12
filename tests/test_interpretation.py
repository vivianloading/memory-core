import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from home_memory_core.evidence import create_evidence_ref
from home_memory_core.interpretation import create_interpretation_record
from home_memory_core.source import create_source_record


class InterpretationRecordTest(unittest.TestCase):
    def test_interpretation_keeps_perspective_and_evidence(self) -> None:
        content = "今天 HOME 真的开工了，我安心很多。"

        source = create_source_record(
            source_id="message-005",
            content=content,
            authored_by="vivi",
            scope="shared",
        )

        exact_text = "我安心很多"
        start = content.index(exact_text)

        evidence = create_evidence_ref(
            source=source,
            start_char=start,
            end_char=start + len(exact_text),
        )

        interpretation = create_interpretation_record(
            interpretation_id="interpretation-001",
            text="HOME 从计划变成现实，会让 Vivi 更安心。",
            perspective_owner="lior",
            about_subject="vivi",
            scope="shared",
            evidence=(evidence,),
        )

        self.assertEqual(
            interpretation.text,
            "HOME 从计划变成现实，会让 Vivi 更安心。",
        )
        self.assertEqual(interpretation.perspective_owner, "lior")
        self.assertEqual(interpretation.about_subject, "vivi")
        self.assertEqual(interpretation.evidence, (evidence,))

    def test_interpretation_requires_evidence(self) -> None:
        with self.assertRaises(ValueError):
            create_interpretation_record(
                interpretation_id="interpretation-002",
                text="这是一条没有证据的理解。",
                perspective_owner="lior",
                about_subject="vivi",
                scope="shared",
                evidence=(),
            )


if __name__ == "__main__":
    unittest.main()