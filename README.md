# Plan definition language

The plan definition language (PDL) describes a plan as sets, rules, and state machines.
The compiler reports the holes in a module, such as a state with no way out or a case that no rule covers, and writes a Markdown document from a module that has none.

## Installation

```sh
uv tool install git+ssh://git@github.com/kuroneko0441/plan-definition-language
```

Append `@v0.1.0` to the URL to install a release.

## Usage

```sh
pdl build door.pdl                  # writes build/door.md
pdl build door.pdl --draft          # writes a draft when the module has holes
pdl build door.pdl --language en --output out
pdl consistency plans/              # compares the modules of one plan
```

`build` exits with a nonzero status when a module has a hole.
The generated sentences are Korean unless `--language en` is given.

## Example

```
module door label "문"

actor Guard label "경비원"

machine Door label "문" {
    states Closed "닫힘", Open "열림"
    initial Closed
    cyclic
    event Unlock "열기", Lock "잠그기"
    Closed -> Open on Unlock by Guard
    Open -> Closed on Lock by Guard
    reject Open on Unlock
    reject Closed on Lock
}
```

## Development

In a clone, `python3 -m pdl` runs the compiler from the `src` directory, and the tests run from there too:

```sh
cd src
python3 -m unittest discover -s tests -t .
```
