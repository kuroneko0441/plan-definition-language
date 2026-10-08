"""Hole detection for plan definition language modules."""

from collections import deque
from dataclasses import dataclass
from itertools import product

from .model import Call, Condition, Exclusion, Machine, Module, Reference, Rule, Term

TIME_TYPES = ("Day", "Week", "Month")
BUILTIN_TYPES = ("Text", "Int", "Bool") + TIME_TYPES
ENUMERATION_LIMIT = 20000


@dataclass
class Finding:
    kind: str
    message: str
    line: int
    blocking: bool = True


@dataclass
class Outcome:
    assignment: dict[str, str]
    rules: list[Rule]


class Index:
    def __init__(self, module: Module):
        self.enums = {}
        for definition in module.enums:
            self.enums.setdefault(definition.name, definition)
        self.entities = {}
        for definition in module.entities:
            self.entities.setdefault(definition.name, definition)
        self.machines = {}
        for machine in module.machines:
            self.machines.setdefault(machine.name, machine)
        kinds = {"actor": set(), "external": set(), "action": set()}
        for declaration in module.declarations:
            kinds[declaration.kind].add(declaration.name)
        self.internal_actors = kinds["actor"]
        self.actors = kinds["actor"] | kinds["external"]
        self.actions = kinds["action"]
        self.guarded_resources = {
            name for name, entity in self.entities.items() if not entity.passive
        }


def describe(assignment: dict[str, str]) -> str:
    if not assignment:
        return "any condition"
    return ", ".join(f"{variable}={value}" for variable, value in sorted(assignment.items()))


def rule_matches(rule: Rule, actor: str, action: str, resource: str) -> bool:
    return all(
        pattern in ("*", value)
        for pattern, value in ((rule.actor, actor), (rule.action, action), (rule.resource, resource))
    )


def is_excluded(exclusion: Exclusion, assignment: dict[str, str]) -> bool:
    def holds(condition: Condition) -> bool:
        return assignment.get(condition.variable) == condition.value

    return holds(exclusion.left) and holds(exclusion.right)


def triple_outcomes(
    module: Module, index: Index, actor: str, action: str, resource: str
) -> list[Outcome] | None:
    matching = [rule for rule in module.rules if rule_matches(rule, actor, action, resource)]
    variables = sorted(
        {
            condition.variable
            for rule in matching
            for condition in rule.conditions
            if condition.variable in index.enums
        }
    )
    domains = [index.enums[variable].values for variable in variables]
    size = 1
    for domain in domains:
        size *= len(domain)
    if size > ENUMERATION_LIMIT:
        return None
    outcomes = []
    for values in product(*domains):
        assignment = dict(zip(variables, values))
        if any(is_excluded(exclusion, assignment) for exclusion in module.exclusions):
            continue
        applicable = [
            rule
            for rule in matching
            if all(assignment.get(c.variable) == c.value for c in rule.conditions)
        ]
        outcomes.append(Outcome(assignment, applicable))
    return outcomes


def check(module: Module) -> list[Finding]:
    index = Index(module)
    findings: list[Finding] = []
    for step in (
        check_definitions,
        check_entities,
        check_rules,
        check_permissions,
        check_machines,
        check_scenarios,
        check_laws,
        check_unknowns,
    ):
        findings.extend(step(module, index))
    return findings


def check_definitions(module: Module, index: Index) -> list[Finding]:
    first: dict[str, int] = {}
    findings = []
    for _, name, line in module.definitions:
        if name in first:
            findings.append(
                Finding("DUPLICATE", f"{name} is defined twice (lines {first[name]} and {line})", line)
            )
        else:
            first[name] = line
    return findings


def check_entities(module: Module, index: Index) -> list[Finding]:
    findings = []
    known_types = set(BUILTIN_TYPES) | set(index.enums) | set(index.entities)
    for entity in module.entities:
        field_names = {name for name, _ in entity.fields}
        for key_field in entity.key:
            if key_field not in field_names:
                findings.append(
                    Finding(
                        "UNDEFINED",
                        f"key field {key_field} of entity {entity.name} is not one of its fields",
                        entity.line,
                    )
                )
        for field_name, type_name in entity.fields:
            if type_name not in known_types:
                findings.append(
                    Finding(
                        "UNDEFINED",
                        f"type {type_name} of {entity.name}.{field_name} is not defined",
                        entity.line,
                    )
                )
    return findings


def check_condition(condition: Condition, index: Index, line: int) -> list[Finding]:
    enum = index.enums.get(condition.variable)
    if enum is None:
        return [Finding("UNDEFINED", f"condition variable {condition.variable} is not an enum", line)]
    if condition.value not in enum.values:
        return [Finding("UNDEFINED", f"{condition.value} is not a value of {condition.variable}", line)]
    return []


def check_rules(module: Module, index: Index) -> list[Finding]:
    findings = []
    for rule in module.rules:
        references = (
            ("actor", rule.actor, index.actors),
            ("action", rule.action, index.actions),
            ("resource", rule.resource, set(index.entities)),
        )
        for kind, value, known in references:
            if value != "*" and value not in known:
                findings.append(Finding("UNDEFINED", f"{kind} {value} is not defined", rule.line))
        for condition in rule.conditions:
            findings.extend(check_condition(condition, index, rule.line))
        if rule.requires and rule.requires not in index.entities and rule.requires not in index.enums:
            findings.append(
                Finding("UNDEFINED", f"required item {rule.requires} is not defined", rule.line)
            )
    for exclusion in module.exclusions:
        findings.extend(check_condition(exclusion.left, index, exclusion.line))
        findings.extend(check_condition(exclusion.right, index, exclusion.line))
    return findings


def check_permissions(module: Module, index: Index) -> list[Finding]:
    findings = []
    triples = product(
        sorted(index.internal_actors), sorted(index.actions), sorted(index.guarded_resources)
    )
    for actor, action, resource in triples:
        outcomes = triple_outcomes(module, index, actor, action, resource)
        label = f"{actor} {action} {resource}"
        if outcomes is None:
            findings.append(
                Finding("TOO_LARGE", f"{label} has too many condition combinations to enumerate", 0)
            )
            continue
        contradictions = [
            outcome
            for outcome in outcomes
            if {rule.effect for rule in outcome.rules} == {"permit", "forbid"}
        ]
        uncovered = [outcome for outcome in outcomes if not outcome.rules]
        if contradictions:
            sample = contradictions[0]
            lines = sorted({rule.line for rule in sample.rules})
            findings.append(
                Finding(
                    "CONTRADICTION",
                    f"{label} is both permitted and forbidden when {describe(sample.assignment)}"
                    f" (rules at lines {', '.join(map(str, lines))}; {len(contradictions)} combinations)",
                    lines[0],
                )
            )
        if uncovered:
            sample = uncovered[0]
            findings.append(
                Finding(
                    "UNCOVERED",
                    f"{label} has no rule when {describe(sample.assignment)}"
                    f" ({len(uncovered)} combinations)",
                    0,
                )
            )
    return findings


def reachable_from(start: str, edges: dict[str, set[str]]) -> set[str]:
    seen = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for neighbor in edges.get(current, ()):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return seen


def check_machine(machine: Machine, index: Index) -> list[Finding]:
    findings = []
    states = set(machine.states)
    events = set(machine.events)
    name = machine.name
    if not machine.initial:
        findings.append(Finding("MISSING", f"machine {name} has no initial state", machine.line))
    elif machine.initial not in states:
        findings.append(Finding("UNDEFINED", f"initial state {machine.initial} is not a state", machine.line))
    if not machine.terminals:
        findings.append(Finding("MISSING", f"machine {name} has no terminal state", machine.line))
    for terminal in machine.terminals:
        if terminal not in states:
            findings.append(Finding("UNDEFINED", f"terminal state {terminal} is not a state", machine.line))
    forward: dict[str, set[str]] = {}
    backward: dict[str, set[str]] = {}
    targets: dict[tuple[str, str], set[str]] = {}
    for transition in machine.transitions:
        label = f"{transition.source} -> {transition.target} on {transition.event}"
        valid = True
        for state in (transition.source, transition.target):
            if state not in states:
                findings.append(Finding("UNDEFINED", f"state {state} in {label} is not a state", transition.line))
                valid = False
        if transition.event not in events:
            findings.append(Finding("UNDEFINED", f"event {transition.event} in {label} is not an event", transition.line))
            valid = False
        if not transition.actor:
            findings.append(Finding("OWNERLESS", f"{label} has no actor", transition.line))
        elif transition.actor not in index.actors:
            findings.append(Finding("UNDEFINED", f"actor {transition.actor} in {label} is not defined", transition.line))
        if valid:
            forward.setdefault(transition.source, set()).add(transition.target)
            backward.setdefault(transition.target, set()).add(transition.source)
            targets.setdefault((transition.source, transition.event), set()).add(transition.target)
    for (state, event), destinations in targets.items():
        if len(destinations) > 1:
            findings.append(
                Finding("CONTRADICTION", f"{state} on {event} leads to {', '.join(sorted(destinations))}", machine.line)
            )
    handled = set(targets)
    for handling in machine.handlings:
        for kind, value, known in (("state", handling.state, states), ("event", handling.event, events)):
            if value != "*" and value not in known:
                findings.append(Finding("UNDEFINED", f"{kind} {value} in {handling.kind} is not defined", handling.line))
        if handling.state == "*":
            handled |= {(state, handling.event) for state in states if (state, handling.event) not in targets}
        elif (handling.state, handling.event) in targets:
            findings.append(
                Finding("CONTRADICTION", f"{handling.state} on {handling.event} is both a transition and {handling.kind}", handling.line)
            )
        else:
            handled.add((handling.state, handling.event))
    if machine.initial in states:
        reachable = reachable_from(machine.initial, forward)
        for state in machine.states:
            if state not in reachable:
                findings.append(Finding("UNREACHABLE", f"state {state} of {name} cannot be reached", machine.line))
    valid_terminals = [terminal for terminal in machine.terminals if terminal in states]
    if valid_terminals:
        can_finish: set[str] = set()
        for terminal in valid_terminals:
            can_finish |= reachable_from(terminal, backward)
        for state in machine.states:
            if state not in can_finish:
                findings.append(Finding("TRAP", f"state {state} of {name} cannot reach a terminal state", machine.line))
    for state in machine.states:
        missing = [event for event in machine.events if (state, event) not in handled]
        if missing:
            findings.append(
                Finding("UNHANDLED", f"state {state} of {name} has no transition or handling for {', '.join(missing)}", machine.line)
            )
    return findings


def check_machines(module: Module, index: Index) -> list[Finding]:
    findings = []
    for machine in module.machines:
        findings.extend(check_machine(machine, index))
    return findings


def check_scenarios(module: Module, index: Index) -> list[Finding]:
    findings = []
    for scenario in module.scenarios:
        machine = index.machines.get(scenario.machine)
        if machine is None:
            findings.append(Finding("UNDEFINED", f"machine {scenario.machine} is not defined", scenario.line))
            continue
        destinations = {(t.source, t.event): t.target for t in machine.transitions}
        ignored = {(h.state, h.event) for h in machine.handlings if h.kind == "ignore" and h.state != "*"}
        ignored_events = {h.event for h in machine.handlings if h.kind == "ignore" and h.state == "*"}
        state = scenario.start
        failed = False
        for event in scenario.events:
            if (state, event) in destinations:
                state = destinations[(state, event)]
            elif (state, event) in ignored or event in ignored_events:
                continue
            else:
                findings.append(
                    Finding("SCENARIO_FAILED", f"scenario {scenario.name}: {event} is not accepted in {state}", scenario.line)
                )
                failed = True
                break
        if not failed and state != scenario.expect:
            findings.append(
                Finding("SCENARIO_FAILED", f"scenario {scenario.name} ends in {state} instead of {scenario.expect}", scenario.line)
            )
    return findings


def term_type(term: Term, index: Index, line: int, findings: list[Finding]) -> str | None:
    if isinstance(term, Reference):
        entity = index.entities.get(term.entity)
        if entity is None:
            findings.append(Finding("UNDEFINED", f"entity {term.entity} is not defined", line))
            return None
        types = dict(entity.fields)
        if term.attribute not in types:
            findings.append(Finding("UNDEFINED", f"{term.entity}.{term.attribute} is not a field", line))
            return None
        return types[term.attribute]
    argument_type = term_type(term.argument, index, line, findings)
    if argument_type is None:
        return None
    if term.function in ("next", "before"):
        if argument_type not in TIME_TYPES:
            findings.append(Finding("UNIT_MISMATCH", f"{term.function} needs a time value but got {argument_type}", line))
            return None
        return argument_type
    if term.function == "month_of":
        if argument_type != "Day":
            findings.append(Finding("UNIT_MISMATCH", f"month_of needs a Day but got {argument_type}", line))
            return None
        return "Month"
    findings.append(Finding("UNDEFINED", f"function {term.function} is not defined", line))
    return None


def check_laws(module: Module, index: Index) -> list[Finding]:
    findings: list[Finding] = []
    for law in module.laws:
        left = term_type(law.left, index, law.line, findings)
        right = term_type(law.right, index, law.line, findings)
        if left is not None and right is not None and left != right:
            findings.append(
                Finding("UNIT_MISMATCH", f"law {law.identifier} compares {left} with {right}", law.line)
            )
    return findings


def check_unknowns(module: Module, index: Index) -> list[Finding]:
    findings = []
    for unknown in module.unknowns:
        attributes = unknown.attributes
        if "source" not in attributes:
            findings.append(Finding("MISSING_SOURCE", f"unknown {unknown.identifier} has no source", unknown.line))
        if unknown.policy == "structure":
            findings.append(
                Finding("UNKNOWN_STRUCTURE", f"the structure {unknown.identifier} is undecided", unknown.line)
            )
        elif unknown.policy == "value":
            if "provisional" not in attributes:
                findings.append(
                    Finding("UNKNOWN_VALUE", f"unknown {unknown.identifier} has no provisional decision", unknown.line)
                )
            elif attributes.get("verified") != "yes":
                findings.append(
                    Finding("UNVERIFIED", f"{unknown.identifier} is provisional and unverified", unknown.line, blocking=False)
                )
        else:
            findings.append(Finding("UNDEFINED", f"unknown policy {unknown.policy} is not structure or value", unknown.line))
    return findings
