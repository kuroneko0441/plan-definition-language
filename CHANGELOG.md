# Changelog

This file records the notable changes of each release of the plan definition language (PDL) compiler. Each release is tagged `v<version>` in the Git repository.

## 0.5.0 - 2026-10-21

This release adds the following features:

- A module reaches one of the levels `poc`, `logical`, `usable`, and `confirmed`, and the generated document states it. `--require <level>` of `build` and `check` sets the level that a module must reach, and each finding in JSON has the `level` it bounds.
- A machine declaration takes `else reject` or `else ignore`, which applies to every event of the machine that has no `else` clause of its own.
- A `text` entry can label a definition that the module imports.
- `pdl consistency` reports `REDECLARED` when two files declare one unknown instead of sharing it through `import`, and compares constant ranges, `fixed` fields, and the permissions that an actor grants.
- A quantifier ranges over a machine, a counter, or a constant, and a guard names its source states with `|`, `&`, and `!`.

This release changes the following behavior:

- A final state rejects every event that no clause of it names, so it is no longer reported as `UNHANDLED`.
- An unverified unknown that nothing assumes is reported as one `UNVERIFIED` note instead of `UNREFERENCED` and `UNVERIFIED`.
- An unknown with `open yes` is listed under open items in the generated document instead of the assumptions.
- `@` after a `reject` or `ignore` clause, an attribute given twice in a `text` entry, a rule tag named like a definition, an enum without values, and a scope of 0 are syntax errors.

This release fixes the following problems:

- An invariant or an assumption without a free enum, such as `all v in S: v = On`, is checked.
- A guard such as `B = R | B = K` no longer adds a transition from every state.
- A value outside the enum in the body of `some` is reported as `UNDEFINED`.
- A run through an undefined event of one machine is reported as `UNDEFINED`.
- An omitted `verified` or `open` flag agrees with `no` in `pdl consistency`.
- A number in non-ASCII digits and an imported file that is not UTF-8 text are syntax errors instead of tracebacks.

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
