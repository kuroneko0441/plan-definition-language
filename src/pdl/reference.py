"""The language reference that ships with this release of the compiler."""

from importlib.resources import files


def reference() -> str:
    return files("pdl").joinpath("reference.md").read_text(encoding="utf-8")
