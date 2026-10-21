# PDL language reference

This reference describes the plan definition language (PDL) that this release of the compiler accepts. `pdl reference` prints it, so a writer, human or agent, reads the syntax of the compiler it runs.

## Module files

A module is a file with the `.pdl` extension that starts with `module <name>`, followed by statements in any order. The statements hold only identifiers and formulas, and one `text` block holds every display text and rationale. Identifiers are written in English, and the `text` block gives the display text that the generated document uses. A `#` starts a comment.

A logic statement never carries a label or a rationale, so an edit to wording never touches a logic line.

## Formulas

Every condition is a formula over enum variables, counters, constants, and machine states. The operators are:

| Operator | Meaning | Accepted symbol |
|---|---|---|
| `&` | and | `∧` |
| `\|` | or | `∨` |
| `!` | not | `¬` |
| `=>` | implies | `⇒` |
| `=`, `!=` | equal, not equal | `≠` |
| `<`, `<=`, `>`, `>=` | order of numbers | `≤`, `≥` |
| `x in {A, B}` | membership | `∈` |
| `all v in S: f` | for every value or instance | `∀` |
| `some v in S: f` | for some value or instance | `∃` |

The ASCII spelling is the canonical one, and the Unicode symbols are aliases. A quantifier ranges over an enum, a scoped entity, a machine, a counter, or a constant. A number is written in ASCII digits. A quantifier extends as far to the right as it can, so a quantifier inside a larger formula takes parentheses.

## Sets and variables

The declarations look like this:

```
import "common.pdl"
term Dealer
Status : {Active, Closed}
Order key (id) passive {
    id: Text
    placed_on: Day
    closed_on: Day?
    items: list Item
    dealer: Dealer fixed
}
scope Order 2
const limit : 1..5 assuming limit_decided
```

The declarations mean:

- `import` merges the enums, entities, terms, declarations, and unknowns of another file, resolved relative to the importing file. A cycle, a missing file, or a file that is not readable UTF-8 text is a syntax error.
- `term` names a concept that the plan uses without modeling it.
- `<Name> : {…}` declares an enum, which is a closed set of at least one value and a variable that holds one of them.
- `<Name> { … }` declares an entity with typed fields, an optional `key`, and a `passive` flag. The flag takes the entity out of the permission rules, so the coverage check does not require a rule for it.
- A field type is a built-in type (`Text`, `Int`, `Bool`, `Timestamp`, `Decimal`, `Money`, `Duration`, `Day`, `Week`, `Month`), an enum, or an entity, with `?` for optional and `list` for several.
- `scope <Entity> <n>` creates exactly `n` instances named `<Entity>1` to `<Entity>n`, and `n` is at least 1 and at most 6.
- `const <name> : <low>..<high>` declares a number that the plan has not fixed. The checker verifies the plan for every value in the range, and `assuming` ties the constant to the unknown that it stands for.

## Machines and transition relations

A machine is a variable with an initial value. Each event is a set of clauses that relate the current state to the next state:

```
Booking : {Requested, Confirmed, Cancelled} init Requested final {Confirmed, Cancelled}
Account : {Active, Locked} init Active cyclic
Account.Tries : 0..limit

Booking.Confirm @Staff {
    Booking = Requested & Payment = Paid => Booking' = Confirmed
    else reject
}
Booking.Cancel {
    Booking in {Requested, Confirmed} => Booking' = Cancelled @Customer, Staff
    else reject
}
Account.Fail @Member {
    Account = Active & Tries < limit => Tries' = Tries + 1
    Account = Active & Tries = limit => Account' = Locked as lock
    else reject
}
```

The parts mean:

- `init` names the initial state, and `final` lists the states where the machine ends. `cyclic` marks a machine that returns to its initial state instead of ending. A final state rejects every event that no clause of it names.
- `else reject` or `else ignore` at the end of the declaration, with an optional `assuming` list, is the `else` clause of every event of the machine that has no `else` clause of its own.
- `<Machine>.<Counter> : 0..<max>` declares a counter of the machine, which starts at 0. The maximum is a number or a constant, and the machine is declared before its counters.
- `<Machine>.<Event> @<actors> { … }` declares an event and the actors or permissions that cause it. One event changes one machine.
- A clause is `<guard> => <outcome>`. The conjuncts of the guard that compare only the machine itself, with `=`, `!=`, `in`, and any combination of them under `|`, `&`, and `!`, name the states that the clause leaves, and a clause without such a conjunct leaves every state.
- `<Machine>' = <State>` in the outcome names the next state, and a clause without it stays in its state.
- `<Counter>' = <n>` sets a counter, and `<Counter>' = <Counter> + <n>` raises it.
- `this.<field>' = <Value>` sets a `var` field of the instance, and `<Instance>.<field>' = <Value>` sets a `var` field of a named instance.
- `reject` and `ignore` as the outcome declare that the event changes nothing. `else reject` or `else ignore` covers every case that no other clause names.
- `@<actors>` after a clause replaces the actors of the event for that clause. A `reject` or `ignore` clause changes nothing, so it names no actors.
- `assuming <unknowns>` after a clause names the unknowns that it depends on, and the generated sentence marks the assumption.
- `as <tag>` after a clause names it, so that the `text` block can attach a rationale or a time limit to it.

## Instances and paths

A machine of an entity runs once for each instance, and a formula reads the fields of an instance through a path:

```
Flow of Order : {Draft, Paid} init Draft final {Paid}
Flow.Pay @Gateway {
    Flow = Draft & this.dealer.grade = Gold => Flow' = Paid
    else reject
}
prop gold_only: always all o in Order: o.Flow = Paid => o.dealer.grade = Gold
```

The parts mean:

- A field whose type is an enum or a scoped entity is a function from an instance to one value, and `?` adds the value `none`.
- A field marked `fixed` keeps its value for the whole run.
- A field marked `var init <Value>` starts at the given value and changes only when a clause sets it. The initial value is required, as it is for a machine.
- A field with neither mark changes between transitions like an enum variable.
- A clause sets a `var` field to a literal value. It cannot copy another field, and it cannot set a field that it reaches through a reference.
- A path such as `o.dealer.grade` reads a field through a reference, and a comparison through a `none` reference is false.
- `o.<Machine>` and `o.<Counter>` read the state and the counters of the copy that belongs to the instance `o`.
- `this` names the instance of the copy inside its clauses, the entity of a `permit` or `forbid` rule inside its condition, and the first instance in a run of the machine.
- A formula cannot read a field of a basic type or a `list` field.

## Permissions

A rule is a tuple of an actor, an action, and an entity, with a condition:

```
actor Operator, Auditor
external Hook
action Approve by (Operator) on (Order), View
permit Operator Approve Order: Status = Active
forbid Operator Approve Order: Status = Closed as closed
forbid * Delete Order
permit Auditor View Order requires Reason
```

The statements mean:

- `actor` declares an internal role, and `external` declares a system outside the plan.
- `action` declares what an actor can do, optionally restricted to actors with `by` and to entities with `on`.
- `permit` and `forbid` take an actor, an action, and an entity, each of which may be `*`, followed by an optional `:` and a formula.
- `requires <Name>` names an item that the actor must supply, which differs from a permission that an event requires.
- `as <tag>` names a rule, so that the `text` block can attach a rationale to it. A rule tag cannot repeat the name of a definition.

A combination of an internal actor, an action, and an entity that is not passive is a hole in every world of the conditions that no rule covers. The language never reads silence as permission.

A permission names something that an account may do, and an actor is a role that grants permissions:

```
permission ApprovePartner, ViewNotice
actor Manager grants ApprovePartner, ViewNotice
Member.Approve @ApprovePartner {
    Member = Applied => Member' = Partner
    else reject
}
screen NoticeList of Notice shows Notice.title @ViewNotice
```

The statements mean:

- `permission` declares permissions. The business manages roles while the system runs, so a permission that no actor grants is not a hole.
- `grants` after a single `actor` lists the permissions that the role holds.
- A permission in the `@` list of an event, a clause, or a screen stands for any account that holds it, and the generated document names it that way.
- `permit` and `forbid` take only actors.

## Assumptions, invariants, properties, and laws

The statements look like this:

```
assume reviewed_only_when_closed: Review = Approved => Status = Closed
inv confirmed_is_paid: Booking = Confirmed => Payment = Paid
prop never_both: always !(Task = Done & Photo = Bad)
prop can_refund: always Booking = Cancelled & Payment = Paid => can Payment = Refunded
prop closes: reachable Task = Done
law month_order: Order.placed_on < next(Order.placed_on)
```

The statements mean:

- `assume` states a formula that the plan takes as given, and no check verifies it.
- `inv` states a formula that the plan must keep.
- `prop` states a property that the checker verifies and never assumes. `always` requires the formula in every reachable state, and `reachable` requires it in at least one.
- `can <formula>` inside a `prop` holds in a state from which some sequence of transitions leads to a state that satisfies the formula.
- `eventually <formula>` inside a `prop` holds in a state from which every fair run reaches a state that satisfies the formula. A `prop` that starts with `eventually` requires it in every initial state.
- `fair <Machine>.<Event>` assumes that the event happens when it stays possible without end.
- `law` compares two terms with `=`, `<`, `>`, `<=`, or `>=`. The checker verifies that both sides have the same time unit and that the laws can hold together.
- The functions `next` and `before` shift a time value, and `month_of` converts a `Day` to a `Month`.
- `assuming <unknowns>` at the end of an `assume`, `inv`, `prop`, `fair`, or `law` statement names the unknowns that it depends on, as it does for a clause, a rule, a constant, a computed value, and a screen.

## Named conditions and paths

A `pred` names a formula and a `fun` names a path, and both take parameters:

```
pred is_paid(p): p.paid = Yes
pred payable(): Payment = Unpaid & Booking = Requested
fun bill(p): p.Billing
prop paid_first: always all p in Parcel: bill(p) = Settled => is_paid(p)
```

The rules are:

- A use stands for the body with each parameter replaced by the given name or path, so a `pred` fits wherever a formula does and a `fun` wherever a path does.
- A parameter has no type. The checker reports a wrong use through the formula that the use stands for.
- A definition cannot use itself, directly or through another definition.
- A quantifier inside a definition cannot bind a name that a use passes in.
- `import` does not carry a definition into another file.
- The body of a `pred` cannot hold `can` or `eventually`.

## Runs

A run replays events from a start state and states the expected end:

```
run lock_after_two: Account = Active & limit = 1 -> Fail, Fail -> Account = Locked
run pay_then_cancel: Booking = Requested & Payment = Unpaid
    -> Payment.Pay, Booking.Cancel, Payment.Refund
    -> Booking = Cancelled & Payment = Refunded
```

The forms mean:

- A run of one machine starts with `<Machine> = <State>`, lists events by name, and ends with one state of the same machine.
- The conjuncts after the start state give values to enums and constants. The run is replayed once for every world that satisfies them, and it passes only when every replay passes.
- A run of several machines writes each event as `<Machine>.<Event>` and names a state for each machine at the start.

A guard that reads a constant is false in a run that gives the constant no value. A run of several machines cannot name the copy of one instance.

## Views and computed values

The statements look like this:

```
derive Standing of Reader from LoanState mixed Mixed
derive Total of Settlement : Money from SettlementRow, Adjustment.amount
screen LoanList of LoanRecord shows LoanRecord.state, Standing
```

The statements mean:

- `derive … from <Enum> mixed <Value>` defines a status of an entity that is computed from the enum values of its linked rows. The status takes the given extra value when the rows differ.
- `derive … : <Type> from <sources>` declares a value of an entity that is computed and not stored. It names the type and the entities, fields, and other computed values that the value is computed from.
- A source of a computed value is linked to the entity by a field in either direction.
- `screen` lists what a screen displays, which are fields, enums, and derived values, so that every shown item is checked against the model. An `@` list after the shown items names the actors or permissions that open the screen.

A computed value states its inputs and never its calculation, because calculation logic is outside the scope of the language.

## Unknowns

An unknown records something that the plan does not yet decide:

```
unknown value limit_decided { label "제한 횟수" source "회의록 12행" provisional "3회" verified yes }
unknown structure channel_relation { label "채널과 계정의 관계" source "ERP-PLANNING.md 120행" }
```

The policy is `value` or `structure`, and the attributes are:

- `label` gives the wording that the generated document shows for the unknown.
- `source` names where the question came from and is required.
- `provisional` is the temporary decision for a value unknown and is required for one.
- `verified yes` records that the business confirmed the decision, and `verified no` that it has not.
- `open yes` marks a question that the business has not answered, so the document lists it as an open item instead of an assumption.

Another policy, another attribute, an attribute given twice, or a `verified` or `open` value other than the word `yes` or `no` is a syntax error. An unknown shares the names of the module, so an unknown named like another definition is a duplicate.

Modules share one question by declaring it in a file that they import. An importing module reports the findings of an imported unknown only when one of its own statements assumes it, at the line of the file that declares it, and only the build of that file reports it as unreferenced.

An unknown value is a parameter inside a rule, such as a limit or a count. A provisional decision lets the build pass, and the generated document lists the decision as an assumption until it is verified. An unknown structure is the existence of a concept or a relation between sets, and the build fails until the structure is decided, because a guessed structure would turn a passing build into a misleading one.

## Display text

The `text` block holds the wording of the generated document, keyed by name:

```
text {
    module "예약과 결제"
    Booking "예약" why "고객이 요청한 예약 한 건이다."
    Booking.Requested "요청됨"
    Booking.Confirm "확정"
    Account.Fail.lock why "한도에 닿으면 잠근다." after "즉시"
    closed why "종료된 주문은 승인하지 않는다."
    Status.Active "활성" stored "ACTIVE"
    Order.placed_on "주문일" why "주문을 넣은 날이다."
    Standing "이용자 상태" mixed "혼합"
}
```

The entries mean:

- A string after a name is its label, and `why` gives its rationale.
- `<Enum>.<Value>` labels a value, and `stored` gives the text that a database holds for it.
- `<Entity>.<field>`, `<Machine>.<State>`, `<Machine>.<Event>`, and `<Machine>.<Counter>` label a member.
- `<Machine>.<Event>.<tag>` and the tag of a rule attach a rationale to a clause or a rule, and `after` records a time limit of a clause as text.
- `<Machine>.<Event>.else` names the `else` clause of an event.
- `mixed` labels the extra value of a derivation.

An entry can name a definition that the module imports. An entry that names nothing in the module is a syntax error, and so is an entry that gives a name a label or a rationale that the name cannot hold or gives one attribute twice.

## Findings

A finding is one hole or one note that the compiler reports about a module, with a kind, a source file and line, and a message. A blocking finding fails the build. The blocking kinds are:

- `SYNTAX`: the module or a file it imports does not follow this reference.
- `UNDEFINED`: a name is used but not defined, a clause sets a field without the `var` mark, a value is outside the set of a field, or a `fair` statement names an event whose guard reads a free value.
- `DUPLICATE`: a name or enum value is defined twice.
- `CONTRADICTION`: two rules or two clauses give different outcomes for the same case, the assumptions exclude every case, or two laws cannot hold together.
- `UNCOVERED`: a combination of actor, action, entity, and condition world, or a state, event, and guard world, has no rule.
- `OWNERLESS`: a transition has no actor.
- `INAPPLICABLE`: a rule applies an action to an actor or entity that the action declaration excludes.
- `UNREACHABLE`: a state cannot be reached from the initial state once guards and counters are applied.
- `TRAP`: a state cannot reach a final state, or in a cyclic machine cannot return to the initial state.
- `UNHANDLED`: a state that is not final has no clause for an event.
- `SCENARIO_FAILED`: a run is refused by the machine or ends in a different state than expected.
- `UNIT_MISMATCH`: a law compares values of different time units, or a formula orders values that are not numbers.
- `INVARIANT_VIOLATED`: an invariant fails in some reachable combination of machine states, and the message gives the event path.
- `ASSERTION_FAILED`: a `prop` statement fails, and the message gives the event path or the events that can repeat forever.
- `OVERFLOW`: a counter can exceed its maximum.
- `UNKNOWN_STRUCTURE`: the model structure is undecided.
- `UNKNOWN_VALUE`: an unknown value has no provisional decision.
- `MISSING_SOURCE`: an unknown has no source.
- `MISSING`: a required part, such as an initial state, is absent.
- `TOO_LARGE`: a check that only enumeration can run would pass the enumeration limit and was not run.
- `INCONSISTENT`: two modules of one plan define a name in conflicting ways.

The non-blocking kinds are notes:

- `UNVERIFIED`: a provisional decision has not been confirmed by the business. The message also says when nothing assumes the unknown.
- `UNREFERENCED`: a declared name that nothing uses, which is an unknown value that no statement or clause assumes and that `UNVERIFIED` does not report, or a permission that no event, clause, or screen requires.
- `LABEL_DIFFERS`: two modules label one name differently.

## Modules of one plan

A plan splits into modules that the compiler builds one at a time, and `pdl consistency` compares them. Entities of the same name may list different fields, because a module lists only the slice of an entity that it uses, and a term is a stub that another module may model. Two modules conflict when they define one name as different kinds of thing, give an enum different values or stored texts, give a field different types, declare different keys, fix a shared field in one module only, give a constant different ranges, give one actor different permissions, describe one machine differently, or give one unknown a different policy, provisional decision, `verified` flag, or `open` flag, where an omitted flag means `no`. Whether an entity is passive and which actors and entities an action names may differ, because each module covers the permission rules of its own slice. The source of an unknown may differ, because one question can come from several places.

## Complete example

The following module builds clean:

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
