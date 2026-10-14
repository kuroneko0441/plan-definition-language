"""Guarded actions over finite variables, the form that every clause of a machine lowers to."""

from dataclasses import dataclass

from .model import Formula, Transition


@dataclass(frozen=True)
class Assign:
    value: str


@dataclass(frozen=True)
class Increase:
    amount: int
    ceiling: str


Update = Assign | Increase


@dataclass
class Action:
    label: str
    machine: str
    origin: Transition
    guard: list[Formula]
    updates: list[tuple[str, Update]]
    free: list[str]
    facts: list[Formula]
    after: list[Formula]

    def apply(self, assignment: dict[str, str]) -> tuple[dict[str, str], list[str]]:
        changes: dict[str, str] = {}
        overflowing = []
        for name, update in self.updates:
            if isinstance(update, Assign):
                changes[name] = update.value
                continue
            raised = int(changes.get(name, assignment[name])) + update.amount
            if raised > int(assignment.get(update.ceiling, update.ceiling)):
                overflowing.append(name)
            else:
                changes[name] = str(raised)
        return changes, overflowing
