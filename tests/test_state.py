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
from home_memory_core.state import resolve_interpretation_status


class InterpretationStateTest(unittest.TestCase):
    def test_resolves_a_to_b_to_c_without_mutating_history(self) -> None:
        interpretation_a = self._make_interpretation(
            interpretation_id="interpretation-012",
            text="A：最初的理解。",
            source_id="message-015",
            source_text="第一段证据。",
        )

        interpretation_b = self._make_interpretation(
            interpretation_id="interpretation-013",
            text="B：后来修正的理解。",
            source_id="message-016",
            source_text="第二段证据。",
        )

        interpretation_c = self._make_interpretation(
            interpretation_id="interpretation-014",
            text="C：现在的理解。",
            source_id="message-017",
            source_text="第三段证据。",
        )

        a_to_b = create_supersession_record(
            previous=interpretation_a,
            new=interpretation_b,
            reason_evidence=interpretation_b.evidence,
        )

        b_to_c = create_supersession_record(
            previous=interpretation_b,
            new=interpretation_c,
            reason_evidence=interpretation_c.evidence,
        )

        supersessions = (a_to_b, b_to_c)

        self.assertEqual(
            resolve_interpretation_status(
                interpretation=interpretation_a,
                supersessions=supersessions,
            ),
            "superseded",
        )

        self.assertEqual(
            resolve_interpretation_status(
                interpretation=interpretation_b,
                supersessions=supersessions,
            ),
            "superseded",
        )

        self.assertEqual(
            resolve_interpretation_status(
                interpretation=interpretation_c,
                supersessions=supersessions,
            ),
            "current",
        )

        # Historical records themselves remain unchanged.
        self.assertEqual(interpretation_a.text, "A：最初的理解。")
        self.assertEqual(interpretation_b.text, "B：后来修正的理解。")
        self.assertEqual(interpretation_c.text, "C：现在的理解。")

    def test_unrevised_interpretation_is_current(self) -> None:
        interpretation = self._make_interpretation(
            interpretation_id="interpretation-015",
            text="这条理解还没有被修订。",
            source_id="message-018",
            source_text="这是一段证据。",
        )

        self.assertEqual(
            resolve_interpretation_status(
                interpretation=interpretation,
                supersessions=(),
            ),
            "current",
        )
    def test_branching_revisions_are_conflicting(self) -> None:
        interpretation_a = self._make_interpretation(
            interpretation_id="interpretation-016",
            text="A：最初的理解。",
            source_id="message-019",
            source_text="最初的证据。",
        )

        interpretation_b = self._make_interpretation(
            interpretation_id="interpretation-017",
            text="B：第一种修订。",
            source_id="message-020",
            source_text="支持 B 的新证据。",
        )

        interpretation_c = self._make_interpretation(
            interpretation_id="interpretation-018",
            text="C：另一种修订。",
            source_id="message-021",
            source_text="支持 C 的新证据。",
        )

        a_to_b = create_supersession_record(
            previous=interpretation_a,
            new=interpretation_b,
            reason_evidence=interpretation_b.evidence,
        )

        a_to_c = create_supersession_record(
            previous=interpretation_a,
            new=interpretation_c,
            reason_evidence=interpretation_c.evidence,
        )

        supersessions = (a_to_b, a_to_c)

        self.assertEqual(
            resolve_interpretation_status(
                interpretation=interpretation_a,
                supersessions=supersessions,
            ),
            "superseded",
        )

        self.assertEqual(
            resolve_interpretation_status(
                interpretation=interpretation_b,
                supersessions=supersessions,
            ),
            "conflicting",
        )

        self.assertEqual(
            resolve_interpretation_status(
                interpretation=interpretation_c,
                supersessions=supersessions,
            ),
            "conflicting",
        )

    def _make_interpretation(
        self,
        *,
        interpretation_id,
        text,
        source_id,
        source_text,
    ):
        source = create_source_record(
            source_id=source_id,
            content=source_text,
            authored_by="vivi",
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
            perspective_owner="lior",
            about_subject="vivi",
            scope="shared",
            evidence=(evidence,),
        )


if __name__ == "__main__":
    unittest.main()