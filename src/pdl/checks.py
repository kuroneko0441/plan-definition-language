"""Hole detection for plan definition language modules."""

from collections import deque
from dataclasses import dataclass
from itertools import product

from .model import (
    And,
    Atom,
    Call,
    Condition,
    ForAll,
    Formula,
    Implies,
    InSet,
    Machine,
    Module,
    Not,
    Or,
    Reference,
    Rule,
    Term,
    Transition,
)

TIME_TYPES = ("Day", "Week", "Month")
BUILTIN_TYPES = ("Text", "Int", "Bool", "Timestamp", "Decimal", "Money", "Duration") + TIME_TYPES
ENUMERATION_LIMIT = 20000
SAMPLE_LIMIT = 6


def base_type(type_name: str) -> str:
    return type_name.removesuffix("?")


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
        actions = [d for d in module.declarations if d.kind == "action"]
        self.action_actors = {d.name: set(d.performed_by) for d in actions if d.performed_by}
        self.action_resources = {d.name: set(d.applies_to) for d in actions if d.applies_to}
        self.unknown_ids = {unknown.identifier for unknown in module.unknowns}
        formulas = [invariant.formula for invariant in module.invariants]
        for exclusion in module.exclusions:
            both = [
                Atom(c.variable, "=", c.value) for c in (exclusion.left, exclusion.right)
            ]
            formulas.append(Not(And(both)))
        self.invariant_terms = [(formula, free_enums(formula, self)) for formula in formulas]

    def applies(self, action: str, actor: str, resource: str) -> bool:
        return actor in self.action_actors.get(action, {actor}) and resource in self.action_resources.get(
            action, {resource}
        )


def describe(assignment: dict[str, str]) -> str:
    if not assignment:
        return "any condition"
    return ", ".join(f"{variable}={value}" for variable, value in sorted(assignment.items()))


def rule_matches(rule: Rule, actor: str, action: str, resource: str) -> bool:
    return all(
        pattern in ("*", value)
        for pattern, value in ((rule.actor, actor), (rule.action, action), (rule.resource, resource))
    )


def resolve(term: str, assignment: dict[str, str], bound: dict[str, str]) -> str:
    if term in bound:
        return bound[term]
    return assignment.get(term, term)


def evaluate(formula: Formula, assignment: dict[str, str], bound: dict[str, str], index: Index) -> bool:
    if isinstance(formula, Atom):
        equal = resolve(formula.left, assignment, bound) == resolve(formula.right, assignment, bound)
        return equal if formula.operator == "=" else not equal
    if isinstance(formula, InSet):
        return resolve(formula.left, assignment, bound) in formula.values
    if isinstance(formula, Not):
        return not evaluate(formula.operand, assignment, bound, index)
    if isinstance(formula, And):
        return all(evaluate(operand, assignment, bound, index) for operand in formula.operands)
    if isinstance(formula, Or):
        return any(evaluate(operand, assignment, bound, index) for operand in formula.operands)
    if isinstance(formula, Implies):
        return not evaluate(formula.premise, assignment, bound, index) or evaluate(
            formula.conclusion, assignment, bound, index
        )
    enum = index.enums.get(formula.enum)
    values = enum.values if enum is not None else []
    return all(evaluate(formula.body, assignment, {**bound, formula.variable: v}, index) for v in values)


def free_enums(formula: Formula, index: Index, bound: frozenset[str] = frozenset()) -> set[str]:
    if isinstance(formula, Atom):
        terms = [formula.left, formula.right]
    elif isinstance(formula, InSet):
        terms = [formula.left]
    elif isinstance(formula, Not):
        return free_enums(formula.operand, index, bound)
    elif isinstance(formula, (And, Or)):
        return set().union(*(free_enums(operand, index, bound) for operand in formula.operands))
    elif isinstance(formula, Implies):
        return free_enums(formula.premise, index, bound) | free_enums(formula.conclusion, index, bound)
    else:
        return free_enums(formula.body, index, bound | {formula.variable})
    return {term for term in terms if term in index.enums and term not in bound}


def condition_holds(condition: Condition, assignment: dict[str, str]) -> bool:
    current = assignment.get(condition.variable)
    if current is None:
        return False
    if condition.operator == "in":
        return current in condition.values
    if condition.operator == "!=":
        return current != condition.value
    return current == condition.value


def worlds(index: Index, variables: set[str]) -> list[dict[str, str]] | None:
    chosen = set(variables)
    changed = True
    while changed:
        changed = False
        for _, enums in index.invariant_terms:
            if enums & chosen and not enums <= chosen:
                chosen |= enums
                changed = True
    names = sorted(chosen)
    domains = [index.enums[name].values for name in names]
    size = 1
    for domain in domains:
        size *= len(domain)
    if size > ENUMERATION_LIMIT:
        return None
    result = []
    for values in product(*domains):
        assignment = dict(zip(names, values))
        if all(
            evaluate(formula, assignment, {}, index)
            for formula, enums in index.invariant_terms
            if enums and enums <= chosen
        ):
            result.append(assignment)
    return result


def triple_outcomes(
    module: Module, index: Index, actor: str, action: str, resource: str
) -> list[Outcome] | None:
    matching = [rule for rule in module.rules if rule_matches(rule, actor, action, resource)]
    variables = {
        condition.variable
        for rule in matching
        for condition in rule.conditions
        if condition.variable in index.enums
    }
    assignments = worlds(index, variables)
    if assignments is None:
        return None
    return [
        Outcome(
            assignment,
            [rule for rule in matching if all(condition_holds(c, assignment) for c in rule.conditions)],
        )
        for assignment in assignments
    ]


def check(module: Module) -> list[Finding]:
    index = Index(module)
    findings: list[Finding] = []
    for step in (
        check_definitions,
        check_entities,
        check_invariants,
        check_views,
        check_actions,
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
            if base_type(type_name).removeprefix("list ") not in known_types:
                findings.append(
                    Finding(
                        "UNDEFINED",
                        f"type {type_name} of {entity.name}.{field_name} is not defined",
                        entity.line,
                    )
                )
    return findings


def row_entities(module: Module, entity: str, source: str) -> list[str]:
    return [
        candidate.name
        for candidate in module.entities
        if any(base_type(type_name).removeprefix("list ") == entity for _, type_name in candidate.fields)
        and any(base_type(type_name).removeprefix("list ") == source for _, type_name in candidate.fields)
    ]


def term_enum(term: str, bound: dict[str, str], index: Index) -> str | None:
    if term in bound:
        return bound[term]
    return term if term in index.enums else None


def check_formula(
    formula: Formula, bound: dict[str, str], index: Index, line: int, findings: list[Finding]
) -> None:
    if isinstance(formula, Atom):
        left = term_enum(formula.left, bound, index)
        right = term_enum(formula.right, bound, index)
        if left is None and right is None:
            findings.append(
                Finding("UNDEFINED", f"neither {formula.left} nor {formula.right} is an enum or a bound variable", line)
            )
        elif left is not None and right is not None and left != right:
            findings.append(Finding("UNIT_MISMATCH", f"{formula.left} and {formula.right} are values of different enums", line))
        elif left is None and formula.left not in index.enums[right].values:
            findings.append(Finding("UNDEFINED", f"{formula.left} is not a value of {right}", line))
        elif right is None and formula.right not in index.enums[left].values:
            findings.append(Finding("UNDEFINED", f"{formula.right} is not a value of {left}", line))
    elif isinstance(formula, InSet):
        enum = term_enum(formula.left, bound, index)
        if enum is None:
            findings.append(Finding("UNDEFINED", f"{formula.left} is not an enum or a bound variable", line))
        else:
            for value in formula.values:
                if value not in index.enums[enum].values:
                    findings.append(Finding("UNDEFINED", f"{value} is not a value of {enum}", line))
    elif isinstance(formula, Not):
        check_formula(formula.operand, bound, index, line, findings)
    elif isinstance(formula, (And, Or)):
        for operand in formula.operands:
            check_formula(operand, bound, index, line, findings)
    elif isinstance(formula, Implies):
        check_formula(formula.premise, bound, index, line, findings)
        check_formula(formula.conclusion, bound, index, line, findings)
    else:
        if formula.enum not in index.enums:
            findings.append(Finding("UNDEFINED", f"enum {formula.enum} of the quantifier is not defined", line))
            return
        check_formula(formula.body, {**bound, formula.variable: formula.enum}, index, line, findings)


def check_invariants(module: Module, index: Index) -> list[Finding]:
    findings: list[Finding] = []
    for invariant in module.invariants:
        check_formula(invariant.formula, {}, index, invariant.line, findings)
    if findings:
        return findings
    enums = sorted(set().union(*(names for _, names in index.invariant_terms)))
    if not enums:
        return findings
    domains = [index.enums[name].values for name in enums]
    size = 1
    for domain in domains:
        size *= len(domain)
    if size > ENUMERATION_LIMIT:
        return findings
    for values in product(*domains):
        assignment = dict(zip(enums, values))
        if all(evaluate(formula, assignment, {}, index) for formula, _ in index.invariant_terms):
            return findings
    line = module.invariants[0].line if module.invariants else module.exclusions[0].line
    return [Finding("CONTRADICTION", "the invariants and exclusions admit no combination of values", line)]


def check_views(module: Module, index: Index) -> list[Finding]:
    findings = []
    derived = {derivation.name for derivation in module.derivations}
    for derivation in module.derivations:
        enum = index.enums.get(derivation.source)
        if derivation.entity not in index.entities:
            findings.append(Finding("UNDEFINED", f"entity {derivation.entity} of {derivation.name} is not defined", derivation.line))
        if enum is None:
            findings.append(Finding("UNDEFINED", f"enum {derivation.source} of {derivation.name} is not defined", derivation.line))
            continue
        if derivation.mixed in enum.values:
            findings.append(
                Finding("DUPLICATE", f"mixed value {derivation.mixed} is already a value of {derivation.source}", derivation.line)
            )
        if derivation.entity in index.entities and not row_entities(module, derivation.entity, derivation.source):
            findings.append(
                Finding(
                    "UNDEFINED",
                    f"no entity links {derivation.entity} to {derivation.source}, so {derivation.name} has no rows to derive from",
                    derivation.line,
                )
            )
    for screen in module.screens:
        if screen.entity not in index.entities:
            findings.append(Finding("UNDEFINED", f"entity {screen.entity} of screen {screen.name} is not defined", screen.line))
        for item in screen.shows:
            if "." in item:
                entity_name, attribute = item.split(".", 1)
                entity = index.entities.get(entity_name)
                if entity is None or attribute not in dict(entity.fields):
                    findings.append(Finding("UNDEFINED", f"{item} shown by screen {screen.name} is not a field", screen.line))
            elif item not in index.enums and item not in derived:
                findings.append(Finding("UNDEFINED", f"{item} shown by screen {screen.name} is not defined", screen.line))
    return findings


def check_condition(condition: Condition, index: Index, line: int) -> list[Finding]:
    enum = index.enums.get(condition.variable)
    if enum is None:
        return [Finding("UNDEFINED", f"condition variable {condition.variable} is not an enum", line)]
    given = condition.values if condition.operator == "in" else [condition.value]
    return [
        Finding("UNDEFINED", f"{value} is not a value of {condition.variable}", line)
        for value in given
        if value not in enum.values
    ]


def check_assumptions(assumes: list[str], index: Index, line: int, owner: str) -> list[Finding]:
    return [
        Finding("UNDEFINED", f"assumption {name} of {owner} is not declared as unknown", line)
        for name in assumes
        if name not in index.unknown_ids
    ]


def check_actions(module: Module, index: Index) -> list[Finding]:
    findings = []
    for declaration in module.declarations:
        for kind, names, known in (
            ("actor", declaration.performed_by, index.actors),
            ("entity", declaration.applies_to, set(index.entities)),
        ):
            for name in names:
                if name not in known:
                    findings.append(
                        Finding("UNDEFINED", f"{kind} {name} of action {declaration.name} is not defined", declaration.line)
                    )
    return findings


def check_rules(module: Module, index: Index) -> list[Finding]:
    findings = []
    for rule in module.rules:
        for kind, value, allowed in (
            ("actor", rule.actor, index.action_actors.get(rule.action)),
            ("resource", rule.resource, index.action_resources.get(rule.action)),
        ):
            if allowed is not None and value != "*" and value not in allowed:
                findings.append(
                    Finding("INAPPLICABLE", f"action {rule.action} does not apply to {kind} {value}", rule.line)
                )
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
        findings.extend(check_assumptions(rule.assumes, index, rule.line, "a rule"))
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
        if not index.applies(action, actor, resource):
            continue
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
            listed = "; ".join(describe(outcome.assignment) for outcome in uncovered[:SAMPLE_LIMIT])
            more = f"; and {len(uncovered) - SAMPLE_LIMIT} more" if len(uncovered) > SAMPLE_LIMIT else ""
            findings.append(
                Finding(
                    "UNCOVERED",
                    f"{label} has no rule when {listed}{more} ({len(uncovered)} combinations)",
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


def check_guards(
    machine: Machine,
    grouped: dict[tuple[str, str], list[Transition]],
    else_covered: set[tuple[str, str]],
    index: Index,
) -> list[Finding]:
    findings = []
    for (state, event), group in grouped.items():
        if len(group) == 1 and not group[0].conditions:
            continue
        label = f"{state} on {event}"
        if len(group) > 1 and any(not transition.conditions for transition in group):
            destinations = {transition.target for transition in group}
            if len(destinations) > 1:
                findings.append(
                    Finding("CONTRADICTION", f"{label} leads to {', '.join(sorted(destinations))}", group[0].line)
                )
            continue
        variables = {
            condition.variable
            for transition in group
            for condition in transition.conditions
            if condition.variable in index.enums
        }
        assignments = worlds(index, variables)
        if assignments is None:
            findings.append(Finding("TOO_LARGE", f"{label} has too many guard combinations to enumerate", group[0].line))
            continue
        conflicts = []
        gaps = []
        for assignment in assignments:
            applicable = [t for t in group if all(condition_holds(c, assignment) for c in t.conditions)]
            if len({t.target for t in applicable}) > 1:
                conflicts.append(assignment)
            elif not applicable and (state, event) not in else_covered:
                gaps.append(assignment)
        if conflicts:
            findings.append(
                Finding("CONTRADICTION", f"{label} leads to different states when {describe(conflicts[0])} ({len(conflicts)} combinations)", group[0].line)
            )
        if gaps:
            listed = "; ".join(describe(a) for a in gaps[:SAMPLE_LIMIT])
            findings.append(
                Finding("UNCOVERED", f"{label} has no outcome when {listed} ({len(gaps)} combinations)", group[0].line)
            )
    return findings


def check_machine(machine: Machine, index: Index) -> list[Finding]:
    findings = []
    states = set(machine.states)
    events = set(machine.events)
    name = machine.name
    if not machine.initial:
        findings.append(Finding("MISSING", f"machine {name} has no initial state", machine.line))
    elif machine.initial not in states:
        findings.append(Finding("UNDEFINED", f"initial state {machine.initial} is not a state", machine.line))
    if not machine.terminals and not machine.cyclic:
        findings.append(Finding("MISSING", f"machine {name} has no terminal state and is not cyclic", machine.line))
    for terminal in machine.terminals:
        if terminal not in states:
            findings.append(Finding("UNDEFINED", f"terminal state {terminal} is not a state", machine.line))
    forward: dict[str, set[str]] = {}
    backward: dict[str, set[str]] = {}
    targets: dict[tuple[str, str], set[str]] = {}
    grouped: dict[tuple[str, str], list[Transition]] = {}
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
        findings.extend(check_assumptions(transition.assumes, index, transition.line, label))
        if not transition.actors:
            findings.append(Finding("OWNERLESS", f"{label} has no actor", transition.line))
        for actor in transition.actors:
            if actor not in index.actors:
                findings.append(Finding("UNDEFINED", f"actor {actor} in {label} is not defined", transition.line))
        for condition in transition.conditions:
            findings.extend(check_condition(condition, index, transition.line))
        if valid:
            forward.setdefault(transition.source, set()).add(transition.target)
            backward.setdefault(transition.target, set()).add(transition.source)
            targets.setdefault((transition.source, transition.event), set()).add(transition.target)
            grouped.setdefault((transition.source, transition.event), []).append(transition)
    handled = set(targets)
    else_covered: set[tuple[str, str]] = set()
    for handling in machine.handlings:
        for kind, value, known in (("state", handling.state, states), ("event", handling.event, events)):
            if value != "*" and value not in known:
                findings.append(Finding("UNDEFINED", f"{kind} {value} in {handling.kind} is not defined", handling.line))
        findings.extend(check_assumptions(handling.assumes, index, handling.line, handling.kind))
        pairs = (
            [(state, handling.event) for state in states]
            if handling.state == "*"
            else [(handling.state, handling.event)]
        )
        for pair in pairs:
            group = grouped.get(pair)
            if group is None:
                handled.add(pair)
            elif all(transition.conditions for transition in group):
                else_covered.add(pair)
            elif handling.state != "*":
                findings.append(
                    Finding("CONTRADICTION", f"{pair[0]} on {pair[1]} is both a transition and {handling.kind}", handling.line)
                )
    findings.extend(check_guards(machine, grouped, else_covered, index))
    if machine.initial in states:
        reachable = reachable_from(machine.initial, forward)
        for state in machine.states:
            if state not in reachable:
                findings.append(Finding("UNREACHABLE", f"state {state} of {name} cannot be reached", machine.line))
    valid_terminals = [terminal for terminal in machine.terminals if terminal in states]
    if machine.cyclic and machine.initial in states:
        can_return = reachable_from(machine.initial, backward)
        for state in machine.states:
            if state not in can_return:
                findings.append(Finding("TRAP", f"state {state} of {name} cannot return to the initial state", machine.line))
    elif valid_terminals:
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
        given = {c.variable: c.value for c in scenario.given if c.operator == "="}
        ignored = {(h.state, h.event) for h in machine.handlings if h.kind == "ignore" and h.state != "*"}
        ignored_events = {h.event for h in machine.handlings if h.kind == "ignore" and h.state == "*"}
        state = scenario.start
        failed = False
        for event in scenario.events:
            applicable = [
                t
                for t in machine.transitions
                if t.source == state and t.event == event and all(condition_holds(c, given) for c in t.conditions)
            ]
            if applicable:
                state = applicable[0].target
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
        return base_type(types[term.attribute])
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


def referenced_unknowns(module: Module) -> set[str]:
    referenced: set[str] = set()
    for owner in (*module.rules, *module.laws, *module.screens, *module.derivations):
        referenced.update(owner.assumes)
    for machine in module.machines:
        for item in (*machine.transitions, *machine.handlings):
            referenced.update(item.assumes)
    return referenced


def check_unknowns(module: Module, index: Index) -> list[Finding]:
    findings = []
    referenced = referenced_unknowns(module)
    for unknown in module.unknowns:
        attributes = unknown.attributes
        if unknown.policy == "value" and unknown.identifier not in referenced:
            findings.append(
                Finding("UNREFERENCED", f"unknown {unknown.identifier} is not assumed by any rule, transition, law, screen, or derivation", unknown.line, blocking=False)
            )
        title = unknown.identifier + (f" ({attributes['label']})" if "label" in attributes else "")
        if "source" not in attributes:
            findings.append(Finding("MISSING_SOURCE", f"unknown {unknown.identifier} has no source", unknown.line))
        if unknown.policy == "structure":
            findings.append(Finding("UNKNOWN_STRUCTURE", f"the structure {title} is undecided", unknown.line))
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
