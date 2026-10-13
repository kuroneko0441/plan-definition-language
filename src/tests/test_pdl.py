import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from pdl.checks import check
from pdl.cli import check_consistency
from pdl.project import compare
from pdl.render import render
from pdl import legacy, syntax
from pdl.format import to_text
from pdl.syntax import PdlSyntaxError


def modern(text: str, source: Path | None = None) -> str:
    return to_text(legacy.parse_module(text, source), imports=False)


def parse_module(text: str, source: Path | None = None):
    return syntax.parse_module(modern(text, source))

LIBRARY = """
module library label "도서관 대출 규칙"

term Renewal label "연장" why "회원이 반납 기한을 늦추는 행위다."
entity EditReason label "수정 사유" key (text) passive {
    text: Text label "사유 문구"
}
    why "대출 기록을 고친 이유이며 기록마다 남긴다."

enum LoanState label "대출 상태" = Active "대출 중" | Returned "반납됨" | Lost "분실"
    why "대출 한 건이 가질 수 있는 상태다."
enum ListGroup label "목록 구분" = Lending "대출" | Returning "반납"
    why "대출 목록을 가르는 화면의 구분이다."
enum DeskStatus label "창구 상태" = Open "열림" | Closed "닫힘"
    why "사서가 창구를 열었는지를 나타낸다."

entity Reader label "이용자" key (card) passive {
    card: Text label "회원증 번호"
}
    why "도서관에 등록한 사람이다."

entity LoanRecord label "대출 기록" key (id) {
    id: Text label "식별자"
    reader: Reader label "이용자"
    state: LoanState label "대출 상태"
    lent_on: Day label "대출일" why "책을 빌려 간 날이다."
    due_month: Month label "반납월"
    returned_on: Day? label "반납일"
}
    why "대출 한 건이다. 책 한 권마다 한 건이 생긴다."

derive ReaderStanding label "이용자 상태" of Reader from LoanState mixed Mixed "혼합"
    why "이용자의 대출 기록마다 상태가 다를 수 있다."

screen LoanList label "대출 목록" of LoanRecord shows ReaderStanding, ListGroup
    why "목록에서 이용자별 상태를 한눈에 본다."
screen LoanDetail label "대출 상세" of LoanRecord shows LoanRecord.state, LoanRecord.lent_on

actor Librarian label "사서", Member label "이용자 계정"
external Archive label "서고 시스템"

action Lend label "대출 처리" by (Librarian) on (LoanRecord),
    Extend label "연장" by (Member, Librarian) on (LoanRecord),
    EditRecord label "기록 수정" by (Librarian) on (LoanRecord)

permit Librarian Lend LoanRecord when DeskStatus = Open
    why "창구가 열려 있을 때만 대출을 처리한다."
forbid Librarian Lend LoanRecord when DeskStatus = Closed
    why "창구가 닫히면 대출을 처리하지 않는다."
permit Member Extend LoanRecord when LoanState = Active assuming renewal_limit
    why "대출 중인 책만 연장할 수 있다."
forbid Member Extend LoanRecord when LoanState = Returned
    why "반납한 책은 연장할 수 없다."
forbid Member Extend LoanRecord when LoanState = Lost
    why "분실한 책은 연장할 수 없다."
permit Librarian Extend LoanRecord
    why "사서는 상태와 무관하게 연장을 처리한다."
permit Librarian EditRecord LoanRecord when LoanState = Active requires EditReason
    why "대출 중인 기록은 사유를 남기고 고친다."
permit Librarian EditRecord LoanRecord when LoanState = Returned requires EditReason assuming editing_actor
    why "반납한 기록도 사유를 남기고 고친다."
forbid * EditRecord LoanRecord when LoanState = Lost
    why "분실 처리한 기록은 고칠 수 없다."

law due_after_lent: LoanRecord.due_month = next(month_of(LoanRecord.lent_on))
    why "반납월은 대출일의 다음 달이다."

machine MonthlyReview label "월별 대출 점검"
    why "점검은 이용자별, 월별로 따로 진행되며 매달 반복된다." {
    states Preparing "준비 중", Reviewing "점검 중", Closed "마감"
    initial Preparing
    cyclic
    event BeginMonth "월 점검 시작", Finish "점검 마감", Reopen "다시 열기"

    Preparing -> Reviewing on BeginMonth by Librarian assuming month_starter
        why "매달 점검이 시작되면 사서가 기록을 살핀다."
    Reviewing -> Closed on Finish by Librarian
    Closed -> Preparing on Reopen by Archive

    ignore Preparing on Finish
    ignore Reviewing on BeginMonth
    ignore Closed on BeginMonth
    reject * on Reopen assuming unlisted_events
    reject Closed on Finish
}

unknown value renewal_limit {
    label "연장 횟수 제한"
    source "도서관 규정집 3쪽"
    provisional "한 건당 한 번만 연장할 수 있다"
}

unknown value editing_actor {
    label "기록을 고치는 주체"
    source "도서관 규정집 5쪽"
    provisional "사서가 고친다"
    verified yes
}

unknown value unlisted_events {
    label "흐름에 적지 않은 사건의 처리"
    source "운영 회의록"
    provisional "적지 않은 사건은 일어나지 않는 것으로 본다"
}

unknown value month_starter {
    label "월 점검을 시작하는 주체"
    source "운영 회의록"
    provisional "사서가 시작한다"
    open yes
}
"""

UNCOVERED_LIBRARY = """
module small_library
actor Librarian
action Lend by (Librarian) on (LoanRecord)
enum LoanState = Active | Returned
entity LoanRecord key (id) {
    id: Text
    state: LoanState
}
permit Librarian Lend LoanRecord when LoanState = Active
"""


def blocking_kinds(text: str) -> Counter:
    return Counter(finding.kind for finding in check(parse_module(text)) if finding.blocking)


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
            root = TempPath(directory)
            source = root / "small_library.pdl"
            source.write_text(modern(UNCOVERED_LIBRARY), encoding="utf-8")
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
                source.write_text(modern(text), encoding="utf-8")
                build_file(source, root / "build", "ko", draft=True)


COUNTER_MACHINE = (
    "module m\nexternal Ext\n"
    "machine M { counter Streak max 2\nstates A, B\ninitial A\nterminal B\nevent Loss, Win\n"
    "A -> A on Loss when Streak in {0, 1} then Streak + 1 by Ext\n"
    "A -> B on Loss when Streak = 2 by Ext\n"
    "A -> A on Win then Streak = 0 by Ext\n"
    "ignore B on Loss\nignore B on Win }\n"
    "scenario three_losses on M { start A events Loss, Loss, Loss expect B }\n"
)

CROSS_MACHINES = (
    "module m\nexternal Ext\n"
    "machine P { states Ok, Bad\ninitial Ok\nterminal Bad\nevent Fail\nOk -> Bad on Fail by Ext\nignore Bad on Fail }\n"
    "machine T { states Open, Done\ninitial Open\nterminal Done\nevent Finish\n"
    "Open -> Done on Finish by Ext\nignore Done on Finish }\n"
    "invariant done_needs_ok: T = Done => P = Ok\n"
)


class CapabilityTest(unittest.TestCase):
    def test_stored_texts_must_be_unique_within_an_enum(self):
        ok = 'module m\nenum A = X "엑스" stored "엑스값" | Y stored "와이값"'
        self.assertEqual(blocking_kinds(ok), Counter())
        clash = 'module m\nenum A = X stored "같은값" | Y stored "같은값"'
        self.assertEqual(blocking_kinds(clash), Counter({"DUPLICATE": 1}))

    def test_stored_text_is_shown_next_to_the_value(self):
        module = parse_module('module m\nenum A = X "엑스" stored "엑스값" | Y')
        document = render(module, check(module))
        self.assertIn("X (엑스) [저장값: 엑스값], Y", document)

    def test_a_repeated_enum_value_is_reported(self):
        self.assertEqual(blocking_kinds("module m\nenum A = X | X"), Counter({"DUPLICATE": 1}))

    def test_import_brings_in_shared_definitions(self):
        import tempfile
        from pathlib import Path as TempPath

        with tempfile.TemporaryDirectory() as directory:
            root = TempPath(directory)
            (root / "common.pdl").write_text("module common\nenum S = On | Off\nactor X\n", encoding="utf-8")
            text = 'module m\nimport "common.pdl"\naction Do\nentity R\nforbid X Do R when S = Off\npermit X Do R when S = On\n'
            module = parse_module(text, root / "main.pdl")
            self.assertEqual([f for f in check(module) if f.blocking], [])

    def test_a_file_imported_twice_is_merged_once(self):
        import tempfile
        from pathlib import Path as TempPath

        with tempfile.TemporaryDirectory() as directory:
            root = TempPath(directory)
            (root / "d.pdl").write_text("module d\nenum S = On | Off\n", encoding="utf-8")
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
            (root / "common.pdl").write_text("module common\nenum S = On | Off\n", encoding="utf-8")
            module = parse_module('module m\nimport "common.pdl"\nenum S = A | B\n', root / "m.pdl")
            self.assertEqual(Counter(f.kind for f in check(module) if f.blocking), Counter({"DUPLICATE": 1}))

    def test_a_counter_with_matching_guards_passes_and_the_scenario_counts(self):
        self.assertEqual(blocking_kinds(COUNTER_MACHINE), Counter())

    def test_a_counter_guard_gap_is_reported(self):
        text = COUNTER_MACHINE.replace("A -> B on Loss when Streak = 2 by Ext\n", "A -> B on Loss when Streak = 1 by Ext\n")
        counts = blocking_kinds(text)
        self.assertEqual(counts["UNCOVERED"], 1)
        self.assertEqual(counts["CONTRADICTION"], 1)

    def test_a_counter_that_can_exceed_its_maximum_is_reported(self):
        text = (
            "module m\nexternal Ext\nmachine M { counter C max 1\nstates A\ninitial A\nterminal A\nevent Go\n"
            "A -> A on Go then C + 1 by Ext }"
        )
        self.assertEqual(blocking_kinds(text), Counter({"OVERFLOW": 1}))

    def test_effects_must_name_a_counter_and_stay_in_range(self):
        text = COUNTER_MACHINE.replace("then Streak = 0", "then Missing = 0").replace("Streak + 1", "Streak = 9")
        self.assertEqual(blocking_kinds(text)["UNDEFINED"], 2)

    def test_counter_and_time_limit_are_rendered(self):
        text = COUNTER_MACHINE.replace("A -> A on Win then Streak = 0 by Ext", 'A -> A on Win then Streak = 0 by Ext after "60초"')
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
            "Open -> Done on Finish by Ext", "Open -> Done on Finish when P = Ok by Ext\nignore Open on Finish"
        ).replace("Ok -> Bad on Fail by Ext\nignore Bad", "Ok -> Bad on Fail when T = Open by Ext\nignore Ok on Fail\nignore Bad")
        self.assertEqual(blocking_kinds(text), Counter({"TRAP": 2}))

    def test_a_state_that_a_guard_makes_unreachable_is_reported(self):
        text = (
            "module m\nexternal Ext\n"
            "machine P { states Ok, Bad\ninitial Ok\nterminal Bad\nevent Fail\nOk -> Ok on Fail by Ext\nignore Bad on Fail }\n"
            "machine T { states Open, Done\ninitial Open\nterminal Done\nevent Finish\n"
            "Open -> Done on Finish when P = Bad by Ext\nignore Open on Finish\nignore Done on Finish }\n"
        )
        counts = blocking_kinds(text)
        self.assertEqual(counts["UNREACHABLE"], 2)
        self.assertEqual(counts["TRAP"], 1)


GUARDED_IGNORE = (
    "module m\nexternal Ext\nenum S = On | Off\n"
    "machine M { states A, B\ninitial A\nterminal B\nevent E, F\n"
    "A -> B on E when S = On by Ext\nignore A on E when S = Off\n"
    "A -> B on F by Ext\nignore B on E\nignore B on F }\n"
    "scenario skipped on M { start A given S = Off events E, F expect B }\n"
)


class GuardedHandlingTest(unittest.TestCase):
    def test_a_guarded_ignore_covers_the_other_world(self):
        self.assertEqual(blocking_kinds(GUARDED_IGNORE), Counter())

    def test_a_world_without_transition_or_handling_is_uncovered(self):
        text = GUARDED_IGNORE.replace("enum S = On | Off", "enum S = On | Off | Hold")
        self.assertEqual(blocking_kinds(text), Counter({"UNCOVERED": 1}))

    def test_a_guarded_ignore_that_overlaps_a_transition_is_a_contradiction(self):
        text = GUARDED_IGNORE.replace("ignore A on E when S = Off", "ignore A on E when S in {On, Off}")
        self.assertEqual(blocking_kinds(text), Counter({"CONTRADICTION": 1}))

    def test_a_guarded_ignore_beside_an_unconditional_transition_is_a_contradiction(self):
        text = GUARDED_IGNORE.replace("A -> B on E when S = On by Ext", "A -> B on E by Ext")
        self.assertEqual(blocking_kinds(text), Counter({"CONTRADICTION": 1}))

    def test_a_scenario_skips_an_event_only_in_the_guarded_world(self):
        text = GUARDED_IGNORE.replace("enum S = On | Off", "enum S = On | Off | Hold").replace("given S = Off", "given S = Hold")
        self.assertEqual(blocking_kinds(text), Counter({"UNCOVERED": 1, "SCENARIO_FAILED": 1}))

    def test_the_guard_is_rendered_beside_the_handling(self):
        module = parse_module(GUARDED_IGNORE)
        self.assertIn("'A' + 'E': ignored (when S is Off)", render(module, check(module), "en"))
        self.assertIn("'A' + 'E': 무시한다 (S가 'Off'일 때)", render(module, check(module), "ko"))


GUARDED_PAIR = CROSS_MACHINES.replace(
    "Open -> Done on Finish by Ext", "Open -> Done on Finish when P = Ok by Ext\nignore Open on Finish"
).replace("Ok -> Bad on Fail by Ext\nignore Bad", "Ok -> Bad on Fail when T = Open by Ext\nignore Ok on Fail\nignore Bad")


class JointScenarioTest(unittest.TestCase):
    def kinds(self, scenario: str) -> Counter:
        return blocking_kinds(GUARDED_PAIR + scenario + "\n")

    def test_events_on_two_machines_follow_each_others_guards(self):
        self.assertEqual(self.kinds("scenario s together { start P = Ok, T = Open events P.Fail, T.Finish expect P = Bad, T = Open }"), Counter({"TRAP": 2}))
        self.assertEqual(self.kinds("scenario s together { start P = Ok, T = Open events T.Finish, P.Fail expect P = Ok, T = Done }"), Counter({"TRAP": 2}))

    def test_a_wrong_end_state_fails_the_scenario(self):
        text = "scenario s together { start P = Bad, T = Open events T.Finish expect P = Bad, T = Done }"
        self.assertEqual(self.kinds(text), Counter({"TRAP": 2, "SCENARIO_FAILED": 1}))

    def test_unknown_machines_states_and_events_are_undefined(self):
        self.assertEqual(self.kinds("scenario s together { start Q = Ok events Q.Fail expect Q = Ok }")["UNDEFINED"], 1)
        self.assertEqual(self.kinds("scenario s together { start P = Ok events P.Nope expect P = Ok }")["UNDEFINED"], 1)
        self.assertEqual(self.kinds("scenario s together { start P = Ok events T.Finish expect P = Ok }")["UNDEFINED"], 1)

    def test_the_joint_scenario_is_rendered(self):
        module = parse_module(GUARDED_PAIR + "scenario s together { start P = Ok, T = Open events P.Fail expect P = Bad }\n")
        document = render(module, check(module), "en")
        self.assertIn("- Start: P = Ok, T = Open", document)
        self.assertIn("- Event sequence: P: Fail", document)


FLAGGED = (
    "module m\nexternal Ext\nenum Flag = On | Off\n"
    "machine M { states A, B\ninitial A\nterminal B\nevent Go\n"
    "A -> B on Go when Flag = On by Ext\nreject A on Go\nreject B on Go }\n"
)


class SystemSemanticsTest(unittest.TestCase):
    def test_findings_follow_the_declared_state_order(self):
        text = (
            "module m\nexternal Ext\nenum Flag = On | Off\n"
            "machine M { states S1, S2, S3, S4, S5, S6\ninitial S1\nterminal S6\nevent Go, Ping\n"
            "S1 -> S2 on Go by Ext\nS2 -> S3 on Go by Ext\nS3 -> S4 on Go by Ext\n"
            "S4 -> S5 on Go by Ext\nS5 -> S6 on Go by Ext\nreject S6 on Go\n"
            "ignore * on Ping when Flag = On }\n"
        )
        states = [f.message.split()[0] for f in check(parse_module(text)) if f.kind == "UNCOVERED"]
        self.assertEqual(states, ["S1", "S2", "S3", "S4", "S5", "S6"])

    def test_transitions_that_change_a_counter_differently_contradict(self):
        machine = (
            "module m\nexternal Ext\n"
            "machine M { counter N max 3\nstates A, B\ninitial A\nterminal B\nevent Go, Inc\n"
            "%s\nA -> B on Go by Ext\nreject B on Go\nreject B on Inc }\n"
        )
        guarded = "A -> A on Inc when N = 0 then N + 1 by Ext\nA -> A on Inc when N = 0 then N + 3 by Ext\nreject A on Inc"
        self.assertEqual(blocking_kinds(machine % guarded), Counter({"CONTRADICTION": 1}))
        unguarded = "A -> A on Inc then N = 1 by Ext\nA -> A on Inc then N = 2 by Ext"
        self.assertEqual(blocking_kinds(machine % unguarded), Counter({"CONTRADICTION": 1}))
        same = "A -> A on Inc then N = 1 by Ext\nA -> A on Inc then N = 1 by Ext"
        self.assertEqual(blocking_kinds(machine % same), Counter())

    def test_a_state_that_a_guard_keeps_from_finishing_is_a_trap(self):
        text = (
            "module m\nexternal Ext\n"
            "machine M { counter N max 1\nstates A, B, C\ninitial A\nterminal C\nevent Go, Skip\n"
            "A -> B on Go by Ext\nA -> C on Skip by Ext\nB -> C on Go when N = 1 by Ext\n"
            "reject B on Go\nreject B on Skip\nreject C on Go\nreject C on Skip }\n"
        )
        findings = [f for f in check(parse_module(text)) if f.blocking]
        self.assertEqual([f.kind for f in findings], ["TRAP"])
        self.assertIn("state B of M cannot reach a terminal state", findings[0].message)
        self.assertIn("after: M: Go", findings[0].message)

    def test_a_transition_must_keep_an_invariant_that_reads_an_enum(self):
        findings = [f for f in check(parse_module(FLAGGED + "invariant i: Flag = On => M = A\n")) if f.blocking]
        self.assertEqual([f.kind for f in findings], ["INVARIANT_VIOLATED"])
        self.assertIn("after: M: Go (Flag=On, M=B)", findings[0].message)

    def test_a_guard_that_keeps_the_enum_invariant_passes(self):
        self.assertEqual(blocking_kinds(FLAGGED + "invariant i: M = B => Flag = On\n"), Counter())

    def test_an_invariant_removes_the_enum_values_that_enable_a_transition(self):
        counts = blocking_kinds(FLAGGED + "invariant i: M = A => Flag = Off\n")
        self.assertEqual(counts["UNREACHABLE"], 1)
        self.assertEqual(counts["INVARIANT_VIOLATED"], 0)

    def test_invariants_that_no_enum_value_satisfies_at_the_start_are_reported(self):
        text = FLAGGED + "invariant i: M = A => Flag = On\ninvariant j: M = A => Flag = Off\n"
        messages = [f.message for f in check(parse_module(text)) if f.kind == "INVARIANT_VIOLATED"]
        self.assertEqual(len(messages), 1)
        self.assertIn("at the start", messages[0])


FREE_PAIR = CROSS_MACHINES.replace("invariant done_needs_ok: T = Done => P = Ok\n", "")


class FormulaTest(unittest.TestCase):
    def test_a_rule_condition_takes_a_full_formula(self):
        base = "module m\nenum S = A | B | C\nactor X\naction Do\nentity R\n"
        covered = base + "permit X Do R when S = A or S = B\nforbid X Do R when not (S = A or S = B)\n"
        self.assertEqual(blocking_kinds(covered), Counter())
        gap = base + "permit X Do R when S = A or S = B\n"
        self.assertEqual(blocking_kinds(gap), Counter({"UNCOVERED": 1}))

    def test_a_guard_takes_a_full_formula(self):
        text = GUARDED.replace("enum G = On | Off", "enum G = On | Off | Hold").replace("when G = Off", "when G = Off or G = Hold")
        self.assertEqual(blocking_kinds(text), Counter())
        overlapping = text.replace("when G = On", "when not G = Off")
        self.assertEqual(blocking_kinds(overlapping), Counter({"CONTRADICTION": 1}))

    def test_a_formula_guard_is_rendered_as_a_formula(self):
        module = parse_module(GUARDED.replace("when G = Off", "when G = Off or G = On => G = Off"))
        self.assertIn("when `G = Off ∨ G = On ⇒ G = Off` holds", render(module, check(module), "en"))
        self.assertIn("`G = Off ∨ G = On ⇒ G = Off` 조건이 성립할 때", render(module, check(module), "ko"))

    def test_a_scenario_is_replayed_in_every_given_world(self):
        passing = GUARDED + "scenario s on M { start A given G = On or G = Off events Go, Go expect B }\n"
        findings = [f for f in check(parse_module(passing)) if f.blocking]
        self.assertEqual([f.kind for f in findings], ["SCENARIO_FAILED"])
        self.assertIn("ends in C instead of B when G=Off", findings[0].message)
        empty = GUARDED + "scenario s on M { start A given G = On and G = Off events Go expect B }\n"
        self.assertEqual(blocking_kinds(empty), Counter({"SCENARIO_FAILED": 1}))


class PremiseTest(unittest.TestCase):
    def test_an_assumption_removes_worlds_without_being_checked(self):
        counts = blocking_kinds(FLAGGED + "assume a: Flag = On => M = A\n")
        self.assertEqual(counts["INVARIANT_VIOLATED"], 0)
        self.assertEqual(counts["UNREACHABLE"], 1)

    def test_an_exclusion_over_machine_states_removes_the_joint_state(self):
        counts = blocking_kinds(FREE_PAIR + "exclusive T = Done, P = Bad\n")
        self.assertEqual(counts["INVARIANT_VIOLATED"], 0)
        self.assertEqual(counts["TRAP"], 2)

    def test_assumptions_that_rule_out_the_start_contradict(self):
        findings = [f for f in check(parse_module(FREE_PAIR + "assume a: T = Done\n")) if f.kind == "CONTRADICTION"]
        self.assertEqual(len(findings), 1)
        self.assertIn("rule out the start", findings[0].message)

    def test_an_assumption_is_rendered_with_its_formula(self):
        module = parse_module(FLAGGED + 'assume a: M = B => Flag = On why "The flag stays on."\n')
        document = render(module, check(module), "en")
        self.assertIn("## Premises\n\n- The flag stays on.", document)
        self.assertIn("- a: `M = B ⇒ Flag = On`", document)


class AssertionTest(unittest.TestCase):
    def failures(self, text: str) -> list[str]:
        return [f.message for f in check(parse_module(text)) if f.kind == "ASSERTION_FAILED"]

    def test_always_reports_the_path_to_a_failing_state(self):
        failures = self.failures(FREE_PAIR + "assert a: always T = Done => P = Ok\n")
        self.assertEqual(len(failures), 1)
        self.assertIn("assertion a fails after:", failures[0])
        self.assertIn("(P=Bad, T=Done)", failures[0])

    def test_always_passes_when_guards_keep_it(self):
        self.assertEqual(self.failures(GUARDED_PAIR + "assert a: always T = Done => P = Ok\n"), [])

    def test_always_reads_every_admissible_enum_value(self):
        self.assertEqual(len(self.failures(FLAGGED + "assert a: always M = B => Flag = On\n")), 1)
        kept = FLAGGED + "assume keep: M = B => Flag = On\nassert a: always M = B => Flag = On\n"
        self.assertEqual(self.failures(kept), [])

    def test_reachable_needs_one_state(self):
        self.assertEqual(self.failures(FREE_PAIR + "assert r: reachable T = Done and P = Bad\n"), [])
        failures = self.failures(GUARDED_PAIR + "assert r: reachable T = Done and P = Bad\n")
        self.assertEqual(failures, ["assertion r holds in no reachable state"])

    def test_can_reads_the_states_ahead(self):
        failures = self.failures(GUARDED_PAIR + "assert live: always can T = Done\n")
        self.assertEqual(failures, ["assertion live fails after: P: Fail (P=Bad, T=Open)"])
        self.assertEqual(self.failures(GUARDED_PAIR + "assert live: always P = Ok => can T = Done\n"), [])

    def test_an_assertion_needs_no_machine(self):
        base = "module m\nenum S = A | B\nexclusive S = A, S = A\n"
        self.assertEqual(self.failures(base + "assert a: always S = B\n"), [])
        self.assertEqual(len(self.failures(base + "assert a: reachable S = A\n")), 1)

    def test_an_assertion_names_defined_values(self):
        self.assertEqual(blocking_kinds(FREE_PAIR + "assert a: always T = Gone\n")["UNDEFINED"], 1)

    def test_can_and_the_mode_are_part_of_the_syntax(self):
        with self.assertRaises(PdlSyntaxError):
            parse_module(FREE_PAIR + "invariant i: can T = Done\n")
        with self.assertRaises(PdlSyntaxError):
            parse_module(FREE_PAIR + "assert a: T = Done\n")

    def test_an_assertion_is_rendered_with_its_formula(self):
        module = parse_module(GUARDED_PAIR + 'assert live: always P = Ok => can T = Done why "A good photo lets the task finish."\n')
        document = render(module, check(module), "en")
        self.assertIn("## Verified properties\n\n- A good photo lets the task finish.", document)
        self.assertIn("- live: `always P = Ok ⇒ can (T = Done)`", document)


SHOP = (
    "module m\nexternal Sys\nenum Grade = Gold | Basic\n"
    "entity Dealer key (id) passive { id: Text\ngrade: Grade fixed }\n"
    "entity Order key (id) passive { id: Text\ndealer: Dealer fixed\nbackup: Dealer? }\n"
    "scope Dealer 2\nscope Order 2\n"
    "machine Flow of Order { states Open, Done\ninitial Open\nterminal Done\nevent Finish\n"
    "Open -> Done on Finish when this.dealer.grade = Gold by Sys\n"
    "reject Open on Finish\nreject Done on Finish }\n"
)
GOLD_ONLY = "assume all_gold: forall d in Dealer: d.grade = Gold\n"


class RelationTest(unittest.TestCase):
    def failures(self, text: str) -> list[str]:
        return [f.message for f in check(parse_module(text)) if f.kind == "ASSERTION_FAILED"]

    def test_each_instance_runs_its_own_machine(self):
        text = SHOP + GOLD_ONLY + "assert apart: reachable Order1.Flow = Done and Order2.Flow = Open\n"
        self.assertEqual(blocking_kinds(text), Counter())

    def test_a_fixed_field_that_blocks_an_instance_is_a_trap(self):
        findings = [f for f in check(parse_module(SHOP)) if f.blocking]
        self.assertEqual([f.kind for f in findings], ["TRAP"])
        self.assertIn("state Open of Order1.Flow cannot reach a terminal state", findings[0].message)
        self.assertIn("Dealer1.grade=Basic", findings[0].message)

    def test_a_path_reads_through_a_reference(self):
        holds = SHOP + GOLD_ONLY + "assert a: always forall o in Order: o.Flow = Done => o.dealer.grade = Gold\n"
        self.assertEqual(self.failures(holds), [])
        fails = SHOP + GOLD_ONLY + "assert a: always forall o in Order: o.dealer = Dealer1\n"
        self.assertEqual(len(self.failures(fails)), 1)

    def test_a_field_that_is_not_fixed_changes_between_transitions(self):
        text = SHOP.replace("grade: Grade fixed", "grade: Grade")
        text += "assert a: always forall o in Order: o.Flow = Done => o.dealer.grade = Gold\n"
        self.assertEqual(len(self.failures(text)), 1)

    def test_a_guard_reads_the_other_instances(self):
        guard = "when this.dealer.grade = Gold"
        alone = guard + " and forall p in Order: p = this or p.dealer != this.dealer or p.Flow = Open"
        one = "assert one: always forall a in Order: forall b in Order: a = b or a.dealer != b.dealer or a.Flow = Open or b.Flow = Open\n"
        self.assertEqual(len(self.failures(SHOP + GOLD_ONLY + one)), 1)
        self.assertEqual(self.failures(SHOP.replace(guard, alone) + GOLD_ONLY + one), [])

    def test_exists_needs_one_instance(self):
        text = SHOP + GOLD_ONLY + "assert some_open: always exists o in Order: o.Flow = Open\n"
        failures = self.failures(text)
        self.assertEqual(len(failures), 1)
        self.assertIn("Order1.Flow=Done", failures[0])
        self.assertIn("Order2.Flow=Done", failures[0])

    def test_an_optional_field_can_be_missing(self):
        text = SHOP + GOLD_ONLY + "assert a: reachable Order1.backup = none\nassert b: always Order1.backup.grade = Gold\n"
        failures = self.failures(text)
        self.assertEqual(len(failures), 1)
        self.assertIn("assertion b", failures[0])

    def test_a_rule_reads_the_instance_it_applies_to(self):
        base = SHOP.replace("passive { id: Text\ndealer", "{ id: Text\ndealer") + "actor Clerk\naction Edit\n"
        covered = base + "permit Clerk Edit Order when this.Flow = Open\nforbid Clerk Edit Order when this.Flow = Done\n"
        self.assertEqual(blocking_kinds(covered + GOLD_ONLY), Counter())
        gap = base + "permit Clerk Edit Order when this.Flow = Open\n"
        self.assertEqual(blocking_kinds(gap + GOLD_ONLY), Counter({"UNCOVERED": 1}))

    def test_a_scenario_replays_the_first_instance(self):
        text = SHOP + GOLD_ONLY + "scenario s on Flow { start Open given this.dealer.grade = Gold events Finish expect Done }\n"
        self.assertEqual(blocking_kinds(text), Counter())

    def test_relational_errors_are_reported(self):
        for formula, part in (
            ("forall o in Order: o.missing = Gold", "no field, machine, or counter named missing"),
            ("forall o in Order: o.id = Gold", "which a formula cannot read"),
            ("forall o in Order: o.dealer = Gold", "Gold is not a value of"),
            ("stranger.grade = Gold", "not a bound variable"),
            ("forall o in Order: o.dealer.grade.more = Gold", "not an entity instance"),
        ):
            messages = [f.message for f in check(parse_module(SHOP + GOLD_ONLY + f"assert a: always {formula}\n")) if f.kind == "UNDEFINED"]
            self.assertEqual(len(messages), 1, formula)
            self.assertIn(part, messages[0])

    def test_a_scope_names_a_defined_entity_within_the_limit(self):
        self.assertEqual(blocking_kinds("module m\nscope Ghost 2\n"), Counter({"UNDEFINED": 1}))
        self.assertEqual(blocking_kinds("module m\nentity E passive\nscope E 9\n"), Counter({"TOO_LARGE": 1}))
        unscoped = SHOP.replace("scope Order 2\n", "")
        self.assertIn("UNDEFINED", blocking_kinds(unscoped))

    def test_the_instance_machine_and_the_quantifier_are_rendered(self):
        module = parse_module(SHOP + GOLD_ONLY + "assert a: always exists o in Order: o.Flow = Open\n")
        document = render(module, check(module), "en")
        self.assertIn("- One flow for each: Order", document)
        self.assertIn("In Open when this.dealer.grade is Gold, Finish moves to Done.", document)
        self.assertIn("dealer: Dealer [fixed]", document)
        self.assertIn("- a: `always ∃ o ∈ Order : o.Flow = Open`", document)


LOGIN = (
    "module m\nexternal Sys\nconst limit in 1..4\n"
    "machine Login { states Active, Locked\ninitial Active\nterminal Locked\nevent Fail\ncounter Tries max limit\n"
    "Active -> Active on Fail when Tries < limit then Tries + 1 by Sys\n"
    "Active -> Locked on Fail when Tries = limit by Sys\nreject Locked on Fail }\n"
)


class ConstantTest(unittest.TestCase):
    def failures(self, text: str) -> list[str]:
        return [f.message for f in check(parse_module(text)) if f.kind == "ASSERTION_FAILED"]

    def test_a_plan_is_checked_for_every_value_of_a_constant(self):
        self.assertEqual(blocking_kinds(LOGIN + "assert a: always Login = Locked => Tries = limit\n"), Counter())
        failures = self.failures(LOGIN + "assert a: always Tries >= 2 => Login = Locked\n")
        self.assertEqual(failures, ["assertion a fails after: Login: Fail -> Login: Fail with limit=2 (Login=Active, Tries=2, limit=2)"])

    def test_a_guard_that_misses_a_value_of_the_constant_is_uncovered(self):
        text = LOGIN.replace("when Tries = limit", "when Tries = 4")
        self.assertIn("UNCOVERED", blocking_kinds(text))

    def test_a_counter_cannot_pass_the_constant(self):
        text = LOGIN.replace("when Tries < limit then", "when Tries <= limit then").replace("when Tries = limit", "when Tries > limit")
        self.assertEqual(blocking_kinds(text)["OVERFLOW"], 1)

    def test_a_scenario_gives_the_constant_a_value(self):
        text = LOGIN + "scenario s on Login { start Active given limit = 2 events Fail, Fail, Fail expect Locked }\n"
        self.assertEqual(blocking_kinds(text), Counter())
        self.assertEqual(blocking_kinds(text.replace("given limit = 2", "given limit = 3")), Counter({"SCENARIO_FAILED": 1}))

    def test_an_ordering_needs_numbers(self):
        text = GUARDED.replace("when G = On", "when G < On")
        self.assertIn("UNIT_MISMATCH", blocking_kinds(text))

    def test_a_counter_maximum_names_a_constant(self):
        self.assertIn("UNDEFINED", blocking_kinds(LOGIN.replace("max limit", "max nothing")))

    def test_a_constant_carries_the_unknown_it_stands_for(self):
        text = LOGIN.replace("const limit in 1..4", 'const limit in 1..4 label "잠금 횟수" assuming lock_limit')
        text += 'unknown value lock_limit { label "잠금 횟수" source "회의록" provisional "3회" }\n'
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
        GUARDED.replace("when G = Off", "when G in {On, Off}"),
        GUARDED.replace("A -> C on Go when G = Off by Ext\n", ""),
        GUARDED_IGNORE.replace("ignore A on E when S = Off", "ignore A on E when S in {On, Off}"),
        "module m\nenum S = A | B | C\nactor X\naction Do\nentity R\npermit X Do R when S in {A, B}\nforbid X Do R when S != A\n",
        "module m\nenum S = A | B\nexclusive S = A, S = A\ninvariant i: S = A\n",
        FREE_PAIR + "assert a: always T = Done => P = Ok\nassert r: reachable T = Done and P = Bad\n",
        GUARDED_PAIR + "assert a: always T = Done => P = Ok\nassert r: reachable T = Done and P = Bad\n",
        FLAGGED + "assert a: always M = B => Flag = On\nassert r: reachable M = B and Flag = Off\n",
        SHOP + GOLD_ONLY + "assert a: always exists o in Order: o.Flow = Open\nassert b: always forall o in Order: o.dealer = Dealer1\n",
        LOGIN + "assert a: always Tries >= 2 => Login = Locked\nassert b: always Login = Locked => Tries = limit\n",
        "module m\nexternal Ext\n"
        "machine P { states Ok, Bad\ninitial Ok\nterminal Bad\nevent Fail\nOk -> Ok on Fail by Ext\nignore Bad on Fail }\n"
        "machine T { states Open, Done\ninitial Open\nterminal Done\nevent Finish\n"
        "Open -> Done on Finish when P = Bad by Ext\nignore Open on Finish\nignore Done on Finish }\n",
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
                    if f.message.startswith("an invariant over machine states fails")
                    or "is never reached" in f.message
                    or (f.kind == "ASSERTION_FAILED" and f.line in plain)
                )

            listed = compared(check(module))
            with mock.patch("pdl.checks.SYSTEM_LIMIT", 0):
                solved = compared(check(module))
            self.assertEqual(solved, listed, text[:60])

    def test_a_space_too_large_to_enumerate_is_solved(self):
        enums = "".join(f"enum E{number} = A | B | C | D\n" for number in range(12))
        every = " and ".join(f"E{number} = A" for number in range(12))
        base = "module m\n" + enums + "actor X\naction Do\nentity R\n"
        gap = [f for f in check(parse_module(base + f"permit X Do R when {every}\n")) if f.blocking]
        self.assertEqual([f.kind for f in gap], ["UNCOVERED"])
        self.assertIn("E0=A, E1=A, E10=A, E11=A, E2=A, E3=A, E4=A, E5=A, E6=A, E7=A, E8=A, E9=B", gap[0].message)
        clash = base + f"permit X Do R when {every}\nforbid X Do R when E0 = A\nforbid X Do R when E0 != A\n"
        self.assertEqual(blocking_kinds(clash), Counter({"CONTRADICTION": 1}))
        covered = base + "permit X Do R when E0 = A\nforbid X Do R when E0 != A\n"
        self.assertEqual(blocking_kinds(covered), Counter())

    def test_laws_that_cannot_hold_together_contradict(self):
        base = "module m\nentity X { d: Day\ne: Day\nf: Day }\n"
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


def document_lines(module) -> list[str]:
    lines = render(module, check(module), "en").splitlines()
    return sorted(line for line in lines if line and "exclusive" not in line and line != "## Premises")


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

    def test_conversion_keeps_the_findings_and_the_document(self):
        for text in SolverTest.texts:
            before = legacy.parse_module(text)
            after = syntax.parse_module(to_text(before, imports=False))
            self.assertEqual(
                Counter(f.kind for f in check(after)), Counter(f.kind for f in check(before)), text[:60]
            )
            self.assertEqual(document_lines(after), document_lines(before), text[:60])
            self.assertEqual(to_text(after, imports=False), to_text(before, imports=False), text[:60])

    def test_the_convert_command_rewrites_a_keyword_module(self):
        import contextlib
        import io
        import tempfile

        from pdl.cli import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "old.pdl").write_text(COVERED_MACHINE, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["convert", str(root / "old.pdl"), "--output", str(root / "new")]), 0)
                self.assertEqual(main(["build", str(root / "new" / "old.pdl"), "--output", str(root / "build")]), 0)
            self.assertIn("M.Go @Ext {", (root / "new" / "old.pdl").read_text(encoding="utf-8"))


class ConsistencyTest(unittest.TestCase):
    def kinds(self, *texts: str) -> Counter:
        modules = [(Path(f"m{number}.pdl"), parse_module(text)) for number, text in enumerate(texts)]
        return Counter((f.kind, f.blocking) for f in compare(modules))

    def test_modules_that_agree_or_list_other_slices_pass(self):
        first = "module a\nentity Doc key (id) {\nid: Text\ntitle: Text\n}\nenum S = On | Off\n"
        second = "module b\nentity Doc key (id) {\nid: Text\nauthor: Text\n}\nenum S = Off | On\n"
        self.assertEqual(self.kinds(first, second), Counter())

    def test_enum_values_that_differ_are_a_conflict(self):
        self.assertEqual(
            self.kinds("module a\nenum S = On | Off\n", "module b\nenum S = On | Off | Hold\n"),
            Counter({("INCONSISTENT", True): 1}),
        )

    def test_a_field_type_or_key_that_differs_is_a_conflict(self):
        base = "module a\nentity Doc key (id) {\nid: Text\ntitle: Text\n}\n"
        other_type = "module b\nentity Doc key (id) {\nid: Text\ntitle: Day\n}\n"
        other_key = "module b\nentity Doc key (title) {\nid: Text\ntitle: Text\n}\n"
        self.assertEqual(self.kinds(base, other_type), Counter({("INCONSISTENT", True): 1}))
        self.assertEqual(self.kinds(base, other_key), Counter({("INCONSISTENT", True): 1}))

    def test_one_name_in_two_categories_is_a_conflict_unless_one_is_a_term(self):
        entity = "module a\nentity Doc key (id) {\nid: Text\n}\n"
        self.assertEqual(self.kinds(entity, "module b\nenum Doc = On | Off\n"), Counter({("INCONSISTENT", True): 1}))
        self.assertEqual(self.kinds(entity, "module b\nterm Doc\n"), Counter())
        self.assertEqual(self.kinds("module b\nterm Doc\n", entity), Counter())

    def test_a_label_that_differs_is_only_a_note(self):
        self.assertEqual(
            self.kinds('module a\nenum S label "상태" = On | Off\n', 'module b\nenum S label "현황" = On | Off\n'),
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
        text = "module m\nactor X\naction Do\nentity R\npermit X Do R assuming nothing"
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
