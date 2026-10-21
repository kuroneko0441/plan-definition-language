"""Tokenizer and parser for plan definition language source text."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple, TypeVar

from .model import (
    And,
    Assertion,
    Atom,
    Call,
    Can,
    Constant,
    Declaration,
    Derivation,
    EntityDefinition,
    EnumDefinition,
    Eventually,
    Exists,
    ForAll,
    Formula,
    Function,
    Handling,
    Implies,
    InSet,
    Invariant,
    JointScenario,
    Law,
    Machine,
    Module,
    Not,
    Or,
    Predicate,
    Premise,
    Reference,
    Rule,
    Scenario,
    Screen,
    Term,
    TermDefinition,
    Transition,
    Unknown,
    is_number,
)

TOKEN_PATTERN = re.compile(
    r"(?P<space>\s+)"
    r"|(?P<comment>#[^\n]*)"
    r"|(?P<string>\"(?:[^\"\\]|\\.)*\")"
    r"|(?P<symbol>->|→|<=|>=|≤|≥|=>|⇒|!=|≠|\.\.|∧|∨|¬|∀|∃|∈|[{}(),:=|*<>.;?+&!@'])"
    r"|(?P<word>\w+)"
)
SYMBOL_ALIASES = {"→": "->", "≤": "<=", "≥": ">=", "⇒": "=>", "≠": "!=", "∧": "&", "∨": "|", "¬": "!"}
WORD_ALIASES = {"∀": "all", "∃": "some", "∈": "in"}
COMPARISON_OPERATORS = ("=", "!=", "<", "<=", ">", ">=")
LAW_OPERATORS = ("=", "<", ">", "<=", ">=")
TEXT_ATTRIBUTES = ("why", "stored", "after", "mixed")
UNKNOWN_POLICIES = ("structure", "value")
UNKNOWN_ATTRIBUTES = ("label", "source", "provisional", "verified", "open")
UNKNOWN_FLAGS = ("verified", "open")
IMPORTED_KINDS = ("enum", "entity", "term", "actor", "action", "external", "permission", "unknown")
LABELED = (TermDefinition, EnumDefinition, EntityDefinition, Declaration, Machine, Constant, Derivation, Screen)


Parsed = TypeVar("Parsed")


class PdlSyntaxError(Exception):
    def __init__(self, line: int, message: str, path: Path | None = None):
        super().__init__(f"line {line}: {message}")
        self.line = line
        self.message = message
        self.path = path


class Token(NamedTuple):
    kind: str
    value: str
    line: int


@dataclass
class Clause:
    line: int
    guard: list[Formula]
    kind: str
    target: str = ""
    effects: list[tuple[str, str, int]] = field(default_factory=list)
    updates: list[tuple[str, str]] = field(default_factory=list)
    actors: list[str] | None = None
    assumes: list[str] = field(default_factory=list)
    tag: str = ""


@dataclass
class Block:
    line: int
    machine: str
    event: str
    actors: list[str]
    clauses: list[Clause]


@dataclass
class Run:
    line: int
    name: str
    start: list[Formula]
    events: list[tuple[str, str]]
    expect: list[Formula]


@dataclass
class TextEntry:
    line: int
    key: list[str]
    attributes: dict[str, str]


def tokenize(text: str, offset: int = 0) -> list[Token]:
    tokens: list[Token] = []
    position = 0
    line = offset + 1
    while position < len(text):
        match = TOKEN_PATTERN.match(text, position)
        if match is None:
            raise PdlSyntaxError(line, f"unexpected character {text[position]!r}")
        kind = match.lastgroup
        value = match.group()
        if kind == "string":
            tokens.append(Token("string", value[1:-1].replace('\\"', '"'), line))
        elif kind == "symbol" and value in WORD_ALIASES:
            tokens.append(Token("word", WORD_ALIASES[value], line))
        elif kind == "symbol":
            tokens.append(Token("symbol", SYMBOL_ALIASES.get(value, value), line))
        elif kind == "word":
            tokens.append(Token("word", value, line))
        line += value.count("\n")
        position = match.end()
    return tokens


def conjuncts(formula: Formula) -> list[Formula]:
    return list(formula.operands) if isinstance(formula, And) else [formula]


def source_states(condition: Formula, machine: Machine) -> list[str] | None:
    if isinstance(condition, Atom) and condition.left == machine.name and condition.operator == "=":
        return [condition.right]
    if isinstance(condition, Atom) and condition.left == machine.name and condition.operator == "!=":
        return [state for state in machine.states if state != condition.right]
    if isinstance(condition, InSet) and condition.left == machine.name:
        return condition.values
    # A compound guard with a misspelled state stays a condition, so the condition check reports the name.
    if isinstance(condition, Not):
        inner = source_states(condition.operand, machine)
        if inner is None or not set(inner) <= set(machine.states):
            return None
        return [state for state in machine.states if state not in inner]
    if isinstance(condition, (And, Or)) and condition.operands:
        parts = [source_states(operand, machine) for operand in condition.operands]
        if any(part is None or not set(part) <= set(machine.states) for part in parts):
            return None
        if isinstance(condition, Or):
            return [state for state in machine.states if any(state in part for part in parts if part is not None)]
        return [state for state in machine.states if all(state in part for part in parts if part is not None)]
    return None


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.index = 0
        self.temporal = False
        self.blocks: list[Block] = []
        self.runs: list[Run] = []
        self.texts: list[TextEntry] = []
        self.tags: dict[tuple[str, ...], list] = {}
        self.named_texts: dict[str, int] = {}
        self.shorthands: dict[str, tuple[str, int]] = {}
        for position, token in enumerate(tokens[:-2]):
            named = tokens[position + 1].kind == "word" and tokens[position + 2].value == "("
            if token.kind == "word" and token.value in ("pred", "fun") and named:
                self.shorthands.setdefault(tokens[position + 1].value, (token.value, position + 2))
        self.arguments: dict[str, str] = {}
        self.expanding: list[str] = []

    def peek(self, offset: int = 0) -> Token | None:
        position = self.index + offset
        return self.tokens[position] if position < len(self.tokens) else None

    def advance(self) -> Token:
        token = self.peek()
        if token is None:
            line = self.tokens[-1].line if self.tokens else 1
            raise PdlSyntaxError(line, "unexpected end of input")
        self.index += 1
        return token

    def at(self, value: str, offset: int = 0) -> bool:
        token = self.peek(offset)
        return token is not None and token.kind != "string" and token.value == value

    def accept(self, value: str) -> bool:
        if self.at(value):
            self.index += 1
            return True
        return False

    def expect(self, value: str) -> Token:
        token = self.advance()
        if token.kind == "string" or token.value != value:
            raise PdlSyntaxError(token.line, f"expected {value!r} but found {token.value!r}")
        return token

    def word(self) -> str:
        token = self.advance()
        if token.kind != "word":
            raise PdlSyntaxError(token.line, f"expected a name but found {token.value!r}")
        return token.value

    def string(self) -> str:
        token = self.advance()
        if token.kind != "string":
            raise PdlSyntaxError(token.line, f"expected a quoted string but found {token.value!r}")
        return token.value

    def number(self) -> int:
        token = self.advance()
        if token.kind != "word" or not is_number(token.value):
            raise PdlSyntaxError(token.line, f"expected a number but found {token.value!r}")
        return int(token.value)

    def name_or_star(self) -> str:
        return "*" if self.accept("*") else self.word()

    def comma_words(self) -> list[str]:
        words = [self.word()]
        while self.accept(","):
            words.append(self.word())
        return words

    def braced_words(self) -> list[str]:
        self.expect("{")
        words = [] if self.at("}") else self.comma_words()
        self.expect("}")
        return words

    def parenthesized_words(self) -> list[str]:
        self.expect("(")
        words = self.comma_words()
        self.expect(")")
        return words

    def assumptions(self) -> list[str]:
        return self.comma_words() if self.accept("assuming") else []

    def parameters(self) -> list[str]:
        self.expect("(")
        words = [] if self.at(")") else self.comma_words()
        self.expect(")")
        return words

    def apply(self, name: str, kind: str, body: Callable[[], Parsed]) -> Parsed:
        line = self.expect("(").line
        found, position = self.shorthands[name]
        if found != kind:
            raise PdlSyntaxError(line, f"{name} is a {found}, which cannot stand in the place of a {kind}")
        if name in self.expanding:
            raise PdlSyntaxError(line, f"{name} is defined in terms of itself")
        values = [] if self.at(")") else [self.path()]
        while self.accept(","):
            values.append(self.path())
        self.expect(")")
        saved = (self.index, self.arguments, self.temporal)
        self.index = position
        names = self.parameters()
        if len(names) != len(values):
            raise PdlSyntaxError(line, f"{name} takes {len(names)} arguments but is given {len(values)}")
        self.expect(":")
        self.arguments, self.temporal = dict(zip(names, values)), False
        self.expanding.append(name)
        expanded = body()
        self.expanding.pop()
        self.index, self.arguments, self.temporal = saved
        return expanded

    def path(self) -> str:
        names = [self.word()]
        if names[0] in self.shorthands and self.at("("):
            names = [self.apply(names[0], "fun", self.path)]
        elif names[0] in self.arguments:
            names = [self.arguments[names[0]]]
        while self.accept("."):
            names.append(self.word())
        return ".".join(names)

    def implication(self) -> Formula:
        premise = self.disjunction()
        if self.accept("=>"):
            return Implies(premise, self.implication())
        return premise

    def disjunction(self) -> Formula:
        operands = [self.conjunction()]
        while self.accept("|"):
            operands.append(self.conjunction())
        return operands[0] if len(operands) == 1 else Or(operands)

    def conjunction(self) -> Formula:
        operands = [self.unary()]
        while self.accept("&"):
            operands.append(self.unary())
        return operands[0] if len(operands) == 1 else And(operands)

    def unary(self) -> Formula:
        if self.accept("!"):
            return Not(self.unary())
        token = self.peek()
        if self.temporal and self.accept("can"):
            return Can(self.unary())
        if self.temporal and self.accept("eventually"):
            return Eventually(self.unary())
        if token is not None and token.kind == "word" and token.value in ("can", "eventually"):
            raise PdlSyntaxError(token.line, f"{token.value} is allowed only inside prop")
        for keyword, quantifier in (("all", ForAll), ("some", Exists)):
            if self.accept(keyword):
                variable = self.word()
                self.expect("in")
                domain = self.word()
                line = self.expect(":").line
                outer = self.arguments
                if any(value.split(".")[0] == variable for name, value in outer.items() if name != variable):
                    raise PdlSyntaxError(line, f"{variable} is bound in a definition that is also given {variable}")
                self.arguments = {name: value for name, value in outer.items() if name != variable}
                body = self.implication()
                self.arguments = outer
                return quantifier(variable, domain, body)
        if self.accept("("):
            formula = self.implication()
            self.expect(")")
            return formula
        if token is not None and self.shorthands.get(token.value, ("", 0))[0] == "pred" and self.at("(", 1):
            return self.apply(self.word(), "pred", self.implication)
        left = self.path()
        if self.accept("in"):
            return InSet(left, self.braced_words())
        token = self.advance()
        if token.kind == "string" or token.value not in COMPARISON_OPERATORS:
            raise PdlSyntaxError(token.line, f"expected a comparison or in but found {token.value!r}")
        return Atom(left, token.value, self.path())

    def module(self) -> Module:
        self.expect("module")
        module = Module(name=self.word())
        statements = {
            "import": self.import_statement,
            "term": self.glossary,
            "actor": self.declaration,
            "action": self.declaration,
            "external": self.declaration,
            "permission": self.declaration,
            "permit": self.rule,
            "forbid": self.rule,
            "assume": self.premise,
            "inv": self.invariant,
            "prop": self.assertion,
            "fair": self.fairness,
            "pred": self.shorthand,
            "fun": self.shorthand,
            "law": self.law,
            "derive": self.derive,
            "screen": self.screen,
            "run": self.run,
            "unknown": self.unknown,
            "scope": self.scope,
            "const": self.constant,
            "text": self.text,
        }
        while (token := self.peek()) is not None:
            if token.kind != "word":
                raise PdlSyntaxError(token.line, f"unexpected {token.value!r}")
            statements.get(token.value, self.named)(module)
        self.finish(module)
        if not module.imports:
            self.place_texts(module)
        return module

    def named(self, module: Module) -> None:
        token = self.advance()
        name = token.value
        if self.accept("of"):
            entity = self.word()
            self.expect(":")
            self.machine(module, token.line, name, entity)
        elif self.accept("."):
            member = self.word()
            if self.accept(":"):
                self.counter(module, token.line, name, member)
            else:
                self.block(token.line, name, member)
        elif self.accept(":"):
            following = self.closing() + 1
            if self.at("{") and not any(self.at(keyword, following) for keyword in ("init", "final", "cyclic")):
                values = self.braced_words()
                if not values:
                    raise PdlSyntaxError(token.line, f"enum {name} needs at least one value")
                module.enums.append(EnumDefinition(token.line, name, values))
                module.definitions.append(("enum", name, token.line))
            else:
                self.machine(module, token.line, name, "")
        elif self.at("{") or self.at("key") or self.at("passive"):
            self.entity(module, token.line, name)
        else:
            raise PdlSyntaxError(token.line, f"unexpected {name!r}")

    def closing(self) -> int:
        offset = 0
        while self.peek(offset) is not None and not self.at("}", offset):
            offset += 1
        return offset

    def machine(self, module: Module, line: int, name: str, entity: str) -> None:
        machine = Machine(line, name, self.braced_words(), entity=entity)
        if self.accept("init"):
            machine.initial = self.word()
        if self.accept("cyclic"):
            machine.cyclic = True
        elif self.accept("final"):
            machine.terminals = self.braced_words()
        module.machines.append(machine)
        module.definitions.append(("machine", name, line))

    def counter(self, module: Module, line: int, owner: str, name: str) -> None:
        low = self.number()
        if low != 0:
            raise PdlSyntaxError(line, f"counter {name} must start at 0")
        self.expect("..")
        maximum = self.word()
        machine = next((machine for machine in module.machines if machine.name == owner), None)
        if machine is None:
            raise PdlSyntaxError(line, f"counter {name} is declared before its machine {owner}")
        machine.counters[name] = int(maximum) if is_number(maximum) else 0
        if not is_number(maximum):
            machine.counter_bounds[name] = maximum
        module.definitions.append(("counter", name, line))

    def block(self, line: int, machine: str, event: str) -> None:
        actors = self.comma_words() if self.accept("@") else []
        self.expect("{")
        clauses = []
        while not self.accept("}"):
            clauses.append(self.clause(machine))
        self.blocks.append(Block(line, machine, event, actors, clauses))

    def clause(self, machine: str) -> Clause:
        token = self.peek()
        if token is None:
            raise PdlSyntaxError(self.tokens[-1].line, f"an event of {machine} is not closed")
        if self.accept("else"):
            clause = Clause(token.line, [], self.outcome())
            clause.tag = "else"
        else:
            guard = [] if self.at("=>") else conjuncts(self.disjunction())
            self.expect("=>")
            clause = Clause(token.line, guard, "move")
            if self.at("reject") or self.at("ignore"):
                clause.kind = self.outcome()
            else:
                self.update(clause, machine)
                while self.accept("&"):
                    self.update(clause, machine)
        if self.accept("@"):
            if clause.kind != "move":
                raise PdlSyntaxError(clause.line, f"a {clause.kind} clause changes nothing, so it names no actor")
            clause.actors = self.comma_words()
        clause.assumes = self.assumptions()
        if self.accept("as"):
            clause.tag = self.word()
        return clause

    def outcome(self) -> str:
        token = self.advance()
        if token.kind != "word" or token.value not in ("reject", "ignore"):
            raise PdlSyntaxError(token.line, f"expected reject or ignore but found {token.value!r}")
        return token.value

    def update(self, clause: Clause, machine: str) -> None:
        name = self.path()
        self.expect("'")
        self.expect("=")
        value = self.word()
        if "." in name:
            clause.updates.append((name, value))
        elif name == machine:
            clause.target = value
        elif self.accept("+"):
            if value != name:
                raise PdlSyntaxError(clause.line, f"{name}' must be {name} plus a number")
            clause.effects.append((name, "+", self.number()))
        elif is_number(value):
            clause.effects.append((name, "=", int(value)))
        else:
            raise PdlSyntaxError(clause.line, f"{name}' must be a number or {name} plus a number")

    def entity(self, module: Module, line: int, name: str) -> None:
        key = self.parenthesized_words() if self.accept("key") else []
        passive = self.accept("passive")
        fields: list[tuple[str, str]] = []
        fixed: list[str] = []
        starts: dict[str, str] = {}
        self.expect("{")
        while not self.accept("}"):
            field_name = self.word()
            self.expect(":")
            prefix = "list " if self.accept("list") else ""
            fields.append((field_name, prefix + self.word() + ("?" if self.accept("?") else "")))
            if self.accept("fixed"):
                fixed.append(field_name)
            elif self.accept("var"):
                self.expect("init")
                starts[field_name] = self.word()
            self.accept(",")
        module.entities.append(EntityDefinition(line, name, key, passive, fields, fixed=fixed, starts=starts))
        module.definitions.append(("entity", name, line))

    def import_statement(self, module: Module) -> None:
        line = self.expect("import").line
        module.imports.append((line, self.string()))

    def glossary(self, module: Module) -> None:
        line = self.expect("term").line
        for name in self.comma_words():
            module.terms.append(TermDefinition(line, name))
            module.definitions.append(("term", name, line))

    def declaration(self, module: Module) -> None:
        token = self.advance()
        first = True
        while True:
            declaration = Declaration(token.line, token.value, self.word())
            while token.value == "action":
                if self.accept("by"):
                    declaration.performed_by = self.parenthesized_words()
                elif self.accept("on"):
                    declaration.applies_to = self.parenthesized_words()
                else:
                    break
            module.declarations.append(declaration)
            module.definitions.append((token.value, declaration.name, token.line))
            if self.at("grants"):
                if token.value != "actor":
                    raise PdlSyntaxError(token.line, f"only an actor grants permissions, and {declaration.name} is not one")
                if not first:
                    raise PdlSyntaxError(token.line, "grants follows a single actor")
                self.advance()
                declaration.grants = self.comma_words()
                break
            if not self.accept(","):
                break
            first = False

    def rule(self, module: Module) -> None:
        token = self.advance()
        actor = self.name_or_star()
        action = self.name_or_star()
        resource = self.name_or_star()
        conditions = conjuncts(self.implication()) if self.accept(":") else []
        requires = self.word() if self.accept("requires") else ""
        rule = Rule(token.line, token.value, actor, action, resource, conditions, requires, "", self.assumptions())
        if self.accept("as"):
            self.tags.setdefault((self.word(),), []).append(rule)
        module.rules.append(rule)

    def named_formula(self, keyword: str) -> tuple[int, str]:
        line = self.expect(keyword).line
        name = self.word()
        self.expect(":")
        return line, name

    def shorthand(self, module: Module) -> None:
        kind = self.advance().value
        token = self.advance()
        names = self.parameters()
        self.expect(":")
        self.expanding.append(token.value)
        if kind == "pred":
            module.predicates.append(Predicate(token.line, token.value, names, self.implication()))
        else:
            module.functions.append(Function(token.line, token.value, names, self.path()))
        self.expanding.pop()
        module.definitions.append((kind, token.value, token.line))

    def premise(self, module: Module) -> None:
        line, name = self.named_formula("assume")
        formula = self.implication()
        module.premises.append(Premise(line, name, formula, assumes=self.assumptions()))
        module.definitions.append(("assume", name, line))

    def invariant(self, module: Module) -> None:
        line, name = self.named_formula("inv")
        formula = self.implication()
        module.invariants.append(Invariant(line, name, formula, assumes=self.assumptions()))
        module.definitions.append(("invariant", name, line))

    def assertion(self, module: Module) -> None:
        line, name = self.named_formula("prop")
        mode = "start" if self.at("eventually") else self.advance().value
        if mode not in ("always", "reachable", "start"):
            raise PdlSyntaxError(line, f"expected always, reachable, or eventually but found {mode!r}")
        self.temporal = True
        formula = self.implication()
        self.temporal = False
        module.assertions.append(Assertion(line, name, mode, formula, assumes=self.assumptions()))
        module.definitions.append(("assert", name, line))

    def fairness(self, module: Module) -> None:
        line = self.expect("fair").line
        machine = self.word()
        self.expect(".")
        event = self.word()
        module.fair.append((line, machine, event, self.assumptions()))

    def term(self) -> Term:
        name = self.word()
        if self.accept("("):
            argument = self.term()
            self.expect(")")
            return Call(name, argument)
        self.expect(".")
        return Reference(name, self.word())

    def law(self, module: Module) -> None:
        line, name = self.named_formula("law")
        left = self.term()
        token = self.advance()
        if token.kind == "string" or token.value not in LAW_OPERATORS:
            raise PdlSyntaxError(token.line, f"expected a comparison but found {token.value!r}")
        right = self.term()
        module.laws.append(Law(line, name, left, token.value, right, "", self.assumptions()))

    def derive(self, module: Module) -> None:
        line = self.expect("derive").line
        name = self.word()
        self.expect("of")
        entity = self.word()
        if self.accept(":"):
            derivation = Derivation(line, name, entity, "", "", type=self.word())
            self.expect("from")
            derivation.sources = [self.path()]
            while self.accept(","):
                derivation.sources.append(self.path())
        else:
            self.expect("from")
            source = self.word()
            self.expect("mixed")
            derivation = Derivation(line, name, entity, source, self.word())
        derivation.assumes = self.assumptions()
        module.derivations.append(derivation)
        module.definitions.append(("derive", name, line))

    def screen(self, module: Module) -> None:
        line = self.expect("screen").line
        name = self.word()
        self.expect("of")
        entity = self.word()
        self.expect("shows")
        shows = [self.path()]
        while self.accept(","):
            shows.append(self.path())
        actors = self.comma_words() if self.accept("@") else []
        module.screens.append(Screen(line, name, entity, shows, assumes=self.assumptions(), actors=actors))
        module.definitions.append(("screen", name, line))

    def run(self, module: Module) -> None:
        line, name = self.named_formula("run")
        start = conjuncts(self.conjunction())
        self.expect("->")
        events: list[tuple[str, str]] = []
        while not self.at("->"):
            first = self.word()
            events.append((first, self.word()) if self.accept(".") else ("", first))
            if not self.accept(","):
                break
        self.expect("->")
        self.runs.append(Run(line, name, start, events, conjuncts(self.conjunction())))

    def unknown(self, module: Module) -> None:
        line = self.expect("unknown").line
        policy = self.word()
        if policy not in UNKNOWN_POLICIES:
            raise PdlSyntaxError(line, f"unknown policy {policy} is not structure or value")
        identifier = self.word()
        attributes: dict[str, str] = {}
        self.expect("{")
        while not self.accept("}"):
            token = self.advance()
            key = token.value
            if token.kind != "word" or key not in UNKNOWN_ATTRIBUTES:
                raise PdlSyntaxError(token.line, f"unknown {identifier} does not take {key!r}")
            if key in attributes:
                raise PdlSyntaxError(token.line, f"unknown {identifier} gives {key} twice")
            value = self.advance()
            if key in UNKNOWN_FLAGS and (value.kind != "word" or value.value not in ("yes", "no")):
                raise PdlSyntaxError(value.line, f"{key} of unknown {identifier} must be yes or no")
            attributes[key] = value.value
        module.unknowns.append(Unknown(line, policy, identifier, attributes))
        module.definitions.append(("unknown", identifier, line))

    def scope(self, module: Module) -> None:
        line = self.expect("scope").line
        name = self.word()
        module.scopes[name] = self.number()
        module.scope_lines[name] = line

    def constant(self, module: Module) -> None:
        line = self.expect("const").line
        name = self.word()
        self.expect(":")
        low = self.number()
        self.expect("..")
        high = self.number()
        if low > high:
            raise PdlSyntaxError(line, f"the range of {name} is empty")
        module.constants.append(Constant(line, name, low, high, assumes=self.assumptions()))
        module.definitions.append(("const", name, line))

    def text(self, module: Module) -> None:
        self.expect("text")
        self.expect("{")
        while not self.accept("}"):
            token = self.peek()
            if token is None:
                raise PdlSyntaxError(self.tokens[-1].line, "the text block is not closed")
            entry = TextEntry(token.line, self.path().split("."), {})
            while True:
                following = self.peek()
                if following is not None and following.kind == "string":
                    attribute = "label"
                elif following is not None and following.kind == "word" and following.value in TEXT_ATTRIBUTES:
                    attribute = self.word()
                else:
                    break
                if attribute in entry.attributes:
                    named = "a label" if attribute == "label" else attribute
                    raise PdlSyntaxError(following.line, f"text gives {'.'.join(entry.key)} {named} twice")
                entry.attributes[attribute] = self.string()
            self.texts.append(entry)

    def finish(self, module: Module) -> None:
        machines = {}
        for machine in module.machines:
            machines.setdefault(machine.name, machine)
        for block in self.blocks:
            machine = machines.get(block.machine)
            if machine is None:
                raise PdlSyntaxError(block.line, f"machine {block.machine} of event {block.event} is not defined")
            if block.event not in machine.events:
                machine.events.append(block.event)
            for clause in block.clauses:
                self.place(machine, block, clause)
        for run in self.runs:
            self.place_run(module, run)

    def place_texts(self, module: Module) -> None:
        machines = {}
        for machine in module.machines:
            machines.setdefault(machine.name, machine)
        defined = {name for _, name, _ in module.definitions}
        for key, items in self.tags.items():
            if len(key) == 1 and key[0] in defined:
                raise PdlSyntaxError(items[0].line, f"rule tag {key[0]} repeats the name of a definition")
        for entry in self.texts:
            self.place_text(module, machines, entry)

    def place(self, machine: Machine, block: Block, clause: Clause) -> None:
        sources: list[str] | None = None
        conditions = []
        for condition in clause.guard:
            chosen = source_states(condition, machine)
            if chosen is None:
                conditions.append(condition)
                continue
            sources = chosen if sources is None else [state for state in sources if state in chosen]
        placed = self.tags.setdefault((machine.name, block.event, clause.tag), []) if clause.tag else []
        if clause.kind != "move":
            for state in ["*"] if sources is None else sources:
                handling = Handling(clause.line, clause.kind, state, block.event, "", clause.assumes, conditions)
                machine.handlings.append(handling)
                placed.append(handling)
            return
        actors = block.actors if clause.actors is None else clause.actors
        for state in machine.states if sources is None else sources:
            transition = Transition(
                clause.line, state, clause.target or state, block.event, actors, "", clause.assumes, conditions, clause.effects
            )
            transition.updates = clause.updates
            machine.transitions.append(transition)
            placed.append(transition)

    def place_run(self, module: Module, run: Run) -> None:
        def states(formulas: list[Formula]) -> dict[str, str]:
            result = {}
            for formula in formulas:
                if not isinstance(formula, Atom) or formula.operator != "=":
                    raise PdlSyntaxError(run.line, f"run {run.name} names each machine state as Machine = State")
                result[formula.left] = formula.right
            return result

        if any(machine for machine, _ in run.events):
            if not all(machine for machine, _ in run.events):
                raise PdlSyntaxError(run.line, f"run {run.name} mixes events with and without a machine")
            module.joint_scenarios.append(
                JointScenario(run.line, run.name, states(run.start), run.events, states(run.expect))
            )
            return
        start = states(run.start[:1])
        expect = states(run.expect)
        machine = next(iter(start))
        if list(expect) != [machine]:
            raise PdlSyntaxError(run.line, f"run {run.name} expects one state of {machine}")
        events = [event for _, event in run.events]
        module.scenarios.append(
            Scenario(run.line, run.name, machine, start[machine], events, expect[machine], run.start[1:])
        )

    def holds(self, owner: object, member: str) -> bool:
        if isinstance(owner, EnumDefinition):
            return member in owner.values
        if isinstance(owner, EntityDefinition):
            return member in dict(owner.fields)
        return isinstance(owner, Machine) and member in (*owner.states, *owner.events, *owner.counters)

    def refuse_unused(self, entry: TextEntry, allowed: set[str]) -> None:
        unused = ["a label" if name == "label" else name for name in entry.attributes if name not in allowed]
        if unused:
            raise PdlSyntaxError(entry.line, f"text gives {'.'.join(entry.key)} {', '.join(unused)}, which it does not take")

    def place_text(self, module: Module, machines: dict[str, Machine], entry: TextEntry) -> None:
        key = entry.key
        text = entry.attributes
        label = text.get("label", "")
        why = text.get("why", "")
        if key == ["module"]:
            self.refuse_unused(entry, {"label"})
            module.label = label
            return
        if tuple(key) in self.tags:
            clauses = all(isinstance(item, Transition) for item in self.tags[tuple(key)])
            self.refuse_unused(entry, {"why", "after"} if clauses else {"why"})
            for item in self.tags[tuple(key)]:
                item.why = why
                if isinstance(item, Transition):
                    item.after = text.get("after", "")
            return
        candidates = [
            definition
            for group in (
                module.terms, module.enums, module.entities, module.declarations, module.machines, module.constants,
                module.derivations, module.screens, module.invariants, module.premises, module.assertions,
            )
            for definition in group
            if definition.name == key[0]
        ]
        candidates += [law for law in module.laws if law.identifier == key[0]]
        if not candidates or len(key) > 2:
            raise PdlSyntaxError(entry.line, f"text names {'.'.join(key)}, which is not defined")
        if len(key) == 1:
            seen = self.named_texts.get(key[0], 0)
            self.named_texts[key[0]] = seen + 1
            owner = candidates[min(seen, len(candidates) - 1)]
            unused = [name for name in text if name not in ("label", "why", "mixed")]
            if label and isinstance(owner, LABELED):
                owner.label = label
            elif label:
                unused.append("a label")
            if why and not isinstance(owner, Declaration):
                owner.why = why
            elif why:
                unused.append("why")
            if "mixed" in text and isinstance(owner, Derivation):
                owner.mixed_label = text["mixed"]
            elif "mixed" in text:
                unused.append("mixed")
            if unused:
                raise PdlSyntaxError(entry.line, f"text gives {key[0]} {', '.join(unused)}, which it does not take")
            return
        member = key[1]
        owner = next((candidate for candidate in candidates if self.holds(candidate, member)), candidates[0])
        if isinstance(owner, EnumDefinition) and member in owner.values:
            self.refuse_unused(entry, {"label", "stored"})
            if label:
                owner.value_labels[member] = label
            if "stored" in text:
                owner.stored[member] = text["stored"]
        elif isinstance(owner, EntityDefinition) and member in dict(owner.fields):
            self.refuse_unused(entry, {"label", "why"})
            if label:
                owner.field_labels[member] = label
            if why:
                owner.field_notes[member] = why
        elif isinstance(owner, Machine) and member in (*owner.states, *owner.events, *owner.counters):
            self.refuse_unused(entry, {"label"})
            if member in owner.states:
                owner.state_labels[member] = label
            elif member in owner.events:
                owner.event_labels[member] = label
            else:
                owner.counter_labels[member] = label
        else:
            raise PdlSyntaxError(entry.line, f"text names {'.'.join(key)}, which is not defined")


def merge_imports(
    module: Module, source: Path | None, merged: set[Path], stack: list[Path], sources: list[tuple[int, Path]]
) -> None:
    for line, relative in module.imports:
        if source is None:
            raise PdlSyntaxError(line, "an import needs the path of the importing file")
        target = (source.parent / relative).resolve()
        if target in stack:
            raise PdlSyntaxError(line, f"import cycle through {relative}")
        if target in merged:
            continue
        if not target.is_file():
            raise PdlSyntaxError(line, f"imported file {relative} does not exist")
        # Each imported file numbers its lines from its own offset, which no file reaches with its own lines.
        offset = 1_000_000 * (len(sources) + 1)
        sources.append((offset, target))
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise PdlSyntaxError(line, f"imported file {relative} cannot be read: {error}") from None
        parser = Parser(tokenize(text, offset))
        imported = parser.module()
        merged.add(target)
        merge_imports(imported, target, merged, [*stack, target], sources)
        if imported.imports:
            parser.place_texts(imported)
        module.enums += imported.enums
        module.entities += imported.entities
        module.terms += imported.terms
        module.declarations += imported.declarations
        module.unknowns += imported.unknowns
        module.definitions += [item for item in imported.definitions if item[0] in IMPORTED_KINDS]


def parse_module(text: str, source: Path | None = None) -> Module:
    parser = Parser(tokenize(text))
    module = parser.module()
    if module.imports:
        resolved = source.resolve() if source is not None else None
        try:
            merge_imports(module, source, {resolved} if resolved else set(), [resolved] if resolved else [], module.sources)
            parser.place_texts(module)
        except PdlSyntaxError as error:
            path, line = module.locate(error.line)
            raise PdlSyntaxError(line, error.message, path or source) from None
    return module
