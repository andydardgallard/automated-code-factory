# Subagent Briefing (handoff template)

The single briefing template the main agent uses when launching ANY subagent:
`factory-analyzer`, `factory-coder`, `factory-tester`, `factory-diagnostician`,
`factory-code-reviewer`, `factory-advisor`. The briefing is the subagent's only input: it does not
see the main agent's dialog history and must not request it. Whatever did not make it into the
briefing does not exist for the subagent.

Sources: `paseo` (handoff: a fixed template + files by path instead of pastes) and Kaggle 5-Day
AI Agents Intensive, Day 2 (the concise-output contract: the subagent returns a digest and a link
to the artifact, not raw data).

## 1. The "files — by path, never by paste" rule

Pasting file contents into the subagent's prompt is FORBIDDEN — only the path and one line
"why the file matters". Reasons:

- **Context isolation**: a subagent is launched for a clean window; pasting foreign content
  clutters it and degrades reasoning exactly where a fresh head is needed.
- **Double payment**: the main agent reads the file (paying tokens for it) and the subagent
  re-reads it with its own tool anyway — a paste is paid for twice and saves nothing.
- **Staleness and truncation**: a pasted fragment may be truncated or already stale; the subagent
  will take it for truth. A path forces reading the current version.
- **Silent loss of an event**: whatever did not fit into the paste never happened for the subagent.

What instead of a paste:
- the path + the file's purpose ("the escalation ladder lives here"), plus a line/section when needed;
- for large logs — `python .agents/skills/code-factory/scripts/log_tail.py <file> --lines N
  --grep PATTERN`: the briefing gets the counters, the match count and the tail, not the whole log;
- for searching/counting across files — not a list of files in the prompt: the subagent is allowed
  to write its own stdlib script (see `Think in Code` in `references/verification-strategy.md`).

## 2. The briefing template (mandatory for all roles)

All eight sections are always present. A section with no content is marked "none" — a silent
omission is forbidden: the subagent cannot tell "nothing to say" from "forgot to pass".

### Task
One sentence: what exactly to do. Phrase the action, not the implementation
("add the transition to Advisor in error-routing", not "call function X"). One briefing — one
high-level task: if there are two tasks, two subagents are launched.

### Context
Why the task exists and where it came from: the business goal, `user_story` (if any), the pipeline
stage, a link to the plan/task. Enough for the subagent to understand why the result is needed and
to be able to object on substance.

### Relevant files
Paths + one line "why the file matters". Contents are not pasted (see §1). If there are more than
~10 files, do not list them all: name the entry points and give a rule for finding the rest with a
script.

### Current state
What is already done by this point: the baseline (commit, branch, results of the latest test run),
the artifacts created in `.code-factory/`, the state of the working tree. The subagent must not
re-ask what is already known.

### What was tried — why it failed
Mandatory for retries and escalations. A list of attempts: what was tried, how it ended, why it did
not work. A role that repeats a rejected approach is a wasted budget. For the first attempt
write "no attempts were made".

### Decisions
Decisions already made that MUST NOT be revisited within this task (model choice, identifiers,
artifact format, forbidden alternatives). If the subagent has an objection — it reports it,
but does not change the decision.

### Acceptance criteria
How the result is verified: concrete commands and the expected output (exit code, PASS/FAIL, grep,
comparison). A criterion without a verification command is considered unverifiable and does not go
into the briefing.

### Constraints
The boundaries of the work: only the listed files (its own files are untouchable for others),
stdlib-only (new dependencies are forbidden), the actual model (`model_preference`), the
environment interpreter (on Windows — `python`, `python3` may be absent), the ban on running the
full test suite where the tester does that, and the no-edits suffix for analytical roles.

The `factory-coder` briefing always carries the ban on git mutations of the shared working tree in
Constraints: `git stash` / `git reset` / `git checkout` / `git clean` are not performed on the
shared tree; the base version of a file is viewed via `git show HEAD:<file>` or a separate temp
clone — the tree is shared by the main agent and parallel subagents.

<!-- factory-rule: no-shared-tree-git-mutations begin -->
**No shared-tree git mutations (canonical wording):** subagents do NOT run `git stash`, `git reset`, `git checkout` or `git clean` on the run's shared working tree — it is shared by the main agent and other parallel subagents, and such operations create a race risk and the loss of others' changes. To prove a bug pre-existed or to view a file's base version, `git show HEAD:<file>` or a separate temp clone is used; only the main agent performs working-tree git mutations.
<!-- factory-rule: no-shared-tree-git-mutations end -->

## 3. The concise-output contract

The subagent's final answer is a handoff, not a process report:

- a short summary ≤ 15 lines (what was done/found, the status, the key numbers) + paths to artifacts;
- NO file or log dumps in the answer: long content stays in files
  (`.code-factory/logs/...`), the answer carries the tail and the counters;
- evidence — by reference (path + line/section) or by an exact quote, not by paraphrase;
- if something was not done — state explicitly what and why (an instructive error: the cause + the
  recovery path); a silent failure is forbidden;
- inflating the answer = higher cost and latency + degradation of the reasoning of the main agent,
  which reads this answer.

## 4. The no-edits suffix

Every analytical role (`analyzer`, `diagnostician`, `advisor`, `code-reviewer`) gets an explicit
suffix line in the briefing: "You MUST NOT create, modify or delete any file". A role without edit
rights cannot "fix along the way" what it finds — it reports it in the handoff, and the main agent
decides. For `advisor` this is additionally pinned by `disallowedTools: Write, Edit`.

## 5. A mini-example of a filled-in briefing

```text
Task: add Advisor to the escalation ladder of references/error-routing.md (§2 and §5).
Context: run task_08 hardens the factory; the rule is already approved in the plan, references to the new subagent are needed.
Relevant files: .agents/skills/code-factory/references/error-routing.md — the escalation ladder; .agents/agents/sub-agents/advisor.md — the role description.
Current state: advisor.md is created; on the base commit all self-tests PASS (test_factory_model.py, test_prompt_structure.py).
What was tried — why it failed: editing only §2 — the reviewer rejected it: §5 was left without Advisor, the document is inconsistent.
Decisions: the role identifier is advisor; the model is secondary (the family contrasting diagnostician); the ladder itself does not change.
Acceptance criteria: grep -n "Advisor" references/error-routing.md finds §2 and §5; python scripts/test_factory_model.py PASS.
Constraints: only the two listed files; stdlib-only; python (no python3); in the answer — a summary ≤ 15 lines, no dumps.
```

## 6. The main agent's checklist before launching a subagent

1. All eight sections are present; the empty ones are marked "none".
2. The briefing contains not a single pasted file/log fragment — only paths.
3. The attempts and the reasons for failure are listed (if this is not the first attempt).
4. The acceptance criteria are verifiable by a command, not by words.
5. Own files, the model, the stdlib constraint and the environment interpreter are specified.
6. The no-edits suffix is added for an analytical role.
7. The answer format per §3 (summary + artifact paths) is requested.
