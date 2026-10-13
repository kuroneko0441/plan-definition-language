"""Command line entry point that builds modules one at a time."""

import argparse
from pathlib import Path

from . import legacy
from .checks import check
from .format import to_text
from .project import compare
from .render import render
from .syntax import PdlSyntaxError, parse_module


def build_file(path: Path, output_directory: Path, language: str, draft: bool = False) -> bool:
    try:
        module = parse_module(path.read_text(encoding="utf-8"), path)
    except PdlSyntaxError as error:
        print(f"{path}: SYNTAX {error}")
        return False
    findings = check(module)
    for finding in findings:
        label = "HOLE" if finding.blocking else "NOTE"
        print(f"{path}:{finding.line}: {label} {finding.kind} {finding.message}")
    failed = any(finding.blocking for finding in findings)
    if failed and not draft:
        print(f"{module.name}: build failed")
        return False
    output_directory.mkdir(parents=True, exist_ok=True)
    suffix = ".draft.md" if failed else ".md"
    target = output_directory / f"{module.name}{suffix}"
    target.write_text(render(module, findings, language, draft=failed), encoding="utf-8")
    print(f"{module.name}: {'draft written to' if failed else 'built'} {target}")
    return not failed


def expand(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        files.extend(sorted(path.glob("*.pdl")) if path.is_dir() else [path])
    return files


def check_consistency(paths: list[Path]) -> bool:
    modules = []
    clean = True
    for path in expand(paths):
        try:
            modules.append((path, parse_module(path.read_text(encoding="utf-8"), path)))
        except PdlSyntaxError as error:
            print(f"{path}: SYNTAX {error}")
            clean = False
    findings = compare(modules)
    for finding in findings:
        label = "HOLE" if finding.blocking else "NOTE"
        print(f"{finding.path}:{finding.line}: {label} {finding.kind} {finding.message}")
    print(f"{len(modules)} modules compared, {sum(1 for f in findings if f.blocking)} inconsistencies")
    return clean and not any(finding.blocking for finding in findings)


def convert_file(path: Path, output_directory: Path) -> bool:
    try:
        module = legacy.Parser(legacy.tokenize(path.read_text(encoding="utf-8"))).module()
    except PdlSyntaxError as error:
        print(f"{path}: SYNTAX {error}")
        return False
    output_directory.mkdir(parents=True, exist_ok=True)
    target = output_directory / path.name
    target.write_text(to_text(module), encoding="utf-8")
    print(f"{module.name}: converted to {target}")
    return True


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pdl")
    parser.add_argument("command", choices=["build", "consistency", "convert"])
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path("build"))
    parser.add_argument("--language", choices=["ko", "en"], default="ko")
    parser.add_argument("--draft", action="store_true")
    options = parser.parse_args(arguments)
    if options.command == "consistency":
        return 0 if check_consistency(options.paths) else 1
    if options.command == "convert":
        return 0 if all([convert_file(path, options.output) for path in expand(options.paths)]) else 1
    results = [build_file(path, options.output, options.language, options.draft) for path in options.paths]
    return 0 if all(results) else 1
