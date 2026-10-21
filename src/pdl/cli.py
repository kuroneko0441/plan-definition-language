"""Command line entry point that builds modules one at a time."""

import argparse
import json
import sys
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .checks import DEFAULT_LEVEL, LEVELS, Finding, achieved, compile_text
from .model import Module
from .project import compare
from .reference import reference
from .render import render
from .syntax import PdlSyntaxError, parse_module


def read_module(path: Path, require: str = DEFAULT_LEVEL) -> tuple[Module | None, list[Finding]] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        print(f"{path}: cannot read the file: {error}", file=sys.stderr)
        return None
    return compile_text(text, path, require)


def finding_record(path: Path, finding: Finding) -> dict:
    return {
        "path": str(finding.path or path),
        "line": finding.line,
        "kind": finding.kind,
        "key": finding.key,
        "blocking": finding.blocking,
        "level": finding.level or None,
        "message": finding.message,
        "subject": list(finding.subject),
        "witness": asdict(finding.witness) if finding.witness else None,
    }


def process(path: Path, options: argparse.Namespace, records: list[dict]) -> bool:
    compiled = read_module(path, options.require)
    if compiled is None:
        return False
    module, findings = compiled
    human = options.format == "text"
    for finding in findings:
        records.append(finding_record(path, finding))
        if human:
            label = "HOLE" if finding.blocking else "NOTE"
            print(f"{finding.path or path}:{finding.line}: {label} {finding.kind} {finding.message}")
    failed = any(finding.blocking for finding in findings)
    if human and module is not None:
        print(f"{module.name}: reaches {achieved([finding.level for finding in findings]) or 'no level'}")
    if module is None or options.command == "check":
        return not failed
    if failed and not options.draft:
        if human:
            print(f"{module.name}: build failed")
        return False
    options.output.mkdir(parents=True, exist_ok=True)
    suffix = ".draft.md" if failed else ".md"
    target = options.output / f"{module.name}{suffix}"
    target.write_text(render(module, findings, options.language, draft=failed), encoding="utf-8")
    if human:
        print(f"{module.name}: {'draft written to' if failed else 'built'} {target}")
    return not failed


def build_file(path: Path, output_directory: Path, language: str, draft: bool = False) -> bool:
    options = argparse.Namespace(
        command="build", output=output_directory, language=language, draft=draft, format="text", require=DEFAULT_LEVEL
    )
    return process(path, options, [])


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
            print(f"{error.path or path}:{error.line}: HOLE SYNTAX {error.message}")
            clean = False
        except (OSError, UnicodeDecodeError) as error:
            print(f"{path}: cannot read the file: {error}", file=sys.stderr)
            clean = False
    findings = compare(modules)
    for finding in findings:
        label = "HOLE" if finding.blocking else "NOTE"
        print(f"{finding.path}:{finding.line}: {label} {finding.kind} {finding.message}")
    print(f"{len(modules)} modules compared, {sum(1 for f in findings if f.blocking)} inconsistencies")
    return clean and not any(finding.blocking for finding in findings)


def release() -> str:
    try:
        return version("plan-definition-language")
    except PackageNotFoundError:
        return "unknown, run from a source tree"


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pdl")
    parser.add_argument("command", choices=["build", "check", "consistency", "reference"])
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--output", type=Path, default=Path("build"))
    parser.add_argument("--language", choices=["ko", "en"], default="ko")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--require", choices=LEVELS, default=DEFAULT_LEVEL)
    parser.add_argument("--version", action="version", version=f"pdl {release()}")
    options = parser.parse_args(arguments)
    if options.command == "reference":
        print(reference(), end="")
        return 0
    if not options.paths:
        parser.error(f"{options.command} needs at least one path")
    if options.command == "consistency":
        return 0 if check_consistency(options.paths) else 1
    records: list[dict] = []
    results = [process(path, options, records) for path in expand(options.paths)]
    if options.format == "json":
        print(json.dumps(records, ensure_ascii=False, indent=2))
    return 0 if all(results) else 1
