"""Markdown rendering of a hole-free module."""

from itertools import product

from .checks import Finding, Index, guard_enums, row_entities, rule_matches, triple_outcomes
from .ground import expand
from .model import (
    Machine,
    Module,
    Reference,
    Term,
)
from .prose import (
    Names,
    attach,
    english_condition,
    formula_text,
    has_final_consonant,
    korean_condition,
    sentence,
)

LABELS = {
    "ko": {
        "unverified": "확인이 필요한 가정",
        "unverified_note": "원문에 적혀 있지 않아 임시로 정한 내용이며, 현업 확인 전까지는 확정된 규칙이 아니다. 본문에서 이 가정에 기대는 줄에는 가정 표시를 붙였다.",
        "assumption": "가정",
        "open_item": "미결 있음",
        "appendix": "부록",
        "appendix_note": "아래는 개발자를 위한 정리이다.",
        "matrix_note": "조건부는 행 상태나 업로드 상태 같은 조건에 따라 허용 여부가 달라진다는 뜻이며, 조건은 위의 규칙 문장을 따른다.",
        "terms": "용어",
        "constants": "정해지지 않은 값의 범위",
        "cyclic": "끝나지 않고 처음 상태로 돌아가며 반복되는 흐름",
        "counter": "카운터",
        "instance": "건마다 따로 진행되는 대상",
        "fixed": "변하지 않음",
        "first_value": "처음 값",
        "update": "값 변경",
        "after": "제한 시간",
        "stored": "저장값",
        "basic_types": "기본 자료형은 Text(글자), Int(정수), Decimal(소수), Money(금액), Bool(참 또는 거짓), Timestamp(시각), Duration(기간), Day(일), Week(주), Month(월)이다. 시간 값은 next(다음), before(이전), month_of(일이 속한 월)로 계산하고, 자료형 뒤의 물음표는 비어 있을 수 있음을, list는 여러 개를 뜻한다.",
        "formulas": "식",
        "draft": "초안",
        "draft_note": "이 문서는 구멍이 남은 상태의 초안이며, 아래 구멍이 모두 해소되어야 확정된 기획서가 된다.",
        "derivations": "상태 판정 규칙",
        "computed": "계산되는 값",
        "invariants": "항상 성립하는 조건",
        "premises": "전제",
        "assertions": "검증한 성질",
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
        "machines": "업무 흐름",
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
        "terminal": "끝",
        "initial": "처음",
        "ignore": "무시한다",
        "reject": "받아들이지 않는다",
        "otherwise": "위에 적은 경우가 아니면 다음 사건은",
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
        "open_item": "open item",
        "appendix": "Appendix",
        "appendix_note": "The tables below are for developers.",
        "matrix_note": "Conditional means the result depends on a condition stated in the rules above.",
        "terms": "Terms",
        "constants": "Ranges of undecided values",
        "cyclic": "A flow that never ends and returns to the initial state",
        "counter": "Counter",
        "instance": "One flow for each",
        "fixed": "fixed",
        "first_value": "starts as",
        "update": "sets",
        "after": "time limit",
        "stored": "Stored text",
        "basic_types": "Basic types are Text, Int, Decimal, Money, Bool, Timestamp, Duration, Day, Week, and Month.",
        "formulas": "Formulas",
        "draft": "Draft",
        "draft_note": "This document is a draft with open holes. It is not a final plan until all holes below are resolved.",
        "derivations": "Status rules",
        "computed": "Computed values",
        "invariants": "Invariants",
        "premises": "Premises",
        "assertions": "Verified properties",
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
        "machines": "Workflow",
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
        "otherwise": "Except for the cases above, these events are",
        "start": "Start",
        "events": "Event sequence",
        "expect": "Expected state",
        "law": "Rule",
        "any": "Any",
    },
}


MINIMUM_DUPLICATE_LENGTH = 12


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ") or "-"


def dedupe_rationales(lines: list[str], labels: dict[str, str]) -> list[str]:
    prefix = f"  - {labels['why']}: "
    corpus = "\n".join(line for line in lines if not line.startswith("  - "))
    seen: set[str] = set()
    result = []
    for line in lines:
        if line.startswith(prefix):
            text = line.removeprefix(prefix)
            if (len(text) >= MINIMUM_DUPLICATE_LENGTH and text in corpus) or text in seen:
                continue
            seen.add(text)
        result.append(line)
    return result


def table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(value) for value in row) + " |" for row in rows]
    return lines + [""]


def term_text(term: Term) -> str:
    if isinstance(term, Reference):
        return f"{term.entity}.{term.attribute}"
    return f"{term.function}({term_text(term.argument)})"


def render_views(module: Module, labels: dict[str, str], names: Names, language: str) -> list[str]:
    lines: list[str] = []
    for key, computed in (("derivations", False), ("computed", True)):
        group = [derivation for derivation in module.derivations if bool(derivation.type) == computed]
        if not group:
            continue
        lines += [f"## {labels[key]}", ""]
        for derivation in group:
            rows = row_entities(module, derivation.entity, derivation.source) or ["?"]
            mixed = derivation.mixed_label if language == "ko" and derivation.mixed_label else derivation.mixed
            note = assumption_text(derivation.assumes, module, labels)
            if derivation.type:
                sources = []
                for source in derivation.sources:
                    owner, _, attribute = source.partition(".")
                    shown = f"{names.show(owner)}의 {names.field(owner, attribute)}" if attribute else names.show(owner)
                    sources.append(shown if language == "ko" else source)
                if language == "ko":
                    lines.append(
                        f"- {attach(names.show(derivation.name), '은', '는')} {names.show(derivation.entity)}의 "
                        f"계산값({derivation.type})이며 {', '.join(sources)}에서 계산한다.{note}"
                    )
                else:
                    lines.append(
                        f"- {derivation.name} of {derivation.entity} is a computed {derivation.type}"
                        f" from {', '.join(sources)}.{note}"
                    )
            elif language == "ko":
                lines.append(
                    f"- {attach(names.show(derivation.name), '은', '는')} {names.show(derivation.entity)}에 속한 "
                    f"{names.show(rows[0])}들의 {attach(names.show(derivation.source), '이', '가')} 모두 같으면 "
                    f"그 값이고, 서로 다르면 '{mixed}'이다.{note}"
                )
            else:
                lines.append(
                    f"- {derivation.name} of {derivation.entity} is the {derivation.source} shared by all its "
                    f"{rows[0]} records when they agree, and {mixed} when they differ.{note}"
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
            note = assumption_text(screen.assumes, module, labels)
            if language == "ko":
                joined = ", ".join(items[:-1] + [attach(items[-1], "을", "를")])
                lines.append(f"- {attach(names.show(screen.name), '은', '는')} {joined} 보여 준다.{note}")
            else:
                lines.append(f"- {names.show(screen.name)} shows {', '.join(items)}.{note}")
            if screen.why:
                lines.append(f"  - {labels['why']}: {screen.why}")
        lines.append("")
    return lines


def assumption_text(assumes: list[str], module: Module, labels: dict[str, str]) -> str:
    found = [unknown for name in assumes for unknown in module.unknowns if unknown.identifier == name]
    parts = []
    for flag, key in ((False, "assumption"), (True, "open_item")):
        shown = [
            unknown.attributes.get("label", unknown.identifier)
            for unknown in found
            if (unknown.attributes.get("open") == "yes") == flag
        ]
        if shown:
            parts.append(f" ({labels[key]}: {', '.join(shown)})")
    return "".join(parts)


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
        for actor in sorted(index.internal_actors):
            entries = []
            for action, resource in pairs:
                if not index.applies(action, actor, resource):
                    continue
                outcomes = triple_outcomes(module, index, actor, action, resource) or []
                effects = {frozenset(rule.effect for rule in outcome.rules) for outcome in outcomes}
                if effects == {frozenset({"permit"})}:
                    result = labels["permit"]
                elif effects == {frozenset({"forbid"})}:
                    result = labels["forbid"]
                else:
                    variables = sorted(
                        {
                            names.show(variable)
                            for rule in module.rules
                            if rule_matches(rule, actor, action, resource)
                            for variable in guard_enums(rule.conditions, index)
                        }
                    )
                    result = f"{labels['conditional']}({', '.join(variables)})"
                entries.append(f"{names.show(resource)} {names.show(action)} {result}")
            lines.append(f"- {names.show(actor)}: {', '.join(entries)}")
        lines.append("")
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

    def update_text(machine: Machine, path: str, value: str) -> str:
        attribute = path.removeprefix("this.")
        if attribute == path:
            return f"{path} = {value}"
        kind = names.field_types.get((machine.entity, attribute), "").removesuffix("?")
        return f"{names.field(machine.entity, attribute)} = {names.value(kind, value)}"

    for machine in module.machines:
        title = machine.label if language == "ko" and machine.label else machine.name
        lines += [f"## {labels['machines']}: {title}", ""]
        if machine.why:
            lines += [machine.why, ""]
        lines += ["```mermaid", "stateDiagram-v2"]
        for state in machine.states:
            if state_text(machine, state) != state:
                lines.append(f'    state "{state_text(machine, state)}" as {state}')
        lines.append(f"    [*] --> {machine.initial}")
        for transition in machine.transitions:
            actor = f" ({', '.join(names.show(a) for a in transition.actors)})" if transition.actors else ""
            event = event_text(machine, transition.event)
            lines.append(f"    {transition.source} --> {transition.target}: {event}{actor}")
        lines += [f"    {terminal} --> [*]" for terminal in machine.terminals]
        lines += ["```", ""]
        lines.append(f"- {labels['initial']}: {state_text(machine, machine.initial)}")
        if machine.terminals:
            lines.append(
                f"- {labels['terminal']}: {', '.join(state_text(machine, s) for s in machine.terminals)}"
            )
        if machine.cyclic:
            lines.append(f"- {labels['cyclic']}")
        if machine.entity:
            lines.append(f"- {labels['instance']}: {names.show(machine.entity)}")
        for counter, maximum in machine.counters.items():
            shown = machine.counter_labels.get(counter) if language == "ko" else None
            limit = names.show(machine.counter_bounds[counter]) if counter in machine.counter_bounds else maximum
            lines.append(f"- {labels['counter']}: {shown or counter} (0 ~ {limit})")
        lines.append("")
        for transition in machine.transitions:
            source = state_text(machine, transition.source)
            target = state_text(machine, transition.target)
            event = event_text(machine, transition.event)
            actor = ", ".join(names.show(a) for a in transition.actors) or "-"
            note = assumption_text(transition.assumes, module, labels)
            effects = ", ".join(
                (
                    f"{(machine.counter_labels.get(counter) if language == 'ko' else None) or counter} "
                    + (f"{amount}(으)로 되돌림" if operator == "=" and language == "ko" else
                       f"reset to {amount}" if operator == "=" else
                       f"+{amount}")
                )
                for counter, operator, amount in transition.effects
            )
            effects_note = f" ({labels['counter']}: {effects})" if effects else ""
            updates = ", ".join(update_text(machine, path, value) for path, value in transition.updates)
            effects_note += f" ({labels['update']}: {updates})" if updates else ""
            after_note = f" ({labels['after']}: {transition.after})" if transition.after else ""
            if language == "ko":
                subject = f"'{event}'" + ("이" if has_final_consonant(event) else "가")
                guard = korean_condition(transition.conditions, names) + " " if transition.conditions else ""
                lines.append(
                    f"- '{source}' 상태에서 {guard}{subject} 일어나면 '{target}' 상태가 된다. "
                    f"(주체: {actor}){after_note}{effects_note}{note}"
                )
            else:
                guard = f" when {english_condition(transition.conditions, names)}" if transition.conditions else ""
                lines.append(
                    f"- In {source}{guard}, {event} moves to {target}. (actor: {actor}){after_note}{effects_note}{note}"
                )
            if transition.why:
                lines.append(f"  - {labels['why']}: {transition.why}")
        otherwise: dict[str, list[str]] = {}
        otherwise_assumes: dict[str, list[str]] = {}
        for handling in machine.handlings:
            event = event_text(machine, handling.event)
            if handling.state == "*" and not handling.conditions:
                otherwise.setdefault(handling.kind, []).append(f"'{event}'")
                known = otherwise_assumes.setdefault(handling.kind, [])
                known.extend(name for name in handling.assumes if name not in known)
            else:
                state = "*" if handling.state == "*" else state_text(machine, handling.state)
                note = assumption_text(handling.assumes, module, labels)
                guard = ""
                if handling.conditions:
                    guard = (
                        f" ({korean_condition(handling.conditions, names)})"
                        if language == "ko"
                        else f" (when {english_condition(handling.conditions, names)})"
                    )
                lines.append(f"- '{state}' + '{event}': {labels[handling.kind]}{guard}{note}")
                if handling.why:
                    lines.append(f"  - {labels['why']}: {handling.why}")
        for kind, events in otherwise.items():
            note = assumption_text(otherwise_assumes[kind], module, labels)
            lines.append(f"- {labels['otherwise']} {labels[kind]}: {', '.join(events)}{note}")
            lines += [
                f"  - {labels['why']}: {handling.why}"
                for handling in machine.handlings
                if handling.kind == kind and handling.state == "*" and not handling.conditions and handling.why
            ]
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

    def joint_states(states: dict[str, str]) -> str:
        return ", ".join(
            f"{names.show(name)} = {state_text(machines[name], state) if name in machines else state}"
            for name, state in states.items()
        )

    for scenario in module.joint_scenarios:
        shown_events = ", ".join(
            f"{names.show(name)}: {event_text(machines[name], event) if name in machines else event}"
            for name, event in scenario.events
        )
        lines += [
            f"### {labels['scenarios']}: {scenario.name}",
            "",
            f"- {labels['start']}: {joint_states(scenario.start)}",
            f"- {labels['events']}: {shown_events}",
            f"- {labels['expect']}: {joint_states(scenario.expect)}",
            "",
        ]
    return lines


def render(module: Module, findings: list[Finding], language: str = "ko", draft: bool = False) -> str:
    labels = LABELS[language]
    expanded, _ = expand(module)
    index = Index(expanded)
    names = Names(module, language)

    def titled(name: str) -> str:
        return f"{names.show(name)} ({name})" if names.show(name) != name else name

    title = module.label if language == "ko" and module.label else module.name
    lines = [f"# {title}", ""]
    if draft:
        lines += [f"## {labels['draft']}", "", labels["draft_note"], ""]
        lines += [f"- {finding.kind}: {finding.message}" for finding in findings if finding.blocking]
        lines.append("")
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
    if module.constants:
        lines += [f"## {labels['constants']}", ""]
        for constant in module.constants:
            shown = constant.label if language == "ko" and constant.label else constant.name
            note = assumption_text(constant.assumes, module, labels)
            lines.append(f"- {shown}: {constant.low} ~ {constant.high}{note}")
            if constant.why:
                lines.append(f"  - {labels['why']}: {constant.why}")
        lines.append("")
    if module.laws:
        lines += [f"## {labels['laws']}", ""]
        for law in module.laws:
            lines.append(f"- {law.why or law.identifier}{assumption_text(law.assumes, module, labels)}")
        lines.append("")
    lines += render_machines(module, labels, names, language)
    lines += render_permissions(module, index, labels, names, language, summary=False)
    lines += render_views(module, labels, names, language)
    if module.invariants:
        lines += [f"## {labels['invariants']}", ""]
        for invariant in module.invariants:
            lines.append(f"- {invariant.why or invariant.name}")
        lines.append("")
    for key, items in (("premises", module.premises), ("assertions", module.assertions)):
        if items:
            lines += [f"## {labels[key]}", ""] + [f"- {item.why or item.name}" for item in items] + [""]
    appendix = []
    formulas = (
        [
            f"- {law.identifier}: `{term_text(law.left)} {law.operator} {term_text(law.right)}`"
            for law in module.laws
        ]
        + [f"- {item.name}({', '.join(item.parameters)}): `{formula_text(item.formula)}`" for item in module.predicates]
        + [f"- {item.name}({', '.join(item.parameters)}): `{item.path}`" for item in module.functions]
        + [f"- {item.name}: `{formula_text(item.formula)}`" for item in (*module.invariants, *module.premises)]
        + [f"- {item.name}: `{item.mode} {formula_text(item.formula)}`" for item in module.assertions]
    )
    if formulas:
        appendix += [f"### {labels['formulas']}", ""] + formulas + [""]
    if module.enums:
        appendix += [f"### {labels['enums']}", ""]
        appendix += table(
            [labels["name"], labels["values"], labels["why"]],
            [
                [
                    titled(e.name),
                    ", ".join(
                        (f"{v} ({e.value_labels[v]})" if v in e.value_labels else v)
                        + (f" [{labels['stored']}: {e.stored[v]}]" if v in e.stored else "")
                        for v in e.values
                    ),
                    e.why,
                ]
                for e in module.enums
            ],
        )
    referenced = {t.removesuffix("?").removeprefix("list ") for e in module.entities for _, t in e.fields}
    described = [e for e in module.entities if e.fields or e.name in referenced]
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
                        + (f" [{labels['fixed']}]" if n in e.fixed else "")
                        + (f" [{labels['first_value']}: {e.starts[n]}]" if n in e.starts else "")
                        + (f" - {e.field_notes[n]}" if n in e.field_notes else "")
                        for n, t in e.fields
                    ),
                    e.why,
                ]
                for e in described
            ],
        )
    appendix += render_permissions(expanded, index, labels, names, language, summary=True)
    if appendix:
        lines += [f"## {labels['appendix']}", "", labels["appendix_note"], labels["basic_types"], ""] + appendix
    return "\n".join(dedupe_rationales(lines, labels)).rstrip() + "\n"
