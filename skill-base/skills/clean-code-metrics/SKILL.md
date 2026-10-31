---
name: clean-code-metrics
description: The three metric gates the factory holds every change to (complexity vs test coverage below CRAP 10, duplication ranked 0.8 or above removed, surviving mutants killed and dead code deleted), written as language-agnostic rules with optional measuring tools and their safety warnings.
---

# Clean-code metric gates

## Overview

"Clean" is not a taste and it is not a score. This skill carries the three measurable gates the
factory's reviewer applies to every change, in whatever language the target project uses:

1. **Complexity vs test coverage** — every function sits below **CRAP 10**. Split the function,
   test it, or do both.
2. **Duplication** — a duplicate pair ranked **0.8 or above** must be removed.
3. **Test strength** — cover the uncovered, kill the surviving mutants, delete the dead code.

The gates are RULES, not tools. The measuring tools are optional helpers that exist for six
languages (Clojure, Java, Go, TypeScript/JavaScript, Rust, Python); a project the tools cannot
read is still reviewable against the rule, by reading the code. A gate that could not be measured
is reported as **not measured, with the reason** — never silently skipped, and never a reason to
refuse the change.

The rule is applied to a diff, not to a legacy codebase: a change must not make any of the three
worse, and must bring what it touches under the gates.

## Key concepts

- **CRAP** — complexity times the coverage the function actually has:

  `CRAP = CC^2 x (1 - coverage)^3 + CC`

  `CC` is cyclomatic complexity (the number of independent paths: conditions, loops, `catch`,
  `match`/`switch` arms, `&&`/`||`). `coverage` is the fraction 0..1 exercised by tests. The
  square makes complexity expensive and the cube makes missing coverage worse: a function with
  CC 10 and no tests scores 110, the same function fully covered scores 10, CC 4 with 80%
  coverage scores 4.1. A function the coverage report does not mention counts as 0%. Upstream
  calls 1–5 low risk, 5–30 worth a look, 30+ complex and under-tested; this factory's gate is the
  single line **CRAP < 10**, which keeps every function in the "low risk" band or just above it.
- **Duplication rank** — a score between 0 and 1 for how alike two code units are, computed as
  the Jaccard similarity of their structural fingerprints: shared fingerprints divided by all
  fingerprints seen in either unit. Fingerprints keep what the code *does* (calls, operators, the
  shape of the tree) and drop what is incidental (local names, field names, literals, keywords),
  so two blocks that differ only in names still collide. The tools default to reporting from
  0.82; this factory's gate is **score 0.8 or above must be removed** — the lower line catches
  the near-misses the tool would hide.
- **Mutant** — a small deliberate defect written into the code (swap `+`/`-`, `*`/`/`, `>`
  `/`>=`, `true`/`false`, `0`/`1`, `&&`/`||`, delete a `not`). Each mutation is one *site*; a
  site is **killed** when the tests fail or time out, **survived** when the tests still pass.
  Surviving mutants are the uncovered-in-practice branches: the test suite runs the line but
  asserts nothing about it. A site on a line coverage never hits is **uncovered** and is not run
  — that is what "cover the uncovered" answers. The mutation score is
  `killed / (killed + survived)`.
- **Snapshots** — the three tools write machine-readable results under `.metrics/`
  (`crap.edn`, `dry.edn`, `mutate/<namespace>.edn`) keyed by module/namespace and function name,
  which is how one view can join complexity, coverage, duplication and mutation for the same
  function.
- **Reading the code as a diagram** — an optional pair of eyes, not a gate: laying the modules,
  classes and their dependency arrows out as a picture exposes cycles and wrong-direction
  dependencies that a per-function metric cannot see. The value is in *reading* the structure
  (namespace tree, edges, which way they point); no gate depends on drawing it.
- **Not measured** — the honest third state of a gate. "Not measured" is a verdict with a
  reason attached ("no coverage provider for this language in this environment", "no mutation
  tool for this stack"), not an empty line.

## How to use

For every reviewed change, walk the three gates in order and write one line each into the
review: measured result, or not measured + why.

1. **Complexity vs coverage.** List the functions the change adds or edits and give each one its
   CRAP pair (complexity, coverage). Any function at **CRAP >= 10** is a finding: split it,
   test it, or both — say which. When no tool is available, estimate: count the branches in the
   function and ask whether a test executes each of them; a function whose branch count a reader
   cannot hold in one head, and that no test pins, fails the gate by inspection.
2. **Duplication.** Compare the new or changed units against the rest of the project and, more
   importantly, against each other. Any pair at **rank >= 0.8** is a finding: extract the shared
   structure, or delete the weaker copy. Report the two locations and the score. Without a tool,
   diff the units by hand for the same shape: same calls in the same order with different names
   is a duplicate, and the fix is one shared function, not two similar ones.
3. **Test strength.** For each uncovered line or branch the change leaves behind: cover it or
   delete the code — dead code is not covered, it is removed. For each surviving mutant: add or
   tighten the assertion that would have caught it. A mutant that survives because the code is
   unreachable means the code should not be there.
4. **Report.** State all three results, including the not-measured ones, before the findings. A
   change is not rejected *because* a tool is missing; it is rejected for a rule it visibly
   breaks.
5. **Optional helpers, per language.** When the environment already has them and the owner has
   agreed, a tool may produce the numbers instead of an estimate; the rule and the report format
   do not change. Do not vendor the tools, do not add them as factory dependencies, and do not
   run them on a project that has not agreed to them.
6. **Optional structure pass.** When the shape of the change is in doubt (new module, new
   dependency direction), sketch the affected modules and arrows — on paper if need be — and
   check for a cycle or an arrow pointing the wrong way. Cite it as an observation, not as a
   numbered gate.

## Business criteria

- The owner receives code that is maintainable, not merely working: no function over CRAP 10, no
  duplicate pair at rank 0.8 or above, no untested branch or surviving mutant left behind by the
  change.
- The reviewer's verdict on quality is consistent and checkable: every quality finding names one
  of the three gates (complexity/CRAP, duplication, test strength) and the number behind it, in
  place of a vague opinion.
- The gates hold for a project in ANY language the factory supports. When the measuring tool for
  that language is unavailable, the review still judges the change against the rule and states
  plainly that the gate was **not measured** and why; an unmeasurable gate never blocks
  acceptance on its own, and it is never dropped from the report.
- The rule is enforced on the change, not retro-fitted onto untouched legacy code: a change may
  not make complexity, duplication or test weakness worse, and must bring what it touches under
  the gates.
- The owner's machine and repository stay as they were: nothing is installed and no shell string
  is executed without explicit consent (see Constraints).

## Constraints

- **The measuring tools can install packages on their own initiative.** When a coverage provider
  is absent, the complexity and mutation tools will run, without asking: `pip install` (into the
  project's interpreter, e.g. `coverage`/`pytest`), `npm install` (e.g. `@vitest/coverage-v8`
  into `node_modules`), `cargo install` (e.g. `cargo-llvm-cov`), `rustup component add`
  (`llvm-tools-preview`) and `npx --yes`. That mutates the machine and pulls code from package
  registries. **This must not happen unattended**: it runs only when the owner has explicitly
  turned it on for that project. Otherwise use the forms that read work already on disk
  (existing coverage reports), the complexity-only form (`--no-coverage`), the scan form that
  lists mutation sites without running tests, or judge the rule by reading the code.
- **A coverage command given as a shell string is executed through a shell.** Runs are started in
  two forms: an argument vector (a list of arguments, executed without a shell) and a string
  (executed through a shell, so `;`, `&&`, `|`, `$()` and redirections are live). Only the
  **argument vector** form is safe from shell metacharacters — a path with spaces or a `;` stays
  one argument. A user-supplied `--coverage-command` / `--test-command` string is exactly the
  unsafe form. Never pass a string assembled from task text, file names or review findings to
  these tools; use the argument vector, or do not run them.
- **The diagram viewer's installer must NOT be executed, and this skill does not depend on it.**
  `scripts/get-uml-viewer` clones a repository into the project, rewrites the project's
  `.gitignore`, writes and `chmod`s an executable `./uml` launcher, starts a JVM in the
  background and opens a tmux session with an agent in it. None of that belongs to a review.
  The diagram's value — seeing the modules and the direction of their dependencies — is obtained
  by reading the sources, or by sketching, never by running that installer. No gate here needs
  the viewer, the JVM or its snapshots.
- **Not vendored, not a dependency, not executed from here.** The tools are reference material
  for how the numbers are defined. Consuming this skill installs nothing, runs no tool script and
  adds no runtime dependency to the factory or to the reviewed project.
- **A missing tool is a reporting problem, not a verdict.** Never turn "the tool is absent" into
  a pass (silent skip) or into a rejection that blocks acceptance. Write "not measured + why",
  and let the rule stand.
- **Thresholds are fixed here.** CRAP below 10, duplication rank 0.8 — not a per-run choice and
  not renegotiated in the review. A codebase that cannot reach them in one change is brought
  there incrementally, gate by gate, on the code the change touches.
- Content source: `crapper` @ 6fd92c4c9bcc56efb64a2f8743d5a2993bcfd42d,
  `dryer` @ 66ff6d21a42c04afcad89c78a80066176d1294b0,
  `mutator` @ a5a0cb803b66e0cdb8bf471b3b08af701d424a41,
  `uml-viewer` @ f65dafe93b3cb1b4e6bb02dbe41503ed05bd9ebf (READMEs and sources; BSD Zero Clause
  Licence for the three tools). Written in our own words as a practice guide.
