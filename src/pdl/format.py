"""Source text of a module in the current syntax."""

import re
from typing import assert_never

from .model import (
    And,
    Atom,
    Can,
    Exists,
    ForAll,
    Formula,
    Handling,
    Implies,
    InSet,
    Machine,
    Module,
    Not,
    Or,
    Reference,
    Term,
    Transition,
)

PRECEDENCE = {Implies: 1, Or: 2, And: 3}
BARE = re.compile(r"\w+")


def quoted(text: str) -> str:
    return '"' + text.replace('"', '\\"') + '"'


def formula_source(formula: Formula, parent: int = 0) -> str:
    if isinstance(formula, Atom):
        return f"{formula.left} {formula.operator} {formula.right}"
    if isinstance(formula, InSet):
        return f"{formula.left} in {{{', '.join(formula.values)}}}"
    if isinstance(formula, (Not, Can)):
        return ("!" if isinstance(formula, Not) else "can ") + f"({formula_source(formula.operand)})"
    if isinstance(formula, (ForAll, Exists)):
        keyword = "all" if isinstance(formula, ForAll) else "some"
        return f"({keyword} {formula.variable} in {formula.enum}: {formula_source(formula.body)})"
    level = PRECEDENCE[type(formula)]
    if isinstance(formula, Implies):
        text = f"{formula_source(formula.premise, level + 1)} => {formula_source(formula.conclusion, level)}"
    elif isinstance(formula, (And, Or)):
        joiner = " & " if isinstance(formula, And) else " | "
        text = joiner.join(formula_source(operand, level + 1) for operand in formula.operands)
    else:
        assert_never(formula)
    return f"({text})" if parent > level else text


def term_source(term: Term) -> str:
    if isinstance(term, Reference):
        return f"{term.entity}.{term.attribute}"
    return f"{term.function}({term_source(term.argument)})"


def assuming(names: list[str]) -> str:
    return f" assuming {', '.join(names)}" if names else ""


class Writer:
    def __init__(self, module: Module):
        self.module = module
        self.lines: list[str] = []
        self.texts: list[str] = []

    def text(self, key: str, label: str = "", **attributes: str) -> None:
        parts = [quoted(label)] if label else []
        parts += [f"{name} {quoted(value)}" for name, value in attributes.items() if value]
        if parts:
            self.texts.append(f"    {key} {' '.join(parts)}")

    def section(self, lines: list[str]) -> None:
        if lines:
            self.lines += [*lines, ""]

    def guard(self, machine: Machine, state: str, conditions: list[Formula]) -> str:
        parts = [] if state == "*" else [f"{machine.name} = {state}"]
        parts += [formula_source(condition, PRECEDENCE[And] + 1) for condition in conditions]
        return " & ".join(parts)

    def block(self, machine: Machine, event: str) -> list[str]:
        transitions = [item for item in machine.transitions if item.event == event]
        handlings = [item for item in machine.handlings if item.event == event]
        shared = transitions[0].actors if transitions else []
        if any(item.actors != shared for item in transitions):
            shared = []
        header = f"{machine.name}.{event}" + (f" @{', '.join(shared)}" if shared else "")
        lines = [header + " {"]
        for number, item in enumerate([*transitions, *handlings], start=1):
            tag = ""
            if isinstance(item, Handling) and item.state == "*" and not item.conditions:
                clause = f"else {item.kind}"
                key = "else"
            else:
                clause = f"{self.guard(machine, self.source(item), item.conditions)} => {self.outcome(machine, item)}".lstrip()
                key = f"c{number}"
                if item.why or getattr(item, "after", ""):
                    tag = f" as {key}"
            if isinstance(item, Transition) and item.actors != shared:
                clause += f" @{', '.join(item.actors)}"
            lines.append(f"    {clause}{assuming(item.assumes)}{tag}")
            self.text(f"{machine.name}.{event}.{key}", why=item.why, after=getattr(item, "after", ""))
        return [*lines, "}"]

    def source(self, item: Transition | Handling) -> str:
        return item.source if isinstance(item, Transition) else item.state

    def outcome(self, machine: Machine, item: Transition | Handling) -> str:
        if isinstance(item, Handling):
            return item.kind
        updates = [f"{machine.name}' = {item.target}"] if item.target != item.source or not item.effects else []
        for counter, operator, amount in item.effects:
            updates.append(f"{counter}' = {amount}" if operator == "=" else f"{counter}' = {counter} + {amount}")
        return " & ".join(updates)

    def machine(self, machine: Machine) -> None:
        owner = f" of {machine.entity}" if machine.entity else ""
        ending = " cyclic" if machine.cyclic else f" final {{{', '.join(machine.terminals)}}}" if machine.terminals else ""
        start = f" init {machine.initial}" if machine.initial else ""
        lines = [f"{machine.name}{owner} : {{{', '.join(machine.states)}}}{start}{ending}"]
        self.text(machine.name, machine.label, why=machine.why)
        for state in machine.states:
            self.text(f"{machine.name}.{state}", machine.state_labels.get(state, ""))
        for counter, maximum in machine.counters.items():
            lines.append(f"{machine.name}.{counter} : 0..{machine.counter_bounds.get(counter, maximum)}")
            self.text(f"{machine.name}.{counter}", machine.counter_labels.get(counter, ""))
        events = list(machine.events)
        events += [item.event for item in (*machine.transitions, *machine.handlings) if item.event not in events]
        for event in dict.fromkeys(events):
            self.text(f"{machine.name}.{event}", machine.event_labels.get(event, ""))
            lines += self.block(machine, event)
        self.section(lines)

    def write(self, imports: bool) -> str:
        module = self.module
        self.lines = [f"module {module.name}", ""]
        self.text("module", module.label)
        if imports:
            self.section([f"import {quoted(path)}" for _, path in module.imports])
        for term in module.terms:
            self.text(term.name, term.label, why=term.why)
        self.section([f"term {term.name}" for term in module.terms])
        lines = []
        for enum in module.enums:
            lines.append(f"{enum.name} : {{{', '.join(enum.values)}}}")
            self.text(enum.name, enum.label, why=enum.why)
            for value in dict.fromkeys([*enum.values, *enum.stored]):
                self.text(f"{enum.name}.{value}", enum.value_labels.get(value, ""), stored=enum.stored.get(value, ""))
        self.section(lines)
        for entity in module.entities:
            key = f" key ({', '.join(entity.key)})" if entity.key else ""
            lines = [f"{entity.name}{key}{' passive' if entity.passive else ''} {{"]
            lines += [f"    {name}: {kind}{' fixed' if name in entity.fixed else ''}" for name, kind in entity.fields]
            self.section([*lines, "}"] if entity.fields else [lines[0] + "}"])
            self.text(entity.name, entity.label, why=entity.why)
            for name, _ in entity.fields:
                self.text(f"{entity.name}.{name}", entity.field_labels.get(name, ""), why=entity.field_notes.get(name, ""))
        self.section([f"scope {name} {count}" for name, count in module.scopes.items()])
        lines = []
        for constant in module.constants:
            lines.append(f"const {constant.name} : {constant.low}..{constant.high}{assuming(constant.assumes)}")
            self.text(constant.name, constant.label, why=constant.why)
        self.section(lines)
        lines = []
        for declaration in module.declarations:
            by = f" by ({', '.join(declaration.performed_by)})" if declaration.performed_by else ""
            on = f" on ({', '.join(declaration.applies_to)})" if declaration.applies_to else ""
            lines.append(f"{declaration.kind} {declaration.name}{by}{on}")
            self.text(declaration.name, declaration.label)
        self.section(lines)
        lines = []
        for number, rule in enumerate(module.rules, start=1):
            condition = f": {formula_source(And(rule.conditions))}" if rule.conditions else ""
            if len(rule.conditions) == 1:
                condition = f": {formula_source(rule.conditions[0])}"
            requires = f" requires {rule.requires}" if rule.requires else ""
            tag = f" as rule{number}" if rule.why else ""
            lines.append(
                f"{rule.effect} {rule.actor} {rule.action} {rule.resource}{condition}{requires}{assuming(rule.assumes)}{tag}"
            )
            self.text(f"rule{number}", why=rule.why)
        self.section(lines)
        lines = []
        for exclusion in module.exclusions:
            both = formula_source(And([exclusion.left, exclusion.right]))
            lines.append(f"assume exclusive{exclusion.line}: !({both})")
        for keyword, items in (("assume", module.premises), ("inv", module.invariants)):
            for item in items:
                lines.append(f"{keyword} {item.name}: {formula_source(item.formula)}")
                self.text(item.name, why=item.why)
        for law in module.laws:
            lines.append(
                f"law {law.identifier}: {term_source(law.left)} {law.operator} {term_source(law.right)}{assuming(law.assumes)}"
            )
            self.text(law.identifier, why=law.why)
        self.section(lines)
        lines = []
        for derivation in module.derivations:
            form = (
                f": {derivation.type} from {', '.join(derivation.sources)}"
                if derivation.type
                else f"from {derivation.source} mixed {derivation.mixed}"
            )
            lines.append(f"derive {derivation.name} of {derivation.entity} {form}{assuming(derivation.assumes)}")
            self.text(derivation.name, derivation.label, why=derivation.why, mixed=derivation.mixed_label)
        for screen in module.screens:
            lines.append(f"screen {screen.name} of {screen.entity} shows {', '.join(screen.shows)}{assuming(screen.assumes)}")
            self.text(screen.name, screen.label, why=screen.why)
        self.section(lines)
        for machine in module.machines:
            self.machine(machine)
        lines = []
        for assertion in module.assertions:
            lines.append(f"prop {assertion.name}: {assertion.mode} {formula_source(assertion.formula)}")
            self.text(assertion.name, why=assertion.why)
        for scenario in module.scenarios:
            start = " & ".join(
                [f"{scenario.machine} = {scenario.start}"]
                + [formula_source(condition, PRECEDENCE[And] + 1) for condition in scenario.given]
            )
            lines.append(
                f"run {scenario.name}: {start} -> {', '.join(scenario.events)} -> {scenario.machine} = {scenario.expect}"
            )
        for scenario in module.joint_scenarios:
            start = " & ".join(f"{name} = {state}" for name, state in scenario.start.items())
            events = ", ".join(f"{name}.{event}" for name, event in scenario.events)
            expect = " & ".join(f"{name} = {state}" for name, state in scenario.expect.items())
            lines.append(f"run {scenario.name}: {start} -> {events} -> {expect}")
        self.section(lines)
        lines = []
        for unknown in module.unknowns:
            attributes = " ".join(
                f"{key} {value if key in ('verified', 'open') and BARE.fullmatch(value) else quoted(value)}"
                for key, value in unknown.attributes.items()
            )
            lines.append(f"unknown {unknown.policy} {unknown.identifier} {{ {attributes} }}")
        self.section(lines)
        if self.texts:
            self.lines += ["text {", *self.texts, "}", ""]
        return "\n".join(self.lines).rstrip() + "\n"


def to_text(module: Module, imports: bool = True) -> str:
    return Writer(module).write(imports)
