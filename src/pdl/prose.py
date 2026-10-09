"""Deterministic sentences for rules, built from labels and Korean particle rules."""

from .model import Condition, Module, Rule

HANGUL_FIRST = 0xAC00
HANGUL_LAST = 0xD7A3
FINAL_CONSONANT_SLOTS = 28


class Names:
    def __init__(self, module: Module, language: str):
        self.labels: dict[str, str] = {}
        self.field_types = {(e.name, n): t for e in module.entities for n, t in e.fields}
        self.field_labels: dict[tuple[str, str], str] = {}
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

    def show(self, name: str) -> str:
        return self.labels.get(name) or name

    def field(self, entity: str, attribute: str) -> str:
        label = self.field_labels.get((entity, attribute))
        type_name = self.field_types.get((entity, attribute), attribute).removesuffix("?").removeprefix("list ")
        return label or self.show(type_name)

    def value(self, variable: str, value: str) -> str:
        return self.value_labels.get((variable, value)) or value


def has_final_consonant(text: str) -> bool:
    for character in reversed(text):
        code = ord(character)
        if HANGUL_FIRST <= code <= HANGUL_LAST:
            return (code - HANGUL_FIRST) % FINAL_CONSONANT_SLOTS != 0
    return False


def attach(text: str, with_consonant: str, without_consonant: str) -> str:
    return text + (with_consonant if has_final_consonant(text) else without_consonant)


def korean_condition(conditions: list[Condition], names: Names) -> str:
    phrases = []
    for position, condition in enumerate(conditions):
        last = position == len(conditions) - 1
        subject = attach(names.show(condition.variable), "이", "가")
        if condition.operator == "in":
            options = " 또는 ".join(f"'{names.value(condition.variable, v)}'" for v in condition.values)
            phrases.append(f"{subject} {options}" + ("일 때" if last else "이고"))
        elif condition.operator == "!=":
            shown = names.value(condition.variable, condition.value)
            phrases.append(
                f"{subject} '{shown}'" + ("이" if has_final_consonant(shown) else "가") + (" 아닐 때" if last else " 아니고")
            )
        else:
            shown = names.value(condition.variable, condition.value)
            phrases.append(f"{subject} '{shown}'" + ("일 때" if last else "이고"))
    return " ".join(phrases)


def english_condition(conditions: list[Condition], names: Names) -> str:
    parts = []
    for condition in conditions:
        variable = names.show(condition.variable)
        if condition.operator == "in":
            parts.append(f"{variable} is one of {', '.join(condition.values)}")
        elif condition.operator == "!=":
            parts.append(f"{variable} is not {condition.value}")
        else:
            parts.append(f"{variable} is {names.value(condition.variable, condition.value)}")
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
