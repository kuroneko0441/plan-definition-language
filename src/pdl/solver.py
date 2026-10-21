"""Z3 queries that replace enumeration when a check is too large to enumerate."""

import operator
from collections.abc import Sequence
from typing import assert_never

import z3
from z3 import z3util

from .kernel import Action, Assign
from .model import (
    And,
    Atom,
    Call,
    Can,
    Eventually,
    Exists,
    ForAll,
    Formula,
    Implies,
    InSet,
    Law,
    Not,
    Or,
    Reference,
    Term,
    is_number,
)

ORDERINGS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}
# Milliseconds per query, so a query that z3 cannot finish ends as undecided instead of running without end.
TIMEOUT = 30000
Environment = dict[str, z3.ArithRef]
Constraint = z3.BoolRef | z3.Probe | bool
Number = z3.ArithRef | int


class Undecided(Exception):
    """Raised when z3 answers unknown, so no caller reads the answer as a pass."""


def timed_solver() -> z3.Solver:
    created = z3.Solver()
    created.set("timeout", TIMEOUT)
    return created


def decide(answer: z3.CheckSatResult) -> bool:
    if answer == z3.unknown:
        raise Undecided
    return answer == z3.sat


class Encoder:
    def __init__(self, enums: dict[str, list[str]]):
        self.enums = enums

    def domain(self, name: str, variable: z3.ArithRef) -> Constraint:
        return z3.And(variable >= 0, variable < len(self.enums[name]))

    def side(self, term: str, environment: Environment, bound: dict[str, str]) -> tuple[bool, str]:
        if term in bound:
            return False, bound[term]
        return term in environment, term

    def number(self, variable: bool, text: str, environment: Environment) -> Number | None:
        if not variable:
            return z3.IntVal(int(text)) if is_number(text) else None
        values = self.enums[text]
        if not all(is_number(value) for value in values):
            return None
        return z3.Sum([z3.If(environment[text] == position, int(value), 0) for position, value in enumerate(values)])

    def equal(self, left: tuple[bool, str], right: tuple[bool, str], environment: Environment) -> Constraint:
        if not left[0] and right[0]:
            left, right = right, left
        if not left[0]:
            return z3.BoolVal(left[1] == right[1])
        values = self.enums[left[1]]
        if not right[0]:
            return environment[left[1]] == values.index(right[1]) if right[1] in values else z3.BoolVal(False)
        return z3.Or(
            [
                z3.And(environment[left[1]] == position, environment[right[1]] == other)
                for position, value in enumerate(values)
                for other, candidate in enumerate(self.enums[right[1]])
                if value == candidate
            ]
        )

    def encode(self, formula: Formula, environment: Environment, bound: dict[str, str] | None = None) -> Constraint:
        bound = bound or {}
        if isinstance(formula, Atom):
            left = self.side(formula.left, environment, bound)
            right = self.side(formula.right, environment, bound)
            if formula.operator in ORDERINGS:
                smaller = self.number(*left, environment)
                larger = self.number(*right, environment)
                if smaller is None or larger is None:
                    return z3.BoolVal(False)
                return ORDERINGS[formula.operator](smaller, larger)
            same = self.equal(left, right, environment)
            return same if formula.operator == "=" else z3.Not(same)
        if isinstance(formula, InSet):
            variable, text = self.side(formula.left, environment, bound)
            if not variable:
                return z3.BoolVal(text in formula.values)
            values = self.enums[text]
            return z3.Or([environment[text] == values.index(value) for value in formula.values if value in values])
        if isinstance(formula, Not):
            return z3.Not(self.encode(formula.operand, environment, bound))
        if isinstance(formula, And):
            return z3.And([self.encode(operand, environment, bound) for operand in formula.operands])
        if isinstance(formula, Or):
            return z3.Or([self.encode(operand, environment, bound) for operand in formula.operands])
        if isinstance(formula, Implies):
            return z3.Implies(
                self.encode(formula.premise, environment, bound), self.encode(formula.conclusion, environment, bound)
            )
        if isinstance(formula, ForAll):
            values = self.enums.get(formula.enum, [])
            return z3.And([self.encode(formula.body, environment, {**bound, formula.variable: value}) for value in values])
        if isinstance(formula, (Exists, Can, Eventually)):
            raise TypeError(f"{type(formula).__name__} has no value in a single state")
        assert_never(formula)


def smallest_model(
    solver: z3.Solver, encoder: Encoder, names: list[str], environment: Environment
) -> dict[str, str]:
    assignment = {}
    for name in names:
        for position, value in enumerate(encoder.enums[name]):
            solver.push()
            solver.add(environment[name] == position)
            if decide(solver.check()):
                assignment[name] = value
                break
            solver.pop()
    return assignment


def find_world(enums: dict[str, list[str]], formulas: list[Formula], names: list[str]) -> dict[str, str] | None:
    encoder = Encoder(enums)
    environment = {name: z3.Int(name) for name in names}
    solver = timed_solver()
    for name, variable in environment.items():
        solver.add(encoder.domain(name, variable))
    for formula in formulas:
        solver.add(encoder.encode(formula, environment))
    if not decide(solver.check()):
        return None
    return smallest_model(solver, encoder, names, environment)


Block = tuple[list[str], list[Formula]]


class TransitionSystem:
    def __init__(
        self, enums: dict[str, list[str]], states: list[str], start: dict[str, str], openings: list[Block], steps: list[Action]
    ):
        self.encoder = Encoder(enums)
        self.states = states
        self.start = start
        self.openings = openings
        self.steps = steps
        self.fresh = 0

    def frame(self, tag: str) -> Environment:
        return {name: z3.Int(f"{name}@{tag}") for name in self.states}

    def bounded(self, environment: Environment) -> list[Constraint]:
        return [self.encoder.domain(name, variable) for name, variable in environment.items()]

    def block(self, block: Block, environment: Environment) -> tuple[list[Constraint], Environment]:
        names, formulas = block
        self.fresh += 1
        world = {name: z3.Int(f"{name}#{self.fresh}") for name in names}
        merged = {**environment, **world}
        return [*self.bounded(world), *(self.encoder.encode(formula, merged) for formula in formulas)], world

    def opening(self, environment: Environment) -> list[Constraint]:
        values = self.encoder.enums
        constraints = [environment[name] == values[name].index(value) for name, value in self.start.items()]
        for block in self.openings:
            constraints += self.block(block, environment)[0]
        return [*self.bounded(environment), *constraints]

    def move(self, action: Action, before: Environment, after: Environment) -> list[Constraint]:
        values = self.encoder.enums
        constraints, world = self.block((action.free, [*action.facts, *action.guard]), before)
        constraints.append(before[action.machine] == values[action.machine].index(action.origin.source))
        constraints += [self.encoder.encode(formula, {**after, **world}) for formula in action.after]
        changed: dict[str, Number] = {}
        for name, update in action.updates:
            if isinstance(update, Assign):
                # A value outside the domain gets a position that no variable can hold.
                known = update.value in values[name]
                changed[name] = values[name].index(update.value) if known else len(values[name])
                continue
            limit = self.encoder.number(not is_number(update.ceiling), update.ceiling, before)
            changed[name] = changed.get(name, before[name]) + update.amount
            constraints.append(z3.BoolVal(False) if limit is None else changed[name] <= limit)
        constraints += [after[name] == changed.get(name, before[name]) for name in self.states]
        return [*self.bounded(after), *constraints]

    def reachable(self, bad: Block) -> bool | None:
        fixedpoint = z3.Fixedpoint()
        fixedpoint.set(engine="spacer", timeout=TIMEOUT)
        reach = z3.Function("reach", *[z3.IntSort()] * len(self.states), z3.BoolSort())
        failure = z3.Function("failure", z3.BoolSort())
        fixedpoint.register_relation(reach, failure)
        before, after = self.frame("before"), self.frame("after")

        def rule(head: z3.ExprRef, body: Sequence[z3.ExprRef | Constraint]) -> None:
            implication = z3.Implies(z3.And(body), head)
            variables = [variable for variable in z3util.get_vars(implication) if z3.is_int(variable)]
            fixedpoint.add_rule(z3.ForAll(variables, implication) if variables else implication)

        rule(reach(*before.values()), self.opening(before))
        for step in self.steps:
            rule(reach(*after.values()), [reach(*before.values()), *self.move(step, before, after)])
        rule(failure(), [reach(*before.values()), *self.block(bad, before)[0]])
        answer = fixedpoint.query(failure())
        return None if answer == z3.unknown else answer == z3.sat

    def witness(self, bad: Block) -> tuple[list[str], dict[str, str]]:
        solver = timed_solver()
        frames = [self.frame("0")]
        choices: list[z3.ArithRef] = []
        solver.add(self.opening(frames[0]))
        while True:
            solver.push()
            constraints, world = self.block(bad, frames[-1])
            solver.add(constraints)
            if decide(solver.check()):
                break
            solver.pop()
            choice = z3.Int(f"choice@{len(choices)}")
            following = self.frame(str(len(frames)))
            solver.add(choice >= 0, choice < len(self.steps))
            for position, step in enumerate(self.steps):
                solver.add(z3.Implies(choice == position, z3.And(self.move(step, frames[-1], following))))
            choices.append(choice)
            frames.append(following)
        path = []
        for choice in choices:
            for position, step in enumerate(self.steps):
                solver.push()
                solver.add(choice == position)
                if decide(solver.check()):
                    path.append(step.label)
                    break
                solver.pop()
        final = {**frames[-1], **world}
        return path, smallest_model(solver, self.encoder, sorted(final), final)

    def reach(self, bad: Block) -> tuple[list[str], dict[str, str]] | bool:
        answer = self.reachable(bad)
        if answer is None:
            return True
        if not answer:
            return False
        try:
            return self.witness(bad)
        except Undecided:
            return True


def term_text(term: Term) -> str:
    if isinstance(term, Reference):
        return f"{term.entity}.{term.attribute}"
    return f"{term.function}({term_text(term.argument)})"


def conflicting_laws(laws: list[Law]) -> list[Law]:
    months: dict[str, tuple[z3.ArithRef, z3.ArithRef]] = {}

    def value(term: Term) -> z3.ArithRef:
        if isinstance(term, Reference):
            return z3.Int(term_text(term))
        argument = value(term.argument)
        if term.function == "next":
            return argument + 1
        if term.function == "before":
            return argument - 1
        return months.setdefault(term_text(term), (argument, z3.Int(term_text(term))))[1]

    constraints = [
        {"=": operator.eq, **ORDERINGS}[law.operator](value(law.left), value(law.right)) for law in laws
    ]
    # month_of is monotone, which is all the laws can observe of it.
    ordering = [
        z3.Implies(day <= other_day, month <= other_month)
        for day, month in months.values()
        for other_day, other_month in months.values()
    ]

    def consistent(kept: list[int]) -> bool:
        solver = timed_solver()
        solver.add(ordering)
        solver.add([constraints[position] for position in kept])
        return decide(solver.check())

    kept = list(range(len(laws)))
    if consistent(kept):
        return []
    for position in range(len(laws)):
        without = [other for other in kept if other != position]
        if not consistent(without):
            kept = without
    return [laws[position] for position in kept]
