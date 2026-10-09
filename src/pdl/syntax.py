"""Tokenizer and parser for plan definition language source text."""

import re
from pathlib import Path
from typing import NamedTuple

from .model import (
    And,
    Atom,
    Call,
    Condition,
    Declaration,
    Derivation,
    EntityDefinition,
    EnumDefinition,
    Exclusion,
    ForAll,
    Formula,
    Handling,
    Implies,
    InSet,
    Invariant,
    Law,
    Machine,
    Module,
    Not,
    Or,
    Reference,
    Rule,
    Scenario,
    Screen,
    Term,
    TermDefinition,
    Transition,
    Unknown,
)

TOKEN_PATTERN = re.compile(
    r"(?P<space>\s+)"
    r"|(?P<comment>#[^\n]*)"
    r"|(?P<string>\"(?:[^\"\\]|\\.)*\")"
    r"|(?P<symbol>->|→|<=|>=|≤|≥|=>|⇒|!=|≠|∧|∨|¬|∀|∈|[{}(),:=|*<>.;?+])"
    r"|(?P<word>\w+)"
)
SYMBOL_ALIASES = {"→": "->", "≤": "<=", "≥": ">=", "⇒": "=>", "≠": "!="}
WORD_ALIASES = {"∧": "and", "∨": "or", "¬": "not", "∀": "forall", "∈": "in"}
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
        elif kind == "symbol" and value in WORD_ALIASES:
            tokens.append(Token("word", WORD_ALIASES[value], line))
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

    def field_type(self) -> str:
        prefix = "list " if self.accept("list") else ""
        name = self.word()
        return prefix + name + ("?" if self.accept("?") else "")

    def parenthesized_words(self) -> list[str]:
        self.expect("(")
        words = self.comma_words()
        self.expect(")")
        return words

    def condition(self) -> Condition:
        variable = self.word()
        if self.accept("in"):
            self.expect("{")
            values = self.comma_words()
            self.expect("}")
            return Condition(variable, operator="in", values=values)
        token = self.advance()
        if token.kind == "string" or token.value not in ("=", "!="):
            raise PdlSyntaxError(token.line, f"expected =, != or in but found {token.value!r}")
        return Condition(variable, self.word(), token.value)

    def conditions_after(self, keyword: str) -> list[Condition]:
        conditions: list[Condition] = []
        if self.accept(keyword):
            conditions.append(self.condition())
            while self.accept("and"):
                conditions.append(self.condition())
        return conditions

    def effects(self) -> list[tuple[str, str, int]]:
        effects: list[tuple[str, str, int]] = []
        if self.accept("then"):
            while True:
                counter = self.word()
                token = self.advance()
                if token.kind == "string" or token.value not in ("+", "="):
                    raise PdlSyntaxError(token.line, f"expected + or = but found {token.value!r}")
                effects.append((counter, token.value, int(self.word())))
                if not self.accept(","):
                    break
        return effects

    def assumptions(self) -> list[str]:
        return self.comma_words() if self.accept("assuming") else []

    def module(self) -> Module:
        self.expect("module")
        module = Module(name=self.word())
        module.label = self.label()
        statements = {
            "import": self.import_statement,
            "term": self.glossary,
            "enum": self.enum,
            "entity": self.entity,
            "derive": self.derive,
            "screen": self.screen,
            "actor": self.declaration,
            "action": self.declaration,
            "external": self.declaration,
            "permit": self.rule,
            "forbid": self.rule,
            "exclusive": self.exclusive,
            "invariant": self.invariant,
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
        stored: dict[str, str] = {}
        while True:
            value = self.word()
            values.append(value)
            following = self.peek()
            if following is not None and following.kind == "string":
                value_labels[value] = self.string()
            if self.accept("stored"):
                stored[value] = self.string()
            if not self.accept("|"):
                break
        module.enums.append(
            EnumDefinition(line, name, values, self.why(), label, value_labels, stored)
        )
        module.definitions.append(("enum", name, line))

    def import_statement(self, module: Module) -> None:
        line = self.expect("import").line
        module.imports.append((line, self.string()))

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
        field_labels: dict[str, str] = {}
        if self.accept("{"):
            while not self.accept("}"):
                field_name = self.word()
                self.expect(":")
                fields.append((field_name, self.field_type()))
                field_label = self.label()
                if field_label:
                    field_labels[field_name] = field_label
                note = self.why()
                if note:
                    field_notes[field_name] = note
                self.accept(",")
        module.entities.append(
            EntityDefinition(
                line, name, key, passive, fields, self.why(), label, field_notes, field_labels
            )
        )
        module.definitions.append(("entity", name, line))

    def derive(self, module: Module) -> None:
        line = self.expect("derive").line
        name = self.word()
        label = self.label()
        self.expect("of")
        entity = self.word()
        self.expect("from")
        source = self.word()
        self.expect("mixed")
        mixed = self.word()
        following = self.peek()
        mixed_label = self.string() if following is not None and following.kind == "string" else ""
        assumes = self.assumptions()
        module.derivations.append(
            Derivation(line, name, entity, source, mixed, label, mixed_label, self.why(), assumes)
        )
        module.definitions.append(("derive", name, line))

    def shown_item(self) -> str:
        name = self.word()
        return f"{name}.{self.word()}" if self.accept(".") else name

    def screen(self, module: Module) -> None:
        line = self.expect("screen").line
        name = self.word()
        label = self.label()
        self.expect("of")
        entity = self.word()
        self.expect("shows")
        shows = [self.shown_item()]
        while self.accept(","):
            shows.append(self.shown_item())
        assumes = self.assumptions()
        module.screens.append(Screen(line, name, entity, shows, label, self.why(), assumes))
        module.definitions.append(("screen", name, line))

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
        conditions = self.conditions_after("when")
        requires = self.word() if self.accept("requires") else ""
        assumes = self.assumptions()
        module.rules.append(
            Rule(token.line, token.value, actor, action, resource, conditions, requires, self.why(), assumes)
        )

    def exclusive(self, module: Module) -> None:
        line = self.expect("exclusive").line
        left = self.condition()
        self.expect(",")
        module.exclusions.append(Exclusion(line, left, self.condition()))

    def invariant(self, module: Module) -> None:
        line = self.expect("invariant").line
        name = self.word()
        self.expect(":")
        formula = self.implication()
        module.invariants.append(Invariant(line, name, formula, self.why()))
        module.definitions.append(("invariant", name, line))

    def implication(self) -> Formula:
        premise = self.disjunction()
        if self.accept("=>"):
            return Implies(premise, self.implication())
        return premise

    def disjunction(self) -> Formula:
        operands = [self.conjunction()]
        while self.accept("or"):
            operands.append(self.conjunction())
        return operands[0] if len(operands) == 1 else Or(operands)

    def conjunction(self) -> Formula:
        operands = [self.unary()]
        while self.accept("and"):
            operands.append(self.unary())
        return operands[0] if len(operands) == 1 else And(operands)

    def unary(self) -> Formula:
        if self.accept("not"):
            return Not(self.unary())
        if self.accept("forall"):
            variable = self.word()
            self.expect("in")
            enum = self.word()
            self.expect(":")
            return ForAll(variable, enum, self.implication())
        if self.accept("("):
            formula = self.implication()
            self.expect(")")
            return formula
        left = self.word()
        if self.accept("in"):
            self.expect("{")
            values = self.comma_words()
            self.expect("}")
            return InSet(left, values)
        token = self.advance()
        if token.kind == "string" or token.value not in ("=", "!="):
            raise PdlSyntaxError(token.line, f"expected = or != but found {token.value!r}")
        return Atom(left, token.value, self.word())

    def machine(self, module: Module) -> None:
        line = self.expect("machine").line
        machine = Machine(line, self.word())
        machine.label = self.label()
        machine.why = self.why()
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
            elif token.kind == "word" and token.value == "cyclic":
                self.advance()
                machine.cyclic = True
            elif token.kind == "word" and token.value == "counter":
                self.advance()
                counter = self.word()
                counter_label = self.string() if self.peek() is not None and self.peek().kind == "string" else ""
                self.expect("max")
                machine.counters[counter] = int(self.word())
                if counter_label:
                    machine.counter_labels[counter] = counter_label
                module.definitions.append(("counter", counter, token.line))
            elif token.kind == "word" and token.value in ("ignore", "reject"):
                self.advance()
                state = self.name_or_star()
                self.expect("on")
                event = self.word()
                conditions = self.conditions_after("when")
                assumes = self.assumptions()
                machine.handlings.append(
                    Handling(token.line, token.value, state, event, self.why(), assumes, conditions)
                )
            else:
                source = self.word()
                self.expect("->")
                target = self.word()
                self.expect("on")
                event = self.word()
                conditions = self.conditions_after("when")
                effects = self.effects()
                actors = self.comma_words() if self.accept("by") else []
                after = self.string() if self.accept("after") else ""
                assumes = self.assumptions()
                machine.transitions.append(
                    Transition(
                        token.line, source, target, event, actors, self.why(), assumes, conditions, effects, after
                    )
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
        given = self.conditions_after("given")
        self.expect("events")
        events = self.comma_words()
        self.expect("expect")
        expect = self.word()
        self.expect("}")
        module.scenarios.append(Scenario(line, name, machine, start, events, expect, given))

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
        assumes = self.assumptions()
        module.laws.append(Law(line, identifier, left, token.value, right, self.why(), assumes))


IMPORTED_KINDS = ("enum", "entity", "term", "actor", "action", "external")


def merge_imports(module: Module, source: Path | None, merged: set[Path], stack: list[Path]) -> None:
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
        imported = Parser(tokenize(target.read_text(encoding="utf-8"))).module()
        merged.add(target)
        merge_imports(imported, target, merged, [*stack, target])
        module.enums += imported.enums
        module.entities += imported.entities
        module.terms += imported.terms
        module.declarations += imported.declarations
        module.definitions += [item for item in imported.definitions if item[0] in IMPORTED_KINDS]


def parse_module(text: str, source: Path | None = None) -> Module:
    module = Parser(tokenize(text)).module()
    if module.imports:
        resolved = source.resolve() if source is not None else None
        merge_imports(module, source, {resolved} if resolved else set(), [resolved] if resolved else [])
    return module
