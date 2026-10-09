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


LINKED = "module m\nenum S = A | B\nentity Parent\nentity Child { parent: Parent\nstate: S }\n"


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

    def test_action_scope_limits_the_required_combinations(self):
        text = "module m\nactor X, Y\naction Do by (X) on (R)\nentity R\npermit X Do R"
        self.assertEqual(blocking_kinds(text), Counter())

    def test_rule_outside_the_action_scope_is_inapplicable(self):
        text = "module m\nactor X, Y\naction Do by (X) on (R)\nentity R\npermit X Do R\npermit Y Do R"
        self.assertEqual(blocking_kinds(text), Counter({"INAPPLICABLE": 1}))

    def test_action_scope_with_undefined_names(self):
        text = "module m\nactor X\naction Do by (Nobody) on (Nothing)"
        self.assertEqual(blocking_kinds(text), Counter({"UNDEFINED": 2}))

    def test_term_name_cannot_repeat_an_action_name(self):
        text = "module m\nterm Do why \"x\"\naction Do"
        self.assertEqual(blocking_kinds(text), Counter({"DUPLICATE": 1}))

    def test_derived_status_and_screen_pass_when_linked(self):
        text = LINKED + "derive D of Parent from S mixed Mixed\nscreen V of Parent shows D, S, Child.state"
        self.assertEqual(blocking_kinds(text), Counter())

    def test_derived_status_needs_rows_that_link_the_entity_to_the_enum(self):
        text = "module m\nenum S = A | B\nentity Parent\nderive D of Parent from S mixed Mixed"
        self.assertEqual(blocking_kinds(text), Counter({"UNDEFINED": 1}))

    def test_mixed_value_cannot_repeat_an_enum_value(self):
        text = LINKED + "derive D of Parent from S mixed A"
        self.assertEqual(blocking_kinds(text), Counter({"DUPLICATE": 1}))

    def test_screen_cannot_show_undefined_items(self):
        text = LINKED + "screen V of Parent shows Nothing, Child.nothing"
        self.assertEqual(blocking_kinds(text), Counter({"UNDEFINED": 2}))

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

    def test_ordered_gates_of_another_tool_pass_with_the_same_core(self):
        self.assertEqual(example_kinds("slack_apps_gates.pdl"), Counter())

    def test_code_acquisition_leaves_unstated_events_and_two_structures_open(self):
        self.assertEqual(
            example_kinds("partner_codes.pdl"),
            Counter({"UNHANDLED": 6, "UNKNOWN_STRUCTURE": 2}),
        )

    def test_settlement_comparison_is_silent_about_changes_after_a_full_match(self):
        self.assertEqual(
            example_kinds("settlement_comparison.pdl"),
            Counter({"UNHANDLED": 1, "UNKNOWN_STRUCTURE": 1}),
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
        self.assertIn("| 딜러 | - | - | - | - | 조건부 |", document)
        self.assertIn("| EDI팀 | 조건부 | 허용 | 허용 | 허용 | - |", document)
        self.assertIn("정산된 행은 수정할 수 없다.", document)
        self.assertIn("권한 규칙을 두지 않은 엔티티: 제약사, 수정 사유, 수정 이력", document)
        self.assertIn("# EDI 업로드, 제출, 행 수정 규칙", document)
        self.assertIn("- EDI팀은 업로드 마감을 설정하거나 해제할 수 있다.", document)

    def test_terms_and_field_notes_are_rendered(self):
        document = self.render_example("edi_row_rules.pdl")
        self.assertIn("- 처방월: 처방이 발생한 달이다.", document)
        self.assertIn("- 업로드: 딜러가 이음에 EDI를 올리는 행위다.", document)
        self.assertIn("- 제약사 마감: 제약사 전산이 더 이상 제출과 수정을 받지 않는 시점이며", document)
        self.assertIn("settlement_month: Month - 제약사가 정산하는 달이다.", document)

    def test_rules_become_korean_sentences_with_the_right_particles(self):
        document = self.render_example("edi_row_rules.pdl")
        self.assertIn("- 업로드 상태가 '열림'일 때, 딜러는 EDI를 업로드할 수 있다.", document)
        self.assertIn("- EDI팀은 EDI를 대리 등록할 수 있다.", document)
        self.assertIn("- 행 상태가 '입력'일 때, EDI팀은 EDI 행을 수정할 수 있다.", document)
        self.assertIn(
            "- 행 상태가 '제약사 마감 완료'일 때, EDI팀은 EDI 행을 수정할 수 있다. 이때 수정 사유를 입력해야 한다.",
            document,
        )
        self.assertIn("- 행 상태가 '정산 완료'일 때, 누구도 EDI 행을 수정할 수 없다.", document)

    def test_rules_become_english_sentences(self):
        document = self.render_example("edi_row_rules.pdl", "en")
        self.assertIn("- When UploadWindow is Open, Dealer may UploadEdi Edi.", document)

    def test_time_rule_is_rendered(self):
        document = self.render_example("edi_row_rules.pdl", "en")
        self.assertIn("Edi.settlement_month = next(Edi.submission_month)", document)

    def test_monthly_workflow_is_rendered_with_labels(self):
        document = self.render_example("edi_row_rules.pdl")
        self.assertIn("## 상태 머신: 월별 EDI 업무", document)
        self.assertIn(
            "- '업로드 시작 전' 상태에서 '매달 업로드 시작' 사건이 일어나면 '업로드와 입력 진행' 상태가 된다. (주체: 매달 정해진 시점)",
            document,
        )
        self.assertIn(
            "- 위에 적은 경우 외의 상태에서 사건 (거부한다): '매달 업로드 시작', '업로드 마감 설정', '업로드 마감 해제', '제약사에 제출'",
            document,
        )
        self.assertIn("  - 근거: 매달 EDI 업로드가 시작되면 EDI팀은 입력을 시작한다.", document)
        self.assertIn('    state "업로드 마감" as Closed', document)

    def test_mixed_state_is_a_derived_status_and_lists_are_screens(self):
        document = self.render_example("edi_row_rules.pdl")
        self.assertIn("## 파생 상태", document)
        self.assertIn(
            "- EDI 상태는 EDI에 속한 EDI 행들의 행 상태가 모두 같으면 그 값이고, 서로 다르면 '혼합'이다.",
            document,
        )
        self.assertIn("  - 근거: EDI의 행마다 상태가 다를 수 있다.", document)
        self.assertIn("## 화면", document)
        self.assertIn("- EDI 목록은 EDI 상태, 목록 상태 구분을 보여 준다.", document)
        self.assertIn("- EDI 상세는 EDI 행의 행 상태를 보여 준다.", document)
        self.assertNotIn("- 혼합 상태:", document)
        self.assertIn("| 목록 상태 구분 (ListStatus) | Input (입력), Submission (제출), Monitoring (모니터링), Settlement (정산) |", document)

    def test_unverified_assumption_is_listed(self):
        document = self.render_example("edi_row_rules.pdl")
        self.assertIn("## 미검증 임시 결정", document)
        self.assertIn("| 업로드 마감 전 제약사 제출 | 업로드 마감 전에는 제약사에 제출하지 않는다 | ERP-PLANNING.md:235 |", document)
        self.assertIn("| 제약사 마감을 기록하는 주체 | EDI팀 | ERP-PLANNING.md:237 |", document)

    def test_examples_from_the_source_section_are_kept(self):
        document = self.render_example("edi_row_rules.pdl")
        self.assertIn("타이레놀 5개와 우루사 3개", document)
        self.assertIn("변경 전후 값, 수정 사유, 수정자와 시각을 이력으로 기록한다", document)
        self.assertIn("edited_at: Timestamp - 수정 시각이다.", document)

    def test_machine_is_rendered_as_a_diagram(self):
        module = parse_module(COVERED_MACHINE)
        document = render(module, check(module))
        self.assertIn("stateDiagram-v2", document)
        self.assertIn("A --> B: Go (Ext)", document)
        self.assertIn("B --> [*]", document)


if __name__ == "__main__":
    unittest.main()
