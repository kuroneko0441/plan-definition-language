"""Expansion of entity instances, paths, and quantifiers into formulas over finite variables."""

from dataclasses import dataclass, replace
from typing import assert_never

from .model import (
    And,
    Atom,
    Can,
    EnumDefinition,
    Eventually,
    Exists,
    ForAll,
    Formula,
    Implies,
    InSet,
    Machine,
    Module,
    Not,
    Or,
    Premise,
    Transition,
)

MAXIMUM_SCOPE = 6
NONE = "none"
THIS = "this"

Problem = tuple[str, str, int]


@dataclass(frozen=True)
class Leaf:
    kind: str
    text: str
    type: str = ""
    domain: tuple[str, ...] = ()


class ExpansionError(Exception):
    pass


def truth(value: bool) -> Formula:
    return And([]) if value else Or([])


def conjunction(parts: list[Formula]) -> Formula:
    return parts[0] if len(parts) == 1 else And(parts)


def terms(formula: Formula) -> list[str]:
    if isinstance(formula, Atom):
        return [formula.left, formula.right]
    if isinstance(formula, InSet):
        return [formula.left]
    if isinstance(formula, (Not, Can, Eventually)):
        return terms(formula.operand)
    if isinstance(formula, (And, Or)):
        return [term for operand in formula.operands for term in terms(operand)]
    if isinstance(formula, Implies):
        return terms(formula.premise) + terms(formula.conclusion)
    if isinstance(formula, (ForAll, Exists)):
        return terms(formula.body)
    assert_never(formula)


def quantifiers(formula: Formula) -> list[ForAll | Exists]:
    if isinstance(formula, (ForAll, Exists)):
        return [formula, *quantifiers(formula.body)]
    if isinstance(formula, (Not, Can, Eventually)):
        return quantifiers(formula.operand)
    if isinstance(formula, (And, Or)):
        return [found for operand in formula.operands for found in quantifiers(operand)]
    if isinstance(formula, Implies):
        return quantifiers(formula.premise) + quantifiers(formula.conclusion)
    if isinstance(formula, (Atom, InSet)):
        return []
    assert_never(formula)


class Expander:
    def __init__(self, module: Module):
        self.module = module
        self.problems: list[Problem] = []
        self.entities = {}
        for entity in module.entities:
            self.entities.setdefault(entity.name, entity)
        self.enums = {}
        for enum in module.enums:
            self.enums.setdefault(enum.name, enum)
        self.atoms: dict[str, list[str]] = {}
        for name, count in module.scopes.items():
            line = module.scope_lines[name]
            if name not in self.entities:
                self.problems.append(("UNDEFINED", f"entity {name} of the scope is not defined", line))
            elif not 1 <= count <= MAXIMUM_SCOPE:
                self.problems.append(("TOO_LARGE", f"the scope of {name} must be between 1 and {MAXIMUM_SCOPE}", line))
            else:
                self.atoms[name] = [f"{name}{number}" for number in range(1, count + 1)]
        self.atom_types = {atom: name for name, atoms in self.atoms.items() for atom in atoms}
        self.bound: dict[str, dict[str, Machine]] = {}
        self.constants = {}
        for constant in module.constants:
            self.constants.setdefault(constant.name, constant)
        self.globals = set(self.enums) | set(self.constants)
        for machine in module.machines:
            if machine.entity in self.atoms:
                self.bound.setdefault(machine.entity, {})[machine.name] = machine
            else:
                self.globals |= {machine.name, *machine.counters}
        self.variables: dict[str, EnumDefinition] = {}
        self.rigid: list[str] = []
        self.mutable: dict[str, str] = {}
        self.bounds: list[Premise] = []
        for constant in self.constants.values():
            values = [str(number) for number in range(constant.low, constant.high + 1)]
            self.variables[constant.name] = EnumDefinition(constant.line, constant.name, values)
            self.rigid.append(constant.name)

    def maximum(self, machine: Machine, counter: str) -> int:
        constant = self.constants.get(machine.counter_bounds.get(counter, ""))
        return constant.high if constant is not None else machine.counters[counter]

    def relational(self, formula: Formula) -> bool:
        return (
            any("." in term or term == THIS for term in terms(formula))
            or any(isinstance(found, Exists) or found.enum in self.entities for found in quantifiers(formula))
        )

    def variable(self, atom: str, name: str, line: int) -> Leaf:
        entity = self.atom_types[atom]
        full = f"{atom}.{name}"
        fields = dict(self.entities[entity].fields)
        machines = self.bound.get(entity, {})
        if name in fields:
            base = fields[name].removesuffix("?")
            if base in self.enums:
                domain = list(self.enums[base].values)
            elif base in self.atoms:
                domain = list(self.atoms[base])
            elif base in self.entities:
                raise ExpansionError(f"{entity}.{name} refers to {base}, which has no scope")
            else:
                raise ExpansionError(f"{entity}.{name} has the type {fields[name]}, which a formula cannot read")
            if fields[name].endswith("?"):
                domain.append(NONE)
            self.variables.setdefault(full, EnumDefinition(line, full, domain))
            if name in self.entities[entity].fixed and full not in self.rigid:
                self.rigid.append(full)
            start = self.entities[entity].starts.get(name)
            if start is not None and start not in domain:
                raise ExpansionError(f"initial value {start} is not a value of {entity}.{name}")
            if start is not None:
                self.mutable[full] = start
            return Leaf("var", full, base, tuple(domain))
        if name in machines:
            return Leaf("var", full, f"{entity}.{name}", tuple(machines[name].states))
        for machine in machines.values():
            if name in machine.counters:
                values = tuple(str(number) for number in range(self.maximum(machine, name) + 1))
                return Leaf("var", full, "counter", values)
        raise ExpansionError(f"{entity} has no field, machine, or counter named {name}")

    def expand_term(self, text: str, environment: dict[str, Leaf], line: int) -> list[tuple[list[Formula], Leaf]]:
        head, *rest = text.split(".")
        if head in environment:
            leaf = environment[head]
        elif head in self.atom_types:
            leaf = Leaf("const", head, self.atom_types[head])
        elif not rest:
            return [([], Leaf("name", head))]
        else:
            raise ExpansionError(f"{head} in {text} is not a bound variable or an entity instance")
        results: list[tuple[list[Formula], Leaf]] = [([], leaf)]
        for name in rest:
            following = []
            for conditions, leaf in results:
                if leaf.type not in self.atoms:
                    raise ExpansionError(f"{name} in {text} is read from a value that is not an entity instance")
                if leaf.kind == "const":
                    following.append((conditions, self.variable(leaf.text, name, line)))
                    continue
                for value in leaf.domain:
                    if value != NONE:
                        step = [*conditions, Atom(leaf.text, "=", value)]
                        following.append((step, self.variable(value, name, line)))
            results = following
        return results

    def equal(self, left: Leaf, right: Leaf) -> Formula:
        if left.kind == "name" and right.kind == "name":
            return Atom(left.text, "=", right.text)
        if left.kind != "var" and right.kind == "var" or left.kind == "name":
            left, right = right, left
        if left.kind == "var" and right.kind == "var":
            if left.type != right.type:
                raise ExpansionError(f"{left.text} and {right.text} hold values of different types")
            shared = [value for value in left.domain if value in right.domain and value != NONE]
            return Or([And([Atom(left.text, "=", value), Atom(right.text, "=", value)]) for value in shared])
        if left.kind == "var":
            if right.text not in left.domain:
                raise ExpansionError(f"{right.text} is not a value of {left.text}")
            return Atom(left.text, "=", right.text)
        if right.kind == "name" and right.text in self.globals:
            return Atom(right.text, "=", left.text)
        return truth(left.text == right.text)

    def compare(self, formula: Atom, environment: dict[str, Leaf], line: int) -> Formula:
        ordered = formula.operator not in ("=", "!=")
        cases = [
            conjunction(
                [
                    *left_conditions,
                    *right_conditions,
                    Atom(left.text, formula.operator, right.text) if ordered else self.equal(left, right),
                ]
            )
            for left_conditions, left in self.expand_term(formula.left, environment, line)
            for right_conditions, right in self.expand_term(formula.right, environment, line)
        ]
        result = cases[0] if len(cases) == 1 else Or(cases)
        if ordered:
            return result
        if formula.operator == "=":
            return result
        if isinstance(result, Atom):
            return Atom(result.left, "!=", result.right)
        return Not(result)

    def member(self, formula: InSet, environment: dict[str, Leaf], line: int) -> Formula:
        cases = []
        for conditions, leaf in self.expand_term(formula.left, environment, line):
            if leaf.kind == "var":
                for value in formula.values:
                    if value not in leaf.domain:
                        raise ExpansionError(f"{value} is not a value of {leaf.text}")
                core: Formula = InSet(leaf.text, formula.values)
            elif leaf.kind == "const":
                core = truth(leaf.text in formula.values)
            else:
                core = InSet(leaf.text, formula.values)
            cases.append(conjunction([*conditions, core]))
        return cases[0] if len(cases) == 1 else Or(cases)

    def expand(self, formula: Formula, environment: dict[str, Leaf], line: int) -> Formula:
        if isinstance(formula, Atom):
            return self.compare(formula, environment, line)
        if isinstance(formula, InSet):
            return self.member(formula, environment, line)
        if isinstance(formula, (Not, Can, Eventually)):
            return type(formula)(self.expand(formula.operand, environment, line))
        if isinstance(formula, (And, Or)):
            return type(formula)([self.expand(operand, environment, line) for operand in formula.operands])
        if isinstance(formula, Implies):
            return Implies(
                self.expand(formula.premise, environment, line), self.expand(formula.conclusion, environment, line)
            )
        if not isinstance(formula, (ForAll, Exists)):
            assert_never(formula)
        if formula.enum in self.atoms:
            values = self.atoms[formula.enum]
        elif formula.enum in self.enums:
            values = self.enums[formula.enum].values
        elif formula.enum in self.entities:
            raise ExpansionError(f"entity {formula.enum} of the quantifier has no scope")
        else:
            raise ExpansionError(f"{formula.enum} of the quantifier is not an enum or an entity")
        bodies = [
            self.expand(formula.body, {**environment, formula.variable: Leaf("const", value, formula.enum)}, line)
            for value in values
        ]
        return And(bodies) if isinstance(formula, ForAll) else Or(bodies)

    def formula(self, formula: Formula, environment: dict[str, Leaf], line: int) -> Formula:
        if not environment and not self.relational(formula):
            return formula
        try:
            return self.expand(formula, environment, line)
        except ExpansionError as error:
            self.problems.append(("UNDEFINED", str(error), line))
            return truth(True)

    def formulas(self, formulas: list[Formula], environment: dict[str, Leaf], line: int) -> list[Formula]:
        return [self.formula(formula, environment, line) for formula in formulas]

    def updates(self, transition: Transition, environment: dict[str, Leaf]) -> list[tuple[str, str]]:
        resolved = []
        for path, value in transition.updates:
            try:
                cases = self.expand_term(path, environment, transition.line)
                conditions, leaf = cases[0]
                if len(cases) > 1 or conditions or leaf.kind != "var":
                    raise ExpansionError(f"{path} is not a field of this or of an entity instance")
                if leaf.text not in self.mutable:
                    raise ExpansionError(f"{path} is not a var field, so a clause cannot set it")
                if value not in leaf.domain:
                    raise ExpansionError(f"{value} is not a value of {path}")
                resolved.append((leaf.text, value))
            except ExpansionError as error:
                self.problems.append(("UNDEFINED", str(error), transition.line))
        return resolved

    def machine(self, machine: Machine, atom: str, replica: bool) -> Machine:
        prefix = f"{atom}." if atom else ""
        environment: dict[str, Leaf] = {}
        if atom:
            environment[THIS] = Leaf("const", atom, machine.entity)
            for counter in machine.counters:
                values = tuple(str(number) for number in range(self.maximum(machine, counter) + 1))
                environment[counter] = Leaf("var", prefix + counter, "counter", values)
        for counter, constant in machine.counter_bounds.items():
            if constant in self.constants:
                self.bounds.append(Premise(machine.line, "", Atom(prefix + counter, "<=", constant)))
            elif not replica:
                self.problems.append(("UNDEFINED", f"maximum {constant} of counter {counter} is not a constant", machine.line))
        return replace(
            machine,
            name=prefix + machine.name,
            replica=replica,
            counters={prefix + counter: self.maximum(machine, counter) for counter in machine.counters},
            counter_bounds={prefix + counter: constant for counter, constant in machine.counter_bounds.items()},
            transitions=[
                replace(
                    transition,
                    conditions=self.formulas(transition.conditions, environment, transition.line),
                    updates=self.updates(transition, environment),
                    effects=[
                        (prefix + counter if counter in machine.counters else counter, operator, amount)
                        for counter, operator, amount in transition.effects
                    ],
                )
                for transition in machine.transitions
            ],
            handlings=[
                replace(handling, conditions=self.formulas(handling.conditions, environment, handling.line))
                for handling in machine.handlings
            ],
        )

    def module_machines(self) -> list[Machine]:
        machines = []
        for machine in self.module.machines:
            if not machine.entity:
                machines.append(self.machine(machine, "", False))
            elif machine.entity in self.atoms:
                atoms = self.atoms[machine.entity]
                machines += [self.machine(machine, atom, atom != atoms[0]) for atom in atoms]
            else:
                reason = "has no scope" if machine.entity in self.entities else "is not defined"
                self.problems.append(("UNDEFINED", f"entity {machine.entity} of machine {machine.name} {reason}", machine.line))
                machines.append(self.machine(replace(machine, entity=""), "", False))
        return machines

    def first(self, entity: str) -> dict[str, Leaf]:
        if entity not in self.atoms:
            return {}
        return {THIS: Leaf("const", self.atoms[entity][0], entity)}


def expand(module: Module) -> tuple[Module, list[Problem]]:
    expander = Expander(module)
    templates = {machine.name: machine for machine in module.machines if machine.entity in expander.atoms}
    scenarios = []
    for scenario in module.scenarios:
        template = templates.get(scenario.machine)
        if template is None:
            scenarios.append(replace(scenario, given=expander.formulas(scenario.given, {}, scenario.line)))
            continue
        environment = expander.first(template.entity)
        scenarios.append(
            replace(
                scenario,
                machine=f"{environment[THIS].text}.{scenario.machine}",
                given=expander.formulas(scenario.given, environment, scenario.line),
            )
        )
    expanded = replace(
        module,
        machines=expander.module_machines(),
        scenarios=scenarios,
        rules=[
            replace(rule, conditions=expander.formulas(rule.conditions, expander.first(rule.resource), rule.line))
            for rule in module.rules
        ],
        exclusions=[
            replace(
                exclusion,
                left=expander.formula(exclusion.left, {}, exclusion.line),
                right=expander.formula(exclusion.right, {}, exclusion.line),
            )
            for exclusion in module.exclusions
        ],
        invariants=[replace(item, formula=expander.formula(item.formula, {}, item.line)) for item in module.invariants],
        premises=[replace(item, formula=expander.formula(item.formula, {}, item.line)) for item in module.premises]
        + expander.bounds,
        assertions=[replace(item, formula=expander.formula(item.formula, {}, item.line)) for item in module.assertions],
    )
    expanded.variables = list(expander.variables.values())
    expanded.rigid = expander.rigid
    expanded.mutable = expander.mutable
    return expanded, expander.problems
