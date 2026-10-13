"""Deterministic sentences for rules, built from labels and Korean particle rules."""

from .model import And, Atom, Can, Exists, ForAll, Formula, Implies, InSet, Module, Not, Or, Rule

HANGUL_FIRST = 0xAC00
HANGUL_LAST = 0xD7A3
FINAL_CONSONANT_SLOTS = 28


class Names:
    def __init__(self, module: Module, language: str):
        self.labels: dict[str, str] = {}
        self.field_types = {(e.name, n): t for e in module.entities for n, t in e.fields}
        self.field_labels: dict[tuple[str, str], str] = {}
        self.constants = {constant.name for constant in module.constants}
        if language != "ko":
            self.value_labels: dict[tuple[str, str], str] = {}
            return
        for entity in module.entities:
            for field_name, field_label in entity.field_labels.items():
                self.field_labels[(entity.name, field_name)] = field_label
        for entity in reversed(module.entities):
            if entity.label:
                self.labels[entity.name] = entity.label
        for declaration in module.declarations:
            if declaration.label:
                self.labels[declaration.name] = declaration.label
        for enum in module.enums:
            if enum.label:
                self.labels[enum.name] = enum.label
        for term in module.terms:
            if term.label:
                self.labels[term.name] = term.label
        for constant in module.constants:
            if constant.label:
                self.labels[constant.name] = constant.label
        for derivation in module.derivations:
            if derivation.label:
                self.labels[derivation.name] = derivation.label
        for screen in module.screens:
            if screen.label:
                self.labels[screen.name] = screen.label
        self.value_labels = {
            (enum.name, value): label
            for enum in module.enums
            for value, label in enum.value_labels.items()
        }
        for machine in module.machines:
            if machine.label:
                self.labels[machine.name] = machine.label
            for counter, counter_label in machine.counter_labels.items():
                self.labels[counter] = counter_label
            for state, state_label in machine.state_labels.items():
                self.value_labels[(machine.name, state)] = state_label

    def show(self, name: str) -> str:
        return self.labels.get(name) or name

    def field(self, entity: str, attribute: str) -> str:
        label = self.field_labels.get((entity, attribute))
        type_name = self.field_types.get((entity, attribute), attribute).removesuffix("?").removeprefix("list ")
        return label or self.show(type_name)

    def value(self, variable: str, value: str) -> str:
        return self.value_labels.get((variable, value)) or (self.show(value) if value in self.constants else value)


def has_final_consonant(text: str) -> bool:
    for character in reversed(text):
        code = ord(character)
        if HANGUL_FIRST <= code <= HANGUL_LAST:
            return (code - HANGUL_FIRST) % FINAL_CONSONANT_SLOTS != 0
    return False


def attach(text: str, with_consonant: str, without_consonant: str) -> str:
    return text + (with_consonant if has_final_consonant(text) else without_consonant)


PRECEDENCE = {Implies: 1, Or: 2, And: 3}
SYMBOLS = {"!=": "≠", "<=": "≤", ">=": "≥"}
KOREAN_ORDERINGS = {
    "<": ("보다 작을 때", "보다 작고"),
    "<=": (" 이하일 때", " 이하이고"),
    ">": ("보다 클 때", "보다 크고"),
    ">=": (" 이상일 때", " 이상이고"),
}
ENGLISH_ORDERINGS = {"<": "less than", "<=": "at most", ">": "greater than", ">=": "at least"}


def formula_text(formula: Formula, parent: int = 0) -> str:
    if isinstance(formula, Atom):
        return f"{formula.left} {SYMBOLS.get(formula.operator, formula.operator)} {formula.right}"
    if isinstance(formula, InSet):
        return f"{formula.left} ∈ {{{', '.join(formula.values)}}}"
    if isinstance(formula, Not):
        return f"¬({formula_text(formula.operand)})"
    if isinstance(formula, Can):
        return f"can ({formula_text(formula.operand)})"
    if isinstance(formula, (ForAll, Exists)):
        symbol = "∀" if isinstance(formula, ForAll) else "∃"
        text = f"{symbol} {formula.variable} ∈ {formula.enum} : {formula_text(formula.body)}"
        return f"({text})" if parent else text
    level = PRECEDENCE[type(formula)]
    if isinstance(formula, Implies):
        text = f"{formula_text(formula.premise, level + 1)} ⇒ {formula_text(formula.conclusion, level)}"
    else:
        joiner = " ∧ " if isinstance(formula, And) else " ∨ "
        text = joiner.join(formula_text(operand, level + 1) for operand in formula.operands)
    return f"({text})" if parent > level else text


def korean_condition(conditions: list[Formula], names: Names) -> str:
    phrases = []
    for position, condition in enumerate(conditions):
        last = position == len(conditions) - 1
        if isinstance(condition, InSet):
            subject = attach(names.show(condition.left), "이", "가")
            options = " 또는 ".join(f"'{names.value(condition.left, v)}'" for v in condition.values)
            phrases.append(f"{subject} {options}" + ("일 때" if last else "이고"))
        elif isinstance(condition, Atom) and condition.operator == "!=":
            subject = attach(names.show(condition.left), "이", "가")
            shown = names.value(condition.left, condition.right)
            phrases.append(
                f"{subject} '{shown}'" + ("이" if has_final_consonant(shown) else "가") + (" 아닐 때" if last else " 아니고")
            )
        elif isinstance(condition, Atom) and condition.operator == "=":
            subject = attach(names.show(condition.left), "이", "가")
            shown = names.value(condition.left, condition.right)
            phrases.append(f"{subject} '{shown}'" + ("일 때" if last else "이고"))
        elif isinstance(condition, Atom) and "." not in condition.left + condition.right:
            subject = attach(names.show(condition.left), "이", "가")
            shown = names.value(condition.left, condition.right)
            closing, joining = KOREAN_ORDERINGS[condition.operator]
            phrases.append(f"{subject} '{shown}'" + (closing if last else joining))
        else:
            phrases.append(f"`{formula_text(condition)}` 조건이 " + ("성립할 때" if last else "성립하고"))
    return " ".join(phrases)


def english_condition(conditions: list[Formula], names: Names) -> str:
    parts = []
    for condition in conditions:
        if isinstance(condition, InSet):
            parts.append(f"{names.show(condition.left)} is one of {', '.join(condition.values)}")
        elif isinstance(condition, Atom) and condition.operator == "!=":
            parts.append(f"{names.show(condition.left)} is not {condition.right}")
        elif isinstance(condition, Atom) and condition.operator == "=":
            parts.append(f"{names.show(condition.left)} is {names.value(condition.left, condition.right)}")
        elif isinstance(condition, Atom) and "." not in condition.left + condition.right:
            relation = ENGLISH_ORDERINGS[condition.operator]
            parts.append(f"{names.show(condition.left)} is {relation} {names.value(condition.left, condition.right)}")
        else:
            parts.append(f"`{formula_text(condition)}` holds")
    return " and ".join(parts)


def korean_sentence(rule: Rule, names: Names) -> str:
    permit = rule.effect == "permit"
    if rule.actor == "*":
        subject = "누구나" if permit else "누구도"
    else:
        subject = attach(names.show(rule.actor), "은", "는")
    resource = "모든 대상" if rule.resource == "*" else names.show(rule.resource)
    ending = "할 수 있다." if permit else "할 수 없다."
    if rule.action == "*":
        predicate = f"{resource}에 대한 모든 동작을 {ending}"
    else:
        predicate = f"{attach(resource, '을', '를')} {names.show(rule.action)}{ending}"
    clause = korean_condition(rule.conditions, names) + ", " if rule.conditions else ""
    sentence = f"{clause}{subject} {predicate}"
    if permit and rule.requires:
        sentence += f" 이때 {attach(names.show(rule.requires), '을', '를')} 입력해야 한다."
    return sentence


def english_sentence(rule: Rule, names: Names) -> str:
    permit = rule.effect == "permit"
    subject = "Anyone" if rule.actor == "*" else names.show(rule.actor)
    modal = "may" if permit else "may not"
    resource = "any resource" if rule.resource == "*" else names.show(rule.resource)
    action = "do anything with" if rule.action == "*" else names.show(rule.action)
    clause = f"When {english_condition(rule.conditions, names)}, " if rule.conditions else ""
    sentence = f"{clause}{subject.lower() if clause and rule.actor == '*' else subject} {modal} {action} {resource}."
    if permit and rule.requires:
        sentence += f" A {names.show(rule.requires)} is required."
    return sentence


def sentence(rule: Rule, names: Names, language: str) -> str:
    return korean_sentence(rule, names) if language == "ko" else english_sentence(rule, names)
