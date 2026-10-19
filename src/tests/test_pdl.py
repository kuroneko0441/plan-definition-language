import contextlib
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

import z3

from pdl.checks import check
from pdl.cli import check_consistency
from pdl.project import compare
from pdl.render import render
from pdl import syntax
from pdl.format import to_text
from pdl.syntax import PdlSyntaxError, parse_module

LIBRARY = """
module library

term Renewal

LoanState : {Active, Returned, Lost}
ListGroup : {Lending, Returning}
DeskStatus : {Open, Closed}

EditReason key (text) passive {
    text: Text
}

Reader key (card) passive {
    card: Text
}

LoanRecord key (id) {
    id: Text
    reader: Reader
    state: LoanState
    lent_on: Day
    due_month: Month
    returned_on: Day?
}

actor Librarian
actor Member
external Archive
action Lend by (Librarian) on (LoanRecord)
action Extend by (Member, Librarian) on (LoanRecord)
action EditRecord by (Librarian) on (LoanRecord)

permit Librarian Lend LoanRecord: DeskStatus = Open as open_desk
forbid Librarian Lend LoanRecord: DeskStatus = Closed as closed_desk
permit Member Extend LoanRecord: LoanState = Active assuming renewal_limit as extend_active
forbid Member Extend LoanRecord: LoanState = Returned as extend_returned
forbid Member Extend LoanRecord: LoanState = Lost as extend_lost
permit Librarian Extend LoanRecord as librarian_extends
permit Librarian EditRecord LoanRecord: LoanState = Active requires EditReason as edit_active
permit Librarian EditRecord LoanRecord: LoanState = Returned requires EditReason assuming editing_actor as edit_returned
forbid * EditRecord LoanRecord: LoanState = Lost as edit_lost

law due_after_lent: LoanRecord.due_month = next(month_of(LoanRecord.lent_on))

derive ReaderStanding of Reader from LoanState mixed Mixed
screen LoanList of LoanRecord shows ReaderStanding, ListGroup
screen LoanDetail of LoanRecord shows LoanRecord.state, LoanRecord.lent_on

MonthlyReview : {Preparing, Reviewing, Closed} init Preparing cyclic
MonthlyReview.BeginMonth @Librarian {
    MonthlyReview = Preparing => MonthlyReview' = Reviewing assuming month_starter as begin
    MonthlyReview = Reviewing => ignore
    MonthlyReview = Closed => ignore
}
MonthlyReview.Finish @Librarian {
    MonthlyReview = Reviewing => MonthlyReview' = Closed
    MonthlyReview = Preparing => ignore
    MonthlyReview = Closed => reject
}
MonthlyReview.Reopen @Archive {
    MonthlyReview = Closed => MonthlyReview' = Preparing
    else reject assuming unlisted_events
}

unknown value renewal_limit { label "연장 횟수 제한" source "도서관 규정집 3쪽" provisional "한 건당 한 번만 연장할 수 있다" }
unknown value editing_actor { label "기록을 고치는 주체" source "도서관 규정집 5쪽" provisional "사서가 고친다" verified yes }
unknown value unlisted_events { label "흐름에 적지 않은 사건의 처리" source "운영 회의록" provisional "적지 않은 사건은 일어나지 않는 것으로 본다" }
unknown value month_starter { label "월 점검을 시작하는 주체" source "운영 회의록" provisional "사서가 시작한다" open yes }

text {
    module "도서관 대출 규칙"
    Renewal "연장" why "회원이 반납 기한을 늦추는 행위다."
    LoanState "대출 상태" why "대출 한 건이 가질 수 있는 상태다."
    LoanState.Active "대출 중"
    LoanState.Returned "반납됨"
    LoanState.Lost "분실"
    ListGroup "목록 구분" why "대출 목록을 가르는 화면의 구분이다."
    ListGroup.Lending "대출"
    ListGroup.Returning "반납"
    DeskStatus "창구 상태" why "사서가 창구를 열었는지를 나타낸다."
    DeskStatus.Open "열림"
    DeskStatus.Closed "닫힘"
    EditReason "수정 사유" why "대출 기록을 고친 이유이며 기록마다 남긴다."
    EditReason.text "사유 문구"
    Reader "이용자" why "도서관에 등록한 사람이다."
    Reader.card "회원증 번호"
    LoanRecord "대출 기록" why "대출 한 건이다. 책 한 권마다 한 건이 생긴다."
    LoanRecord.id "식별자"
    LoanRecord.reader "이용자"
    LoanRecord.state "대출 상태"
    LoanRecord.lent_on "대출일" why "책을 빌려 간 날이다."
    LoanRecord.due_month "반납월"
    LoanRecord.returned_on "반납일"
    Librarian "사서"
    Member "이용자 계정"
    Archive "서고 시스템"
    Lend "대출 처리"
    Extend "연장"
    EditRecord "기록 수정"
    open_desk why "창구가 열려 있을 때만 대출을 처리한다."
    closed_desk why "창구가 닫히면 대출을 처리하지 않는다."
    extend_active why "대출 중인 책만 연장할 수 있다."
    extend_returned why "반납한 책은 연장할 수 없다."
    extend_lost why "분실한 책은 연장할 수 없다."
    librarian_extends why "사서는 상태와 무관하게 연장을 처리한다."
    edit_active why "대출 중인 기록은 사유를 남기고 고친다."
    edit_returned why "반납한 기록도 사유를 남기고 고친다."
    edit_lost why "분실 처리한 기록은 고칠 수 없다."
    due_after_lent why "반납월은 대출일의 다음 달이다."
    ReaderStanding "이용자 상태" why "이용자의 대출 기록마다 상태가 다를 수 있다." mixed "혼합"
    LoanList "대출 목록" why "목록에서 이용자별 상태를 한눈에 본다."
    LoanDetail "대출 상세"
    MonthlyReview "월별 대출 점검" why "점검은 이용자별, 월별로 따로 진행되며 매달 반복된다."
    MonthlyReview.Preparing "준비 중"
    MonthlyReview.Reviewing "점검 중"
    MonthlyReview.Closed "마감"
    MonthlyReview.BeginMonth "월 점검 시작"
    MonthlyReview.BeginMonth.begin why "매달 점검이 시작되면 사서가 기록을 살핀다."
    MonthlyReview.Finish "점검 마감"
    MonthlyReview.Reopen "다시 열기"
}
"""

UNCOVERED_LIBRARY = """
module small_library
actor Librarian
action Lend by (Librarian) on (LoanRecord)
LoanState : {Active, Returned}
LoanRecord key (id) {
    id: Text
    state: LoanState
}
permit Librarian Lend LoanRecord: LoanState = Active
"""


def blocking_kinds(text: str) -> Counter:
    return Counter(finding.kind for finding in check(parse_module(text)) if finding.blocking)


COVERED_MACHINE = """
module covered
external Ext
M : {A, B} init A final {B}
M.Go @Ext {
    M = A => M' = B
    M = B => ignore
}
run reaches_end: M = A -> Go, Go -> M = B
"""


LINKED = "module m\nS : {A, B}\nParent {}\nChild { parent: Parent\nstate: S }\n"

CONFLICTING_RULES = (
    "module m\nS : {On, Off}\nP : {Open, Closed}\nactor X\naction Do\nR {}\n"
    "forbid * Do R: S = Off\npermit X Do R: P = Open\n"
    "forbid * Do R: S = On & P = Closed\n"
)


class SeededHoleTest(unittest.TestCase):
    def test_undefined_key_field(self):
        text = "module m\nA key (missing) { id: Text }"
        self.assertEqual(blocking_kinds(text), Counter({"UNDEFINED": 1}))

    def test_undefined_field_type(self):
        text = "module m\nA { id: Nowhere }"
        self.assertEqual(blocking_kinds(text), Counter({"UNDEFINED": 1}))

    def test_duplicate_definition(self):
        text = "module m\nE : {A, B}\nE : {C}"
        self.assertEqual(blocking_kinds(text), Counter({"DUPLICATE": 1}))

    def test_ownerless_transition(self):
        text = "module m\nM : {A, B} init A final {B}\nM.Go {\nM = A => M' = B\nM = B => ignore\n}"
        self.assertEqual(blocking_kinds(text), Counter({"OWNERLESS": 1}))

    def test_uncovered_combination(self):
        text = "module m\nactor X\naction Do\nR {}"
        self.assertEqual(blocking_kinds(text), Counter({"UNCOVERED": 1}))
        self.assertEqual([f.line for f in check(parse_module(text))], [3])
        ruled = "module m\nS : {A, B}\nactor X\naction Do\nR {}\npermit X Do R: S = A"
        self.assertEqual([f.line for f in check(parse_module(ruled))], [6])
        with mock.patch("pdl.checks.worlds", side_effect=static_only):
            self.assertEqual([f.line for f in check(parse_module(ruled))], [6])

    def test_wildcard_covers_every_combination(self):
        text = "module m\nactor X, Y\naction Do\nR {}\npermit * Do R"
        self.assertEqual(blocking_kinds(text), Counter())

    def test_contradiction_between_wildcard_and_specific_rule(self):
        text = "module m\nactor X\naction Do\nR {}\npermit * Do R\nforbid X Do R"
        self.assertEqual(blocking_kinds(text), Counter({"CONTRADICTION": 1}))

    def test_assumption_resolves_a_conditional_contradiction(self):
        self.assertEqual(blocking_kinds(CONFLICTING_RULES), Counter({"CONTRADICTION": 1}))
        resolved = CONFLICTING_RULES + "assume apart: !(S = Off & P = Open)\n"
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
            "module m\nE passive { submitted_on: Day\nsettled_in: Month }\n"
            "law l: E.submitted_on = E.settled_in"
        )
        self.assertEqual(blocking_kinds(text), Counter({"UNIT_MISMATCH": 1}))

    def test_month_of_converts_a_day_to_a_month(self):
        text = (
            "module m\nE passive { submitted_on: Day\nsettled_in: Month }\n"
            "law l: month_of(E.submitted_on) < E.settled_in"
        )
        self.assertEqual(blocking_kinds(text), Counter())

    def test_action_scope_limits_the_required_combinations(self):
        text = "module m\nactor X, Y\naction Do by (X) on (R)\nR {}\npermit X Do R"
        self.assertEqual(blocking_kinds(text), Counter())

    def test_rule_outside_the_action_scope_is_inapplicable(self):
        text = "module m\nactor X, Y\naction Do by (X) on (R)\nR {}\npermit X Do R\npermit Y Do R"
        self.assertEqual(blocking_kinds(text), Counter({"INAPPLICABLE": 1}))

    def test_action_scope_with_undefined_names(self):
        text = "module m\nactor X\naction Do by (Nobody) on (Nothing)"
        self.assertEqual(blocking_kinds(text), Counter({"UNDEFINED": 2}))

    def test_term_name_cannot_repeat_an_action_name(self):
        text = "module m\nterm Do\naction Do\ntext { Do why \"x\" }"
        self.assertEqual(blocking_kinds(text), Counter({"DUPLICATE": 1}))

    def test_derived_status_and_screen_pass_when_linked(self):
        text = LINKED + "derive D of Parent from S mixed Mixed\nscreen V of Parent shows D, S, Child.state"
        self.assertEqual(blocking_kinds(text), Counter())

    def test_derived_status_needs_rows_that_link_the_entity_to_the_enum(self):
        text = "module m\nS : {A, B}\nParent {}\nderive D of Parent from S mixed Mixed"
        self.assertEqual(blocking_kinds(text), Counter({"UNDEFINED": 1}))

    def test_mixed_value_cannot_repeat_an_enum_value(self):
        text = LINKED + "derive D of Parent from S mixed A"
        self.assertEqual(blocking_kinds(text), Counter({"DUPLICATE": 1}))

    def test_screen_cannot_show_undefined_items(self):
        text = LINKED + "screen V of Parent shows Nothing, Child.nothing"
        self.assertEqual(blocking_kinds(text), Counter({"UNDEFINED": 2}))

    def test_invariant_removes_the_worlds_that_cause_a_contradiction(self):
        self.assertEqual(blocking_kinds(CONFLICTING_RULES), Counter({"CONTRADICTION": 1}))
        ascii_form = CONFLICTING_RULES + "inv I: S = Off => P != Open\n"
        unicode_form = CONFLICTING_RULES + "inv I: S = Off ⇒ P ≠ Open\n"
        self.assertEqual(blocking_kinds(ascii_form), Counter())
        self.assertEqual(blocking_kinds(unicode_form), Counter())

    def test_quantifier_ranges_over_the_values_of_an_enum(self):
        text = CONFLICTING_RULES + "inv I: ∀ s ∈ S : s = Off ⇒ P ∈ {Closed}\n"
        self.assertEqual(blocking_kinds(text), Counter())

    def test_invariant_with_undefined_names_is_reported(self):
        text = "module m\nS : {On, Off}\ninv I: S = Maybe\ninv J: Nothing = On\ninv K: T ∈ {On}"
        self.assertEqual(blocking_kinds(text), Counter({"UNDEFINED": 3}))

    def test_invariants_that_exclude_every_combination_contradict(self):
        text = "module m\nS : {On, Off}\ninv A: S = On\ninv B: S = Off"
        self.assertEqual(blocking_kinds(text), Counter({"CONTRADICTION": 1}))

    def test_invariant_is_rendered_with_symbols(self):
        text = "module m\nS : {On, Off}\nP : {Open, Closed}\ninv I: ∀ s ∈ S : (s = Off ∧ P = Open) ⇒ ¬(P = Closed)\ntext { I why \"x\" }"
        module = parse_module(text)
        document = render(module, check(module))
        self.assertIn("- x\n", document)
        self.assertIn("- I: `∀ s ∈ S : s = Off ∧ P = Open ⇒ ¬(P = Closed)`", document)

    def test_syntax_error_reports_the_line(self):
        with self.assertRaises(PdlSyntaxError) as raised:
            parse_module("module m\nE : A")
        self.assertEqual(raised.exception.line, 2)


class MachineTest(unittest.TestCase):
    def test_covered_machine_and_scenario_pass(self):
        self.assertEqual(blocking_kinds(COVERED_MACHINE), Counter())

    def test_unreachable_trap_and_unhandled_states(self):
        text = (
            "module m\nexternal Ext\nM : {A, B, C, D} init A final {B}\n"
            "M.Go @Ext {\nM = A => M' = B\nM = C => M' = D\nM = B => ignore\nM = D => ignore\n}"
        )
        self.assertEqual(blocking_kinds(text), Counter({"UNREACHABLE": 2, "TRAP": 2}))

    def test_unhandled_event_in_a_state(self):
        text = (
            "module m\nexternal Ext\nM : {A, B} init A final {B}\n"
            "M.Go @Ext {\nM = A => M' = B\nM = B => ignore\n}\nM.Stop {\n}"
        )
        self.assertEqual(blocking_kinds(text), Counter({"UNHANDLED": 2}))

    def test_two_targets_for_the_same_event_contradict(self):
        text = (
            "module m\nexternal Ext\nM : {A, B, C} init A final {B, C}\n"
            "M.Go @Ext {\nM = A => M' = B\nM = A => M' = C\nM = B => ignore\nM = C => ignore\n}"
        )
        self.assertEqual(blocking_kinds(text), Counter({"CONTRADICTION": 1}))

    def test_scenario_that_ends_elsewhere_fails(self):
        text = COVERED_MACHINE.replace("Go, Go -> M = B", "Go, Go -> M = A")
        self.assertEqual(blocking_kinds(text), Counter({"SCENARIO_FAILED": 1}))

    def test_scenario_through_a_missing_transition_fails(self):
        text = COVERED_MACHINE.replace("Go, Go -> M = B", "Go, Go, Go -> M = B").replace("M = B => ignore", "M = B => reject")
        self.assertEqual(blocking_kinds(text), Counter({"SCENARIO_FAILED": 1}))


GUARDED = (
    "module m\nG : {On, Off}\nexternal Ext, Other\n"
    "M : {A, B, C} init A final {B, C}\nM.Go @Ext {\n"
    "M = A & G = On => M' = B\n"
    "M = A & G = Off => M' = C\n"
    "M = B => ignore\nM = C => ignore\n}\n"
)


class ExtensionTest(unittest.TestCase):
    def test_value_sets_and_negation_in_rule_conditions(self):
        base = "module m\nS : {A, B, C}\nactor X\naction Do\nR {}\n"
        covered = base + "permit X Do R: S in {A, B}\nforbid X Do R: S != A & S != B\n"
        self.assertEqual(blocking_kinds(covered), Counter())
        overlapping = base + "permit X Do R: S in {A, B}\nforbid X Do R: S != A\n"
        self.assertEqual(blocking_kinds(overlapping), Counter({"CONTRADICTION": 1}))

    def test_condition_values_must_belong_to_the_enum(self):
        text = "module m\nS : {A, B}\nactor X\naction Do\nR {}\npermit X Do R: S in {A, Z}"
        self.assertIn("UNDEFINED", blocking_kinds(text))

    def test_guards_that_cover_every_case_pass(self):
        self.assertEqual(blocking_kinds(GUARDED), Counter())

    def test_a_missing_guard_branch_is_reported(self):
        text = GUARDED.replace("M = A & G = Off => M' = C\n", "")
        self.assertEqual(blocking_kinds(text), Counter({"UNCOVERED": 1, "UNREACHABLE": 1}))

    def test_overlapping_guards_with_different_targets_contradict(self):
        text = GUARDED.replace("G = Off =>", "G in {On, Off} =>")
        self.assertEqual(blocking_kinds(text), Counter({"CONTRADICTION": 1}))

    def test_an_explicit_handling_covers_the_other_guard_branch(self):
        text = GUARDED.replace("M = A & G = Off => M' = C\n", "M = A => ignore\n")
        self.assertEqual(blocking_kinds(text), Counter({"UNREACHABLE": 1}))

    def test_scenario_uses_the_given_values_to_pick_a_guard(self):
        passing = GUARDED + "run s: M = A & G = Off -> Go -> M = C\n"
        self.assertEqual(blocking_kinds(passing), Counter())
        failing = GUARDED + "run s: M = A & G = Off -> Go -> M = B\n"
        self.assertEqual(blocking_kinds(failing), Counter({"SCENARIO_FAILED": 1}))

    def test_cyclic_machine_needs_no_terminal_state(self):
        text = "module m\nexternal Ext\nM : {A, B} init A cyclic\nM.Go @Ext {\nM = A => M' = B\nM = B => M' = A\n}"
        self.assertEqual(blocking_kinds(text), Counter())

    def test_cyclic_machine_reports_a_state_that_cannot_return(self):
        text = (
            "module m\nexternal Ext\nM : {A, B, C} init A cyclic\n"
            "M.Go @Ext {\nM = A => M' = B\nM = B => M' = A\nM = C => reject\n}"
        )
        counts = blocking_kinds(text)
        self.assertEqual(counts["TRAP"], 1)
        self.assertEqual(counts["UNREACHABLE"], 1)

    def test_machine_without_terminal_and_not_cyclic_is_reported(self):
        text = "module m\nexternal Ext\nM : {A} init A\nM.Go {\nM = A => ignore\n}"
        self.assertEqual(blocking_kinds(text), Counter({"MISSING": 1}))

    def test_a_transition_can_name_several_actors(self):
        ok = GUARDED.replace("G = On => M' = B", "G = On => M' = B @Ext, Other")
        self.assertEqual(blocking_kinds(ok), Counter())
        bad = GUARDED.replace("G = On => M' = B", "G = On => M' = B @Ext, Nobody")
        self.assertEqual(blocking_kinds(bad), Counter({"UNDEFINED": 1}))

    def test_several_assumptions_on_one_line(self):
        unknowns = 'unknown value a { provisional "1" source "s" verified no }\nunknown value b { provisional "2" source "s" verified no }\n'
        base = "module m\nactor X\naction Do\nR {}\n" + unknowns
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
        text = GUARDED.replace("M = B => ignore\n", "M = B => ignore assuming a as waits\n") + (
            'unknown value a { provisional "1" source "s" verified no }\ntext { M.Go.waits why "b" }\n'
        )
        module = parse_module(text)
        self.assertEqual(blocking_kinds(text), Counter())
        document = render(module, check(module))
        self.assertIn("'B' 상태에서", document.replace("'B' + 'Go'", "'B' 상태에서"))
        self.assertIn("  - 근거: b", document)

    def test_nullable_and_list_field_types(self):
        ok = "module m\nS : {A, B}\nE passive { a: Text?\nb: list S\nc: Decimal\nd: Money?\ne: Duration }"
        self.assertEqual(blocking_kinds(ok), Counter())
        bad = "module m\nE passive { a: list Nowhere }"
        self.assertEqual(blocking_kinds(bad), Counter({"UNDEFINED": 1}))

    def test_nullable_time_field_still_works_in_a_law(self):
        text = "module m\nE passive { a: Month?\nb: Month }\nlaw l: E.b = next(E.a)"
        self.assertEqual(blocking_kinds(text), Counter())

    def test_guard_condition_is_rendered_in_the_flow(self):
        text = GUARDED + 'text {\nG "스위치"\nG.On "켜짐"\nG.Off "꺼짐"\n}\n'
        module = parse_module(text)
        document = render(module, check(module))
        self.assertIn("'A' 상태에서 스위치가 '켜짐'일 때 'Go'가 일어나면 'B' 상태가 된다.", document)

    def test_draft_build_lists_the_holes_in_a_separate_file(self):
        import tempfile
        from pathlib import Path as TempPath

        from pdl.cli import build_file

        with tempfile.TemporaryDirectory() as directory:
            root = TempPath(directory)
            source = root / "small_library.pdl"
            source.write_text(UNCOVERED_LIBRARY, encoding="utf-8")
            output = root / "build"
            self.assertFalse(build_file(source, output, "ko"))
            self.assertFalse(output.exists())
            self.assertFalse(build_file(source, output, "ko", draft=True))
            draft = (output / "small_library.draft.md").read_text(encoding="utf-8")
            self.assertIn("## 초안", draft)
            self.assertIn("UNCOVERED", draft)

    def test_draft_build_never_crashes_on_any_module(self):
        import tempfile
        from pathlib import Path as TempPath

        from pdl.cli import build_file

        with tempfile.TemporaryDirectory() as directory:
            root = TempPath(directory)
            for number, text in enumerate((LIBRARY, UNCOVERED_LIBRARY, GUARDED_IGNORE, COUNTER_MACHINE, CROSS_MACHINES)):
                source = root / f"module{number}.pdl"
                source.write_text(text, encoding="utf-8")
                build_file(source, root / "build", "ko", draft=True)


COUNTER_MACHINE = (
    "module m\nexternal Ext\n"
    "M : {A, B} init A final {B}\nM.Streak : 0..2\n"
    "M.Loss @Ext {\nM = A & Streak in {0, 1} => Streak' = Streak + 1\nM = A & Streak = 2 => M' = B\nM = B => ignore\n}\n"
    "M.Win @Ext {\nM = A => Streak' = 0\nM = B => ignore\n}\n"
    "run three_losses: M = A -> Loss, Loss, Loss -> M = B\n"
)

CROSS_MACHINES = (
    "module m\nexternal Ext\n"
    "P : {Ok, Bad} init Ok final {Bad}\nP.Fail @Ext {\nP = Ok => P' = Bad\nP = Bad => ignore\n}\n"
    "T : {Open, Done} init Open final {Done}\nT.Finish @Ext {\nT = Open => T' = Done\nT = Done => ignore\n}\n"
    "inv done_needs_ok: T = Done => P = Ok\n"
)


class CapabilityTest(unittest.TestCase):
    def test_stored_texts_must_be_unique_within_an_enum(self):
        ok = 'module m\nA : {X, Y}\ntext {\nA.X "엑스" stored "엑스값"\nA.Y stored "와이값"\n}'
        self.assertEqual(blocking_kinds(ok), Counter())
        clash = 'module m\nA : {X, Y}\ntext {\nA.X stored "같은값"\nA.Y stored "같은값"\n}'
        self.assertEqual(blocking_kinds(clash), Counter({"DUPLICATE": 1}))

    def test_stored_text_is_shown_next_to_the_value(self):
        module = parse_module('module m\nA : {X, Y}\ntext { A.X "엑스" stored "엑스값" }')
        document = render(module, check(module))
        self.assertIn("X (엑스) [저장값: 엑스값], Y", document)

    def test_a_repeated_enum_value_is_reported(self):
        self.assertEqual(blocking_kinds("module m\nA : {X, X}"), Counter({"DUPLICATE": 1}))

    def test_import_brings_in_shared_definitions(self):
        import tempfile
        from pathlib import Path as TempPath

        with tempfile.TemporaryDirectory() as directory:
            root = TempPath(directory)
            (root / "common.pdl").write_text("module common\nS : {On, Off}\nactor X\n", encoding="utf-8")
            text = 'module m\nimport "common.pdl"\naction Do\nR {}\nforbid X Do R: S = Off\npermit X Do R: S = On\n'
            module = parse_module(text, root / "main.pdl")
            self.assertEqual([f for f in check(module) if f.blocking], [])

    def test_a_file_imported_twice_is_merged_once(self):
        import tempfile
        from pathlib import Path as TempPath

        with tempfile.TemporaryDirectory() as directory:
            root = TempPath(directory)
            (root / "d.pdl").write_text("module d\nS : {On, Off}\n", encoding="utf-8")
            (root / "b.pdl").write_text('module b\nimport "d.pdl"\n', encoding="utf-8")
            (root / "c.pdl").write_text('module c\nimport "d.pdl"\n', encoding="utf-8")
            module = parse_module('module a\nimport "b.pdl"\nimport "c.pdl"\n', root / "a.pdl")
            self.assertEqual([f for f in check(module) if f.blocking], [])
            self.assertEqual(len(module.enums), 1)

    def test_import_problems_are_syntax_errors(self):
        import tempfile
        from pathlib import Path as TempPath

        with self.assertRaises(PdlSyntaxError):
            parse_module('module m\nimport "x.pdl"')
        with tempfile.TemporaryDirectory() as directory:
            root = TempPath(directory)
            with self.assertRaises(PdlSyntaxError):
                parse_module('module m\nimport "missing.pdl"', root / "m.pdl")
            (root / "a.pdl").write_text('module a\nimport "b.pdl"\n', encoding="utf-8")
            (root / "b.pdl").write_text('module b\nimport "a.pdl"\n', encoding="utf-8")
            with self.assertRaises(PdlSyntaxError):
                parse_module((root / "a.pdl").read_text(encoding="utf-8"), root / "a.pdl")

    def test_imported_definition_that_clashes_is_a_duplicate(self):
        import tempfile
        from pathlib import Path as TempPath

        with tempfile.TemporaryDirectory() as directory:
            root = TempPath(directory)
            (root / "common.pdl").write_text("module common\nS : {On, Off}\n", encoding="utf-8")
            module = parse_module('module m\nimport "common.pdl"\nS : {A, B}\n', root / "m.pdl")
            self.assertEqual(Counter(f.kind for f in check(module) if f.blocking), Counter({"DUPLICATE": 1}))

    def test_a_counter_with_matching_guards_passes_and_the_scenario_counts(self):
        self.assertEqual(blocking_kinds(COUNTER_MACHINE), Counter())

    def test_a_counter_guard_gap_is_reported(self):
        text = COUNTER_MACHINE.replace("Streak = 2 => M' = B", "Streak = 1 => M' = B")
        counts = blocking_kinds(text)
        self.assertEqual(counts["UNCOVERED"], 1)
        self.assertEqual(counts["CONTRADICTION"], 1)

    def test_a_counter_that_can_exceed_its_maximum_is_reported(self):
        text = "module m\nexternal Ext\nM : {A} init A final {A}\nM.C : 0..1\nM.Go @Ext {\nM = A => C' = C + 1\n}"
        self.assertEqual(blocking_kinds(text), Counter({"OVERFLOW": 1}))

    def test_effects_must_name_a_counter_and_stay_in_range(self):
        text = COUNTER_MACHINE.replace("Streak' = 0", "Missing' = 0").replace("Streak' = Streak + 1", "Streak' = 9")
        self.assertEqual(blocking_kinds(text)["UNDEFINED"], 2)

    def test_counter_and_time_limit_are_rendered(self):
        text = COUNTER_MACHINE.replace("Streak' = 0", "Streak' = 0 as reset") + 'text { M.Win.reset after "60초" }\n'
        module = parse_module(text)
        document = render(module, check(module))
        self.assertIn("- 카운터: Streak (0 ~ 2)", document)
        self.assertIn("(제한 시간: 60초)", document)
        self.assertIn("(카운터: Streak 0(으)로 되돌림)", document)
        self.assertIn("(카운터: Streak +1)", document)

    def test_a_task_cannot_finish_while_a_photo_has_failed(self):
        findings = [f for f in check(parse_module(CROSS_MACHINES)) if f.blocking]
        self.assertEqual([f.kind for f in findings], ["INVARIANT_VIOLATED"])
        self.assertIn("P: Fail -> T: Finish", findings[0].message)

    def test_a_guard_on_another_machine_keeps_the_invariant(self):
        text = CROSS_MACHINES.replace(
            "T = Open => T' = Done\n", "T = Open & P = Ok => T' = Done\nT = Open => ignore\n"
        ).replace("P = Ok => P' = Bad\n", "P = Ok & T = Open => P' = Bad\nP = Ok => ignore\n")
        self.assertEqual(blocking_kinds(text), Counter({"TRAP": 2}))

    def test_a_state_that_a_guard_makes_unreachable_is_reported(self):
        text = (
            "module m\nexternal Ext\n"
            "P : {Ok, Bad} init Ok final {Bad}\nP.Fail @Ext {\nP = Ok => P' = Ok\nP = Bad => ignore\n}\n"
            "T : {Open, Done} init Open final {Done}\n"
            "T.Finish @Ext {\nT = Open & P = Bad => T' = Done\nT = Open => ignore\nT = Done => ignore\n}\n"
        )
        counts = blocking_kinds(text)
        self.assertEqual(counts["UNREACHABLE"], 2)
        self.assertEqual(counts["TRAP"], 1)


GUARDED_IGNORE = (
    "module m\nexternal Ext\nS : {On, Off}\n"
    "M : {A, B} init A final {B}\n"
    "M.E @Ext {\nM = A & S = On => M' = B\nM = A & S = Off => ignore\nM = B => ignore\n}\n"
    "M.F @Ext {\nM = A => M' = B\nM = B => ignore\n}\n"
    "run skipped: M = A & S = Off -> E, F -> M = B\n"
)


class GuardedHandlingTest(unittest.TestCase):
    def test_a_guarded_ignore_covers_the_other_world(self):
        self.assertEqual(blocking_kinds(GUARDED_IGNORE), Counter())

    def test_a_world_without_transition_or_handling_is_uncovered(self):
        text = GUARDED_IGNORE.replace("S : {On, Off}", "S : {On, Off, Hold}")
        self.assertEqual(blocking_kinds(text), Counter({"UNCOVERED": 1}))

    def test_a_guarded_ignore_that_overlaps_a_transition_is_a_contradiction(self):
        text = GUARDED_IGNORE.replace("S = Off => ignore", "S in {On, Off} => ignore")
        self.assertEqual(blocking_kinds(text), Counter({"CONTRADICTION": 1}))

    def test_a_guarded_ignore_beside_an_unconditional_transition_is_a_contradiction(self):
        text = GUARDED_IGNORE.replace("M = A & S = On => M' = B", "M = A => M' = B")
        self.assertEqual(blocking_kinds(text), Counter({"CONTRADICTION": 1}))

    def test_a_scenario_skips_an_event_only_in_the_guarded_world(self):
        text = GUARDED_IGNORE.replace("S : {On, Off}", "S : {On, Off, Hold}").replace("M = A & S = Off ->", "M = A & S = Hold ->")
        self.assertEqual(blocking_kinds(text), Counter({"UNCOVERED": 1, "SCENARIO_FAILED": 1}))

    def test_the_guard_is_rendered_beside_the_handling(self):
        module = parse_module(GUARDED_IGNORE)
        self.assertIn("'A' + 'E': ignored (when S is Off)", render(module, check(module), "en"))
        self.assertIn("'A' + 'E': 무시한다 (S가 'Off'일 때)", render(module, check(module), "ko"))


GUARDED_PAIR = CROSS_MACHINES.replace(
    "T = Open => T' = Done\n", "T = Open & P = Ok => T' = Done\nT = Open => ignore\n"
).replace("P = Ok => P' = Bad\n", "P = Ok & T = Open => P' = Bad\nP = Ok => ignore\n")


class JointScenarioTest(unittest.TestCase):
    def kinds(self, run: str) -> Counter:
        return blocking_kinds(GUARDED_PAIR + run + "\n")

    def test_events_on_two_machines_follow_each_others_guards(self):
        self.assertEqual(self.kinds("run s: P = Ok & T = Open -> P.Fail, T.Finish -> P = Bad & T = Open"), Counter({"TRAP": 2}))
        self.assertEqual(self.kinds("run s: P = Ok & T = Open -> T.Finish, P.Fail -> P = Ok & T = Done"), Counter({"TRAP": 2}))

    def test_a_wrong_end_state_fails_the_scenario(self):
        text = "run s: P = Bad & T = Open -> T.Finish -> P = Bad & T = Done"
        self.assertEqual(self.kinds(text), Counter({"TRAP": 2, "SCENARIO_FAILED": 1}))

    def test_unknown_machines_states_and_events_are_undefined(self):
        self.assertEqual(self.kinds("run s: Q = Ok -> Q.Fail -> Q = Ok")["UNDEFINED"], 1)
        self.assertEqual(self.kinds("run s: P = Ok -> P.Nope -> P = Ok")["UNDEFINED"], 1)
        self.assertEqual(self.kinds("run s: P = Ok -> T.Finish -> P = Ok")["UNDEFINED"], 1)

    def test_the_joint_scenario_is_rendered(self):
        module = parse_module(GUARDED_PAIR + "run s: P = Ok & T = Open -> P.Fail -> P = Bad\n")
        document = render(module, check(module), "en")
        self.assertIn("- Start: P = Ok, T = Open", document)
        self.assertIn("- Event sequence: P: Fail", document)


FLAGGED = (
    "module m\nexternal Ext\nFlag : {On, Off}\n"
    "M : {A, B} init A final {B}\n"
    "M.Go @Ext {\nM = A & Flag = On => M' = B\nM = A => reject\nM = B => reject\n}\n"
)


class SystemSemanticsTest(unittest.TestCase):
    def test_findings_follow_the_declared_state_order(self):
        text = (
            "module m\nexternal Ext\nFlag : {On, Off}\n"
            "M : {S1, S2, S3, S4, S5, S6} init S1 final {S6}\n"
            "M.Go @Ext {\nM = S1 => M' = S2\nM = S2 => M' = S3\nM = S3 => M' = S4\n"
            "M = S4 => M' = S5\nM = S5 => M' = S6\nM = S6 => reject\n}\n"
            "M.Ping {\nFlag = On => ignore\n}\n"
        )
        states = [f.message.split()[0] for f in check(parse_module(text)) if f.kind == "UNCOVERED"]
        self.assertEqual(states, ["S1", "S2", "S3", "S4", "S5", "S6"])

    def test_transitions_that_change_a_counter_differently_contradict(self):
        machine = (
            "module m\nexternal Ext\n"
            "M : {A, B} init A final {B}\nM.N : 0..3\n"
            "M.Go @Ext {\nM = A => M' = B\nM = B => reject\n}\n"
            "M.Inc @Ext {\n%s\nM = B => reject\n}\n"
        )
        guarded = "M = A & N = 0 => N' = N + 1\nM = A & N = 0 => N' = N + 3\nM = A => reject"
        self.assertEqual(blocking_kinds(machine % guarded), Counter({"CONTRADICTION": 1}))
        unguarded = "M = A => N' = 1\nM = A => N' = 2"
        self.assertEqual(blocking_kinds(machine % unguarded), Counter({"CONTRADICTION": 1}))
        same = "M = A => N' = 1\nM = A => N' = 1"
        self.assertEqual(blocking_kinds(machine % same), Counter())

    def test_a_state_that_a_guard_keeps_from_finishing_is_a_trap(self):
        text = (
            "module m\nexternal Ext\n"
            "M : {A, B, C} init A final {C}\nM.N : 0..1\n"
            "M.Go @Ext {\nM = A => M' = B\nM = B & N = 1 => M' = C\nM = B => reject\nM = C => reject\n}\n"
            "M.Skip @Ext {\nM = A => M' = C\nM = B => reject\nM = C => reject\n}\n"
        )
        findings = [f for f in check(parse_module(text)) if f.blocking]
        self.assertEqual([f.kind for f in findings], ["TRAP"])
        self.assertIn("state B of M cannot reach a terminal state", findings[0].message)
        self.assertIn("after: M: Go", findings[0].message)

    def test_a_transition_must_keep_an_invariant_that_reads_an_enum(self):
        findings = [f for f in check(parse_module(FLAGGED + "inv i: Flag = On => M = A\n")) if f.blocking]
        self.assertEqual([f.kind for f in findings], ["INVARIANT_VIOLATED"])
        self.assertIn("after: M: Go (Flag=On, M=B)", findings[0].message)

    def test_a_violated_invariant_is_reported_at_its_own_line(self):
        text = CROSS_MACHINES.replace("inv done_needs_ok", "inv always_true: P = Ok | P = Bad\ninv done_needs_ok")
        findings = [f for f in check(parse_module(text)) if f.kind == "INVARIANT_VIOLATED"]
        self.assertEqual([f.line for f in findings], [text.splitlines().index("inv done_needs_ok: T = Done => P = Ok") + 1])
        self.assertIn("invariant done_needs_ok ", findings[0].message)
        with mock.patch("pdl.checks.SYSTEM_LIMIT", 0):
            solved = [f for f in check(parse_module(text)) if f.kind == "INVARIANT_VIOLATED"]
        self.assertEqual([f.line for f in solved], [f.line for f in findings])

    def test_a_guard_that_keeps_the_enum_invariant_passes(self):
        self.assertEqual(blocking_kinds(FLAGGED + "inv i: M = B => Flag = On\n"), Counter())

    def test_an_invariant_removes_the_enum_values_that_enable_a_transition(self):
        counts = blocking_kinds(FLAGGED + "inv i: M = A => Flag = Off\n")
        self.assertEqual(counts["UNREACHABLE"], 1)
        self.assertEqual(counts["INVARIANT_VIOLATED"], 0)

    def test_invariants_that_no_enum_value_satisfies_at_the_start_are_reported(self):
        text = FLAGGED + "inv i: M = A => Flag = On\ninv j: M = A => Flag = Off\n"
        messages = [f.message for f in check(parse_module(text)) if f.kind == "INVARIANT_VIOLATED"]
        self.assertEqual(len(messages), 1)
        self.assertIn("at the start", messages[0])


FREE_PAIR = CROSS_MACHINES.replace("inv done_needs_ok: T = Done => P = Ok\n", "")


class FormulaTest(unittest.TestCase):
    def test_a_rule_condition_takes_a_full_formula(self):
        base = "module m\nS : {A, B, C}\nactor X\naction Do\nR {}\n"
        covered = base + "permit X Do R: S = A | S = B\nforbid X Do R: !(S = A | S = B)\n"
        self.assertEqual(blocking_kinds(covered), Counter())
        gap = base + "permit X Do R: S = A | S = B\n"
        self.assertEqual(blocking_kinds(gap), Counter({"UNCOVERED": 1}))

    def test_a_guard_takes_a_full_formula(self):
        text = GUARDED.replace("G : {On, Off}", "G : {On, Off, Hold}").replace("G = Off =>", "(G = Off | G = Hold) =>")
        self.assertEqual(blocking_kinds(text), Counter())
        overlapping = text.replace("G = On =>", "!(G = Off) =>")
        self.assertEqual(blocking_kinds(overlapping), Counter({"CONTRADICTION": 1}))

    def test_a_formula_guard_is_rendered_as_a_formula(self):
        module = parse_module(GUARDED.replace("G = Off =>", "(G = Off | G = On => G = Off) =>"))
        self.assertIn("when `G = Off ∨ G = On ⇒ G = Off` holds", render(module, check(module), "en"))
        self.assertIn("`G = Off ∨ G = On ⇒ G = Off` 조건이 성립할 때", render(module, check(module), "ko"))

    def test_a_scenario_is_replayed_in_every_given_world(self):
        passing = GUARDED + "run s: M = A & (G = On | G = Off) -> Go, Go -> M = B\n"
        findings = [f for f in check(parse_module(passing)) if f.blocking]
        self.assertEqual([f.kind for f in findings], ["SCENARIO_FAILED"])
        self.assertIn("ends in C instead of B when G=Off", findings[0].message)
        empty = GUARDED + "run s: M = A & G = On & G = Off -> Go -> M = B\n"
        self.assertEqual(blocking_kinds(empty), Counter({"SCENARIO_FAILED": 1}))


class PremiseTest(unittest.TestCase):
    def test_an_assumption_removes_worlds_without_being_checked(self):
        counts = blocking_kinds(FLAGGED + "assume a: Flag = On => M = A\n")
        self.assertEqual(counts["INVARIANT_VIOLATED"], 0)
        self.assertEqual(counts["UNREACHABLE"], 1)

    def test_an_assumption_over_machine_states_removes_the_joint_state(self):
        counts = blocking_kinds(FREE_PAIR + "assume apart: !(T = Done & P = Bad)\n")
        self.assertEqual(counts["INVARIANT_VIOLATED"], 0)
        self.assertEqual(counts["TRAP"], 2)

    def test_assumptions_that_rule_out_the_start_contradict(self):
        findings = [f for f in check(parse_module(FREE_PAIR + "assume a: T = Done\n")) if f.kind == "CONTRADICTION"]
        self.assertEqual(len(findings), 1)
        self.assertIn("rule out the start", findings[0].message)

    def test_an_assumption_is_rendered_with_its_formula(self):
        module = parse_module(FLAGGED + 'assume a: M = B => Flag = On\ntext { a why "The flag stays on." }\n')
        document = render(module, check(module), "en")
        self.assertIn("## Premises\n\n- The flag stays on.", document)
        self.assertIn("- a: `M = B ⇒ Flag = On`", document)


class AssertionTest(unittest.TestCase):
    def failures(self, text: str) -> list[str]:
        return [f.message for f in check(parse_module(text)) if f.kind == "ASSERTION_FAILED"]

    def test_always_reports_the_path_to_a_failing_state(self):
        failures = self.failures(FREE_PAIR + "prop a: always T = Done => P = Ok\n")
        self.assertEqual(len(failures), 1)
        self.assertIn("assertion a fails after:", failures[0])
        self.assertIn("(P=Bad, T=Done)", failures[0])

    def test_always_passes_when_guards_keep_it(self):
        self.assertEqual(self.failures(GUARDED_PAIR + "prop a: always T = Done => P = Ok\n"), [])

    def test_always_reads_every_admissible_enum_value(self):
        self.assertEqual(len(self.failures(FLAGGED + "prop a: always M = B => Flag = On\n")), 1)
        kept = FLAGGED + "assume keep: M = B => Flag = On\nprop a: always M = B => Flag = On\n"
        self.assertEqual(self.failures(kept), [])

    def test_reachable_needs_one_state(self):
        self.assertEqual(self.failures(FREE_PAIR + "prop r: reachable T = Done & P = Bad\n"), [])
        failures = self.failures(GUARDED_PAIR + "prop r: reachable T = Done & P = Bad\n")
        self.assertEqual(failures, ["assertion r holds in no reachable state"])

    def test_can_reads_the_states_ahead(self):
        failures = self.failures(GUARDED_PAIR + "prop live: always can T = Done\n")
        self.assertEqual(failures, ["assertion live fails after: P: Fail (P=Bad, T=Open)"])
        self.assertEqual(self.failures(GUARDED_PAIR + "prop live: always P = Ok => can T = Done\n"), [])

    def test_an_assertion_needs_no_machine(self):
        base = "module m\nS : {A, B}\nassume never_a: !(S = A)\n"
        self.assertEqual(self.failures(base + "prop a: always S = B\n"), [])
        self.assertEqual(len(self.failures(base + "prop a: reachable S = A\n")), 1)

    def test_an_assertion_names_defined_values(self):
        self.assertEqual(blocking_kinds(FREE_PAIR + "prop a: always T = Gone\n")["UNDEFINED"], 1)

    def test_can_and_the_mode_are_part_of_the_syntax(self):
        with self.assertRaises(PdlSyntaxError):
            parse_module(FREE_PAIR + "inv i: can T = Done\n")
        with self.assertRaises(PdlSyntaxError):
            parse_module(FREE_PAIR + "prop a: T = Done\n")

    def test_an_assertion_is_rendered_with_its_formula(self):
        module = parse_module(GUARDED_PAIR + 'prop live: always P = Ok => can T = Done\ntext { live why "A good photo lets the task finish." }\n')
        document = render(module, check(module), "en")
        self.assertIn("## Verified properties\n\n- A good photo lets the task finish.", document)
        self.assertIn("- live: `always P = Ok ⇒ can (T = Done)`", document)


SHOP = (
    "module m\nexternal Sys\nGrade : {Gold, Basic}\n"
    "Dealer key (id) passive { id: Text\ngrade: Grade fixed }\n"
    "Order key (id) passive { id: Text\ndealer: Dealer fixed\nbackup: Dealer? }\n"
    "scope Dealer 2\nscope Order 2\n"
    "Flow of Order : {Open, Done} init Open final {Done}\n"
    "Flow.Finish @Sys {\nFlow = Open & this.dealer.grade = Gold => Flow' = Done\n"
    "Flow = Open => reject\nFlow = Done => reject\n}\n"
)
GOLD_ONLY = "assume all_gold: all d in Dealer: d.grade = Gold\n"


class RelationTest(unittest.TestCase):
    def failures(self, text: str) -> list[str]:
        return [f.message for f in check(parse_module(text)) if f.kind == "ASSERTION_FAILED"]

    def test_each_instance_runs_its_own_machine(self):
        text = SHOP + GOLD_ONLY + "prop apart: reachable Order1.Flow = Done & Order2.Flow = Open\n"
        self.assertEqual(blocking_kinds(text), Counter())

    def test_a_fixed_field_that_blocks_an_instance_is_a_trap(self):
        findings = [f for f in check(parse_module(SHOP)) if f.blocking]
        self.assertEqual([f.kind for f in findings], ["TRAP"])
        self.assertIn("state Open of Order1.Flow cannot reach a terminal state", findings[0].message)
        self.assertIn("Dealer1.grade=Basic", findings[0].message)

    def test_a_path_reads_through_a_reference(self):
        holds = SHOP + GOLD_ONLY + "prop a: always all o in Order: o.Flow = Done => o.dealer.grade = Gold\n"
        self.assertEqual(self.failures(holds), [])
        fails = SHOP + GOLD_ONLY + "prop a: always all o in Order: o.dealer = Dealer1\n"
        self.assertEqual(len(self.failures(fails)), 1)

    def test_a_field_that_is_not_fixed_changes_between_transitions(self):
        text = SHOP.replace("grade: Grade fixed", "grade: Grade")
        text += "prop a: always all o in Order: o.Flow = Done => o.dealer.grade = Gold\n"
        self.assertEqual(len(self.failures(text)), 1)

    def test_a_guard_reads_the_other_instances(self):
        guard = "Flow = Open & this.dealer.grade = Gold"
        alone = guard + " & (all p in Order: p = this | p.dealer != this.dealer | p.Flow = Open)"
        one = "prop one: always all a in Order: all b in Order: a = b | a.dealer != b.dealer | a.Flow = Open | b.Flow = Open\n"
        self.assertEqual(len(self.failures(SHOP + GOLD_ONLY + one)), 1)
        self.assertEqual(self.failures(SHOP.replace(guard, alone) + GOLD_ONLY + one), [])

    def test_exists_needs_one_instance(self):
        text = SHOP + GOLD_ONLY + "prop some_open: always some o in Order: o.Flow = Open\n"
        failures = self.failures(text)
        self.assertEqual(len(failures), 1)
        self.assertIn("Order1.Flow=Done", failures[0])
        self.assertIn("Order2.Flow=Done", failures[0])

    def test_an_optional_field_can_be_missing(self):
        text = SHOP + GOLD_ONLY + "prop a: reachable Order1.backup = none\nprop b: always Order1.backup.grade = Gold\n"
        failures = self.failures(text)
        self.assertEqual(len(failures), 1)
        self.assertIn("assertion b", failures[0])

    def test_an_inequality_through_a_missing_reference_is_false(self):
        failures = self.failures(SHOP + GOLD_ONLY + "prop a: reachable Order1.backup.grade != Gold\n")
        self.assertEqual(failures, ["assertion a holds in no reachable state"])
        self.assertEqual(self.failures(SHOP + GOLD_ONLY + "prop a: reachable !(Order1.backup.grade = Gold)\n"), [])

    def test_a_rule_reads_the_instance_it_applies_to(self):
        base = SHOP.replace("Order key (id) passive {", "Order key (id) {") + "actor Clerk\naction Edit\n"
        covered = base + "permit Clerk Edit Order: this.Flow = Open\nforbid Clerk Edit Order: this.Flow = Done\n"
        self.assertEqual(blocking_kinds(covered + GOLD_ONLY), Counter())
        gap = base + "permit Clerk Edit Order: this.Flow = Open\n"
        self.assertEqual(blocking_kinds(gap + GOLD_ONLY), Counter({"UNCOVERED": 1}))

    def test_a_scenario_replays_the_first_instance(self):
        text = SHOP + GOLD_ONLY + "run s: Flow = Open & this.dealer.grade = Gold -> Finish -> Flow = Done\n"
        self.assertEqual(blocking_kinds(text), Counter())

    def test_relational_errors_are_reported(self):
        for formula, part in (
            ("all o in Order: o.missing = Gold", "no field, machine, or counter named missing"),
            ("all o in Order: o.id = Gold", "which a formula cannot read"),
            ("all o in Order: o.dealer = Gold", "Gold is not a value of"),
            ("stranger.grade = Gold", "not a bound variable"),
            ("all o in Order: o.dealer.grade.more = Gold", "not an entity instance"),
        ):
            messages = [f.message for f in check(parse_module(SHOP + GOLD_ONLY + f"prop a: always {formula}\n")) if f.kind == "UNDEFINED"]
            self.assertEqual(len(messages), 1, formula)
            self.assertIn(part, messages[0])

    def test_a_scope_names_a_defined_entity_within_the_limit(self):
        self.assertEqual(blocking_kinds("module m\nscope Ghost 2\n"), Counter({"UNDEFINED": 1}))
        self.assertEqual(blocking_kinds("module m\nE passive {}\nscope E 9\n"), Counter({"TOO_LARGE": 1}))
        unscoped = SHOP.replace("scope Order 2\n", "")
        self.assertIn("UNDEFINED", blocking_kinds(unscoped))

    def test_the_instance_machine_and_the_quantifier_are_rendered(self):
        module = parse_module(SHOP + GOLD_ONLY + "prop a: always some o in Order: o.Flow = Open\n")
        document = render(module, check(module), "en")
        self.assertIn("- One flow for each: Order", document)
        self.assertIn("In Open when this.dealer.grade is Gold, Finish moves to Done.", document)
        self.assertIn("dealer: Dealer [fixed]", document)
        self.assertIn("- a: `always ∃ o ∈ Order : o.Flow = Open`", document)


PARCEL = """
module m
actor Courier
external Gateway
Flag : {No, Yes}
Parcel key (id) passive { id: Text, paid: Flag var init No }
scope Parcel 2
Flow of Parcel : {Packed, Shipped} init Packed final {Shipped}
Billing of Parcel : {Open, Settled} init Open final {Settled}
Billing.Pay @Gateway {
    Billing = Open => Billing' = Settled & this.paid' = Yes
    else reject
}
Flow.Ship @Courier {
    Flow = Packed & this.paid = Yes => Flow' = Shipped
    else reject
}
prop shipped_is_paid: always all p in Parcel: p.Flow = Shipped => p.paid = Yes
prop stays_paid: always all p in Parcel: p.Billing = Settled => p.paid = Yes
"""


class FieldUpdateTest(unittest.TestCase):
    def findings(self, text: str) -> list[tuple[str, str]]:
        return [(f.kind, f.message) for f in check(syntax.parse_module(text)) if f.blocking]

    def test_a_var_field_keeps_the_value_that_a_clause_sets(self):
        self.assertEqual(self.findings(PARCEL), [])

    def test_a_var_field_starts_at_its_initial_value(self):
        findings = self.findings(PARCEL.replace("this.paid' = Yes", "this.paid' = No"))
        self.assertEqual([kind for kind, _ in findings], ["UNREACHABLE", "ASSERTION_FAILED"])
        self.assertIn("Parcel1.paid=No", findings[1][1])

    def test_a_field_without_var_still_changes_between_transitions(self):
        findings = self.findings(PARCEL.replace(" var init No", "").replace(" & this.paid' = Yes", ""))
        self.assertEqual([kind for kind, _ in findings], ["ASSERTION_FAILED", "ASSERTION_FAILED"])

    def test_a_clause_sets_only_a_var_field_to_one_of_its_values(self):
        plain = self.findings(PARCEL.replace(" var init No", ""))
        self.assertIn(("UNDEFINED", "this.paid is not a var field, so a clause cannot set it"), plain)
        wrong = self.findings(PARCEL.replace("this.paid' = Yes", "this.paid' = Maybe"))
        self.assertIn(("UNDEFINED", "Maybe is not a value of this.paid"), wrong)
        start = self.findings(PARCEL.replace("init No", "init Maybe"))
        self.assertIn(("UNDEFINED", "initial value Maybe is not a value of Parcel.paid"), start)

    def test_clauses_that_set_a_field_differently_contradict(self):
        text = PARCEL.replace("    else reject\n}\nFlow.Ship", "    Billing = Open => Billing' = Settled\n}\nFlow.Ship")
        self.assertIn(("CONTRADICTION", "Open on Pay changes the fields in different ways"), self.findings(text))

    def test_the_solver_agrees_with_enumeration(self):
        broken = PARCEL.replace("this.paid' = Yes", "this.paid' = No")
        with mock.patch("pdl.checks.SYSTEM_LIMIT", 0):
            self.assertEqual(self.findings(PARCEL)[1:], [])
            solved = self.findings(broken)[1:]
        self.assertEqual(solved, self.findings(broken))

    def test_a_run_applies_the_update(self):
        run = "run paid: Billing = Open -> Pay -> Billing = Settled\n"
        self.assertEqual(self.findings(PARCEL + run), [])

    def test_the_module_is_written_back_and_rendered(self):
        module = syntax.parse_module(PARCEL)
        text = to_text(module)
        self.assertIn("paid: Flag var init No", text)
        self.assertIn("Billing = Open => Billing' = Settled & this.paid' = Yes", text)
        self.assertEqual(to_text(syntax.parse_module(text)), text)
        document = render(module, check(module), "en")
        self.assertIn("Pay moves to Settled. (actor: Gateway) (sets: Flag = Yes)", document)
        self.assertIn("paid: Flag [starts as: No]", document)


SHORTHANDS = PARCEL.replace("this.paid = Yes", "is_paid(this)") + (
    "pred is_paid(p): p.paid = Yes\n"
    "pred settled(p): bill(p) = Settled & is_paid(p)\n"
    "fun bill(p): p.Billing\n"
    "prop named: always all q in Parcel: q.Flow = Shipped => settled(q)\n"
)


class ShorthandTest(unittest.TestCase):
    def error(self, text: str) -> str:
        with self.assertRaises(PdlSyntaxError) as raised:
            syntax.parse_module(text)
        return str(raised.exception)

    def test_a_pred_and_a_fun_stand_for_their_bodies(self):
        module = syntax.parse_module(SHORTHANDS)
        self.assertEqual([f for f in check(module) if f.blocking], [])
        named = module.assertions[-1].formula
        plain = syntax.parse_module(
            PARCEL + "prop named: always all q in Parcel: q.Flow = Shipped => q.Billing = Settled & q.paid = Yes\n"
        )
        self.assertEqual(named, plain.assertions[-1].formula)
        self.assertEqual(module.machines[0].transitions[0].conditions, plain.machines[0].transitions[0].conditions)

    def test_a_pred_that_fails_is_reported_through_the_property_that_uses_it(self):
        text = SHORTHANDS.replace("this.paid' = Yes", "this.paid' = No")
        kinds = [f.kind for f in check(syntax.parse_module(text)) if f.blocking]
        self.assertEqual(kinds, ["UNREACHABLE", "ASSERTION_FAILED"])

    def test_a_pred_without_parameters_names_a_condition(self):
        text = SHORTHANDS + "pred first_paid(): is_paid(Parcel1)\nprop first: reachable first_paid()\n"
        self.assertEqual([f for f in check(syntax.parse_module(text)) if f.blocking], [])

    def test_a_definition_cannot_use_itself(self):
        text = SHORTHANDS + "pred a(p): b(p)\npred b(p): a(p)\n"
        self.assertIn("a is defined in terms of itself", self.error(text))

    def test_the_number_and_the_kind_of_a_use_are_checked(self):
        self.assertIn("is_paid takes 1 arguments but is given 2", self.error(SHORTHANDS + "inv i: is_paid(Parcel1, Parcel2)\n"))
        self.assertIn("is_paid is a pred", self.error(SHORTHANDS + "inv i: Parcel1.paid = is_paid(Parcel1)\n"))

    def test_an_argument_is_not_captured_by_a_quantifier_of_the_definition(self):
        text = SHORTHANDS + "pred alone(p): all q in Parcel: q.Flow = Packed | is_paid(p)\nprop c: always all q in Parcel: alone(q)\n"
        self.assertIn("q is bound in a definition that is also given q", self.error(text))

    def test_definitions_are_written_back_and_listed(self):
        module = syntax.parse_module(SHORTHANDS)
        text = to_text(module)
        self.assertIn("pred settled(p): p.Billing = Settled & p.paid = Yes", text)
        self.assertIn("fun bill(p): p.Billing", text)
        self.assertEqual(to_text(syntax.parse_module(text)), text)
        self.assertIn("- is_paid(p): `p.paid = Yes`", render(module, check(module)))


RETRY = """
module m
actor Clerk
external Bank
Transfer : {Draft, Sent, Failed, Done} init Draft final {Done}
Transfer.Send @Clerk {
    Transfer in {Draft, Failed} => Transfer' = Sent
    else reject
}
Transfer.Settle @Bank {
    Transfer = Sent => Transfer' = Done
    else reject
}
Transfer.Bounce @Bank {
    Transfer = Sent => Transfer' = Failed
    else reject
}
"""


class LivenessTest(unittest.TestCase):
    def failures(self, text: str) -> list[str]:
        return [f.message for f in check(syntax.parse_module(text)) if f.kind == "ASSERTION_FAILED"]

    def test_nothing_has_to_happen_without_a_fair_event(self):
        failures = self.failures(RETRY + "prop done: eventually Transfer = Done\n")
        self.assertEqual(
            failures, ["assertion done fails at the start (Transfer=Draft), because nothing has to happen in Transfer=Draft"]
        )

    def test_a_fair_event_is_taken_while_it_stays_enabled(self):
        text = RETRY + "fair Transfer.Send\nprop sent: eventually Transfer = Sent\n"
        self.assertEqual(self.failures(text), [])

    def test_a_loop_that_takes_every_fair_event_can_repeat_forever(self):
        text = RETRY + "fair Transfer.Send\nfair Transfer.Settle\nfair Transfer.Bounce\nprop done: eventually Transfer = Done\n"
        self.assertEqual(
            self.failures(text),
            [
                "assertion done fails at the start (Transfer=Draft),"
                " because Transfer: Bounce, Transfer: Send can repeat forever after Transfer: Send"
            ],
        )

    def test_a_fair_event_leaves_a_loop_that_never_takes_it(self):
        text = RETRY.replace("Transfer' = Failed", "Transfer' = Sent") + "fair Transfer.Send\nfair Transfer.Settle\n"
        self.assertEqual(self.failures(text + "prop done: eventually Transfer = Done\n"), [])

    def test_eventually_answers_inside_always(self):
        text = RETRY + "fair Transfer.Send\nprop again: always Transfer = Failed => eventually Transfer = Sent\n"
        self.assertEqual(self.failures(text), [])
        failures = self.failures(text.replace("fair Transfer.Send\n", ""))
        self.assertEqual(len(failures), 1)
        self.assertIn("fails after: Transfer: Send -> Transfer: Bounce (Transfer=Failed), because nothing has to happen", failures[0])

    def test_a_fair_event_names_an_event_whose_guard_reads_no_free_value(self):
        text = RETRY.replace("Transfer in {Draft, Failed} =>", "Transfer in {Draft, Failed} & Window = Open =>")
        text += "Window : {Open, Shut}\nfair Transfer.Send\nfair Transfer.Cancel\nfair Other.Send\n"
        text += "prop done: reachable Transfer = Done\n"
        messages = [f.message for f in check(syntax.parse_module(text)) if f.kind == "UNDEFINED"]
        self.assertEqual(
            messages,
            [
                "fair Transfer.Send reads Window, which changes freely, so nothing makes the event happen",
                "event Cancel of fair is not an event of Transfer",
                "machine Other of fair is not defined",
            ],
        )

    def test_eventually_needs_the_enumerated_state_space(self):
        with mock.patch("pdl.checks.SYSTEM_LIMIT", 0):
            findings = check(syntax.parse_module(RETRY + "prop done: eventually Transfer = Done\n"))
        self.assertIn("assertion done uses eventually, which needs the enumerated state space", [f.message for f in findings])

    def test_eventually_belongs_to_a_property(self):
        with self.assertRaises(PdlSyntaxError):
            syntax.parse_module(RETRY + "inv i: eventually Transfer = Done\n")

    def test_fairness_and_eventually_are_written_back_and_rendered(self):
        module = syntax.parse_module(RETRY + "fair Transfer.Send\nprop sent: eventually Transfer = Sent\n")
        text = to_text(module)
        self.assertIn("fair Transfer.Send\nprop sent: eventually (Transfer = Sent)", text)
        self.assertEqual(to_text(syntax.parse_module(text)), text)
        document = render(module, check(module), "en")
        self.assertIn("## Events assumed to happen while they stay possible\n\n- Transfer: Send", document)
        self.assertIn("- sent: `eventually (Transfer = Sent)`", document)


LOGIN = (
    "module m\nexternal Sys\nconst limit : 1..4\n"
    "Login : {Active, Locked} init Active final {Locked}\nLogin.Tries : 0..limit\n"
    "Login.Fail @Sys {\nLogin = Active & Tries < limit => Tries' = Tries + 1\n"
    "Login = Active & Tries = limit => Login' = Locked\nLogin = Locked => reject\n}\n"
)


class ConstantTest(unittest.TestCase):
    def failures(self, text: str) -> list[str]:
        return [f.message for f in check(parse_module(text)) if f.kind == "ASSERTION_FAILED"]

    def test_a_plan_is_checked_for_every_value_of_a_constant(self):
        self.assertEqual(blocking_kinds(LOGIN + "prop a: always Login = Locked => Tries = limit\n"), Counter())
        failures = self.failures(LOGIN + "prop a: always Tries >= 2 => Login = Locked\n")
        self.assertEqual(failures, ["assertion a fails after: Login: Fail -> Login: Fail with limit=2 (Login=Active, Tries=2, limit=2)"])

    def test_a_guard_that_misses_a_value_of_the_constant_is_uncovered(self):
        text = LOGIN.replace("Tries = limit =>", "Tries = 4 =>")
        self.assertIn("UNCOVERED", blocking_kinds(text))

    def test_a_counter_cannot_pass_the_constant(self):
        text = LOGIN.replace("Tries < limit =>", "Tries <= limit =>").replace("Tries = limit =>", "Tries > limit =>")
        self.assertEqual(blocking_kinds(text)["OVERFLOW"], 1)

    def test_a_scenario_gives_the_constant_a_value(self):
        text = LOGIN + "run s: Login = Active & limit = 2 -> Fail, Fail, Fail -> Login = Locked\n"
        self.assertEqual(blocking_kinds(text), Counter())
        self.assertEqual(blocking_kinds(text.replace("limit = 2", "limit = 3")), Counter({"SCENARIO_FAILED": 1}))

    def test_an_ordering_needs_numbers(self):
        text = GUARDED.replace("G = On =>", "G < On =>")
        self.assertIn("UNIT_MISMATCH", blocking_kinds(text))

    def test_a_counter_maximum_names_a_constant(self):
        self.assertIn("UNDEFINED", blocking_kinds(LOGIN.replace("Tries : 0..limit", "Tries : 0..nothing")))

    def test_a_constant_carries_the_unknown_it_stands_for(self):
        text = LOGIN.replace("const limit : 1..4", "const limit : 1..4 assuming lock_limit")
        text += 'unknown value lock_limit { label "잠금 횟수" source "회의록" provisional "3회" }\ntext { limit "잠금 횟수" }\n'
        module = parse_module(text)
        findings = check(module)
        self.assertEqual([f.kind for f in findings], ["UNVERIFIED"])
        document = render(module, findings)
        self.assertIn("- 잠금 횟수: 1 ~ 4 (가정: 잠금 횟수)", document)
        self.assertIn("(0 ~ 잠금 횟수)", document)
        self.assertIn("'Active' 상태에서 Tries가 '잠금 횟수'보다 작을 때 'Fail'가 일어나면", document)
        self.assertIn("'Active' 상태에서 Tries가 '잠금 횟수'일 때 'Fail'가 일어나면", document)
        self.assertIn("In Active when Tries is less than limit, Fail moves to Active.", render(module, findings, "en"))


class SolverTest(unittest.TestCase):
    texts = [
        LIBRARY, UNCOVERED_LIBRARY, COVERED_MACHINE, GUARDED, COUNTER_MACHINE, CROSS_MACHINES, GUARDED_IGNORE,
        GUARDED_PAIR, FLAGGED, FREE_PAIR, SHOP, SHOP + GOLD_ONLY, LOGIN,
        GUARDED.replace("G = Off =>", "G in {On, Off} =>"),
        GUARDED.replace("M = A & G = Off => M' = C\n", ""),
        GUARDED_IGNORE.replace("S = Off => ignore", "S in {On, Off} => ignore"),
        "module m\nS : {A, B, C}\nactor X\naction Do\nR {}\npermit X Do R: S in {A, B}\nforbid X Do R: S != A\n",
        "module m\nS : {A, B}\nassume never_a: !(S = A)\ninv i: S = A\n",
        FREE_PAIR + "prop a: always T = Done => P = Ok\nprop r: reachable T = Done & P = Bad\n",
        GUARDED_PAIR + "prop a: always T = Done => P = Ok\nprop r: reachable T = Done & P = Bad\n",
        FLAGGED + "prop a: always M = B => Flag = On\nprop r: reachable M = B & Flag = Off\n",
        SHOP + GOLD_ONLY + "prop a: always some o in Order: o.Flow = Open\nprop b: always all o in Order: o.dealer = Dealer1\n",
        LOGIN + "prop a: always Tries >= 2 => Login = Locked\nprop b: always Login = Locked => Tries = limit\n",
        "module m\nexternal Ext\n"
        "P : {Ok, Bad} init Ok final {Bad}\nP.Fail @Ext {\nP = Ok => P' = Ok\nP = Bad => ignore\n}\n"
        "T : {Open, Done} init Open final {Done}\n"
        "T.Finish @Ext {\nT = Open & P = Bad => T' = Done\nT = Open => ignore\nT = Done => ignore\n}\n",
    ]

    def test_the_solver_agrees_with_enumeration_on_worlds(self):
        for text in self.texts:
            listed = Counter(f.kind for f in check(parse_module(text)) if f.kind in ("CONTRADICTION", "UNCOVERED"))
            with mock.patch("pdl.checks.worlds", side_effect=static_only):
                solved = Counter(f.kind for f in check(parse_module(text)) if f.kind in ("CONTRADICTION", "UNCOVERED"))
            self.assertEqual(solved, listed, text[:60])

    def test_the_solver_agrees_with_enumeration_on_reachability(self):
        for text in self.texts:
            module = parse_module(text)
            plain = {assertion.line for assertion in module.assertions if "can" not in assertion_text(assertion)}

            def compared(findings):
                return sorted(
                    (f.kind, f.line)
                    for f in findings
                    if " over machine states fails after: " in f.message
                    or "is never reached" in f.message
                    or (f.kind == "ASSERTION_FAILED" and f.line in plain)
                )

            listed = compared(check(module))
            with mock.patch("pdl.checks.SYSTEM_LIMIT", 0):
                solved = compared(check(module))
            self.assertEqual(solved, listed, text[:60])

    def test_a_space_too_large_to_enumerate_is_solved(self):
        enums = "".join(f"E{number} : {{A, B, C, D}}\n" for number in range(12))
        every = " & ".join(f"E{number} = A" for number in range(12))
        base = "module m\n" + enums + "actor X\naction Do\nR {}\n"
        gap = [f for f in check(parse_module(base + f"permit X Do R: {every}\n")) if f.blocking]
        self.assertEqual([f.kind for f in gap], ["UNCOVERED"])
        self.assertIn("E0=A, E1=A, E10=A, E11=A, E2=A, E3=A, E4=A, E5=A, E6=A, E7=A, E8=A, E9=B", gap[0].message)
        clash = base + f"permit X Do R: {every}\nforbid X Do R: E0 = A\nforbid X Do R: E0 != A\n"
        self.assertEqual(blocking_kinds(clash), Counter({"CONTRADICTION": 1}))
        covered = base + "permit X Do R: E0 = A\nforbid X Do R: E0 != A\n"
        self.assertEqual(blocking_kinds(covered), Counter())

    def test_an_undecided_query_is_too_large_and_never_a_pass_or_a_contradiction(self):
        cases = (
            (GUARDED.replace("M = A & G = Off => M' = C\n", ""), "pdl.checks.worlds"),
            ("module m\nS : {A, B}\nactor X\naction Do\nR {}\npermit X Do R: S = A\n", "pdl.checks.worlds"),
            ("module m\nS : {A, B}\ninv i: S = A\n", "pdl.checks.ENUMERATION_LIMIT"),
            ("module m\nX { d: Day\ne: Day }\nlaw a: X.d < X.e\nlaw b: X.e < X.d\n", None),
        )
        for text, enumeration in cases:
            with contextlib.ExitStack() as stack:
                if enumeration == "pdl.checks.worlds":
                    stack.enter_context(mock.patch(enumeration, side_effect=static_only))
                elif enumeration:
                    stack.enter_context(mock.patch(enumeration, 0))
                stack.enter_context(mock.patch("pdl.solver.z3.Solver.check", return_value=z3.unknown))
                kinds = Counter(f.kind for f in check(parse_module(text)) if f.blocking)
            self.assertIn("TOO_LARGE", kinds, text)
            self.assertNotIn("CONTRADICTION", kinds, text)

    def test_laws_that_cannot_hold_together_contradict(self):
        base = "module m\nX { d: Day\ne: Day\nf: Day }\n"
        clash = base + "law a: X.d < X.e\nlaw free: X.f < next(X.f)\nlaw b: X.e < X.d\n"
        findings = [f for f in check(parse_module(clash)) if f.blocking]
        self.assertEqual([f.message for f in findings], ["the laws a, b cannot hold together"])
        self.assertEqual(blocking_kinds(base + "law a: X.d < X.e\nlaw b: X.e < next(X.e)\n"), Counter())
        self.assertEqual(blocking_kinds(base + "law a: X.d < before(X.d)\n"), Counter({"CONTRADICTION": 1}))
        months = base + "law a: month_of(X.d) < month_of(X.e)\nlaw b: X.e <= X.d\n"
        self.assertEqual(blocking_kinds(months), Counter({"CONTRADICTION": 1}))


def static_only(index, variables):
    return None


def assertion_text(assertion) -> str:
    from pdl.prose import formula_text

    return formula_text(assertion.formula)


BOOKING = """
module booking

actor Customer, Staff
external Gateway

Booking : {Requested, Confirmed, Cancelled} init Requested final {Confirmed, Cancelled}
Payment : {Unpaid, Paid, Refunded, Void} init Unpaid final {Paid, Refunded, Void}

Booking.Confirm @Staff {
    Booking = Requested & Payment = Paid => Booking' = Confirmed
    else reject as unpaid
}
Booking.Cancel @Customer {
    Booking in {Requested, Confirmed} => Booking' = Cancelled
    else reject
}
Payment.Pay @Gateway {
    Payment = Unpaid & Booking = Requested => Payment' = Paid
    else reject
}
Payment.Refund @Staff {
    Payment = Paid & Booking = Cancelled => Payment' = Refunded
    else reject
}
Payment.Close @Staff {
    Payment = Unpaid & Booking = Cancelled => Payment' = Void
    else reject
}

inv confirmed_is_paid: Booking = Confirmed => Payment = Paid
prop refund_is_possible: always Booking = Cancelled & Payment = Paid => can Payment = Refunded
run pay_then_cancel: Booking = Requested & Payment = Unpaid
    -> Payment.Pay, Booking.Confirm, Booking.Cancel, Payment.Refund
    -> Booking = Cancelled & Payment = Refunded

text {
    module "예약과 결제"
    Booking "예약"
    Booking.Requested "요청됨"
    Booking.Confirm "확정"
    Booking.Confirm.unpaid why "결제 전에는 확정하지 않는다."
    Staff "직원"
    confirmed_is_paid why "확정된 예약은 결제가 끝난 예약이다."
}
"""


class SyntaxTest(unittest.TestCase):
    def kinds(self, text: str) -> Counter:
        return Counter(f.kind for f in check(syntax.parse_module(text)) if f.blocking)

    def test_a_module_of_relations_builds(self):
        self.assertEqual(self.kinds(BOOKING), Counter())

    def test_a_missing_guard_breaks_the_invariant(self):
        text = BOOKING.replace("Booking = Requested & Payment = Paid =>", "Booking = Requested =>")
        self.assertEqual(self.kinds(text)["INVARIANT_VIOLATED"], 1)

    def test_else_covers_the_states_that_no_clause_names(self):
        text = BOOKING.replace("    Payment = Paid & Booking = Cancelled => Payment' = Refunded\n    else reject", "    Payment = Paid & Booking = Cancelled => Payment' = Refunded")
        counts = self.kinds(text)
        self.assertEqual(counts["UNHANDLED"], 3)
        self.assertEqual(counts["UNCOVERED"], 1)

    def test_a_clause_names_its_source_states_as_a_set(self):
        module = syntax.parse_module(BOOKING)
        cancel = [(t.source, t.target) for t in module.machines[0].transitions if t.event == "Cancel"]
        self.assertEqual(cancel, [("Requested", "Cancelled"), ("Confirmed", "Cancelled")])
        other = syntax.parse_module(BOOKING.replace("Booking in {Requested, Confirmed} =>", "Booking != Cancelled =>"))
        self.assertEqual([(t.source, t.target) for t in other.machines[0].transitions if t.event == "Cancel"], cancel)

    def test_a_counter_is_updated_through_its_next_value(self):
        text = (
            "module m\nexternal Sys\nconst limit : 1..3\n"
            "Login : {Active, Locked} init Active final {Locked}\nLogin.Tries : 0..limit\n"
            "Login.Fail @Sys {\n  Login = Active & Tries < limit => Tries' = Tries + 1\n"
            "  Login = Active & Tries = limit => Login' = Locked & Tries' = 0\n  else reject\n}\n"
            "prop a: always Login = Locked => Tries = 0\n"
            "run two: Login = Active & limit = 1 -> Fail, Fail -> Login = Locked\n"
        )
        self.assertEqual(self.kinds(text), Counter())
        with self.assertRaises(PdlSyntaxError):
            syntax.parse_module(text.replace("Tries' = Tries + 1", "Tries' = limit"))

    def test_the_text_block_supplies_the_document_wording(self):
        module = syntax.parse_module(BOOKING)
        document = render(module, check(module))
        self.assertIn("# 예약과 결제", document)
        self.assertIn("## 업무 흐름: 예약", document)
        self.assertIn("'요청됨' 상태에서 Payment가 'Paid'일 때 '확정'이 일어나면 'Confirmed' 상태가 된다. (주체: 직원)", document)
        self.assertIn("근거: 결제 전에는 확정하지 않는다.", document)
        with self.assertRaises(PdlSyntaxError) as raised:
            syntax.parse_module(BOOKING.replace('Staff "직원"', 'Stuff "직원"'))
        self.assertIn("Stuff, which is not defined", str(raised.exception))
        with self.assertRaises(PdlSyntaxError) as raised:
            syntax.parse_module(BOOKING.replace("confirmed_is_paid why", 'confirmed_is_paid "확정" why'))
        self.assertIn("gives confirmed_is_paid a label, which it does not take", str(raised.exception))

    def test_symbols_are_aliases_of_the_operators(self):
        text = BOOKING.replace(" & ", " ∧ ").replace(" => ", " ⇒ ").replace(" in {", " ∈ {").replace("->", "→")
        self.assertEqual(self.kinds(text), Counter())
        quantified = "module m\nS : {A, B}\nassume a: ∀ v ∈ S: ¬(S = v) ∨ S ≠ B\nprop p: always (some v in S: S = v)\n"
        self.assertEqual(self.kinds(quantified), Counter())

    def test_the_keyword_syntax_is_rejected(self):
        for text, line in (("module m\nenum S = A | B\n", 2), ("module m\nS : {A}\ninvariant i: S = A\n", 3)):
            with self.assertRaises(PdlSyntaxError) as raised:
                syntax.parse_module(text)
            self.assertEqual(raised.exception.line, line)
        with self.assertRaises(PdlSyntaxError):
            syntax.parse_module("module m\nS : {A, B}\nassume a: S = A and S = B\n")

    def test_a_run_is_single_or_joint(self):
        single = BOOKING + "run cancel: Booking = Requested -> Cancel -> Booking = Cancelled\n"
        self.assertEqual(self.kinds(single), Counter())
        wrong = BOOKING + "run cancel: Booking = Requested -> Cancel -> Booking = Confirmed\n"
        self.assertEqual(self.kinds(wrong), Counter({"SCENARIO_FAILED": 1}))
        with self.assertRaises(PdlSyntaxError):
            syntax.parse_module(BOOKING + "run bad: Booking = Requested -> Cancel, Payment.Pay -> Booking = Cancelled\n")

    def test_an_event_names_a_defined_machine(self):
        with self.assertRaises(PdlSyntaxError):
            syntax.parse_module("module m\nGhost.Go { else reject }\n")

    def test_an_import_reads_the_current_syntax(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "common.pdl").write_text('module common\nS : {On, Off}\nactor X\ntext { S "스위치" }\n', encoding="utf-8")
            text = 'module m\nimport "common.pdl"\naction Do\nR {}\npermit X Do R: S = On\nforbid X Do R: S = Off\n'
            module = syntax.parse_module(text, root / "m.pdl")
            self.assertEqual([f for f in check(module) if f.blocking], [])
            self.assertEqual(module.enums[0].label, "스위치")

    def test_a_computed_value_names_its_type_and_its_sources(self):
        base = (
            "module m\nBill passive { month: Month }\nLine passive { bill: Bill, amount: Money }\n"
            "Other passive { amount: Money }\n"
        )
        good = base + "derive Total of Bill : Money from Line.amount, Line\nscreen Bills of Bill shows Total, Bill.month\n"
        good += 'text { Total "총금액" Bill "청구서" Line "청구 행" Line.amount "금액" }\n'
        self.assertEqual(self.kinds(good), Counter())
        module = syntax.parse_module(good)
        self.assertIn("- 총금액은 청구서의 계산값(Money)이며 청구 행의 금액, 청구 행에서 계산한다.", render(module, check(module)))
        self.assertIn("- Total of Bill is a computed Money from Line.amount, Line.", render(module, check(module), "en"))
        for statement, part in (
            ("derive Total of Bill : Money from Other.amount", "is not linked to Bill"),
            ("derive Total of Bill : Money from Line.missing", "is not a field"),
            ("derive Total of Bill : Money from Ghost", "is not an entity, a field, or a computed value"),
            ("derive Total of Bill : Cash from Line.amount", "type Cash of Total is not defined"),
            ("derive Total of Bill : Money from Net\nderive Net of Bill : Money from Total", "is computed from itself"),
        ):
            messages = [f.message for f in check(syntax.parse_module(base + statement + "\n")) if f.kind == "UNDEFINED"]
            self.assertTrue(any(part in message for message in messages), statement)
        self.assertEqual(to_text(module), to_text(syntax.parse_module(to_text(module))))


class ReferenceTest(unittest.TestCase):
    def test_the_reference_command_prints_the_packaged_reference(self):
        import contextlib
        import io

        from pdl.cli import main
        from pdl.reference import reference

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["reference"]), 0)
        self.assertEqual(output.getvalue(), reference())

    def test_the_complete_example_of_the_reference_builds_clean(self):
        from pdl.reference import reference

        example = reference().split("## Complete example", 1)[1].split("```", 2)[1]
        findings = check(syntax.parse_module(example))
        self.assertEqual([f for f in findings if f.blocking], [])


class ConsistencyTest(unittest.TestCase):
    def kinds(self, *texts: str) -> Counter:
        modules = [(Path(f"m{number}.pdl"), parse_module(text)) for number, text in enumerate(texts)]
        return Counter((f.kind, f.blocking) for f in compare(modules))

    def test_modules_that_agree_or_list_other_slices_pass(self):
        first = "module a\nDoc key (id) {\nid: Text\ntitle: Text\n}\nS : {On, Off}\n"
        second = "module b\nDoc key (id) {\nid: Text\nauthor: Text\n}\nS : {Off, On}\n"
        self.assertEqual(self.kinds(first, second), Counter())

    def test_enum_values_that_differ_are_a_conflict(self):
        self.assertEqual(
            self.kinds("module a\nS : {On, Off}\n", "module b\nS : {On, Off, Hold}\n"),
            Counter({("INCONSISTENT", True): 1}),
        )

    def test_a_field_type_or_key_that_differs_is_a_conflict(self):
        base = "module a\nDoc key (id) {\nid: Text\ntitle: Text\n}\n"
        other_type = "module b\nDoc key (id) {\nid: Text\ntitle: Day\n}\n"
        other_key = "module b\nDoc key (title) {\nid: Text\ntitle: Text\n}\n"
        self.assertEqual(self.kinds(base, other_type), Counter({("INCONSISTENT", True): 1}))
        self.assertEqual(self.kinds(base, other_key), Counter({("INCONSISTENT", True): 1}))

    def test_one_name_in_two_categories_is_a_conflict_unless_one_is_a_term(self):
        entity = "module a\nDoc key (id) {\nid: Text\n}\n"
        self.assertEqual(self.kinds(entity, "module b\nDoc : {On, Off}\n"), Counter({("INCONSISTENT", True): 1}))
        self.assertEqual(self.kinds(entity, "module b\nterm Doc\n"), Counter())
        self.assertEqual(self.kinds("module b\nterm Doc\n", entity), Counter())

    def test_a_label_that_differs_is_only_a_note(self):
        self.assertEqual(
            self.kinds('module a\nS : {On, Off}\ntext { S "상태" }\n', 'module b\nS : {On, Off}\ntext { S "현황" }\n'),
            Counter({("LABEL_DIFFERS", False): 1}),
        )

    def test_the_command_reads_a_directory(self):
        import tempfile
        from contextlib import redirect_stdout
        from io import StringIO

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.pdl").write_text("module a\nS : {On, Off}\n", encoding="utf-8")
            (root / "b.pdl").write_text("module b\nS : {On}\n", encoding="utf-8")
            with redirect_stdout(StringIO()) as output:
                clean = check_consistency([root])
            self.assertFalse(clean)
            self.assertIn("INCONSISTENT", output.getvalue())
            self.assertIn("2 modules compared, 1 inconsistencies", output.getvalue())


class RenderTest(unittest.TestCase):
    def render_library(self, language: str = "ko") -> str:
        module = parse_module(LIBRARY)
        return render(module, check(module), language)

    def test_the_library_fixture_builds_without_a_blocking_finding(self):
        self.assertEqual(blocking_kinds(LIBRARY), Counter())

    def test_permission_matrix_and_rationale_are_rendered(self):
        document = self.render_library()
        self.assertIn("## 권한 규칙", document)
        self.assertIn("- 사서: 대출 기록 기록 수정 조건부(대출 상태), 대출 기록 연장 허용, 대출 기록 대출 처리 조건부(창구 상태)", document)
        self.assertIn("- 이용자 계정: 대출 기록 연장 조건부(대출 상태)", document)
        self.assertIn("  - 근거: 분실 처리한 기록은 고칠 수 없다.", document)
        self.assertIn("# 도서관 대출 규칙", document)
        self.assertLess(document.index("## 권한 규칙"), document.index("## 부록"))
        self.assertLess(document.index("### 권한 요약"), len(document))

    def test_assumptions_are_marked_on_the_lines_that_depend_on_them(self):
        document = self.render_library()
        self.assertEqual(document.count("(가정: 연장 횟수 제한)"), 1)
        self.assertIn("(가정: 기록을 고치는 주체)", document)
        self.assertIn("(미결 있음: 월 점검을 시작하는 주체)", document)
        self.assertNotIn("(가정: 월 점검을 시작하는 주체)", document)
        self.assertIn(
            "- 대출 상태가 '대출 중'일 때, 이용자 계정은 대출 기록을 연장할 수 있다. (가정: 연장 횟수 제한)",
            document,
        )

    def test_monthly_flow_is_cyclic_and_runs_per_reader_and_month(self):
        document = self.render_library()
        self.assertIn("점검은 이용자별, 월별로 따로 진행되며 매달 반복된다.", document)
        self.assertIn("- 끝나지 않고 처음 상태로 돌아가며 반복되는 흐름", document)
        self.assertNotIn("- 끝:", document)
        self.assertNotIn("--> [*]", document)

    def test_assumption_must_name_a_declared_unknown(self):
        text = "module m\nactor X\naction Do\nR {}\npermit X Do R assuming nothing"
        self.assertEqual(blocking_kinds(text), Counter({"UNDEFINED": 1}))

    def test_terms_and_field_notes_are_rendered(self):
        document = self.render_library()
        self.assertIn("- 연장: 회원이 반납 기한을 늦추는 행위다.", document)
        self.assertIn("lent_on (대출일): Day - 책을 빌려 간 날이다.", document)
        self.assertIn("대출 한 건이다. 책 한 권마다 한 건이 생긴다.", document)

    def test_rules_become_korean_sentences_with_the_right_particles(self):
        document = self.render_library()
        self.assertIn("- 창구 상태가 '열림'일 때, 사서는 대출 기록을 대출 처리할 수 있다.", document)
        self.assertIn("- 사서는 대출 기록을 연장할 수 있다.", document)
        self.assertIn("- 대출 상태가 '반납됨'일 때, 이용자 계정은 대출 기록을 연장할 수 없다.", document)
        self.assertIn(
            "- 대출 상태가 '대출 중'일 때, 사서는 대출 기록을 기록 수정할 수 있다. 이때 수정 사유를 입력해야 한다.",
            document,
        )
        self.assertIn("- 대출 상태가 '분실'일 때, 누구도 대출 기록을 기록 수정할 수 없다.", document)

    def test_rules_become_english_sentences(self):
        document = self.render_library("en")
        self.assertIn("- When DeskStatus is Open, Librarian may Lend LoanRecord.", document)
        self.assertIn("- When LoanState is Lost, anyone may not EditRecord LoanRecord.", document)

    def test_time_rule_is_rendered(self):
        document = self.render_library("en")
        self.assertIn("LoanRecord.due_month = next(month_of(LoanRecord.lent_on))", document)

    def test_monthly_workflow_is_rendered_with_labels(self):
        document = self.render_library()
        self.assertIn("## 업무 흐름: 월별 대출 점검", document)
        self.assertIn(
            "- '준비 중' 상태에서 '월 점검 시작'이 일어나면 '점검 중' 상태가 된다. "
            "(주체: 사서) (미결 있음: 월 점검을 시작하는 주체)",
            document,
        )
        self.assertIn("- '마감' 상태에서 '다시 열기'가 일어나면 '준비 중' 상태가 된다. (주체: 서고 시스템)", document)
        self.assertIn("- 위에 적은 경우가 아니면 다음 사건은 받아들이지 않는다: '다시 열기' (가정: 흐름에 적지 않은 사건의 처리)", document)
        self.assertIn("  - 근거: 매달 점검이 시작되면 사서가 기록을 살핀다.", document)
        self.assertIn('    state "마감" as Closed', document)

    def test_mixed_state_is_a_derived_status_and_lists_are_screens(self):
        document = self.render_library()
        self.assertIn("## 상태 판정 규칙", document)
        self.assertIn(
            "- 이용자 상태는 이용자에 속한 대출 기록들의 대출 상태가 모두 같으면 그 값이고, 서로 다르면 '혼합'이다.",
            document,
        )
        self.assertIn("  - 근거: 이용자의 대출 기록마다 상태가 다를 수 있다.", document)
        self.assertIn("## 화면", document)
        self.assertIn("- 대출 목록은 이용자 상태, 목록 구분을 보여 준다.", document)
        self.assertIn("- 대출 상세는 대출 기록의 대출 상태, 대출 기록의 대출일을 보여 준다.", document)
        self.assertNotIn("- 혼합 상태:", document)
        self.assertIn("| 목록 구분 (ListGroup) | Lending (대출), Returning (반납) |", document)

    def test_unverified_assumption_is_listed(self):
        document = self.render_library()
        self.assertIn("## 확인이 필요한 가정", document)
        self.assertIn("| 연장 횟수 제한 | 한 건당 한 번만 연장할 수 있다 | 도서관 규정집 3쪽 |", document)
        self.assertIn("| 월 점검을 시작하는 주체 | 사서가 시작한다 | 운영 회의록 |", document)
        self.assertNotIn("| 기록을 고치는 주체 |", document)

    def test_machine_is_rendered_as_a_diagram(self):
        module = parse_module(COVERED_MACHINE)
        document = render(module, check(module))
        self.assertIn("stateDiagram-v2", document)
        self.assertIn("A --> B: Go (Ext)", document)
        self.assertIn("B --> [*]", document)


if __name__ == "__main__":
    unittest.main()
