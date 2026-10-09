"""Tokenizer and parser for plan definition language source text."""

import re
from typing import NamedTuple

from .model import (
    Call,
    Condition,
    Declaration,
    EntityDefinition,
    EnumDefinition,
    Exclusion,
    Handling,
    Law,
    Machine,
    Module,
    Reference,
    Rule,
    Scenario,
    Term,
    TermDefinition,
    Transition,
    Unknown,
)

TOKEN_PATTERN = re.compile(
    r"(?P<space>\s+)"
    r"|(?P<comment>#[^\n]*)"
    r"|(?P<string>\"(?:[^\"\\]|\\.)*\")"
    r"|(?P<symbol>->|→|<=|>=|≤|≥|∧|[{}(),:=|*<>.;])"
    r"|(?P<word>\w+)"
)
SYMBOL_ALIASES = {"→": "->", "≤": "<=", "≥": ">="}
COMPARISON_OPERATORS = ("=", "<", ">", "<=", ">=")


class PdlSyntaxError(Exception):
    def __init__(self, line: int, message: str):
        super().__init__(f"line {line}: {message}")
        self.line = line


class Token(NamedTuple):
    kind: str
    value: str
    line: int


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    position = 0
    line = 1
    while position < len(text):
        match = TOKEN_PATTERN.match(text, position)
        if match is None:
            raise PdlSyntaxError(line, f"unexpected character {text[position]!r}")
        kind = match.lastgroup
        value = match.group()
        if kind == "string":
            tokens.append(Token("string", value[1:-1].replace('\\"', '"'), line))
        elif kind == "symbol" and value == "∧":
            tokens.append(Token("word", "and", line))
        elif kind == "symbol":
            tokens.append(Token("symbol", SYMBOL_ALIASES.get(value, value), line))
        elif kind == "word":
            tokens.append(Token("word", value, line))
        line += value.count("\n")
        position = match.end()
    return tokens


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.index = 0

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

    def accept(self, value: str) -> bool:
        token = self.peek()
        if token is not None and token.kind != "string" and token.value == value:
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

    def name_or_star(self) -> str:
        return "*" if self.accept("*") else self.word()

    def comma_words(self) -> list[str]:
        words = [self.word()]
        while self.accept(","):
            words.append(self.word())
        return words

    def why(self) -> str:
        return self.string() if self.accept("why") else ""

    def label(self) -> str:
        return self.string() if self.accept("label") else ""

    def labeled_words(self) -> list[tuple[str, str]]:
        items = []
        while True:
            word = self.word()
            following = self.peek()
            label = self.string() if following is not None and following.kind == "string" else ""
            items.append((word, label))
            if not self.accept(","):
                return items

    def parenthesized_words(self) -> list[str]:
        self.expect("(")
        words = self.comma_words()
        self.expect(")")
        return words

    def condition(self) -> Condition:
        variable = self.word()
        self.expect("=")
        return Condition(variable, self.word())

    def module(self) -> Module:
        self.expect("module")
        module = Module(name=self.word())
        statements = {
            "term": self.glossary,
            "enum": self.enum,
            "entity": self.entity,
            "actor": self.declaration,
            "action": self.declaration,
            "external": self.declaration,
            "permit": self.rule,
            "forbid": self.rule,
            "exclusive": self.exclusive,
            "machine": self.machine,
            "scenario": self.scenario,
            "unknown": self.unknown,
            "law": self.law,
        }
        while (token := self.peek()) is not None:
            handler = statements.get(token.value) if token.kind == "word" else None
            if handler is None:
                raise PdlSyntaxError(token.line, f"unexpected {token.value!r}")
            handler(module)
        return module

    def glossary(self, module: Module) -> None:
        line = self.expect("term").line
        name = self.word()
        label = self.label()
        module.terms.append(TermDefinition(line, name, self.why(), label))
        module.definitions.append(("term", name, line))

    def enum(self, module: Module) -> None:
        line = self.expect("enum").line
        name = self.word()
        label = self.label()
        self.expect("=")
        values: list[str] = []
        value_labels: dict[str, str] = {}
        while True:
            value = self.word()
            values.append(value)
            following = self.peek()
            if following is not None and following.kind == "string":
                value_labels[value] = self.string()
            if not self.accept("|"):
                break
        module.enums.append(EnumDefinition(line, name, values, self.why(), label, value_labels))
        module.definitions.append(("enum", name, line))

    def entity(self, module: Module) -> None:
        line = self.expect("entity").line
        name = self.word()
        label = self.label()
        key: list[str] = []
        if self.accept("key"):
            self.expect("(")
            key = self.comma_words()
            self.expect(")")
        passive = self.accept("passive")
        fields: list[tuple[str, str]] = []
        field_notes: dict[str, str] = {}
        if self.accept("{"):
            while not self.accept("}"):
                field_name = self.word()
                self.expect(":")
                fields.append((field_name, self.word()))
                note = self.why()
                if note:
                    field_notes[field_name] = note
                self.accept(",")
        module.entities.append(
            EntityDefinition(line, name, key, passive, fields, self.why(), label, field_notes)
        )
        module.definitions.append(("entity", name, line))

    def declaration(self, module: Module) -> None:
        token = self.advance()
        while True:
            name = self.word()
            declaration = Declaration(token.line, token.value, name, self.label())
            while token.value == "action":
                if self.accept("by"):
                    declaration.performed_by = self.parenthesized_words()
                elif self.accept("on"):
                    declaration.applies_to = self.parenthesized_words()
                else:
                    break
            module.declarations.append(declaration)
            module.definitions.append((token.value, name, token.line))
            if not self.accept(","):
                break

    def rule(self, module: Module) -> None:
        token = self.advance()
        actor = self.name_or_star()
        action = self.name_or_star()
        resource = self.name_or_star()
        conditions: list[Condition] = []
        if self.accept("when"):
            conditions.append(self.condition())
            while self.accept("and"):
                conditions.append(self.condition())
        requires = self.word() if self.accept("requires") else ""
        module.rules.append(
            Rule(token.line, token.value, actor, action, resource, conditions, requires, self.why())
        )

    def exclusive(self, module: Module) -> None:
        line = self.expect("exclusive").line
        left = self.condition()
        self.expect(",")
        module.exclusions.append(Exclusion(line, left, self.condition()))

    def machine(self, module: Module) -> None:
        line = self.expect("machine").line
        machine = Machine(line, self.word())
        machine.label = self.label()
        self.expect("{")
        while not self.accept("}"):
            token = self.peek()
            if token is None:
                raise PdlSyntaxError(line, f"machine {machine.name} is not closed")
            if token.kind == "word" and token.value == "states":
                self.advance()
                for state, state_label in self.labeled_words():
                    machine.states.append(state)
                    if state_label:
                        machine.state_labels[state] = state_label
            elif token.kind == "word" and token.value == "initial":
                self.advance()
                machine.initial = self.word()
            elif token.kind == "word" and token.value == "terminal":
                self.advance()
                machine.terminals += self.comma_words()
            elif token.kind == "word" and token.value == "event":
                self.advance()
                for event, event_label in self.labeled_words():
                    machine.events.append(event)
                    if event_label:
                        machine.event_labels[event] = event_label
            elif token.kind == "word" and token.value in ("ignore", "reject"):
                self.advance()
                state = self.name_or_star()
                self.expect("on")
                machine.handlings.append(Handling(token.line, token.value, state, self.word()))
            else:
                source = self.word()
                self.expect("->")
                target = self.word()
                self.expect("on")
                event = self.word()
                actor = self.word() if self.accept("by") else ""
                machine.transitions.append(
                    Transition(token.line, source, target, event, actor, self.why())
                )
        module.machines.append(machine)
        module.definitions.append(("machine", machine.name, line))

    def scenario(self, module: Module) -> None:
        line = self.expect("scenario").line
        name = self.word()
        self.expect("on")
        machine = self.word()
        self.expect("{")
        self.expect("start")
        start = self.word()
        self.expect("events")
        events = self.comma_words()
        self.expect("expect")
        expect = self.word()
        self.expect("}")
        module.scenarios.append(Scenario(line, name, machine, start, events, expect))

    def unknown(self, module: Module) -> None:
        line = self.expect("unknown").line
        policy = self.word()
        identifier = self.word()
        attributes: dict[str, str] = {}
        self.expect("{")
        while not self.accept("}"):
            key = self.word()
            attributes[key] = self.advance().value
        module.unknowns.append(Unknown(line, policy, identifier, attributes))

    def term(self) -> Term:
        name = self.word()
        if self.accept("("):
            argument = self.term()
            self.expect(")")
            return Call(name, argument)
        self.expect(".")
        return Reference(name, self.word())

    def law(self, module: Module) -> None:
        line = self.expect("law").line
        identifier = self.word()
        self.expect(":")
        left = self.term()
        token = self.advance()
        if token.value not in COMPARISON_OPERATORS:
            raise PdlSyntaxError(token.line, f"expected a comparison but found {token.value!r}")
        right = self.term()
        module.laws.append(Law(line, identifier, left, token.value, right, self.why()))


def parse_module(text: str) -> Module:
    return Parser(tokenize(text)).module()
