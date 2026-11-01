# Factory backlog — open items not yet run as factory tasks
project: repo
repo_path: .
project_id: dd18352c83a5

# Intake file for the factory's own backlog (owner decision 2026-11-01).
# Each item is written in the task-file format and starts as a separate run:
#   /skill:code-factory backlog_review_workflow_dead_paths.yaml
# This file is NOT part of the factory workflow; it is a queue the owner reads.

open:
  - item: Review factory workflow for dead paths after the Kimi Code upgrade (EnterPlanMode and similar)
    task_file: backlog_review_workflow_dead_paths.yaml
    task_type: review
    status: done — run 20261101-e519a1da (report-only); 10 findings (3 critical) handed over as .code-factory/review/fix-tasks.yaml; subtask A premise about root docs refuted, subtask B confirmed with a non-vacuous check proposal
    severity: warning
    follow_up: true
    why: |
      The factory's flow (SKILL.md node I, code-factory.md Phase 3, planning-guide.md §6) tells the
      agent to "call EnterPlanMode then ExitPlanMode". In Kimi Code 2.4.1 plan mode is user-only
      (Shift-Tab or /plan) and there is no tool to enter it; only ExitPlanMode exists. The plan
      approval gate still works (plan file + an explicit approval question), so the workflow
      degrades silently rather than losing the gate — the owner wants a full review of the flow for
      other dead paths and dead code, then deletion of what is dead.
    found: 2026-11-01
    evidence: |
      https://www.kimi.com/code/docs/en/kimi-code-cli/reference/tools.html ("Plan mode ... only the
      user can turn on (Shift-Tab or /plan); the agent has no tool to enter it");
      https://www.kimi.com/code/docs/en/kimi-code-cli/guides/interaction.html (Plan mode section).
      Carriers verified by grep in this repo:
        .agents/skills/code-factory/SKILL.md:111
        .agents/agents/code-factory.md:259
        .agents/skills/code-factory/references/planning-guide.md:192
    subtasks:
      - id: A
        item: Operator-facing carriers outside the three factory files — AGENTS.md and .agents/README.md also describe plan mode / EnterPlanMode as working mechanics; find them (file:line) and hand them to the same follow-up task file
      - id: B
        item: Validation gap — check_factory_rules.py reconciles only `factory-rule` blocks, so every flow statement outside those blocks (flowchart node descriptions, tool names, CLI modes) goes unchecked; propose a deterministic check and prove it is red on the current tree

  - item: Factory must enforce obvious variable/input validation in code it writes
    task_file: (not written yet — queue entry only)
    task_type: implement
    status: queued
    severity: warning
    follow_up: true
    why: |
      Owner finding from run farukon_v3.1.0/20261101-85052459: the factory added a new optional
      config field `lshade_params.stall_patience` as a `usize`. A type-only choice silently covered
      the negative case (serde rejects `-1` for `usize`) and hid the real defect — `0` was accepted
      and degenerated into "for 0 consecutive iterations", an immediate early stop. The neighbouring
      fields of the same struct carry explicit `> 0` validation (farukon_core/src/settings.rs:464-479);
      the NEW field was added without one, and no reviewer gate noticed that the new input path was
      left unprotected. The owner wants this class of mistake caught by the factory itself, not by a
      human reading the diff.
    found: 2026-11-01
    evidence: |
      Reproduced: config with stall_patience=-1 -> "invalid value: integer `-1`, expected usize" (exit 1);
      config with stall_patience=0 -> accepted, console prints "LSHADE-RSP converged: no relative
      improvement > 0.000001 for 0 consecutive iterations. Stopping early at Evals=20/300".
      Sibling guards at farukon_core/src/settings.rs:464-479; the new field has none.
      Recorded in the target project's backlog as commit 75da663c (farukon_v3.1.0).
    owner_requirements: |
      - Missing input validation must be caught by the factory itself — a human must not have to find
        it while reading a diff.
      - The checks must be chosen by the field's TYPE AND PURPOSE, not applied mechanically: a value
        that may legitimately be 0 must not be rejected by a blanket "non-zero" rule, and a check
        imposed without a reason is as much a defect as a missing one.
      - OVERFLOW must be checked too: conversions, arithmetic on user-supplied numbers, and casts
        between widths/signedness are in scope, not only range and non-zero.
      - The factory decides HOW to strengthen itself (which rule, which carriers, which gate, which
        deterministic check) — this item records the requirement, not the design.
    evidence_of_overflow_class: |
      The same run's target code already shows the class: `stall_patience: usize` is unbounded above
      (a huge value outlives any realistic `max_evaluations`), and `Farukon_2/src/main.rs` /
      `portfolio` configs use `usize`/`u64`/`f64` for counts and prices whose conversions are not
      systematically guarded. Recorded as a class to investigate, not as a verified defect.
    related: |
      Paths that today can silently pass an unvalidated new input: analyzer (no validation inventory),
      planner (no boundary/overflow task), coder (followed the plan literally), reviewer (checked the
      field exists, not that it is validated in a way that fits its purpose), acceptance (verify
      criteria checked text presence, not behaviour on refusal).
