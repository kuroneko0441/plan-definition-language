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
        self.assertEqual(sorted(kinds), ["UNREFERENCED", "UNVERIFIED"])

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

    def test_invariant_removes_the_worlds_that_cause_a_contradiction(self):
        base = (
            "module m\nenum S = On | Off\nenum P = Open | Closed\nactor X\naction Do\nentity R\n"
            "forbid * Do R when S = Off\npermit X Do R when P = Open\n"
            "forbid * Do R when S = On and P = Closed\n"
        )
        self.assertEqual(blocking_kinds(base), Counter({"CONTRADICTION": 1}))
        ascii_form = base + "invariant I: S = Off => P != Open\n"
        unicode_form = base + "invariant I: S = Off ⇒ P ≠ Open\n"
        self.assertEqual(blocking_kinds(ascii_form), Counter())
        self.assertEqual(blocking_kinds(unicode_form), Counter())

    def test_quantifier_ranges_over_the_values_of_an_enum(self):
        base = (
            "module m\nenum S = On | Off\nenum P = Open | Closed\nactor X\naction Do\nentity R\n"
            "forbid * Do R when S = Off\npermit X Do R when P = Open\n"
            "forbid * Do R when S = On and P = Closed\n"
        )
        text = base + "invariant I: ∀ s ∈ S : s = Off ⇒ P ∈ {Closed}\n"
        self.assertEqual(blocking_kinds(text), Counter())

    def test_invariant_with_undefined_names_is_reported(self):
        text = "module m\nenum S = On | Off\ninvariant I: S = Maybe\ninvariant J: Nothing = On\ninvariant K: T ∈ {On}"
        self.assertEqual(blocking_kinds(text), Counter({"UNDEFINED": 3}))

    def test_invariants_that_exclude_every_combination_contradict(self):
        text = "module m\nenum S = On | Off\ninvariant A: S = On\ninvariant B: S = Off"
        self.assertEqual(blocking_kinds(text), Counter({"CONTRADICTION": 1}))

    def test_invariant_is_rendered_with_symbols(self):
        text = "module m\nenum S = On | Off\nenum P = Open | Closed\ninvariant I: ∀ s ∈ S : (s = Off ∧ P = Open) ⇒ ¬(P = Closed) why \"x\""
        module = parse_module(text)
        document = render(module, check(module))
        self.assertIn("- x\n", document)
        self.assertIn("- I: `∀ s ∈ S : s = Off ∧ P = Open ⇒ ¬(P = Closed)`", document)

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


GUARDED = (
    "module m\nenum G = On | Off\nexternal Ext, Other\n"
    "machine M { states A, B, C\ninitial A\nterminal B, C\nevent Go\n"
    "A -> B on Go when G = On by Ext\n"
    "A -> C on Go when G = Off by Ext\n"
    "ignore B on Go\nignore C on Go }\n"
)


class ExtensionTest(unittest.TestCase):
    def test_value_sets_and_negation_in_rule_conditions(self):
        base = "module m\nenum S = A | B | C\nactor X\naction Do\nentity R\n"
        covered = base + "permit X Do R when S in {A, B}\nforbid X Do R when S != A and S != B\n"
        self.assertEqual(blocking_kinds(covered), Counter())
        overlapping = base + "permit X Do R when S in {A, B}\nforbid X Do R when S != A\n"
        self.assertEqual(blocking_kinds(overlapping), Counter({"CONTRADICTION": 1}))

    def test_condition_values_must_belong_to_the_enum(self):
        text = "module m\nenum S = A | B\nactor X\naction Do\nentity R\npermit X Do R when S in {A, Z}"
        self.assertIn("UNDEFINED", blocking_kinds(text))

    def test_guards_that_cover_every_case_pass(self):
        self.assertEqual(blocking_kinds(GUARDED), Counter())

    def test_a_missing_guard_branch_is_reported(self):
        text = GUARDED.replace("A -> C on Go when G = Off by Ext\n", "")
        self.assertEqual(blocking_kinds(text), Counter({"UNCOVERED": 1, "UNREACHABLE": 1}))

    def test_overlapping_guards_with_different_targets_contradict(self):
        text = GUARDED.replace("when G = Off", "when G in {On, Off}")
        self.assertEqual(blocking_kinds(text), Counter({"CONTRADICTION": 1}))

    def test_an_explicit_handling_covers_the_other_guard_branch(self):
        text = GUARDED.replace("A -> C on Go when G = Off by Ext\n", "ignore A on Go\n")
        self.assertEqual(blocking_kinds(text), Counter({"UNREACHABLE": 1}))

    def test_scenario_uses_the_given_values_to_pick_a_guard(self):
        passing = GUARDED + "scenario s on M { start A given G = Off events Go expect C }\n"
        self.assertEqual(blocking_kinds(passing), Counter())
        failing = GUARDED + "scenario s on M { start A given G = Off events Go expect B }\n"
        self.assertEqual(blocking_kinds(failing), Counter({"SCENARIO_FAILED": 1}))

    def test_cyclic_machine_needs_no_terminal_state(self):
        text = (
            "module m\nexternal Ext\nmachine M { cyclic\nstates A, B\ninitial A\nevent Go\n"
            "A -> B on Go by Ext\nB -> A on Go by Ext }"
        )
        self.assertEqual(blocking_kinds(text), Counter())

    def test_cyclic_machine_reports_a_state_that_cannot_return(self):
        text = (
            "module m\nexternal Ext\nmachine M { cyclic\nstates A, B, C\ninitial A\nevent Go\n"
            "A -> B on Go by Ext\nB -> A on Go by Ext\nreject C on Go }"
        )
        counts = blocking_kinds(text)
        self.assertEqual(counts["TRAP"], 1)
        self.assertEqual(counts["UNREACHABLE"], 1)

    def test_machine_without_terminal_and_not_cyclic_is_reported(self):
        text = "module m\nexternal Ext\nmachine M { states A\ninitial A\nevent Go\nignore A on Go }"
        self.assertEqual(blocking_kinds(text), Counter({"MISSING": 1}))

    def test_a_transition_can_name_several_actors(self):
        ok = GUARDED.replace("when G = On by Ext", "when G = On by Ext, Other")
        self.assertEqual(blocking_kinds(ok), Counter())
        bad = GUARDED.replace("when G = On by Ext", "when G = On by Ext, Nobody")
        self.assertEqual(blocking_kinds(bad), Counter({"UNDEFINED": 1}))

    def test_several_assumptions_on_one_line(self):
        unknowns = 'unknown value a { provisional "1" source "s" verified no }\nunknown value b { provisional "2" source "s" verified no }\n'
        base = "module m\nactor X\naction Do\nentity R\n" + unknowns
        ok = base + "permit X Do R assuming a, b\n"
        kinds = [f.kind for f in check(parse_module(ok))]
        self.assertNotIn("UNREFERENCED", kinds)
        self.assertEqual(blocking_kinds(ok), Counter())
        bad = base + "permit X Do R assuming a, c\n"
        self.assertEqual(blocking_kinds(bad), Counter({"UNDEFINED": 1}))

    def test_unreferenced_value_unknown_is_a_note_and_not_a_hole(self):
        text = 'module m\nunknown value a { provisional "1" source "s" verified no }'
        findings = check(parse_module(text))
        self.assertEqual(sorted(f.kind for f in findings), ["UNREFERENCED", "UNVERIFIED"])
        self.assertFalse(any(f.blocking for f in findings))

    def test_handling_can_carry_an_assumption_and_a_rationale(self):
        text = GUARDED.replace(
            "ignore B on Go\n", 'ignore B on Go assuming a why "b"\n'
        ) + 'unknown value a { provisional "1" source "s" verified no }\n'
        module = parse_module(text)
        self.assertEqual(blocking_kinds(text), Counter())
        document = render(module, check(module))
        self.assertIn("'B' 상태에서", document.replace("'B' + 'Go'", "'B' 상태에서"))
        self.assertIn("  - 근거: b", document)

    def test_nullable_and_list_field_types(self):
        ok = "module m\nenum S = A | B\nentity E passive { a: Text?\nb: list S\nc: Decimal\nd: Money?\ne: Duration }"
        self.assertEqual(blocking_kinds(ok), Counter())
        bad = "module m\nentity E passive { a: list Nowhere }"
        self.assertEqual(blocking_kinds(bad), Counter({"UNDEFINED": 1}))

    def test_nullable_time_field_still_works_in_a_law(self):
        text = "module m\nentity E passive { a: Month?\nb: Month }\nlaw l: E.b = next(E.a)"
        self.assertEqual(blocking_kinds(text), Counter())

    def test_guard_condition_is_rendered_in_the_flow(self):
        text = GUARDED.replace('enum G = On | Off', 'enum G label "스위치" = On "켜짐" | Off "꺼짐"')
        module = parse_module(text)
        document = render(module, check(module))
        self.assertIn("'A' 상태에서 스위치가 '켜짐'일 때 'Go'가 일어나면 'B' 상태가 된다.", document)

    def test_draft_build_lists_the_holes_in_a_separate_file(self):
        import tempfile
        from pathlib import Path as TempPath

        from pdl.cli import build_file

        with tempfile.TemporaryDirectory() as directory:
            output = TempPath(directory)
            self.assertFalse(build_file(EXAMPLES / "org_roles.pdl", output, "ko"))
            self.assertEqual(list(output.iterdir()), [])
            self.assertFalse(build_file(EXAMPLES / "org_roles.pdl", output, "ko", draft=True))
            draft = (output / "org_roles.draft.md").read_text(encoding="utf-8")
            self.assertIn("## 초안", draft)
            self.assertIn("UNCOVERED", draft)

    def test_draft_build_never_crashes_on_any_module(self):
        import tempfile
        from pathlib import Path as TempPath

        from pdl.cli import build_file

        with tempfile.TemporaryDirectory() as directory:
            for path in sorted(EXAMPLES.glob("*.pdl")) + sorted(EXAMPLES.parent.glob("plans/*/*.pdl")):
                build_file(path, TempPath(directory), "ko", draft=True)


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

    def test_carry_over_waits_for_two_undecided_structures(self):
        self.assertEqual(example_kinds("carry_over.pdl"), Counter({"UNKNOWN_STRUCTURE": 2}))

    def test_channels_wait_for_two_undecided_structures(self):
        self.assertEqual(example_kinds("channels.pdl"), Counter({"UNKNOWN_STRUCTURE": 2}))

    def test_team_permissions_leave_one_combination_and_one_structure_open(self):
        self.assertEqual(
            example_kinds("org_roles.pdl"),
            Counter({"UNCOVERED": 1, "UNKNOWN_STRUCTURE": 1}),
        )

    def test_auto_answer_rules_leave_five_combinations_unanswered_per_action(self):
        self.assertEqual(
            example_kinds("filtering_auto_answer.pdl"), Counter({"UNCOVERED": 2})
        )
        module = parse_module((EXAMPLES / "filtering_auto_answer.pdl").read_text(encoding="utf-8"))
        message = next(f.message for f in check(module) if "AnswerAvailable" in f.message)
        self.assertIn("(5 combinations)", message)
        self.assertIn("DealerHolds=Yes, Received=Provisional, UpstreamReply=NotAsked", message)
        self.assertIn("DealerHolds=No, Received=Nothing, UpstreamReply=Otherwise", message)

    def test_commission_waits_for_three_undecided_structures(self):
        self.assertEqual(example_kinds("commission.pdl"), Counter({"UNKNOWN_STRUCTURE": 3}))

    def test_hospital_size_split_waits_for_two_undecided_structures(self):
        self.assertEqual(example_kinds("hospital_size_split.pdl"), Counter({"UNKNOWN_STRUCTURE": 2}))

    def test_history_transfer_audit_log_and_integration_have_no_holes(self):
        for name in ("history_transfer.pdl", "audit_log.pdl", "external_integration.pdl"):
            self.assertEqual(example_kinds(name), Counter(), name)

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
        self.assertIn("- 딜러: EDI 업로드 조건부", document)
        self.assertIn("EDI 행 수정 조건부", document)
        self.assertIn("업로드 마감 설정·해제 허용", document)
        self.assertIn("정산된 행은 수정할 수 없다.", document)
        self.assertIn("# EDI 업로드, 제출, 행 수정 규칙", document)
        self.assertIn("- EDI팀은 업로드 마감을 설정·해제할 수 있다.", document)
        self.assertLess(document.index("## 권한 규칙"), document.index("## 부록"))
        self.assertLess(document.index("### 권한 요약"), len(document))

    def test_assumptions_are_marked_on_the_lines_that_depend_on_them(self):
        document = self.render_example("edi_row_rules.pdl")
        self.assertEqual(document.count("(가정: 행을 수정하는 주체)"), 3)
        self.assertIn(
            "- EDI팀은 제약사 마감 기록을 등록할 수 있다. (가정: 제약사 마감을 기록하는 주체)",
            document,
        )
        self.assertIn("| 제약사의 입금이 늦어진 경우의 정산월 | 입금이 늦어져도", document)

    def test_scope_lines_139_to_142_are_kept(self):
        document = self.render_example("edi_row_rules.pdl")
        self.assertIn("- 제출 양식의 정산월 칸: 일부 프로그램 제출 양식의 정산월 칸은 이음의 제출월에 해당하며", document)
        self.assertIn("특정 시점에 실제로 제출된 값을 확인할 수 있어야 한다.", document)

    def test_assumption_must_name_a_declared_unknown(self):
        text = "module m\nactor X\naction Do\nentity R\npermit X Do R assuming nothing"
        self.assertEqual(blocking_kinds(text), Counter({"UNDEFINED": 1}))

    def test_terms_and_field_notes_are_rendered(self):
        document = self.render_example("edi_row_rules.pdl")
        self.assertIn("- 처방월: 처방이 발생한 달이다.", document)
        self.assertIn("- 업로드: 딜러가 이음에 EDI를 올리는 행위다.", document)
        self.assertIn("- 제약사 마감: 제약사 전산이 더 이상 제출과 수정을 받지 않는 시점이며", document)
        self.assertIn("pharma: PharmaCompany - 마감을 설정하는 제약사다.", document)

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
        self.assertIn("## 업무 흐름: 월별 EDI 업무", document)
        self.assertIn(
            "- '업로드 시작 전' 상태에서 '매달 업로드 시작'이 일어나면 '업로드와 입력 진행' 상태가 된다. "
            "(주체: 매달 정해진 시점) (가정: 매달 업로드를 시작하는 주체)",
            document,
        )
        self.assertIn(
            "- '제약사에 제출됨' 상태에서 '마감 전 재제출'이 일어나면 '제약사에 제출됨' 상태가 된다. (주체: EDI팀)",
            document,
        )
        self.assertIn(
            "- 위에 적은 경우가 아니면 다음 사건은 받아들이지 않는다: '매달 업로드 시작', '업로드 마감 설정', "
            "'업로드 마감 해제', '제약사에 제출', '마감 전 재제출', '제약사 마감'",
            document,
        )
        self.assertIn("  - 근거: 매달 EDI 업로드가 시작되면 EDI팀은 입력을 시작한다.", document)
        self.assertIn('    state "업로드 마감" as Closed', document)

    def test_mixed_state_is_a_derived_status_and_lists_are_screens(self):
        document = self.render_example("edi_row_rules.pdl")
        self.assertIn("## 상태 판정 규칙", document)
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
        self.assertIn("## 확인이 필요한 가정", document)
        self.assertIn("| 업로드 마감 전 제약사 제출 | 업로드 마감 전에는 제약사에 제출하지 않는다 | ERP-PLANNING.md:235 |", document)
        self.assertIn("| 제약사 마감을 기록하는 주체 | EDI팀 | ERP-PLANNING.md:237 |", document)

    def test_examples_from_the_source_section_are_kept(self):
        document = self.render_example("edi_row_rules.pdl")
        self.assertIn("타이레놀 5개와 우루사 3개", document)
        self.assertIn("변경 전후 값, 수정 사유, 수정자와 시각을 이력으로 기록한다", document)
        self.assertIn("edited_at: Timestamp - 수정 시각이다.", document)

    def test_screen_items_use_field_labels(self):
        text = (EXAMPLES / "carry_over.pdl").read_text(encoding="utf-8")
        module = parse_module(text[: text.index("unknown structure")])
        self.assertEqual([f for f in check(module) if f.blocking], [])
        document = render(module, check(module))
        self.assertIn(
            "- 이월 현황은 원장 행의 분할 전 행, 원장 행의 제출월, 원장 행의 정산월을 보여 준다.",
            document,
        )
        self.assertIn("- EDI팀은 제출채널을 관리할 수 있다.", self.render_without_unknowns("channels.pdl"))

    def render_without_unknowns(self, name: str) -> str:
        text = (EXAMPLES / name).read_text(encoding="utf-8")
        module = parse_module(text[: text.index("unknown structure")])
        return render(module, check(module))

    def test_machine_is_rendered_as_a_diagram(self):
        module = parse_module(COVERED_MACHINE)
        document = render(module, check(module))
        self.assertIn("stateDiagram-v2", document)
        self.assertIn("A --> B: Go (Ext)", document)
        self.assertIn("B --> [*]", document)


if __name__ == "__main__":
    unittest.main()
