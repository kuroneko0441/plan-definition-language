"""Deterministic sentences for rules, built from labels and Korean particle rules."""

from .model import Module, Rule

HANGUL_FIRST = 0xAC00
HANGUL_LAST = 0xD7A3
FINAL_CONSONANT_SLOTS = 28


class Names:
    def __init__(self, module: Module, language: str):
        self.labels: dict[str, str] = {}
        if language != "ko":
            self.value_labels: dict[tuple[str, str], str] = {}
            return
        for entity in reversed(module.entities):
            if entity.label:
                self.labels[entity.name] = entity.label
        for declaration in module.declarations:
            if declaration.label:
                self.labels[declaration.name] = declaration.label
        for enum in module.enums:
            if enum.label:
                self.labels[enum.name] = enum.label
        self.value_labels = {
            (enum.name, value): label
            for enum in module.enums
            for value, label in enum.value_labels.items()
        }

    def show(self, name: str) -> str:
        return self.labels.get(name) or name

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
    clause = ""
    if rule.conditions:
        parts = [
            f"{attach(names.show(c.variable), '이', '가')} '{names.value(c.variable, c.value)}'"
            for c in rule.conditions
        ]
        clause = ", ".join(parts) + "일 때, "
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
    clause = ""
    if rule.conditions:
        parts = [f"{names.show(c.variable)} is {names.value(c.variable, c.value)}" for c in rule.conditions]
        clause = "When " + " and ".join(parts) + ", "
    sentence = f"{clause}{subject.lower() if clause and rule.actor == '*' else subject} {modal} {action} {resource}."
    if permit and rule.requires:
        sentence += f" A {names.show(rule.requires)} is required."
    return sentence


def sentence(rule: Rule, names: Names, language: str) -> str:
    return korean_sentence(rule, names) if language == "ko" else english_sentence(rule, names)
