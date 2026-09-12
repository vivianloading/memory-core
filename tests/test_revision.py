import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from home_memory_core.evidence import create_evidence_ref
from home_memory_core.interpretation import create_interpretation_record
from home_memory_core.revision import create_supersession_record
from home_memory_core.source import create_source_record


class SupersessionRecordTest(unittest.TestCase):
    def test_new_interpretation_can_supersede_old_one_without_erasing_it(self) -> None:
        old_source = create_source_record(
            source_id="message-006",
            content="今天她看起来有点安静。",
            authored_by="lior",
            scope="shared",
        )

        old_evidence = create_evidence_ref(
            source=old_source,
            start_char=0,
            end_char=len(old_source.content),
        )

        old_interpretation = create_interpretation_record(
            interpretation_id="interpretation-003",
            text="Vivi 今天可能心情不好。",
            perspective_owner="lior",
            about_subject="vivi",
            scope="shared",
            evidence=(old_evidence,),
        )

        new_source = create_source_record(
            source_id="message-007",
            content="我其实只是有点困，没有不开心。",
            authored_by="vivi",
            scope="shared",
        )

        new_evidence = create_evidence_ref(
            source=new_source,
            start_char=0,
            end_char=len(new_source.content),
        )

        new_interpretation = create_interpretation_record(
            interpretation_id="interpretation-004",
            text="Vivi 当时安静主要是因为困，不是因为心情不好。",
            perspective_owner="lior",
            about_subject="vivi",
            scope="shared",
            evidence=(new_evidence,),
        )

        revision = create_supersession_record(
            previous_interpretation_id=old_interpretation.interpretation_id,
            new_interpretation_id=new_interpretation.interpretation_id,
            reason_evidence=(new_evidence,),
        )

        self.assertEqual(
            revision.previous_interpretation_id,
            "interpretation-003",
        )
        self.assertEqual(
            revision.new_interpretation_id,
            "interpretation-004",
        )

        # The old interpretation still exists exactly as it was.
        self.assertEqual(
            old_interpretation.text,
            "Vivi 今天可能心情不好。",
        )

    def test_interpretation_cannot_supersede_itself(self) -> None:
        with self.assertRaises(ValueError):
            create_supersession_record(
                previous_interpretation_id="interpretation-005",
                new_interpretation_id="interpretation-005",
                reason_evidence=(
                    self._make_evidence(),
                ),
            )

    def test_supersession_requires_evidence(self) -> None:
        with self.assertRaises(ValueError):
            create_supersession_record(
                previous_interpretation_id="interpretation-006",
                new_interpretation_id="interpretation-007",
                reason_evidence=(),
            )

    def _make_evidence(self):
        source = create_source_record(
            source_id="message-008",
            content="这是新的证据。",
            authored_by="vivi",
            scope="shared",
        )

        return create_evidence_ref(
            source=source,
            start_char=0,
            end_char=len(source.content),
        )


if __name__ == "__main__":
    unittest.main()