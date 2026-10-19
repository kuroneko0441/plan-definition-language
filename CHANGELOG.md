# Changelog

This file records the notable changes of each release of the plan definition language (PDL) compiler. Each release is tagged `v<version>` in the Git repository.

## 0.4.0 - 2026-10-19

This release adds the following features:

- A `permission` statement declares what an account may do, and `actor <Name> grants <permissions>` lists the permissions that a role holds.
- The `@` list of an event, a clause, or a screen accepts a permission, which stands for any account that holds it. The generated document lists each permission with the events and screens that require it and the actors that grant it.
- `import` merges the unknowns of the imported file, so modules share one question. An importing module reports an imported unknown only when it assumes it, at the line of the declaring file.
- `pdl consistency` compares unknowns and permissions of the same name across modules.
- `assume`, `inv`, `prop`, and `fair` statements take `assuming <unknowns>`.

This release changes the following behavior:

- An unknown shares the names of the module, so an unknown named like an enum, a machine, or another definition is reported as `DUPLICATE`.
- An unknown policy other than `value` or `structure` is a syntax error instead of an `UNDEFINED` finding.
- `UNREFERENCED` also reports a permission that no event, clause, or screen requires.

This release fixes the following problems:

- An unknown that only an invariant, a premise, a property, or a fair event depends on is no longer reported as unreferenced.
- An undeclared name in the `assuming` list of a law, a screen, or a computed value is reported as `UNDEFINED`.
- An unknown attribute with a misspelled key, a repeated key, or a `verified` or `open` value other than `yes` or `no` is a syntax error instead of being ignored.

## 0.3.0 - 2026-10-19

This release adds the following features:

- Each finding has a `key` that stays the same when its wording or line changes, the `subject` names it concerns, and a `witness` with its counterexample.
- `pdl check` prints the findings without writing documents, and `--format json` prints them as JSON.
- `pdl build` takes a directory and builds every module in it.
- `pdl --version` prints the version.

This release changes the following behavior:

- A syntax error is returned as a `SYNTAX` finding, and an unreadable module is reported without a traceback.
- A problem in an imported file is reported at that file and its line.
- A `text` entry that gives a name a label or a rationale that the name cannot hold is a syntax error.
- A solver query that ends undecided is reported as `TOO_LARGE` instead of passing.

This release removes the following feature:

- The earlier keyword syntax is no longer read. `pdl convert` from `v0.2.1` rewrites a module in that syntax.

This release fixes the following problem:

- An inequality through a missing reference is false, as the reference states.

## 0.2.1 - 2026-10-15

This release adds the following feature:

- The language reference ships with the compiler, and `pdl reference` prints the reference of the running release.

## 0.2.0 - 2026-10-14

This release adds the following features:

- A plan is written as sets, transition relations, and formulas, and one `text` block holds every label and rationale.
- A machine can run once for each instance of an entity, and a formula reads fields through references.
- `assume` and `prop` state assumptions and properties as full formulas, and `eventually` with `fair` requires that a state is reached.
- `const` declares an undecided number, and the checker verifies the plan for every value in its range.
- The Z3 solver runs the checks that are too large to enumerate.
- A computed value declares its type and inputs, and a clause sets a `var` field.
- `pred` and `fun` name a condition or a path once for reuse.

## 0.1.0 - 2026-10-11

This first release provides the following features:

- Enums, entities, terms, actors, actions, and permit and forbid rules, with a check that every combination of actor, action, and entity is covered.
- State machines with guards, cyclic flows, counters, and time limits, with checks for unreachable states, traps, and unhandled events.
- Invariants with quantifiers, scenarios that replay events across machines, derived statuses, and screens.
- Unknowns with sources and provisional decisions, and draft builds for modules with holes.
- Imports of shared files, stored database texts for enum values, and `pdl consistency` for the modules of one plan.
- Markdown documents generated from hole-free modules.
