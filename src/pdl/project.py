"""Cross-module consistency check for the modules of one plan."""

from dataclasses import dataclass
from pathlib import Path

from .model import Module


@dataclass
class Entry:
    path: Path
    line: int
    category: str
    signature: tuple
    label: str


@dataclass
class ProjectFinding:
    kind: str
    message: str
    path: Path
    line: int
    blocking: bool = True


def collect(path: Path, module: Module) -> dict[str, Entry]:
    entries: dict[str, Entry] = {}

    def add(name: str, line: int, category: str, signature: tuple, label: str = "") -> None:
        entries.setdefault(name, Entry(path, line, category, signature, label))

    for enum in module.enums:
        stored = tuple(sorted(enum.stored.items()))
        add(enum.name, enum.line, "enum", (tuple(sorted(enum.values)), stored), enum.label)
    for entity in module.entities:
        add(entity.name, entity.line, "entity", (tuple(entity.key), tuple(sorted(entity.fields))), entity.label)
    for term in module.terms:
        add(term.name, term.line, "term", (), term.label)
    for declaration in module.declarations:
        add(declaration.name, declaration.line, declaration.kind, (), declaration.label)
    for derivation in module.derivations:
        signature = (derivation.entity, derivation.source, derivation.mixed, derivation.type, tuple(derivation.sources))
        add(derivation.name, derivation.line, "derive", signature, derivation.label)
    for screen in module.screens:
        add(screen.name, screen.line, "screen", (screen.entity, tuple(screen.shows)), screen.label)
    for machine in module.machines:
        signature = (
            tuple(sorted(machine.states)),
            tuple(sorted(machine.events)),
            machine.initial,
            tuple(sorted(machine.terminals)),
            machine.cyclic,
            tuple(sorted(machine.counters.items())),
        )
        add(machine.name, machine.line, "machine", signature, machine.label)
    return entries


def difference(category: str, left: tuple, right: tuple) -> str:
    """Describe a conflict between two definitions of one name, or return an empty string when they agree."""
    parts: list[str] = []
    if category == "enum":
        only_left = sorted(set(left[0]) - set(right[0]))
        only_right = sorted(set(right[0]) - set(left[0]))
        if only_left:
            parts.append(f"only the first has {', '.join(only_left)}")
        if only_right:
            parts.append(f"only the second has {', '.join(only_right)}")
        if left[1] != right[1]:
            parts.append("the stored texts differ")
    elif category == "entity":
        if left[0] and right[0] and left[0] != right[0]:
            parts.append(f"key {', '.join(left[0])} against {', '.join(right[0])}")
        left_fields, right_fields = dict(left[1]), dict(right[1])
        for name in sorted(left_fields.keys() & right_fields.keys()):
            if left_fields[name] != right_fields[name]:
                parts.append(f"field {name} is {left_fields[name]} against {right_fields[name]}")
    elif category == "machine":
        labels = ("states", "events", "initial state", "terminal states", "cyclic flag", "counters")
        parts = [f"{label} differ" for label, a, b in zip(labels, left, right) if a != b]
    elif left != right:
        parts.append("the definitions differ")
    return "; ".join(parts)


def compare(modules: list[tuple[Path, Module]]) -> list[ProjectFinding]:
    seen: dict[str, Entry] = {}
    findings: list[ProjectFinding] = []
    for path, module in modules:
        for name, entry in collect(path, module).items():
            first = seen.get(name)
            if first is None:
                seen[name] = entry
                continue
            where = f"{first.path.name}:{first.line}"
            if first.category != entry.category and "term" in (first.category, entry.category):
                if first.category == "term":
                    seen[name] = entry
            elif first.category != entry.category:
                findings.append(
                    ProjectFinding(
                        "INCONSISTENT",
                        f"{name} is a {entry.category} here and a {first.category} at {where}",
                        path,
                        entry.line,
                    )
                )
            elif difference(first.category, first.signature, entry.signature):
                findings.append(
                    ProjectFinding(
                        "INCONSISTENT",
                        f"{first.category} {name} differs from {where}: {difference(first.category, first.signature, entry.signature)}",
                        path,
                        entry.line,
                    )
                )
            elif first.label and entry.label and first.label != entry.label:
                findings.append(
                    ProjectFinding(
                        "LABEL_DIFFERS",
                        f"{name} is labeled '{entry.label}' here and '{first.label}' at {where}",
                        path,
                        entry.line,
                        blocking=False,
                    )
                )
    return findings
