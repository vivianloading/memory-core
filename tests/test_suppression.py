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
from home_memory_core.suppression import (
    create_suppression_record,
    is_interpretation_usable,
    is_source_usable,
    is_supersession_usable,
)


class SuppressionSemanticsTest(unittest.TestCase):
    def test_suppression_marks_source_unusable_without_mutating_it(self) -> None:
        source = create_source_record(
            source_id="suppression-message-001",
            content="这段历史仍然存在，但停止用于记忆工作。",
            authored_by="vivi",
            scope="shared",
        )

        suppression = create_suppression_record(
            suppression_id="suppression-001",
            source_id=source.source_id,
            requested_by="vivi",
            reason="不要再使用这段 source。",
        )

        self.assertFalse(
            is_source_usable(
                source=source,
                suppressions=(suppression,),
            )
        )
        self.assertEqual(
            source.content,
            "这段历史仍然存在，但停止用于记忆工作。",
        )

    def test_interpretation_is_unusable_if_any_evidence_is_suppressed(
        self,
    ) -> None:
        source_a = create_source_record(
            source_id="suppression-message-002",
            content="第一段证据。",
            authored_by="vivi",
            scope="shared",
        )
        source_b = create_source_record(
            source_id="suppression-message-003",
            content="第二段证据。",
            authored_by="vivi",
            scope="shared",
        )

        evidence_a = create_evidence_ref(
            source=source_a,
            start_char=0,
            end_char=len(source_a.content),
        )
        evidence_b = create_evidence_ref(
            source=source_b,
            start_char=0,
            end_char=len(source_b.content),
        )

        interpretation = create_interpretation_record(
            interpretation_id="suppression-interpretation-001",
            text="这条理解同时依赖两段证据。",
            perspective_owner="lior",
            about_subject="vivi",
            scope="shared",
            evidence=(evidence_a, evidence_b),
        )

        suppression = create_suppression_record(
            suppression_id="suppression-002",
            source_id=source_b.source_id,
            requested_by="vivi",
            reason="停止使用第二段证据。",
        )

        self.assertFalse(
            is_interpretation_usable(
                interpretation=interpretation,
                suppressions=(suppression,),
            )
        )

    def test_interpretation_is_usable_when_all_evidence_is_active(
        self,
    ) -> None:
        source = create_source_record(
            source_id="suppression-message-004",
            content="这段证据仍然允许使用。",
            authored_by="vivi",
            scope="shared",
        )

        evidence = create_evidence_ref(
            source=source,
            start_char=0,
            end_char=len(source.content),
        )

        interpretation = create_interpretation_record(
            interpretation_id="suppression-interpretation-002",
            text="这条理解仍然可用。",
            perspective_owner="lior",
            about_subject="vivi",
            scope="shared",
            evidence=(evidence,),
        )

        self.assertTrue(
            is_interpretation_usable(
                interpretation=interpretation,
                suppressions=(),
            )
        )

    def test_supersession_is_unusable_when_reason_source_is_suppressed(
        self,
    ) -> None:
        old_source = create_source_record(
            source_id="suppression-message-005",
            content="旧证据。",
            authored_by="vivi",
            scope="shared",
        )
        new_source = create_source_record(
            source_id="suppression-message-006",
            content="新证据。",
            authored_by="vivi",
            scope="shared",
        )

        old_evidence = create_evidence_ref(
            source=old_source,
            start_char=0,
            end_char=len(old_source.content),
        )
        new_evidence = create_evidence_ref(
            source=new_source,
            start_char=0,
            end_char=len(new_source.content),
        )

        previous = create_interpretation_record(
            interpretation_id="suppression-interpretation-003",
            text="旧理解。",
            perspective_owner="lior",
            about_subject="vivi",
            scope="shared",
            evidence=(old_evidence,),
        )
        new = create_interpretation_record(
            interpretation_id="suppression-interpretation-004",
            text="新理解。",
            perspective_owner="lior",
            about_subject="vivi",
            scope="shared",
            evidence=(old_evidence,),
        )

        supersession = create_supersession_record(
            previous=previous,
            new=new,
            reason_evidence=(new_evidence,),
        )

        suppression = create_suppression_record(
            suppression_id="suppression-003",
            source_id=new_source.source_id,
            requested_by="vivi",
            reason="不再允许这段修订理由参与记忆工作。",
        )

        self.assertFalse(
            is_supersession_usable(
                supersession=supersession,
                previous=previous,
                new=new,
                suppressions=(suppression,),
            )
        )

    def test_suppression_requires_an_auditable_reason(self) -> None:
        with self.assertRaises(ValueError):
            create_suppression_record(
                suppression_id="suppression-004",
                source_id="suppression-message-007",
                requested_by="vivi",
                reason="   ",
            )


if __name__ == "__main__":
    unittest.main()