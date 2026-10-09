"""Markdown rendering of a hole-free module."""

from itertools import product

from .checks import Finding, Index, row_entities, triple_outcomes
from .model import (
    And,
    Atom,
    ForAll,
    Formula,
    Implies,
    InSet,
    Machine,
    Module,
    Not,
    Or,
    Reference,
    Term,
)
from .prose import Names, attach, has_final_consonant, sentence

LABELS = {
    "ko": {
        "unverified": "확인이 필요한 가정",
        "unverified_note": "원문에 적혀 있지 않아 임시로 정한 내용이며, 현업 확인 전까지는 확정된 규칙이 아니다. 본문에서 이 가정에 기대는 줄에는 가정 표시를 붙였다.",
        "assumption": "가정",
        "appendix": "부록",
        "appendix_note": "아래는 개발자를 위한 정리이다.",
        "matrix_note": "조건부는 행 상태나 업로드 상태 같은 조건에 따라 허용 여부가 달라진다는 뜻이며, 조건은 위의 규칙 문장을 따른다.",
        "terms": "용어",
        "derivations": "파생 상태",
        "invariants": "항상 성립하는 조건",
        "screens": "화면",
        "enums": "열거형",
        "entities": "엔티티",
        "name": "이름",
        "key": "유일성 키",
        "fields": "필드",
        "values": "값",
        "passive": "권한 규칙을 두지 않은 엔티티",
        "rules": "권한 규칙",
        "matrix": "권한 요약",
        "machines": "상태 머신",
        "scenarios": "시나리오",
        "laws": "시간 규칙",
        "effect": "구분",
        "actor": "주체",
        "action": "동작",
        "resource": "대상",
        "condition": "조건",
        "requires": "필요 항목",
        "why": "근거",
        "permit": "허용",
        "forbid": "금지",
        "conditional": "조건부",
        "state": "상태",
        "event": "사건",
        "from": "출발",
        "to": "도착",
        "source": "출처",
        "provisional": "임시 값",
        "terminal": "종결 상태",
        "initial": "시작 상태",
        "ignore": "무시한다",
        "reject": "거부한다",
        "otherwise": "위에 적은 경우 외의 상태에서 사건",
        "start": "시작",
        "events": "사건 순서",
        "expect": "기대 상태",
        "law": "규칙",
        "any": "조건 없음",
    },
    "en": {
        "unverified": "Assumptions that need confirmation",
        "unverified_note": "These items are not stated in the source and were decided provisionally. Lines that depend on them carry an assumption mark.",
        "assumption": "assumption",
        "appendix": "Appendix",
        "appendix_note": "The tables below are for developers.",
        "matrix_note": "Conditional means the result depends on a condition stated in the rules above.",
        "terms": "Terms",
        "derivations": "Derived statuses",
        "invariants": "Invariants",
        "screens": "Screens",
        "enums": "Enumerations",
        "entities": "Entities",
        "name": "Name",
        "key": "Unique key",
        "fields": "Fields",
        "values": "Values",
        "passive": "Entities outside permission rules",
        "rules": "Permission rules",
        "matrix": "Permission summary",
        "machines": "State machines",
        "scenarios": "Scenarios",
        "laws": "Time rules",
        "effect": "Effect",
        "actor": "Actor",
        "action": "Action",
        "resource": "Resource",
        "condition": "Condition",
        "requires": "Requires",
        "why": "Rationale",
        "permit": "Permit",
        "forbid": "Forbid",
        "conditional": "Conditional",
        "state": "State",
        "event": "Event",
        "from": "From",
        "to": "To",
        "source": "Source",
        "provisional": "Provisional value",
        "terminal": "Terminal states",
        "initial": "Initial state",
        "ignore": "ignored",
        "reject": "rejected",
        "otherwise": "In states not listed above, events",
        "start": "Start",
        "events": "Event sequence",
        "expect": "Expected state",
        "law": "Rule",
        "any": "Any",
    },
}


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ") or " "


def table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(value) for value in row) + " |" for row in rows]
    return lines + [""]


PRECEDENCE = {Implies: 1, Or: 2, And: 3}


def formula_text(formula: Formula, parent: int = 0) -> str:
    if isinstance(formula, Atom):
        return f"{formula.left} {'=' if formula.operator == '=' else '≠'} {formula.right}"
    if isinstance(formula, InSet):
        return f"{formula.left} ∈ {{{', '.join(formula.values)}}}"
    if isinstance(formula, Not):
        return f"¬({formula_text(formula.operand)})"
    if isinstance(formula, ForAll):
        text = f"∀ {formula.variable} ∈ {formula.enum} : {formula_text(formula.body)}"
        return f"({text})" if parent else text
    level = PRECEDENCE[type(formula)]
    if isinstance(formula, Implies):
        text = f"{formula_text(formula.premise, level + 1)} ⇒ {formula_text(formula.conclusion, level)}"
    else:
        joiner = " ∧ " if isinstance(formula, And) else " ∨ "
        text = joiner.join(formula_text(operand, level + 1) for operand in formula.operands)
    return f"({text})" if parent > level else text


def term_text(term: Term) -> str:
    if isinstance(term, Reference):
        return f"{term.entity}.{term.attribute}"
    return f"{term.function}({term_text(term.argument)})"


def render_views(module: Module, labels: dict[str, str], names: Names, language: str) -> list[str]:
    lines: list[str] = []
    if module.derivations:
        lines += [f"## {labels['derivations']}", ""]
        for derivation in module.derivations:
            rows = row_entities(module, derivation.entity, derivation.source)
            mixed = derivation.mixed_label if language == "ko" and derivation.mixed_label else derivation.mixed
            if language == "ko":
                lines.append(
                    f"- {attach(names.show(derivation.name), '은', '는')} {names.show(derivation.entity)}에 속한 "
                    f"{names.show(rows[0])}들의 {attach(names.show(derivation.source), '이', '가')} 모두 같으면 "
                    f"그 값이고, 서로 다르면 '{mixed}'이다."
                )
            else:
                lines.append(
                    f"- {derivation.name} of {derivation.entity} is the {derivation.source} shared by all its "
                    f"{rows[0]} records when they agree, and {mixed} when they differ."
                )
            if derivation.why:
                lines.append(f"  - {labels['why']}: {derivation.why}")
        lines.append("")
    if module.screens:
        lines += [f"## {labels['screens']}", ""]
        for screen in module.screens:
            items = []
            for item in screen.shows:
                if "." in item:
                    entity_name, attribute = item.split(".", 1)
                    shown = f"{names.show(entity_name)}의 {names.field(entity_name, attribute)}"
                    items.append(shown if language == "ko" else item)
                else:
                    items.append(names.show(item))
            if language == "ko":
                joined = ", ".join(items[:-1] + [attach(items[-1], "을", "를")])
                lines.append(f"- {attach(names.show(screen.name), '은', '는')} {joined} 보여 준다.")
            else:
                lines.append(f"- {names.show(screen.name)} shows {', '.join(items)}.")
            if screen.why:
                lines.append(f"  - {labels['why']}: {screen.why}")
        lines.append("")
    return lines


def assumption_text(assumes: str, module: Module, labels: dict[str, str]) -> str:
    if not assumes:
        return ""
    for unknown in module.unknowns:
        if unknown.identifier == assumes:
            return f" ({labels['assumption']}: {unknown.attributes.get('label', assumes)})"
    return ""


def render_permissions(
    module: Module,
    index: Index,
    labels: dict[str, str],
    names: Names,
    language: str,
    summary: bool,
) -> list[str]:
    if not module.rules:
        return []
    lines: list[str] = []
    if not summary:
        lines = [f"## {labels['rules']}", ""]
        for rule in module.rules:
            lines.append(f"- {sentence(rule, names, language)}{assumption_text(rule.assumes, module, labels)}")
            if rule.why:
                lines.append(f"  - {labels['why']}: {rule.why}")
        lines.append("")
        return lines
    pairs = [
        (action, resource)
        for action, resource in product(sorted(index.actions), sorted(index.guarded_resources))
        if any(index.applies(action, actor, resource) for actor in index.internal_actors)
    ]
    if pairs and index.internal_actors:
        lines += [f"### {labels['matrix']}", "", labels["matrix_note"], ""]
        matrix = []
        for actor in sorted(index.internal_actors):
            row = [names.show(actor)]
            for action, resource in pairs:
                if not index.applies(action, actor, resource):
                    row.append("-")
                    continue
                outcomes = triple_outcomes(module, index, actor, action, resource) or []
                effects = {frozenset(rule.effect for rule in outcome.rules) for outcome in outcomes}
                if effects == {frozenset({"permit"})}:
                    row.append(labels["permit"])
                elif effects == {frozenset({"forbid"})}:
                    row.append(labels["forbid"])
                else:
                    row.append(labels["conditional"])
            matrix.append(row)
        headers = [labels["actor"]] + [f"{names.show(r)} {names.show(a)}" for a, r in pairs]
        lines += table(headers, matrix)
    return lines


def render_machines(
    module: Module, labels: dict[str, str], names: Names, language: str
) -> list[str]:
    lines: list[str] = []
    machines = {machine.name: machine for machine in module.machines}

    def state_text(machine: Machine, state: str) -> str:
        return machine.state_labels.get(state) or state if language == "ko" else state

    def event_text(machine: Machine, event: str) -> str:
        return machine.event_labels.get(event) or event if language == "ko" else event

    for machine in module.machines:
        title = machine.label if language == "ko" and machine.label else machine.name
        lines += [f"## {labels['machines']}: {title}", "", "```mermaid", "stateDiagram-v2"]
        for state in machine.states:
            if state_text(machine, state) != state:
                lines.append(f'    state "{state_text(machine, state)}" as {state}')
        lines.append(f"    [*] --> {machine.initial}")
        for transition in machine.transitions:
            actor = f" ({names.show(transition.actor)})" if transition.actor else ""
            event = event_text(machine, transition.event)
            lines.append(f"    {transition.source} --> {transition.target}: {event}{actor}")
        lines += [f"    {terminal} --> [*]" for terminal in machine.terminals]
        lines += ["```", ""]
        lines.append(f"- {labels['initial']}: {state_text(machine, machine.initial)}")
        lines.append(
            f"- {labels['terminal']}: {', '.join(state_text(machine, s) for s in machine.terminals)}"
        )
        lines.append("")
        for transition in machine.transitions:
            source = state_text(machine, transition.source)
            target = state_text(machine, transition.target)
            event = event_text(machine, transition.event)
            actor = names.show(transition.actor) if transition.actor else "-"
            note = assumption_text(transition.assumes, module, labels)
            if language == "ko":
                subject = f"'{event}'" + ("이" if has_final_consonant(event) else "가")
                lines.append(
                    f"- '{source}' 상태에서 {subject} 일어나면 '{target}' 상태가 된다. (주체: {actor}){note}"
                )
            else:
                lines.append(f"- In {source}, {event} moves to {target}. (actor: {actor}){note}")
            if transition.why:
                lines.append(f"  - {labels['why']}: {transition.why}")
        otherwise: dict[str, list[str]] = {}
        for handling in machine.handlings:
            event = event_text(machine, handling.event)
            if handling.state == "*":
                otherwise.setdefault(handling.kind, []).append(f"'{event}'")
            else:
                state = state_text(machine, handling.state)
                lines.append(f"- '{state}' + '{event}': {labels[handling.kind]}")
        for kind, events in otherwise.items():
            lines.append(f"- {labels['otherwise']} ({labels[kind]}): {', '.join(events)}")
        lines.append("")
    for scenario in module.scenarios:
        machine = machines.get(scenario.machine)
        if machine is None:
            continue
        lines += [
            f"### {labels['scenarios']}: {scenario.name}",
            "",
            f"- {labels['start']}: {state_text(machine, scenario.start)}",
            f"- {labels['events']}: {', '.join(event_text(machine, e) for e in scenario.events)}",
            f"- {labels['expect']}: {state_text(machine, scenario.expect)}",
            "",
        ]
    return lines


def render(module: Module, findings: list[Finding], language: str = "ko") -> str:
    labels = LABELS[language]
    index = Index(module)
    names = Names(module, language)

    def titled(name: str) -> str:
        return f"{names.show(name)} ({name})" if names.show(name) != name else name

    title = module.label if language == "ko" and module.label else module.name
    lines = [f"# {title}", ""]
    unverified = [finding for finding in findings if finding.kind == "UNVERIFIED"]
    if unverified:
        lines += [f"## {labels['unverified']}", "", labels["unverified_note"], ""]
        rows = [
            [
                u.attributes.get("label", u.identifier),
                u.attributes.get("provisional", ""),
                u.attributes.get("source", ""),
            ]
            for u in module.unknowns
            if u.policy == "value" and u.attributes.get("verified") != "yes"
        ]
        lines += table([labels["name"], labels["provisional"], labels["source"]], rows)
    if module.terms:
        lines += [f"## {labels['terms']}", ""]
        lines += [f"- {names.show(term.name)}: {term.why}" for term in module.terms]
        lines.append("")
    if module.laws:
        lines += [f"## {labels['laws']}", ""]
        for law in module.laws:
            formula = f"{term_text(law.left)} {law.operator} {term_text(law.right)}"
            lines.append(f"- {law.why or law.identifier} (`{formula}`)")
        lines.append("")
    lines += render_machines(module, labels, names, language)
    lines += render_permissions(module, index, labels, names, language, summary=False)
    lines += render_views(module, labels, names, language)
    if module.invariants:
        lines += [f"## {labels['invariants']}", ""]
        for invariant in module.invariants:
            lines.append(f"- {invariant.why or invariant.name} (`{formula_text(invariant.formula)}`)")
        lines.append("")
    appendix = []
    if module.enums:
        appendix += [f"### {labels['enums']}", ""]
        appendix += table(
            [labels["name"], labels["values"], labels["why"]],
            [
                [
                    titled(e.name),
                    ", ".join(f"{v} ({e.value_labels[v]})" if v in e.value_labels else v for v in e.values),
                    e.why,
                ]
                for e in module.enums
            ],
        )
    described = [e for e in module.entities if e.fields or e.why]
    if described:
        appendix += [f"### {labels['entities']}", ""]
        appendix += table(
            [labels["name"], labels["key"], labels["fields"], labels["why"]],
            [
                [
                    titled(e.name),
                    ", ".join(e.key),
                    "<br>".join(
                        (f"{n} ({e.field_labels[n]})" if n in e.field_labels else n)
                        + f": {t}"
                        + (f" - {e.field_notes[n]}" if n in e.field_notes else "")
                        for n, t in e.fields
                    ),
                    e.why,
                ]
                for e in described
            ],
        )
    appendix += render_permissions(module, index, labels, names, language, summary=True)
    if appendix:
        lines += [f"## {labels['appendix']}", "", labels["appendix_note"], ""] + appendix
    return "\n".join(lines).rstrip() + "\n"
