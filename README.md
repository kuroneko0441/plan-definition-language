# Plan definition language

The plan definition language (PDL) describes a plan as sets, state machines, and formulas.
The compiler reports the holes in a module, such as a state with no way out or a case that no rule covers, and writes a Markdown document from a module that has none.

## Installation

```sh
uv tool install git+ssh://git@github.com/kuroneko0441/plan-definition-language
```

Append `@v0.2.1` to the URL to install a release.

## Usage

```sh
pdl build door.pdl                  # writes build/door.md
pdl build door.pdl --draft          # writes a draft when the module has holes
pdl build door.pdl --language en --output out
pdl consistency plans/              # compares the modules of one plan
pdl reference                       # prints the language reference of this release
```

`build` exits with a nonzero status when a module has a hole.
The generated sentences are Korean unless `--language en` is given.
A module in the earlier keyword syntax must first be rewritten with `pdl convert` from `v0.2.1`.

## Example

```
module door

actor Guard
Door : {Closed, Open} init Closed cyclic

Door.Unlock @Guard {
    Door = Closed => Door' = Open
    else reject
}
Door.Lock @Guard {
    Door = Open => Door' = Closed
    else reject
}

text {
    module "문"
    Guard "경비원"
    Door "문"
    Door.Closed "닫힘"
    Door.Open "열림"
    Door.Unlock "열기"
    Door.Lock "잠그기"
}
```

Each folder under `src/tests/cases` holds a larger module with the document and the findings the compiler produces from it.

## Development

The checker uses the Z3 solver, so a clone needs the `z3-solver` package.
In a clone, `python3 -m pdl` runs the compiler from the `src` directory, and the tests run from there too:

```sh
pyright
cd src
python3 -m unittest discover -s tests -t .
PDL_UPDATE_CASES=1 python3 -m unittest tests.test_cases   # rewrites the stored case outputs
```
