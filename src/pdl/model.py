"""Syntax tree for the plan definition language."""

from dataclasses import dataclass, field
from typing import Union


@dataclass
class Condition:
    variable: str
    value: str


@dataclass
class EnumDefinition:
    line: int
    name: str
    values: list[str]
    why: str = ""
    label: str = ""
    value_labels: dict[str, str] = field(default_factory=dict)


@dataclass
class EntityDefinition:
    line: int
    name: str
    key: list[str]
    passive: bool
    fields: list[tuple[str, str]]
    why: str = ""
    label: str = ""


@dataclass
class Declaration:
    line: int
    kind: str
    name: str
    label: str = ""


@dataclass
class Rule:
    line: int
    effect: str
    actor: str
    action: str
    resource: str
    conditions: list[Condition]
    requires: str = ""
    why: str = ""


@dataclass
class Exclusion:
    line: int
    left: Condition
    right: Condition


@dataclass
class Transition:
    line: int
    source: str
    target: str
    event: str
    actor: str = ""
    why: str = ""


@dataclass
class Handling:
    line: int
    kind: str
    state: str
    event: str


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


@dataclass
class Scenario:
    line: int
    name: str
    machine: str
    start: str
    events: list[str]
    expect: str


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


@dataclass
class Module:
    name: str
    definitions: list[tuple[str, str, int]] = field(default_factory=list)
    enums: list[EnumDefinition] = field(default_factory=list)
    entities: list[EntityDefinition] = field(default_factory=list)
    declarations: list[Declaration] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    exclusions: list[Exclusion] = field(default_factory=list)
    machines: list[Machine] = field(default_factory=list)
    scenarios: list[Scenario] = field(default_factory=list)
    unknowns: list[Unknown] = field(default_factory=list)
    laws: list[Law] = field(default_factory=list)
