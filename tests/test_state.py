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
from home_memory_core.state import (
    resolve_interpretation_status,
    resolve_lineage_terminal_ids,
)


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

    def test_indirect_branching_revisions_are_conflicting(self) -> None:
        interpretation_a = self._make_interpretation(
            interpretation_id="interpretation-019",
            text="A：最初的理解。",
            source_id="message-022",
            source_text="最初证据。",
        )

        interpretation_b = self._make_interpretation(
            interpretation_id="interpretation-020",
            text="B：A 的第一步修订。",
            source_id="message-023",
            source_text="支持 B 的证据。",
        )

        interpretation_c = self._make_interpretation(
            interpretation_id="interpretation-021",
            text="C：从 A 长出的另一条支线。",
            source_id="message-024",
            source_text="支持 C 的证据。",
        )

        interpretation_d = self._make_interpretation(
            interpretation_id="interpretation-022",
            text="D：B 后面的进一步修订。",
            source_id="message-025",
            source_text="支持 D 的证据。",
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

        b_to_d = create_supersession_record(
            previous=interpretation_b,
            new=interpretation_d,
            reason_evidence=interpretation_d.evidence,
        )

        supersessions = (a_to_b, a_to_c, b_to_d)

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
            "conflicting",
        )

        self.assertEqual(
            resolve_interpretation_status(
                interpretation=interpretation_d,
                supersessions=supersessions,
            ),
            "conflicting",
        )

    def test_linear_lineage_reports_one_terminal_interpretation(self) -> None:
        interpretation_a = self._make_interpretation(
            interpretation_id="interpretation-023",
            text="A。",
            source_id="message-026",
            source_text="A 的证据。",
        )

        interpretation_b = self._make_interpretation(
            interpretation_id="interpretation-024",
            text="B。",
            source_id="message-027",
            source_text="B 的证据。",
        )

        interpretation_c = self._make_interpretation(
            interpretation_id="interpretation-025",
            text="C。",
            source_id="message-028",
            source_text="C 的证据。",
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

        terminal_ids = resolve_lineage_terminal_ids(
            interpretation_id=interpretation_a.interpretation_id,
            supersessions=(a_to_b, b_to_c),
        )

        self.assertEqual(
            terminal_ids,
            frozenset({"interpretation-025"}),
        )

    def test_branching_lineage_reports_all_terminal_interpretations(self) -> None:
        interpretation_a = self._make_interpretation(
            interpretation_id="interpretation-026",
            text="A。",
            source_id="message-029",
            source_text="A 的证据。",
        )

        interpretation_b = self._make_interpretation(
            interpretation_id="interpretation-027",
            text="B。",
            source_id="message-030",
            source_text="B 的证据。",
        )

        interpretation_c = self._make_interpretation(
            interpretation_id="interpretation-028",
            text="C。",
            source_id="message-031",
            source_text="C 的证据。",
        )

        interpretation_d = self._make_interpretation(
            interpretation_id="interpretation-029",
            text="D。",
            source_id="message-032",
            source_text="D 的证据。",
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

        b_to_d = create_supersession_record(
            previous=interpretation_b,
            new=interpretation_d,
            reason_evidence=interpretation_d.evidence,
        )

        terminal_ids = resolve_lineage_terminal_ids(
            interpretation_id=interpretation_a.interpretation_id,
            supersessions=(a_to_b, a_to_c, b_to_d),
        )

        self.assertEqual(
            terminal_ids,
            frozenset(
                {
                    "interpretation-028",
                    "interpretation-029",
                }
            ),
        )

    def test_cycle_is_rejected(self) -> None:
        interpretation_a = self._make_interpretation(
            interpretation_id="interpretation-030",
            text="A。",
            source_id="message-033",
            source_text="A 的证据。",
        )

        interpretation_b = self._make_interpretation(
            interpretation_id="interpretation-031",
            text="B。",
            source_id="message-034",
            source_text="B 的证据。",
        )

        a_to_b = create_supersession_record(
            previous=interpretation_a,
            new=interpretation_b,
            reason_evidence=interpretation_b.evidence,
        )

        b_to_a = create_supersession_record(
            previous=interpretation_b,
            new=interpretation_a,
            reason_evidence=interpretation_a.evidence,
        )

        with self.assertRaises(ValueError):
            resolve_lineage_terminal_ids(
                interpretation_id=interpretation_a.interpretation_id,
                supersessions=(a_to_b, b_to_a),
            )

    def test_duplicate_supersession_edge_is_rejected(self) -> None:
        interpretation_a = self._make_interpretation(
            interpretation_id="interpretation-032",
            text="A。",
            source_id="message-035",
            source_text="A 的证据。",
        )

        interpretation_b = self._make_interpretation(
            interpretation_id="interpretation-033",
            text="B。",
            source_id="message-036",
            source_text="B 的证据。",
        )

        a_to_b = create_supersession_record(
            previous=interpretation_a,
            new=interpretation_b,
            reason_evidence=interpretation_b.evidence,
        )

        with self.assertRaises(ValueError):
            resolve_lineage_terminal_ids(
                interpretation_id=interpretation_a.interpretation_id,
                supersessions=(a_to_b, a_to_b),
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