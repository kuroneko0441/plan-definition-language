"""Markdown rendering of a hole-free module."""

from itertools import product

from .checks import Finding, Index, triple_outcomes
from .model import Module, Reference, Term
from .prose import Names, sentence

LABELS = {
    "ko": {
        "unverified": "미검증 임시 결정",
        "terms": "용어",
        "enums": "열거형",
        "entities": "엔티티",
        "name": "이름",
        "key": "유일성 키",
        "fields": "필드",
        "values": "값",
        "passive": "권한 규칙 범위 밖 엔티티",
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
        "start": "시작",
        "events": "사건 순서",
        "expect": "기대 상태",
        "law": "규칙",
        "any": "조건 없음",
    },
    "en": {
        "unverified": "Unverified provisional decisions",
        "terms": "Terms",
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


def term_text(term: Term) -> str:
    if isinstance(term, Reference):
        return f"{term.entity}.{term.attribute}"
    return f"{term.function}({term_text(term.argument)})"


def render_permissions(
    module: Module, index: Index, labels: dict[str, str], names: Names, language: str
) -> list[str]:
    if not module.rules:
        return []
    lines = [f"## {labels['rules']}", ""]
    for rule in module.rules:
        lines.append(f"- {sentence(rule, names, language)}")
        if rule.why:
            lines.append(f"  - {labels['why']}: {rule.why}")
    lines.append("")
    pairs = [
        (action, resource)
        for action, resource in product(sorted(index.actions), sorted(index.guarded_resources))
        if any(index.applies(action, actor, resource) for actor in index.internal_actors)
    ]
    if pairs and index.internal_actors:
        lines += [f"### {labels['matrix']}", ""]
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
        headers = [labels["actor"]] + [f"{names.show(a)} {names.show(r)}" for a, r in pairs]
        lines += table(headers, matrix)
    return lines


def render_machines(module: Module, labels: dict[str, str]) -> list[str]:
    lines = []
    for machine in module.machines:
        lines += [f"## {labels['machines']}: {machine.name}", "", "```mermaid", "stateDiagram-v2"]
        lines.append(f"    [*] --> {machine.initial}")
        for transition in machine.transitions:
            actor = f" ({transition.actor})" if transition.actor else ""
            lines.append(f"    {transition.source} --> {transition.target}: {transition.event}{actor}")
        lines += [f"    {terminal} --> [*]" for terminal in machine.terminals]
        lines += ["```", ""]
        rows = [[t.source, t.event, t.target, t.actor, t.why] for t in machine.transitions]
        lines += table([labels[key] for key in ("from", "event", "to", "actor", "why")], rows)
    for scenario in module.scenarios:
        lines += [
            f"### {labels['scenarios']}: {scenario.name}",
            "",
            f"- {labels['start']}: {scenario.start}",
            f"- {labels['events']}: {', '.join(scenario.events)}",
            f"- {labels['expect']}: {scenario.expect}",
            "",
        ]
    return lines


def render(module: Module, findings: list[Finding], language: str = "ko") -> str:
    labels = LABELS[language]
    index = Index(module)
    names = Names(module, language)

    def titled(name: str) -> str:
        return f"{names.show(name)} ({name})" if names.show(name) != name else name

    lines = [f"# {module.name}", ""]
    unverified = [finding for finding in findings if finding.kind == "UNVERIFIED"]
    if unverified:
        lines += [f"## {labels['unverified']}", ""]
        rows = [
            [u.identifier, u.attributes.get("provisional", ""), u.attributes.get("source", "")]
            for u in module.unknowns
            if u.policy == "value" and u.attributes.get("verified") != "yes"
        ]
        lines += table([labels["name"], labels["provisional"], labels["source"]], rows)
    if module.terms:
        lines += [f"## {labels['terms']}", ""]
        lines += [f"- {names.show(term.name)}: {term.why}" for term in module.terms]
        lines.append("")
    if module.enums:
        lines += [f"## {labels['enums']}", ""]
        lines += table(
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
    if module.entities:
        lines += [f"## {labels['entities']}", ""]
        lines += table(
            [labels["name"], labels["key"], labels["fields"], labels["why"]],
            [
                [
                    titled(e.name),
                    ", ".join(e.key),
                    "<br>".join(
                        f"{n}: {t}" + (f" - {e.field_notes[n]}" if n in e.field_notes else "")
                        for n, t in e.fields
                    ),
                    e.why,
                ]
                for e in module.entities
            ],
        )
        passive = [names.show(e.name) for e in module.entities if e.passive]
        if passive:
            lines += [f"- {labels['passive']}: {', '.join(passive)}", ""]
    lines += render_permissions(module, index, labels, names, language)
    lines += render_machines(module, labels)
    if module.laws:
        lines += [f"## {labels['laws']}", ""]
        for law in module.laws:
            formula = f"{term_text(law.left)} {law.operator} {term_text(law.right)}"
            lines.append(f"- {law.why or law.identifier} (`{formula}`)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
