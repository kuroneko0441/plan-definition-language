"""Syntax tree for the plan definition language."""

from dataclasses import dataclass, field
from typing import Union


@dataclass
class EnumDefinition:
    line: int
    name: str
    values: list[str]
    why: str = ""
    label: str = ""
    value_labels: dict[str, str] = field(default_factory=dict)
    stored: dict[str, str] = field(default_factory=dict)


@dataclass
class EntityDefinition:
    line: int
    name: str
    key: list[str]
    passive: bool
    fields: list[tuple[str, str]]
    why: str = ""
    label: str = ""
    field_notes: dict[str, str] = field(default_factory=dict)
    field_labels: dict[str, str] = field(default_factory=dict)
    fixed: list[str] = field(default_factory=list)


@dataclass
class TermDefinition:
    line: int
    name: str
    why: str = ""
    label: str = ""


@dataclass
class Derivation:
    line: int
    name: str
    entity: str
    source: str
    mixed: str
    label: str = ""
    mixed_label: str = ""
    why: str = ""
    assumes: list[str] = field(default_factory=list)
    type: str = ""
    sources: list[str] = field(default_factory=list)


@dataclass
class Screen:
    line: int
    name: str
    entity: str
    shows: list[str]
    label: str = ""
    why: str = ""
    assumes: list[str] = field(default_factory=list)


@dataclass
class Declaration:
    line: int
    kind: str
    name: str
    label: str = ""
    performed_by: list[str] = field(default_factory=list)
    applies_to: list[str] = field(default_factory=list)


@dataclass
class Rule:
    line: int
    effect: str
    actor: str
    action: str
    resource: str
    conditions: list["Formula"]
    requires: str = ""
    why: str = ""
    assumes: list[str] = field(default_factory=list)


@dataclass
class Exclusion:
    line: int
    left: "Formula"
    right: "Formula"


@dataclass
class Transition:
    line: int
    source: str
    target: str
    event: str
    actors: list[str] = field(default_factory=list)
    why: str = ""
    assumes: list[str] = field(default_factory=list)
    conditions: list["Formula"] = field(default_factory=list)
    effects: list[tuple[str, str, int]] = field(default_factory=list)
    after: str = ""

    @property
    def actor(self) -> str:
        return ", ".join(self.actors)


@dataclass
class Handling:
    line: int
    kind: str
    state: str
    event: str
    why: str = ""
    assumes: list[str] = field(default_factory=list)
    conditions: list["Formula"] = field(default_factory=list)


@dataclass
class Machine:
    line: int
    name: str
    states: list[str] = field(default_factory=list)
    initial: str = ""
    terminals: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    handlings: list[Handling] = field(default_factory=list)
    label: str = ""
    state_labels: dict[str, str] = field(default_factory=dict)
    event_labels: dict[str, str] = field(default_factory=dict)
    cyclic: bool = False
    why: str = ""
    counters: dict[str, int] = field(default_factory=dict)
    counter_labels: dict[str, str] = field(default_factory=dict)
    entity: str = ""
    replica: bool = False
    counter_bounds: dict[str, str] = field(default_factory=dict)


@dataclass
class Scenario:
    line: int
    name: str
    machine: str
    start: str
    events: list[str]
    expect: str
    given: list["Formula"] = field(default_factory=list)


@dataclass
class JointScenario:
    line: int
    name: str
    start: dict[str, str]
    events: list[tuple[str, str]]
    expect: dict[str, str]


@dataclass
class Unknown:
    line: int
    policy: str
    identifier: str
    attributes: dict[str, str]


@dataclass
class Reference:
    entity: str
    attribute: str


@dataclass
class Call:
    function: str
    argument: "Term"


Term = Union[Reference, Call]


@dataclass
class Law:
    line: int
    identifier: str
    left: Term
    operator: str
    right: Term
    why: str = ""
    assumes: list[str] = field(default_factory=list)


@dataclass
class Atom:
    left: str
    operator: str
    right: str


@dataclass
class InSet:
    left: str
    values: list[str]


@dataclass
class Not:
    operand: "Formula"


@dataclass
class And:
    operands: list["Formula"]


@dataclass
class Or:
    operands: list["Formula"]


@dataclass
class Implies:
    premise: "Formula"
    conclusion: "Formula"


@dataclass
class ForAll:
    variable: str
    enum: str
    body: "Formula"


@dataclass
class Exists:
    variable: str
    enum: str
    body: "Formula"


@dataclass
class Can:
    operand: "Formula"


Formula = Union[Atom, InSet, Not, And, Or, Implies, ForAll, Exists, Can]


@dataclass
class Invariant:
    line: int
    name: str
    formula: Formula
    why: str = ""


@dataclass
class Constant:
    line: int
    name: str
    low: int
    high: int
    label: str = ""
    why: str = ""
    assumes: list[str] = field(default_factory=list)


@dataclass
class Premise:
    line: int
    name: str
    formula: Formula
    why: str = ""


@dataclass
class Assertion:
    line: int
    name: str
    mode: str
    formula: Formula
    why: str = ""


@dataclass
class Module:
    name: str
    label: str = ""
    imports: list[tuple[int, str]] = field(default_factory=list)
    definitions: list[tuple[str, str, int]] = field(default_factory=list)
    terms: list[TermDefinition] = field(default_factory=list)
    enums: list[EnumDefinition] = field(default_factory=list)
    entities: list[EntityDefinition] = field(default_factory=list)
    derivations: list[Derivation] = field(default_factory=list)
    screens: list[Screen] = field(default_factory=list)
    declarations: list[Declaration] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    exclusions: list[Exclusion] = field(default_factory=list)
    invariants: list[Invariant] = field(default_factory=list)
    premises: list[Premise] = field(default_factory=list)
    assertions: list[Assertion] = field(default_factory=list)
    machines: list[Machine] = field(default_factory=list)
    scenarios: list[Scenario] = field(default_factory=list)
    joint_scenarios: list[JointScenario] = field(default_factory=list)
    unknowns: list[Unknown] = field(default_factory=list)
    laws: list[Law] = field(default_factory=list)
    constants: list[Constant] = field(default_factory=list)
    scopes: dict[str, int] = field(default_factory=dict)
    scope_lines: dict[str, int] = field(default_factory=dict)
    variables: list[EnumDefinition] = field(default_factory=list)
    rigid: list[str] = field(default_factory=list)
