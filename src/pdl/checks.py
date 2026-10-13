"""Hole detection for plan definition language modules."""

from collections import deque
from dataclasses import dataclass
from itertools import product

from .ground import expand
from .model import (
    And,
    Atom,
    Call,
    Can,
    EnumDefinition,
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
    Rule,
    Scenario,
    Term,
    Transition,
)

TIME_TYPES = ("Day", "Week", "Month")
BUILTIN_TYPES = ("Text", "Int", "Bool", "Timestamp", "Decimal", "Money", "Duration") + TIME_TYPES
ENUMERATION_LIMIT = 20000
SAMPLE_LIMIT = 6
SYSTEM_LIMIT = 100000


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


@dataclass
class System:
    machines: list[Machine]
    counter_order: list[str]
    rigid: list[str]
    interesting: set[str]
    seen: dict[tuple, tuple | None]
    steps: dict[tuple, str]
    behind: dict[tuple, list[tuple]]

    def assignment(self, config: tuple) -> dict[str, str]:
        states, values, fixed = config
        result = {machine.name: state for machine, state in zip(self.machines, states)}
        result.update({counter: str(value) for counter, value in zip(self.counter_order, values)})
        result.update(zip(self.rigid, fixed))
        return result

    def path(self, config: tuple) -> str:
        path = []
        while self.seen[config] is not None:
            path.append(self.steps[config])
            config = self.seen[config]
        route = " -> ".join(reversed(path)) or "the start"
        return f"{route} with {describe(dict(zip(self.rigid, config[2])))}" if self.rigid else route


class Index:
    def __init__(self, module: Module):
        self.enums = {}
        for definition in module.enums:
            self.enums.setdefault(definition.name, definition)
        for definition in module.variables:
            self.enums.setdefault(definition.name, definition)
        self.entities = {}
        for definition in module.entities:
            self.entities.setdefault(definition.name, definition)
        self.machines = {}
        for machine in module.machines:
            self.machines.setdefault(machine.name, machine)
            self.enums.setdefault(machine.name, EnumDefinition(machine.line, machine.name, list(machine.states)))
            for counter, maximum in machine.counters.items():
                values = [str(number) for number in range(maximum + 1)]
                self.enums.setdefault(counter, EnumDefinition(machine.line, counter, values))
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
        obligations = [invariant.formula for invariant in module.invariants]
        premises = [Not(And([exclusion.left, exclusion.right])) for exclusion in module.exclusions]
        premises += [premise.formula for premise in module.premises]
        self.obligation_terms = [(formula, free_enums(formula, self)) for formula in obligations]
        self.premise_terms = [(formula, free_enums(formula, self)) for formula in premises]
        self.invariant_terms = self.obligation_terms + self.premise_terms
        self.fact_line = min(
            (item.line for item in (*module.invariants, *module.exclusions, *module.premises)), default=0
        )
        self.system: System | None = None

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
    if isinstance(formula, ForAll):
        enum = index.enums.get(formula.enum)
        values = enum.values if enum is not None else []
        return all(evaluate(formula.body, assignment, {**bound, formula.variable: v}, index) for v in values)
    raise TypeError(f"{type(formula).__name__} has no value in a single state")


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
    elif isinstance(formula, ForAll):
        return free_enums(formula.body, index, bound | {formula.variable})
    else:
        return set()
    return {term for term in terms if term in index.enums and term not in bound}


def guard_enums(conditions: list[Formula], index: Index) -> set[str]:
    return set().union(*(free_enums(condition, index) for condition in conditions))


def condition_holds(condition: Formula, assignment: dict[str, str], index: Index) -> bool:
    return free_enums(condition, index) <= assignment.keys() and evaluate(condition, assignment, {}, index)


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
    variables = set().union(*(guard_enums(rule.conditions, index) for rule in matching))
    assignments = worlds(index, variables)
    if assignments is None:
        return None
    return [
        Outcome(
            assignment,
            [rule for rule in matching if all(condition_holds(c, assignment, index) for c in rule.conditions)],
        )
        for assignment in assignments
    ]


def check(module: Module) -> list[Finding]:
    module, problems = expand(module)
    index = Index(module)
    findings = [Finding(kind, message, line) for kind, message, line in problems]
    for step in (
        check_definitions,
        check_entities,
        check_invariants,
        check_views,
        check_actions,
        check_rules,
        check_permissions,
        check_machines,
        check_system,
        check_assertions,
        check_enums,
        check_scenarios,
        check_joint_scenarios,
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
    elif isinstance(formula, (Not, Can)):
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
    for item in (*module.invariants, *module.premises, *module.assertions):
        check_formula(item.formula, {}, index, item.line, findings)
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
    return [
        Finding("CONTRADICTION", "the invariants, assumptions, and exclusions admit no combination of values", index.fact_line)
    ]


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


def check_condition(condition: Formula, index: Index, line: int) -> list[Finding]:
    findings: list[Finding] = []
    check_formula(condition, {}, index, line, findings)
    return findings


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


def transition_outcome(transition: Transition) -> tuple:
    changes: dict[str, list[tuple[str, int]]] = {}
    for counter, operator, amount in transition.effects:
        changes.setdefault(counter, []).append((operator, amount))
    return transition.target, tuple(sorted((counter, tuple(steps)) for counter, steps in changes.items()))


def agrees(world: dict[str, str], assignment: dict[str, str]) -> bool:
    return all(assignment.get(variable, value) == value for variable, value in world.items())


def check_guards(
    machine: Machine,
    grouped: dict[tuple[str, str], list[Transition]],
    else_covered: set[tuple[str, str]],
    index: Index,
    guarded_handlings: dict[tuple[str, str], list[Handling]] | None = None,
) -> list[Finding]:
    findings = []
    guarded_handlings = guarded_handlings or {}
    for (state, event) in [*grouped, *(key for key in guarded_handlings if key not in grouped)]:
        group = grouped.get((state, event), [])
        held = guarded_handlings.get((state, event), [])
        if len(group) == 1 and not group[0].conditions and not held:
            continue
        label = f"{state} on {event}"
        line = (group or held)[0].line
        if held and any(not transition.conditions for transition in group):
            findings.append(Finding("CONTRADICTION", f"{label} is both an unconditional transition and a guarded {held[0].kind}", line))
            continue
        if len(group) > 1 and any(not transition.conditions for transition in group):
            destinations = {transition.target for transition in group}
            if len(destinations) > 1:
                findings.append(
                    Finding("CONTRADICTION", f"{label} leads to {', '.join(sorted(destinations))}", line)
                )
            elif len({transition_outcome(transition) for transition in group}) > 1:
                findings.append(Finding("CONTRADICTION", f"{label} changes the counters in different ways", line))
            continue
        variables = set().union(*(guard_enums(item.conditions, index) for item in (*group, *held)))
        assignments = worlds(index, variables)
        if assignments is None:
            findings.append(Finding("TOO_LARGE", f"{label} has too many guard combinations to enumerate", line))
            continue
        conflicts = []
        gaps = []
        for assignment in assignments:
            applicable = [t for t in group if all(condition_holds(c, assignment, index) for c in t.conditions)]
            applicable_held = [h for h in held if all(condition_holds(c, assignment, index) for c in h.conditions)]
            if len({transition_outcome(t) for t in applicable}) > 1 or (applicable and applicable_held):
                conflicts.append(assignment)
            elif not applicable and not applicable_held and (state, event) not in else_covered:
                gaps.append(assignment)
        if conflicts:
            findings.append(
                Finding("CONTRADICTION", f"{label} has conflicting outcomes when {describe(conflicts[0])} ({len(conflicts)} combinations)", line)
            )
        if gaps:
            listed = "; ".join(describe(a) for a in gaps[:SAMPLE_LIMIT])
            findings.append(
                Finding("UNCOVERED", f"{label} has no outcome when {listed} ({len(gaps)} combinations)", line)
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
        for counter, operator, amount in transition.effects:
            maximum = machine.counters.get(counter)
            if maximum is None:
                findings.append(Finding("UNDEFINED", f"counter {counter} in {label} is not a counter of {name}", transition.line))
            elif operator == "=" and not 0 <= amount <= maximum:
                findings.append(Finding("UNDEFINED", f"{counter} = {amount} in {label} is outside 0..{maximum}", transition.line))
            elif operator == "+" and amount <= 0:
                findings.append(Finding("UNDEFINED", f"{counter} + {amount} in {label} does not increase the counter", transition.line))
        if valid:
            forward.setdefault(transition.source, set()).add(transition.target)
            backward.setdefault(transition.target, set()).add(transition.source)
            targets.setdefault((transition.source, transition.event), set()).add(transition.target)
            grouped.setdefault((transition.source, transition.event), []).append(transition)
    handled = set(targets)
    else_covered: set[tuple[str, str]] = set()
    guarded_handlings: dict[tuple[str, str], list[Handling]] = {}
    for handling in machine.handlings:
        for kind, value, known in (("state", handling.state, states), ("event", handling.event, events)):
            if value != "*" and value not in known:
                findings.append(Finding("UNDEFINED", f"{kind} {value} in {handling.kind} is not defined", handling.line))
        findings.extend(check_assumptions(handling.assumes, index, handling.line, handling.kind))
        for condition in handling.conditions:
            findings.extend(check_condition(condition, index, handling.line))
        pairs = (
            [(state, handling.event) for state in machine.states]
            if handling.state == "*"
            else [(handling.state, handling.event)]
        )
        for pair in pairs:
            group = grouped.get(pair)
            if handling.conditions:
                unguarded = group is not None and any(not transition.conditions for transition in group)
                if not (handling.state == "*" and unguarded):
                    guarded_handlings.setdefault(pair, []).append(handling)
            elif group is None:
                handled.add(pair)
                else_covered.add(pair)
            elif all(transition.conditions for transition in group):
                else_covered.add(pair)
            elif handling.state != "*":
                findings.append(
                    Finding("CONTRADICTION", f"{pair[0]} on {pair[1]} is both a transition and {handling.kind}", handling.line)
                )
    findings.extend(check_guards(machine, grouped, else_covered, index, guarded_handlings))
    handled |= set(guarded_handlings)
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


def check_enums(module: Module, index: Index) -> list[Finding]:
    findings = []
    for enum in module.enums:
        counts: dict[str, int] = {}
        for value in enum.values:
            counts[value] = counts.get(value, 0) + 1
        for value, count in counts.items():
            if count > 1:
                findings.append(Finding("DUPLICATE", f"value {value} of {enum.name} is listed {count} times", enum.line))
        stored_counts: dict[str, list[str]] = {}
        for value, text in enum.stored.items():
            stored_counts.setdefault(text, []).append(value)
            if value not in enum.values:
                findings.append(Finding("UNDEFINED", f"stored text for {value}, which is not a value of {enum.name}", enum.line))
        for text, values in stored_counts.items():
            if len(values) > 1:
                findings.append(
                    Finding("DUPLICATE", f"values {', '.join(values)} of {enum.name} share the stored text {text!r}", enum.line)
                )
    return findings


def check_system(module: Module, index: Index) -> list[Finding]:
    machines = [machine for machine in module.machines if machine.initial in machine.states]
    counters = [(machine.name, counter) for machine in machines for counter in machine.counters]
    rigid = [name for name in module.rigid if name in index.enums]
    interesting = {machine.name for machine in machines} | {counter for _, counter in counters} | set(rigid)
    guarded = any(
        guard_enums(transition.conditions, index) & interesting
        for machine in machines
        for transition in machine.transitions
    )
    settled = [formula for formula, enums in index.obligation_terms if enums and enums <= set(rigid)]
    watched = [
        formula
        for formula, enums in index.obligation_terms
        if enums and enums <= interesting and not enums <= set(rigid)
    ]
    mixed = [
        (formula, enums)
        for formula, enums in index.obligation_terms
        if enums & interesting and not enums <= interesting
    ]
    pruning = [(formula, enums) for formula, enums in index.premise_terms if enums & interesting]
    if not (machines and (counters or guarded or watched or mixed or pruning or rigid)) and not module.assertions:
        return []
    counter_order = [counter for _, counter in counters]
    limits = {counter: machine.counters[counter] for machine in machines for counter in machine.counters}
    seen: dict[tuple, tuple | None] = {}
    steps: dict[tuple, str] = {}
    findings: list[Finding] = []
    reported_overflow: set[tuple[str, int]] = set()
    violated: set[int] = set()
    broken: set[int] = set()
    behind: dict[tuple, list[tuple]] = {}
    known_worlds: dict[frozenset[str], list[dict[str, str]] | None] = {}
    scopes: dict[int, list[dict[str, str]]] = {}
    for machine in machines:
        for transition in machine.transitions:
            changed = {machine.name, *(counter for counter, _, _ in transition.effects)}
            variables = guard_enums(transition.conditions, index) - interesting
            for _, enums in (*mixed, *pruning):
                if enums & changed:
                    variables |= enums - interesting
            key = frozenset(variables)
            if key not in known_worlds:
                known_worlds[key] = worlds(index, variables) if variables else [{}]
            scope = known_worlds[key]
            if scope is None:
                findings.append(
                    Finding(
                        "TOO_LARGE",
                        f"{transition.source} -> {transition.target} on {transition.event} of {machine.name}"
                        " has too many enum combinations to check against the invariants",
                        transition.line,
                    )
                )
                scope = [{}]
            scopes[id(transition)] = scope
    system = System(machines, counter_order, rigid, interesting, seen, steps, behind)
    describe_path = system.path

    def start_problem(start: dict[str, str]) -> Finding | None:
        for _, enums in mixed:
            scope = worlds(index, enums - interesting)
            if scope is not None and not any(agrees(world, start) for world in scope):
                message = f"no enum values satisfy the invariants at the start ({describe(start)})"
                return Finding("INVARIANT_VIOLATED", message, index.fact_line)
        for formula, enums in pruning:
            scope = worlds(index, enums - interesting) if enums - interesting else [{}]
            if scope is not None and not any(
                agrees(world, start) and evaluate(formula, {**world, **start}, {}, index) for world in scope
            ):
                return Finding("CONTRADICTION", f"the assumptions rule out the start ({describe(start)})", index.fact_line)
        return None

    domains = [index.enums[name].values for name in rigid]
    size = 1
    for domain in domains:
        size *= len(domain)
    if size > SYSTEM_LIMIT:
        return findings + [Finding("TOO_LARGE", "the fixed fields have too many combinations to explore", 0)]
    problems = []
    for fixed in product(*domains):
        initial = (tuple(machine.initial for machine in machines), tuple(0 for _ in counter_order), fixed)
        start = system.assignment(initial)
        if not all(evaluate(formula, start, {}, index) for formula in settled):
            continue
        problem = start_problem(start)
        if problem is None:
            seen[initial] = None
        else:
            problems.append(problem)
    if not seen:
        message = "no values of the fixed fields satisfy the invariants"
        findings.append(problems[0] if problems else Finding("CONTRADICTION", message, index.fact_line))
    queue = deque(seen)

    while queue:
        config = queue.popleft()
        states, values, fixed = config
        assignment = system.assignment(config)
        for position, formula in enumerate(watched):
            if position not in violated and not evaluate(formula, assignment, {}, index):
                violated.add(position)
                findings.append(
                    Finding(
                        "INVARIANT_VIOLATED",
                        f"an invariant over machine states fails after: {describe_path(config)}"
                        f" ({describe(assignment)})",
                        module.invariants[0].line if module.invariants else 0,
                    )
                )
        for number, machine in enumerate(machines):
            for transition in machine.transitions:
                if transition.source != states[number]:
                    continue
                enabling = [
                    world
                    for world in ({**scope, **assignment} for scope in scopes[id(transition)] if agrees(scope, assignment))
                    if all(
                        evaluate(condition, world, {}, index)
                        for condition in transition.conditions
                        if free_enums(condition, index) <= world.keys()
                    )
                ]
                if not enabling:
                    continue
                new_values = list(values)
                overflow = False
                for counter, operator, amount in transition.effects:
                    if counter not in limits:
                        continue
                    position = counter_order.index(counter)
                    if operator == "=":
                        new_values[position] = amount
                    elif new_values[position] + amount > limits[counter]:
                        overflow = True
                        key = (counter, transition.line)
                        if key not in reported_overflow:
                            reported_overflow.add(key)
                            findings.append(
                                Finding(
                                    "OVERFLOW",
                                    f"{counter} can exceed {limits[counter]} on {transition.source} -> {transition.target}"
                                    f" on {transition.event} after: {describe_path(config)}",
                                    transition.line,
                                )
                            )
                    else:
                        new_values[position] += amount
                if overflow:
                    continue
                new_states = list(states)
                new_states[number] = transition.target
                successor = (tuple(new_states), tuple(new_values), fixed)
                after = {machine.name: transition.target}
                after.update({counter: str(value) for counter, value in zip(counter_order, new_values)})
                enabling = [
                    world
                    for world in enabling
                    if all(
                        evaluate(formula, {**world, **after}, {}, index)
                        for formula, enums in pruning
                        if enums <= world.keys()
                    )
                ]
                if not enabling:
                    continue
                behind.setdefault(successor, []).append(config)
                step = f"{machine.name}: {transition.event}"
                for position, (formula, enums) in enumerate(mixed):
                    if position in broken:
                        continue
                    for world in enabling:
                        result = {**world, **after}
                        if enums <= result.keys() and not evaluate(formula, result, {}, index):
                            broken.add(position)
                            path = step if seen[config] is None else f"{describe_path(config)} -> {step}"
                            findings.append(
                                Finding(
                                    "INVARIANT_VIOLATED",
                                    f"an invariant over machine states and enum values fails after: {path}"
                                    f" ({describe(result)})",
                                    transition.line,
                                )
                            )
                            break
                if successor not in seen:
                    seen[successor] = config
                    steps[successor] = f"{machine.name}: {transition.event}"
                    queue.append(successor)
                    if len(seen) > SYSTEM_LIMIT:
                        return findings + [Finding("TOO_LARGE", "the combined state space is too large to explore", 0)]
    for number, machine in enumerate(machines):
        if machine.replica:
            continue
        forward: dict[str, set[str]] = {}
        backward: dict[str, set[str]] = {}
        for transition in machine.transitions:
            forward.setdefault(transition.source, set()).add(transition.target)
            backward.setdefault(transition.target, set()).add(transition.source)
        statically = reachable_from(machine.initial, forward)
        reached = {config[0][number] for config in seen}
        for state in machine.states:
            if state in statically and state not in reached:
                findings.append(
                    Finding("UNREACHABLE", f"state {state} of {machine.name} is never reached once guards and counters are applied", machine.line)
                )
        goals = {machine.initial} if machine.cyclic else set(machine.terminals)
        finishing = {config for config in seen if config[0][number] in goals}
        if not finishing:
            continue
        queue = deque(finishing)
        while queue:
            for previous in behind.get(queue.popleft(), ()):
                if previous not in finishing:
                    finishing.add(previous)
                    queue.append(previous)
        statically_finishing = set().union(*(reachable_from(goal, backward) for goal in goals))
        aim = "return to the initial state" if machine.cyclic else "reach a terminal state"
        for state in machine.states:
            stuck = next((c for c in seen if c[0][number] == state and c not in finishing), None)
            if state in statically_finishing and stuck is not None:
                findings.append(
                    Finding(
                        "TRAP",
                        f"state {state} of {machine.name} cannot {aim} once guards and counters are applied"
                        f" after: {describe_path(stuck)}",
                        machine.line,
                    )
                )
    index.system = system
    return findings


def outer_cans(formula: Formula) -> list[Can]:
    if isinstance(formula, Can):
        return [formula]
    if isinstance(formula, Not):
        return outer_cans(formula.operand)
    if isinstance(formula, (And, Or)):
        return [found for operand in formula.operands for found in outer_cans(operand)]
    if isinstance(formula, Implies):
        return outer_cans(formula.premise) + outer_cans(formula.conclusion)
    if isinstance(formula, ForAll):
        return outer_cans(formula.body)
    return []


def check_assertions(module: Module, index: Index) -> list[Finding]:
    system = index.system
    if not module.assertions:
        return []
    if system is None:
        return [Finding("TOO_LARGE", "the assertions were not checked because the state space is too large", module.assertions[0].line)]
    findings: list[Finding] = []
    scopes: dict[int, list[dict[str, str]] | None] = {}
    can_sets: dict[int, set[tuple]] = {}

    def scope_of(formula: Formula) -> list[dict[str, str]] | None:
        if id(formula) not in scopes:
            variables = free_enums(formula, index) - system.interesting
            scopes[id(formula)] = worlds(index, variables) if variables else [{}]
        return scopes[id(formula)]

    def ground(formula: Formula, config: tuple) -> Formula:
        if isinstance(formula, Can):
            return And([]) if config in can_set(formula) else Or([])
        if isinstance(formula, Not):
            return Not(ground(formula.operand, config))
        if isinstance(formula, (And, Or)):
            return type(formula)([ground(operand, config) for operand in formula.operands])
        if isinstance(formula, Implies):
            return Implies(ground(formula.premise, config), ground(formula.conclusion, config))
        if isinstance(formula, ForAll):
            return ForAll(formula.variable, formula.enum, ground(formula.body, config))
        return formula

    def states_of(formula: Formula, config: tuple) -> list[tuple[dict[str, str], bool]]:
        grounded = ground(formula, config)
        assignment = system.assignment(config)
        return [
            ({**world, **assignment}, evaluate(grounded, {**world, **assignment}, {}, index))
            for world in scope_of(formula) or []
            if agrees(world, assignment)
        ]

    def can_set(formula: Can) -> set[tuple]:
        if id(formula) not in can_sets:
            found = {config for config in system.seen if any(holds for _, holds in states_of(formula.operand, config))}
            queue = deque(found)
            while queue:
                for previous in system.behind.get(queue.popleft(), ()):
                    if previous not in found:
                        found.add(previous)
                        queue.append(previous)
            can_sets[id(formula)] = found
        return can_sets[id(formula)]

    def unscoped(formula: Formula) -> bool:
        return scope_of(formula) is None or any(unscoped(inner.operand) for inner in outer_cans(formula))

    for assertion in module.assertions:
        label = f"assertion {assertion.name}"
        if unscoped(assertion.formula):
            findings.append(Finding("TOO_LARGE", f"{label} has too many enum combinations to enumerate", assertion.line))
            continue
        if assertion.mode == "reachable":
            if not any(holds for config in system.seen for _, holds in states_of(assertion.formula, config)):
                findings.append(Finding("ASSERTION_FAILED", f"{label} holds in no reachable state", assertion.line))
            continue
        failure = next(
            (
                (config, state)
                for config in system.seen
                for state, holds in states_of(assertion.formula, config)
                if not holds
            ),
            None,
        )
        if failure is not None:
            config, state = failure
            where = "at the start" if system.seen[config] is None else f"after: {system.path(config)}"
            findings.append(Finding("ASSERTION_FAILED", f"{label} fails {where} ({describe(state)})", assertion.line))
    return findings


def check_machines(module: Module, index: Index) -> list[Finding]:
    findings = []
    for machine in module.machines:
        if not machine.replica:
            findings.extend(check_machine(machine, index))
    return findings


def scenario_step(
    machine: Machine, state: str, event: str, world: dict[str, str], index: Index
) -> tuple[str, Transition | None]:
    applicable = [
        t
        for t in machine.transitions
        if t.source == state and t.event == event and all(condition_holds(c, world, index) for c in t.conditions)
    ]
    if applicable:
        return "moved", applicable[0]
    ignored = any(
        h.kind == "ignore"
        and h.event == event
        and h.state in (state, "*")
        and all(condition_holds(c, world, index) for c in h.conditions)
        for h in machine.handlings
    )
    return ("ignored" if ignored else "refused"), None


def apply_effects(transition: Transition, counters: dict[str, int]) -> None:
    for counter, operator, amount in transition.effects:
        if counter in counters:
            counters[counter] = amount if operator == "=" else counters[counter] + amount


def check_joint_scenarios(module: Module, index: Index) -> list[Finding]:
    findings = []
    for scenario in module.joint_scenarios:
        names = {*scenario.start, *scenario.expect, *(machine for machine, _ in scenario.events)}
        unknown = sorted(name for name in names if name not in index.machines)
        if unknown:
            findings.append(Finding("UNDEFINED", f"scenario {scenario.name} names {', '.join(unknown)}, which is not a machine", scenario.line))
            continue
        problems = []
        for machine_name, state in (*scenario.start.items(), *scenario.expect.items()):
            if state not in index.machines[machine_name].states:
                problems.append(f"{state} is not a state of {machine_name}")
        for machine_name, event in scenario.events:
            if event not in index.machines[machine_name].events:
                problems.append(f"{event} is not an event of {machine_name}")
        missing = [name for name in index.machines if name in names and name not in scenario.start]
        problems += [f"{name} has no start state" for name in missing]
        if problems:
            findings.append(Finding("UNDEFINED", f"scenario {scenario.name}: {'; '.join(problems)}", scenario.line))
            continue
        states = dict(scenario.start)
        counters = {counter: 0 for name in states for counter in index.machines[name].counters}
        failed = False
        for machine_name, event in scenario.events:
            machine = index.machines[machine_name]
            world = {**states, **{counter: str(value) for counter, value in counters.items()}}
            outcome, transition = scenario_step(machine, states[machine_name], event, world, index)
            if transition is not None:
                states[machine_name] = transition.target
                apply_effects(transition, counters)
            elif outcome != "ignored":
                findings.append(
                    Finding(
                        "SCENARIO_FAILED",
                        f"scenario {scenario.name}: {machine_name}.{event} is not accepted in {states[machine_name]} ({describe(world)})",
                        scenario.line,
                    )
                )
                failed = True
                break
        if not failed:
            differing = [f"{name} is {states[name]} instead of {state}" for name, state in scenario.expect.items() if states[name] != state]
            if differing:
                findings.append(Finding("SCENARIO_FAILED", f"scenario {scenario.name} ends with {'; '.join(differing)}", scenario.line))
    return findings


def check_scenarios(module: Module, index: Index) -> list[Finding]:
    findings = []
    for scenario in module.scenarios:
        machine = index.machines.get(scenario.machine)
        if machine is None:
            findings.append(Finding("UNDEFINED", f"machine {scenario.machine} is not defined", scenario.line))
            continue
        problems = [finding for condition in scenario.given for finding in check_condition(condition, index, scenario.line)]
        if problems:
            findings.extend(problems)
            continue
        names = sorted(guard_enums(scenario.given, index))
        domains = [index.enums[name].values for name in names]
        size = 1
        for domain in domains:
            size *= len(domain)
        if size > ENUMERATION_LIMIT:
            findings.append(Finding("TOO_LARGE", f"scenario {scenario.name} has too many given combinations to enumerate", scenario.line))
            continue
        givens = [
            given
            for given in (dict(zip(names, values)) for values in product(*domains))
            if all(evaluate(condition, given, {}, index) for condition in scenario.given)
        ]
        if not givens:
            findings.append(Finding("SCENARIO_FAILED", f"scenario {scenario.name} is given values that no combination satisfies", scenario.line))
        for given in givens:
            failure = replay(machine, scenario, given, index)
            if failure:
                where = f" when {describe(given)}" if len(givens) > 1 else ""
                findings.append(Finding("SCENARIO_FAILED", f"scenario {scenario.name}{failure}{where}", scenario.line))
                break
    return findings


def replay(machine: Machine, scenario: Scenario, given: dict[str, str], index: Index) -> str:
    counters = {counter: 0 for counter in machine.counters}
    state = scenario.start
    for event in scenario.events:
        world = {**given, **{counter: str(value) for counter, value in counters.items()}}
        outcome, transition = scenario_step(machine, state, event, world, index)
        if transition is not None:
            state = transition.target
            apply_effects(transition, counters)
        elif outcome != "ignored":
            return f": {event} is not accepted in {state}"
    return "" if state == scenario.expect else f" ends in {state} instead of {scenario.expect}"


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
