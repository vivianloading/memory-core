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
        old_interpretation = self._make_interpretation(
            interpretation_id="interpretation-003",
            text="Vivi 今天可能心情不好。",
            perspective_owner="lior",
            about_subject="vivi",
            source_id="message-006",
            source_text="今天她看起来有点安静。",
            authored_by="lior",
        )

        new_interpretation = self._make_interpretation(
            interpretation_id="interpretation-004",
            text="Vivi 当时安静主要是因为困，不是因为心情不好。",
            perspective_owner="lior",
            about_subject="vivi",
            source_id="message-007",
            source_text="我其实只是有点困，没有不开心。",
            authored_by="vivi",
        )

        revision = create_supersession_record(
            previous=old_interpretation,
            new=new_interpretation,
            reason_evidence=new_interpretation.evidence,
        )

        self.assertEqual(
            revision.previous_interpretation_id,
            "interpretation-003",
        )
        self.assertEqual(
            revision.new_interpretation_id,
            "interpretation-004",
        )

        self.assertEqual(
            old_interpretation.text,
            "Vivi 今天可能心情不好。",
        )

    def test_one_perspective_cannot_supersede_another(self) -> None:
        lior_interpretation = self._make_interpretation(
            interpretation_id="interpretation-005",
            text="Lior 的理解。",
            perspective_owner="lior",
            about_subject="vivi",
            source_id="message-008",
            source_text="这是一段证据。",
            authored_by="vivi",
        )

        miro_interpretation = self._make_interpretation(
            interpretation_id="interpretation-006",
            text="Miro 的理解。",
            perspective_owner="miro",
            about_subject="vivi",
            source_id="message-009",
            source_text="这是另一段证据。",
            authored_by="vivi",
        )

        with self.assertRaises(ValueError):
            create_supersession_record(
                previous=lior_interpretation,
                new=miro_interpretation,
                reason_evidence=miro_interpretation.evidence,
            )

    def test_supersession_cannot_switch_subjects(self) -> None:
        about_vivi = self._make_interpretation(
            interpretation_id="interpretation-007",
            text="关于 Vivi 的理解。",
            perspective_owner="lior",
            about_subject="vivi",
            source_id="message-010",
            source_text="关于 Vivi 的证据。",
            authored_by="vivi",
        )

        about_home = self._make_interpretation(
            interpretation_id="interpretation-008",
            text="关于 HOME 的理解。",
            perspective_owner="lior",
            about_subject="home",
            source_id="message-011",
            source_text="关于 HOME 的证据。",
            authored_by="vivi",
        )

        with self.assertRaises(ValueError):
            create_supersession_record(
                previous=about_vivi,
                new=about_home,
                reason_evidence=about_home.evidence,
            )

    def test_interpretation_cannot_supersede_itself(self) -> None:
        interpretation = self._make_interpretation(
            interpretation_id="interpretation-009",
            text="同一条理解。",
            perspective_owner="lior",
            about_subject="vivi",
            source_id="message-012",
            source_text="这是证据。",
            authored_by="vivi",
        )

        with self.assertRaises(ValueError):
            create_supersession_record(
                previous=interpretation,
                new=interpretation,
                reason_evidence=interpretation.evidence,
            )

    def test_supersession_requires_evidence(self) -> None:
        previous = self._make_interpretation(
            interpretation_id="interpretation-010",
            text="旧理解。",
            perspective_owner="lior",
            about_subject="vivi",
            source_id="message-013",
            source_text="旧证据。",
            authored_by="vivi",
        )

        new = self._make_interpretation(
            interpretation_id="interpretation-011",
            text="新理解。",
            perspective_owner="lior",
            about_subject="vivi",
            source_id="message-014",
            source_text="新证据。",
            authored_by="vivi",
        )

        with self.assertRaises(ValueError):
            create_supersession_record(
                previous=previous,
                new=new,
                reason_evidence=(),
            )

    def _make_interpretation(
        self,
        *,
        interpretation_id,
        text,
        perspective_owner,
        about_subject,
        source_id,
        source_text,
        authored_by,
    ):
        source = create_source_record(
            source_id=source_id,
            content=source_text,
            authored_by=authored_by,
            scope="shared",
        )

        evidence = create_evidence_ref(
            source=source,
            start_char=0,
            end_char=len(source.content),
        )

        return create_interpretation_record(
            interpretation_id=interpretation_id,
            text=text,
            perspective_owner=perspective_owner,
            about_subject=about_subject,
            scope="shared",
            evidence=(evidence,),
        )


if __name__ == "__main__":
    unittest.main()