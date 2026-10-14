"""Comparison of each case folder's module with the document and findings stored beside it."""

import os
import unittest
from pathlib import Path

from pdl.checks import check
from pdl.render import render
from pdl.syntax import parse_module

CASES = Path(__file__).parent / "cases"
UPDATE = os.environ.get("PDL_UPDATE_CASES") == "1"


def outputs(source: Path) -> dict[str, str]:
    module = parse_module(source.read_text(encoding="utf-8"), source)
    findings = check(module)
    failed = any(finding.blocking for finding in findings)
    listing = "".join(
        f"{finding.line}: {'HOLE' if finding.blocking else 'NOTE'} {finding.kind} {finding.message}\n"
        for finding in findings
    )
    document = f"{module.name}{'.draft' if failed else ''}.md"
    return {document: render(module, findings, "ko", draft=failed), "findings.txt": listing}


class CaseTest(unittest.TestCase):
    def test_every_case_matches_its_stored_outputs(self):
        folders = sorted(path for path in CASES.iterdir() if path.is_dir())
        self.assertTrue(folders)
        for folder in folders:
            with self.subTest(case=folder.name):
                sources = list(folder.glob("*.pdl"))
                self.assertEqual(len(sources), 1, "a case holds one module")
                expected = outputs(sources[0])
                if UPDATE:
                    for stale in folder.iterdir():
                        if stale != sources[0] and stale.name not in expected:
                            stale.unlink()
                    for name, text in expected.items():
                        (folder / name).write_text(text, encoding="utf-8")
                stored = {path.name: path.read_text(encoding="utf-8") for path in folder.iterdir() if path != sources[0]}
                self.assertEqual(stored, expected)
