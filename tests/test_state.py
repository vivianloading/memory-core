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
    resolve_connected_component_terminal_ids,
    validate_supersession_graph,
)


class ConnectedComponentTopologyTest(unittest.TestCase):
    def test_linear_component_reports_one_terminal(self) -> None:
        a = self._make_interpretation("interpretation-012", "message-015")
        b = self._make_interpretation("interpretation-013", "message-016")
        c = self._make_interpretation("interpretation-014", "message-017")

        edges = (
            create_supersession_record(
                previous=a,
                new=b,
                reason_evidence=b.evidence,
            ),
            create_supersession_record(
                previous=b,
                new=c,
                reason_evidence=c.evidence,
            ),
        )

        self.assertEqual(
            resolve_connected_component_terminal_ids(
                interpretation_id=a.interpretation_id,
                supersessions=edges,
            ),
            frozenset({c.interpretation_id}),
        )

    def test_singleton_component_reports_itself_as_terminal(self) -> None:
        interpretation = self._make_interpretation(
            "interpretation-015",
            "message-018",
        )

        self.assertEqual(
            resolve_connected_component_terminal_ids(
                interpretation_id=interpretation.interpretation_id,
                supersessions=(),
            ),
            frozenset({interpretation.interpretation_id}),
        )

    def test_direct_fork_reports_all_component_terminals(self) -> None:
        a = self._make_interpretation("interpretation-016", "message-019")
        b = self._make_interpretation("interpretation-017", "message-020")
        c = self._make_interpretation("interpretation-018", "message-021")

        edges = (
            create_supersession_record(
                previous=a,
                new=b,
                reason_evidence=b.evidence,
            ),
            create_supersession_record(
                previous=a,
                new=c,
                reason_evidence=c.evidence,
            ),
        )

        self.assertEqual(
            resolve_connected_component_terminal_ids(
                interpretation_id=a.interpretation_id,
                supersessions=edges,
            ),
            frozenset({b.interpretation_id, c.interpretation_id}),
        )

    def test_indirect_fork_reports_all_component_terminals(self) -> None:
        a = self._make_interpretation("interpretation-019", "message-022")
        b = self._make_interpretation("interpretation-020", "message-023")
        c = self._make_interpretation("interpretation-021", "message-024")
        d = self._make_interpretation("interpretation-022", "message-025")

        edges = (
            create_supersession_record(
                previous=a,
                new=b,
                reason_evidence=b.evidence,
            ),
            create_supersession_record(
                previous=a,
                new=c,
                reason_evidence=c.evidence,
            ),
            create_supersession_record(
                previous=b,
                new=d,
                reason_evidence=d.evidence,
            ),
        )

        self.assertEqual(
            resolve_connected_component_terminal_ids(
                interpretation_id=b.interpretation_id,
                supersessions=edges,
            ),
            frozenset({c.interpretation_id, d.interpretation_id}),
        )

    def test_nonterminal_seed_still_reports_component_terminals(self) -> None:
        a = self._make_interpretation("interpretation-023", "message-026")
        b = self._make_interpretation("interpretation-024", "message-027")
        c = self._make_interpretation("interpretation-025", "message-028")

        edges = (
            create_supersession_record(
                previous=a,
                new=b,
                reason_evidence=b.evidence,
            ),
            create_supersession_record(
                previous=b,
                new=c,
                reason_evidence=c.evidence,
            ),
        )

        self.assertEqual(
            resolve_connected_component_terminal_ids(
                interpretation_id=b.interpretation_id,
                supersessions=edges,
            ),
            frozenset({c.interpretation_id}),
        )

    def test_cycle_is_rejected(self) -> None:
        a = self._make_interpretation("interpretation-026", "message-029")
        b = self._make_interpretation("interpretation-027", "message-030")

        a_to_b = create_supersession_record(
            previous=a,
            new=b,
            reason_evidence=b.evidence,
        )
        b_to_a = create_supersession_record(
            previous=b,
            new=a,
            reason_evidence=a.evidence,
        )

        with self.assertRaises(ValueError):
            validate_supersession_graph(
                supersessions=(a_to_b, b_to_a),
            )

    def test_duplicate_edge_is_rejected(self) -> None:
        a = self._make_interpretation("interpretation-028", "message-031")
        b = self._make_interpretation("interpretation-029", "message-032")
        edge = create_supersession_record(
            previous=a,
            new=b,
            reason_evidence=b.evidence,
        )

        with self.assertRaises(ValueError):
            validate_supersession_graph(
                supersessions=(edge, edge),
            )

    def test_implicit_merge_is_rejected(self) -> None:
        a = self._make_interpretation("interpretation-030", "message-033")
        b = self._make_interpretation("interpretation-031", "message-034")
        c = self._make_interpretation("interpretation-032", "message-035")
        d = self._make_interpretation("interpretation-033", "message-036")

        edges = (
            create_supersession_record(
                previous=a,
                new=b,
                reason_evidence=b.evidence,
            ),
            create_supersession_record(
                previous=a,
                new=c,
                reason_evidence=c.evidence,
            ),
            create_supersession_record(
                previous=b,
                new=d,
                reason_evidence=d.evidence,
            ),
            create_supersession_record(
                previous=c,
                new=d,
                reason_evidence=d.evidence,
            ),
        )

        with self.assertRaises(ValueError):
            validate_supersession_graph(supersessions=edges)

    def _make_interpretation(self, interpretation_id, source_id):
        source = create_source_record(
            source_id=source_id,
            content=f"evidence for {interpretation_id}",
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
            text=f"interpretation {interpretation_id}",
            perspective_owner="lior",
            about_subject="vivi",
            scope="shared",
            evidence=(evidence,),
        )


if __name__ == "__main__":
    unittest.main()
