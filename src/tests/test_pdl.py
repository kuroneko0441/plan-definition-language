import unittest
from collections import Counter
from pathlib import Path

from pdl.checks import check
from pdl.render import render
from pdl.syntax import PdlSyntaxError, parse_module

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def blocking_kinds(text: str) -> Counter:
    return Counter(finding.kind for finding in check(parse_module(text)) if finding.blocking)


def example_kinds(name: str) -> Counter:
    return blocking_kinds((EXAMPLES / name).read_text(encoding="utf-8"))


COVERED_MACHINE = """
module covered
external Ext
machine M {
    states A, B
    initial A
    terminal B
    event Go
    A -> B on Go by Ext
    ignore B on Go
}
scenario reaches_end on M {
    start A
    events Go, Go
    expect B
}
"""


class SeededHoleTest(unittest.TestCase):
    def test_undefined_key_field(self):
        text = "module m\nentity A key (missing) { id: Text }"
        self.assertEqual(blocking_kinds(text), Counter({"UNDEFINED": 1}))

    def test_undefined_field_type(self):
        text = "module m\nentity A { id: Nowhere }"
        self.assertEqual(blocking_kinds(text), Counter({"UNDEFINED": 1}))

    def test_duplicate_definition(self):
        text = "module m\nenum E = A | B\nenum E = C"
        self.assertEqual(blocking_kinds(text), Counter({"DUPLICATE": 1}))

    def test_ownerless_transition(self):
        text = "module m\nmachine M { states A, B\ninitial A\nterminal B\nevent Go\nA -> B on Go\nignore B on Go }"
        self.assertEqual(blocking_kinds(text), Counter({"OWNERLESS": 1}))

    def test_uncovered_combination(self):
        text = "module m\nactor X\naction Do\nentity R"
        self.assertEqual(blocking_kinds(text), Counter({"UNCOVERED": 1}))

    def test_wildcard_covers_every_combination(self):
        text = "module m\nactor X, Y\naction Do\nentity R\npermit * Do R"
        self.assertEqual(blocking_kinds(text), Counter())

    def test_contradiction_between_wildcard_and_specific_rule(self):
        text = "module m\nactor X\naction Do\nentity R\npermit * Do R\nforbid X Do R"
        self.assertEqual(blocking_kinds(text), Counter({"CONTRADICTION": 1}))

    def test_exclusion_resolves_a_conditional_contradiction(self):
        base = (
            "module m\nenum S = On | Off\nenum P = Open | Closed\nactor X\naction Do\nentity R\n"
            "forbid * Do R when S = Off\npermit X Do R when P = Open\n"
            "forbid * Do R when S = On and P = Closed\n"
        )
        self.assertEqual(blocking_kinds(base), Counter({"CONTRADICTION": 1}))
        resolved = base + "exclusive S=Off, P=Open\n"
        self.assertEqual(blocking_kinds(resolved), Counter())

    def test_structure_unknown_blocks_and_value_unknown_does_not(self):
        structure = 'module m\nunknown structure s { source "x" }'
        self.assertEqual(blocking_kinds(structure), Counter({"UNKNOWN_STRUCTURE": 1}))
        value = 'module m\nunknown value v { source "x" provisional "1" verified no }'
        self.assertEqual(blocking_kinds(value), Counter())
        kinds = [finding.kind for finding in check(parse_module(value))]
        self.assertEqual(kinds, ["UNVERIFIED"])

    def test_value_unknown_without_provisional_decision_blocks(self):
        text = 'module m\nunknown value v { source "x" }'
        self.assertEqual(blocking_kinds(text), Counter({"UNKNOWN_VALUE": 1}))

    def test_unknown_without_source_blocks(self):
        text = 'module m\nunknown value v { provisional "1" verified yes }'
        self.assertEqual(blocking_kinds(text), Counter({"MISSING_SOURCE": 1}))

    def test_time_unit_mismatch(self):
        text = (
            "module m\nentity E passive { submitted_on: Day\nsettled_in: Month }\n"
            "law l: E.submitted_on = E.settled_in"
        )
        self.assertEqual(blocking_kinds(text), Counter({"UNIT_MISMATCH": 1}))

    def test_month_of_converts_a_day_to_a_month(self):
        text = (
            "module m\nentity E passive { submitted_on: Day\nsettled_in: Month }\n"
            "law l: month_of(E.submitted_on) < E.settled_in"
        )
        self.assertEqual(blocking_kinds(text), Counter())

    def test_syntax_error_reports_the_line(self):
        with self.assertRaises(PdlSyntaxError) as raised:
            parse_module("module m\nenum E A")
        self.assertEqual(raised.exception.line, 2)


class MachineTest(unittest.TestCase):
    def test_covered_machine_and_scenario_pass(self):
        self.assertEqual(blocking_kinds(COVERED_MACHINE), Counter())

    def test_unreachable_trap_and_unhandled_states(self):
        text = (
            "module m\nexternal Ext\nmachine M { states A, B, C, D\ninitial A\nterminal B\n"
            "event Go\nA -> B on Go by Ext\nC -> D on Go by Ext\nignore B on Go\nignore D on Go }"
        )
        self.assertEqual(blocking_kinds(text), Counter({"UNREACHABLE": 2, "TRAP": 2}))

    def test_unhandled_event_in_a_state(self):
        text = (
            "module m\nexternal Ext\nmachine M { states A, B\ninitial A\nterminal B\n"
            "event Go, Stop\nA -> B on Go by Ext\nignore B on Go }"
        )
        self.assertEqual(blocking_kinds(text), Counter({"UNHANDLED": 2}))

    def test_two_targets_for_the_same_event_contradict(self):
        text = (
            "module m\nexternal Ext\nmachine M { states A, B, C\ninitial A\nterminal B, C\n"
            "event Go\nA -> B on Go by Ext\nA -> C on Go by Ext\nignore B on Go\nignore C on Go }"
        )
        self.assertEqual(blocking_kinds(text), Counter({"CONTRADICTION": 1}))

    def test_scenario_that_ends_elsewhere_fails(self):
        text = COVERED_MACHINE.replace("expect B", "expect A")
        self.assertEqual(blocking_kinds(text), Counter({"SCENARIO_FAILED": 1}))

    def test_scenario_through_a_missing_transition_fails(self):
        text = COVERED_MACHINE.replace("events Go, Go", "events Go, Go, Go").replace("ignore B on Go", "reject B on Go")
        self.assertEqual(blocking_kinds(text), Counter({"SCENARIO_FAILED": 1}))


class ExampleTest(unittest.TestCase):
    def test_negative_control_has_no_blocking_finding(self):
        self.assertEqual(example_kinds("edi_row_rules.pdl"), Counter())

    def test_real_holes_are_all_found(self):
        self.assertEqual(
            example_kinds("erp_real_holes.pdl"),
            Counter(
                {
                    "DUPLICATE": 1,
                    "UNDEFINED": 3,
                    "CONTRADICTION": 1,
                    "UNCOVERED": 3,
                    "UNKNOWN_STRUCTURE": 1,
                }
            ),
        )

    def test_documented_issue_transitions_leave_user_set_states_open(self):
        kinds = example_kinds("issue_tracker.pdl")
        self.assertEqual(kinds["UNREACHABLE"], 2)
        self.assertEqual(kinds["TRAP"], 5)
        self.assertEqual(kinds["UNHANDLED"], 6)


class RenderTest(unittest.TestCase):
    def render_example(self, name: str, language: str = "ko") -> str:
        module = parse_module((EXAMPLES / name).read_text(encoding="utf-8"))
        return render(module, check(module), language)

    def test_permission_matrix_and_rationale_are_rendered(self):
        document = self.render_example("edi_row_rules.pdl")
        self.assertIn("## 권한 규칙", document)
        self.assertIn("| EdiTeam | 조건부 | 허용 |", document)
        self.assertIn("정산된 행은 수정할 수 없다.", document)
        self.assertIn("권한 규칙 범위 밖 엔티티: Reason, EdiSubmission", document)

    def test_time_rule_is_rendered(self):
        document = self.render_example("edi_row_rules.pdl", "en")
        self.assertIn("EdiSubmission.settlement_month = next(EdiSubmission.submission_month)", document)

    def test_machine_is_rendered_as_a_diagram(self):
        module = parse_module(COVERED_MACHINE)
        document = render(module, check(module))
        self.assertIn("stateDiagram-v2", document)
        self.assertIn("A --> B: Go (Ext)", document)
        self.assertIn("B --> [*]", document)


if __name__ == "__main__":
    unittest.main()
