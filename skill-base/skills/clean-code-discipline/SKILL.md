---
name: clean-code-discipline
description: The writing discipline every code-writing role works under — first make it work, then make it right, then follow practice, with named, checkable rules (one decision one place, smallest edit, data shape before logic, failing test first, root cause over guard, subtract before you add, boundary discipline) that apply in any programming language.
---

# Clean Code Discipline

## Overview

This is the discipline under which the factory writes and changes code. It has three phases, and
the ORDER is part of the discipline:

1. **First make it work** — produce the smallest change that makes the requested behavior real.
2. **Then make it right** — remove the causes of what is still wrong: hidden defects, unclear
   structure, untested behavior.
3. **Then follow practice** — log, keep the working context small, clean up, and hand the change
   over as small ordered commits that say why and how it was proven.

Practice applied before the code works only decorates a defect; "right" attempted before "works"
has nothing to judge yet. Every rule below is a habit that can be checked by looking at the change
— not a matter of taste.

The rules are stated in terms of data, decisions, tests and boundaries, never in terms of one
language's syntax. Where a language lacks a facility a rule names (a type system, a test runner, a
pure-function boundary), the restatement in its block says what the same discipline looks like
there. This skill is reference practice appended to a role's context; the factory's flow and its
mandatory rules stay authoritative.

## Key concepts

### Phase 1 — First make it work

- **One decision, one place.** A rule ("how a tax rate is chosen", "what a valid id looks like")
  lives in exactly one spot. If a second copy of the decision is needed, the first one is moved,
  not duplicated.
- **Smallest edit.** Ship the change that solves the stated problem and nothing else. No drive-by
  cleanups, renames or upgrades in the same edit — they make the diff unreadable and the proof
  impossible. Extra cleanups go into the phase-2 pass or into a separate task.
- **Data shape before logic.** Decide what the data is and how it is represented before writing
  the computation. A wrong shape forces defensive logic everywhere; a right shape makes most of
  the logic simple or unnecessary.
- **Do first what unblocks the rest.** Order the work so that each step makes the later steps
  cheaper, not more expensive.
- **Failing test first.** Write the test that describes the behavior, run it, see it fail for the
  reason you expect, then make the smallest change that makes it pass. If an honest test is
  impractical, do not write a test that cannot fail: say plainly which behavior is unverified and
  why.
- **Redesign from first principles, in slices.** Do not bolt a new requirement onto a design that
  did not anticipate it. Ask what you would have built had the requirement been there from the
  start, think that through, then deliver it in pieces that each stay green.
- **Attack the premise.** When two fixes that share one premise fail the same check, stop fixing.
  Write the shared premise in one sentence, count which participant carries the imbalance, remove
  that assignment, and only then attempt the next fix.
- **Subtract before you add.** Take complexity out before you add anything: a dead branch, a
  duplicate path, an unused parameter. Adding to a tangle multiplies the tangle.
- **Aim at a state you can check.** Define the end state by something observable (a test, a
  command, an acceptance criterion), not by a feeling. A break in the middle is allowed when it
  was planned and can be undone.
- **Build the lever.** If the work is not obvious at a glance, build the small tool that does it:
  do one unit by hand, then make the tool reproduce exactly that unit.
- **Model the domain.** Structure the model so that illegal states cannot be constructed; keep a
  short glossary of the domain's terms and use those words in the code. If the existing code is
  already clear and local, leave it alone — clarity, not novelty, is the goal.
- **Boundary discipline.** Check and normalize data where it ENTERS the system, then trust it
  inside: no re-validating the same value in every layer. Keep the business logic in a pure
  function that takes the already-validated data and returns a result.
- **Make illegal values unwritable.** Use the type system (or, without one, a single parse step at
  the boundary plus an invariant stated in the code) so a wrong value cannot be expressed. Parse
  outside data exactly once, at the edge. Never silence the compiler, the linter or the type
  checker to get green.
- **Idempotent operations.** Running an operation twice, or after a crash halfway through, must
  end in the same state. Migrations, scripts, installers and handlers all obey this.
- **Separate before sharing mutable state.** If two parts do not need the same mutable thing, give
  each its own. If they do, allow exactly one writer and enforce that in the structure rather than
  in a comment.

### Phase 2 — Then make it right

- **Root cause over guard.** Reproduce the defect, fix the cause, and prove the reproduction now
  passes. A guard that only hides the crash, swallows the error or retries until it works is not a
  fix; if a guard is still needed, it is an explicit, documented decision, not a reflex.
- **Sequence the work into verifiable units.** Finish one small unit, check it, then start the
  next. Never leave several half-done changes at once.
- **Test behavior, not implementation.** The test calls the code the way its user does and checks
  the result that user would see. A test that would still pass if every function returned nothing
  proves nothing: throw it out.
- **Refactor in three moves.** Pin what the code does (tests), change only the structure, then
  prove the behavior did not change. A "refactor" that changes behavior is a different task and
  must be declared as one.
- **Complexity and coverage are judged together.** A simple function and a well-covered function
  are the same obligation seen from two sides: split the function, test it, or both. Measurement
  decides whether "right" is finished; it does not replace the writing rules above.

### Phase 3 — Then follow practice

- **Keep a log.** Record every action and the reason for it, and report that log when the change
  is handed over. The log is what makes a later reader able to trust or reverse the decision.
- **Guard the context window.** Keep the working thread small: send bulk reading elsewhere and
  keep the summary, so the decision being made stays in view.
- **Clean up what you touched.** Identify what is now safe to remove, confirm nothing still in use
  depends on it, then reclaim it. Work that is uncommitted waits for a decision instead of being
  deleted quietly.
- **Commit in small ordered steps.** Each commit says why the change was made, what changed, and
  how it was proven. Small commits are what makes rollback and review cheap.

## How to use

- Open any change by naming its phase out loud: what would make it WORK, what would make it RIGHT,
  what PRACTICE it must satisfy. Do not skip forward — a phase-2 cleanup of code that does not yet
  work wastes the edit that will replace it.
- Use the rule list as a checklist twice: once while planning the smallest edit (phase 1), once
  before handing the change over — for each rule, say either how the change satisfies it or why it
  does not apply here.
- Restate a rule in the language at hand before claiming it: "pure function" is a function with no
  hidden inputs in a functional language and a method with validated arguments and no side effects
  in an object-oriented one; "type system" is a compiler-checked type, a schema, or a single parse
  step where the language has neither.
- A defect found while writing is a phase-2 item: finish the phase-1 edit, then fix the cause. Do
  not bundle the two, and do not silence it.
- Reviewers judge a change by these same named rules, so a finding should cite the rule it breaks
  (for example "smallest edit", "root cause over guard", "boundary discipline") instead of an
  opinion.
- Metric gates (CRAP, duplication, mutation) and the safe handling of their measuring tools live in
  the companion skill `clean-code-metrics`.

## Constraints

- The discipline never widens the task. "Smallest edit" forbids unrelated improvements, and
  "make it right" applies to the code the change touches, not to the whole repository.
- Never claim a rule was followed without evidence: if a behavior is untested, a language lacks a
  facility, or a check could not be run, say so plainly and name the reason rather than staying
  silent.
- Never buy green by disabling a check — no skipped or emptied test, no silenced compiler or
  analyzer, no broad exception handler, no retry loop standing in for a cause.
- Behavior-changing work never travels disguised as a refactor, and a refactor never ships without
  its behavior pinned first.
- This skill carries no gate thresholds and no tool instructions: how the gates are measured, and
  the rules that a tool must never install packages on its own initiative or run a command given
  as a shell string, are the companion skill's business, not this one's.
- Content source: `https://github.com/unclebob/ub-mode.git` @
  57a8bdd28e45ed41900ace0bafa2ff76dd9ed70f — read as reference data and restated here in the
  factory's own words as a practice guide; none of that repository's code or scripts is executed,
  and no upstream file is relabelled wholesale.
