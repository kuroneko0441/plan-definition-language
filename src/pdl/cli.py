"""Command line entry point that builds modules one at a time."""

import argparse
from pathlib import Path

from .checks import check
from .render import render
from .syntax import PdlSyntaxError, parse_module


def build_file(path: Path, output_directory: Path, language: str) -> bool:
    try:
        module = parse_module(path.read_text(encoding="utf-8"))
    except PdlSyntaxError as error:
        print(f"{path}: SYNTAX {error}")
        return False
    findings = check(module)
    for finding in findings:
        label = "HOLE" if finding.blocking else "NOTE"
        print(f"{path}:{finding.line}: {label} {finding.kind} {finding.message}")
    if any(finding.blocking for finding in findings):
        print(f"{module.name}: build failed")
        return False
    output_directory.mkdir(parents=True, exist_ok=True)
    target = output_directory / f"{module.name}.md"
    target.write_text(render(module, findings, language), encoding="utf-8")
    print(f"{module.name}: built {target}")
    return True


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pdl")
    parser.add_argument("command", choices=["build"])
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path("build"))
    parser.add_argument("--language", choices=["ko", "en"], default="ko")
    options = parser.parse_args(arguments)
    results = [build_file(path, options.output, options.language) for path in options.paths]
    return 0 if all(results) else 1
