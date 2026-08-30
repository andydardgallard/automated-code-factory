# Refactoring Task Type

Goal: systematically reduce technical debt — remove duplication, simplify complex architecture,
improve structure — **without changing behavior for the end user**. A refactor succeeds only if
the code structure improves AND 100% of the existing regression, integration and business tests
pass unchanged. Any change to external behavior or business logic is a critical error and
triggers automatic rollback.

## 1. Core invariant — "freeze functionality"

- **Tests are frozen.** The existing test suite is the contract. The refactor must NOT modify,
  weaken, delete or add-to the *behavioral* expectations of any existing test. (Adding new
  pure-unit tests for a newly extracted helper is allowed, but they must not change what the
  existing suite asserts.)
- **No behavior change.** Public APIs, output formats, return values, config keys, file paths and
  side effects stay identical. Only internal structure may change (rename locals, extract
  functions/classes, dedupe, reorder, split modules).
- **Any drift = rollback.** If any existing test needs editing to match the new code, or any
  business result differs from the baseline, the refactor has leaked behavior → classify as a
  critical regression and roll back (see `verification-strategy.md` §4).

## 2. Flow

1. **Baseline first.** Run the full existing suite and save it (`.code-factory/logs/baseline.md`).
   This is the reference that "no behavior change" is measured against.
2. **Detect debt.** Use `factory-analyzer` (or the `factory-refactorer` subagent) to locate
   duplication, dead code, over-complex modules, and unclear boundaries. Report findings as the
   plan's DAG tasks.
3. **Plan structural-only changes.** Each task is a small, independently-verifiable structural
   improvement with a single verification command (`run the existing suite for the affected module`).
4. **Implement.** The `factory-refactorer` subagent performs the change following the project's
   style, applying the Lazy Senior ladder, and re-runs the affected tests itself.
5. **Verify the invariant.** After ALL changes, run the FULL existing suite. Compare to the
   baseline byte-for-byte on the results: the same tests pass, and no test changed.
6. **Acceptance.** Success = structural improvement (recorded in the plan/diff) + full suite
   passes unchanged. If the suite changed at all, roll back and route the failure per
   `error-routing.md`.

## 3. Verification commands

- Regression: the project's canonical full test command (from `tech-stack-detection.md`), run
  BEFORE and AFTER, results compared.
- `git diff --stat` must show only internal-structure changes (no public API / config / output
  changes). The code reviewer double-checks this in the final gate.

## 4. Specialized agents

- `factory-refactorer` — performs the structural edits under the freeze-functionality invariant.
- `factory-code-reviewer` — the final gate re-verifies that the diff is structural-only and no
  behavior leaked.

## 5. Rules

- Do not "improve while I'm in there" beyond the planned structural change — scope stays minimal.
- Do not fix unrelated bugs; if one is found, record it as an assumption/finding and leave it
  out of this refactor (or create a separate task).
- A refactor task is never accepted while the existing suite has any change or failure.
