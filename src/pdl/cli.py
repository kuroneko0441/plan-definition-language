"""Command line entry point that builds modules one at a time."""

import argparse
from pathlib import Path

from .checks import check
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


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pdl")
    parser.add_argument("command", choices=["build"])
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path("build"))
    parser.add_argument("--language", choices=["ko", "en"], default="ko")
    parser.add_argument("--draft", action="store_true")
    options = parser.parse_args(arguments)
    results = [build_file(path, options.output, options.language, options.draft) for path in options.paths]
    return 0 if all(results) else 1
