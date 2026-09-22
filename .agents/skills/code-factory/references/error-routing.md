# Error Routing

Goal: on ANY test/build failure, route the fix to the right role deterministically (~90% of
cases, zero LLM tokens), and only escalate to the Diagnostician (1 LLM call) for the rest.
The factory NEVER crashes silently — unknown errors always fall through to the Diagnostician,
then the Advisor (a second opinion, §4.1), then Human, then FAILED with a full log.

## 1. Classification (deterministic, regex-based)

The machine-readable source of the patterns is the project's `.code-factory/state/error-patterns.json`
(project-learned: the Diagnostician adds new patterns during runs and `python
.agents/skills/code-factory/scripts/error_router.py merge --project <file>` folds them in,
project-first); the fallback is the shipped snapshot `references/error-patterns.default.json`.
Classification is executed by `python .agents/skills/code-factory/scripts/error_router.py classify
--log <file>` (exit 1 = unreadable log, exit 2 = unusable patterns JSON); when a table below
disagrees with the JSON, the JSON is authoritative. The tables are kept as documentation of the
default snapshot.

Known quirks of that snapshot (carried over verbatim so the JSON and the tables below match):
row 8 keeps `error[E\d+]` as a character class — it matches one of the characters `E`, `\d`, `+`,
not a Rust error code; row 18 keeps unescaped parentheses in `Traceback (most recent call last)`,
so they form a group; rows 16/17 are two identical TIMEOUT rows and, under first-match-wins, row
16 shadows row 17 (an output containing "test" routes to PLANNER, anything else never reaches
row 17's CODER); and the §2 nuance `WRONG_RESULTS (with "regression")` → CODER does NOT apply
under JSON-first classification: row 2 of the snapshot matches any WRONG_RESULTS (its pattern
contains `regression`) and routes it to DIAGNOSTICIAN, and the JSON is authoritative over the §2
table.

Match the combined error output (stdout + stderr) against these patterns IN ORDER — more
specific first. First match wins.

| # | Category | Match patterns (regex, case-insensitive) | Route to |
|---|----------|-------------------------------------------|----------|
| 1 | MISSING_INPUT | `Task file not found\|Work dir not found` | HUMAN |
| 2 | WRONG_RESULTS | `zero Total_Return\|no trades occurred\|all combinations produced identical\|expected .* but got\|regression\|no meaningful signals\|no nonzero\|zero return` | DIAGNOSTICIAN |
| 3 | INFRASTRUCTURE | `Merge conflict in (target/|node_modules/|__pycache__/|build/|dist/)` | INFRASTRUCTURE (auto-fix) |
| 4 | INFRASTRUCTURE | `(build artifacts|target/|node_modules/) (tracked|committed) in git` | INFRASTRUCTURE (auto-fix) |
| 5 | MISSING_FILE | `No such file or directory\|cannot open file\|file not found\|does not exist` | BA |
| 6 | MISSING_FILE | `ModuleNotFoundError\|ImportError.*No module named` | BA |
| 7 | BAD_COMMAND | `command not found\|: not found\|No such command\|unknown option\|syntax error near unexpected token` | PLANNER |
| 8 | COMPILE_ERROR | `error[E\d+]\|^error: \|cannot find\|failed to compile\|no member named` | CODER |
| 9 | COMPILE_ERROR | `SyntaxError\|IndentationError\|NameError.*not defined` | CODER |
| 10 | COMPILE_ERROR | `npm ERR!\|error TS\d+\|Type error:\|cannot find module` | CODER |
| 11 | COMPILE_ERROR | `go: cannot find\|cannot find package\|\.go:\d+:\d+: .* undefined` | CODER |
| 12 | COMPILE_ERROR | `cannot find symbol\|\.java:\d+: error:` | CODER |
| 13 | LINK_ERROR | `linking\|undefined reference\|cannot find -l\|ld returned\|library not found` | CODER |
| 14 | DEPENDENCY | `cargo.*could not compile.*dependency\|npm ERR! 404\|pip.*No matching distribution` | INFRASTRUCTURE |
| 15 | PERMISSION | `Permission denied\|EACCES\|operation not permitted\|sudo required` | HUMAN |
| 16 | TIMEOUT | `timed?\s*out\|timeout\|TimeoutExpired\|operation timed out` (with "test" in output) | PLANNER |
| 17 | TIMEOUT | `timed?\s*out\|timeout\|TimeoutExpired\|operation timed out` | CODER |
| 18 | RUNTIME_CRASH | `thread .* panicked\|Segmentation fault\|core dumped\|Fatal error\|Traceback (most recent call last)\|panic:` | CODER |
| 19 | ASSERTION | `AssertionError\|assert .* failed\|test.*failed\|FAILED.*test` | CODER |
| 20 | UNKNOWN | (no pattern matched) | DIAGNOSTICIAN |

Notes:
- Patterns are language-agnostic; add more regexes over time as new error families appear.
- The "wrong business results" pattern (row 2) MUST be checked before generic assertion/compile
  patterns, because business markers may appear inside an assertion message.

## 1.1 Provider errors (Kimi / Qwen) — integrated into the same routing

When a task's `models` field selects a Kimi (Kimi K3 / Moonshot) or Qwen model, the same
deterministic routing handles provider-side failures. See `references/providers.md` for the
endpoint/auth/routing rules. Add these patterns (in order, most specific first):

| # | Category | Match patterns (regex, case-insensitive) | Route to |
|---|----------|------------------------------------------|----------|
| A | PROVIDER_AUTH | `401\|unauthorized\|invalid api key\|authentication failed\|api key (missing\|expired)` | INFRASTRUCTURE |
| B | PROVIDER_AUTH | `403\|forbidden\|access denied\|insufficient permission` | INFRASTRUCTURE |
| C | PROVIDER_RATE | `429\|rate limit\|too many requests\|quota exceeded\|billing\|insufficient.*balance` | INFRASTRUCTURE |
| D | PROVIDER_MODEL | `model (not found\|does not exist\|not available\|invalid.*model)` | PLANNER |
| E | PROVIDER_UPSTREAM | `502\|503\|504\|5\d\d\|upstream\|temporarily unavailable\|connection (refused\|reset)` | INFRASTRUCTURE |
| F | PROVIDER_FORMAT | `unsupported.*format\|malformed.*request\|invalid_request_error\|base_url.*not reachable` | PLANNER |

Routing rules:
- AUTH / RATE / UPSTREAM → INFRASTRUCTURE (auto-fix: verify/repair the provider config in
  `~/.kimi-code/config.toml` — api_key, base_url, provider `type` — then re-run). These are
  configuration/environment problems, not code problems; do NOT roll back the code.
- MODEL / FORMAT → PLANNER (the chosen model alias does not resolve to a configured provider, or
  the request shape is wrong for that provider — re-read `providers.md` and fix the mapping).
- The retry budget for provider errors is INFRASTRUCTURE=3 (see §3).

## 2. Routing decision

After classification, decide who retries:

| Category | Route to | What happens |
|----------|----------|--------------|
| WRONG_RESULTS (without "regression") | DIAGNOSTICIAN | deep analysis needed |
| WRONG_RESULTS (with "regression") | CODER | code changed behavior incorrectly |
| INFRASTRUCTURE | auto-fix | run the auto-fix command, then re-run verification |
| COMPILE_ERROR / LINK_ERROR | CODER | coder fixes code with the error output |
| MISSING_FILE | BA | BA re-studied configs incorrectly |
| BAD_COMMAND | PLANNER | planner rewrites the verification command |
| TIMEOUT (test) | PLANNER | lighter verification command |
| TIMEOUT (other) | CODER | likely infinite loop / perf bug |
| RUNTIME_CRASH | CODER | fix the crash |
| ASSERTION | CODER | fix code to pass tests |
| PERMISSION | HUMAN | manual fix required |
| UNKNOWN | DIAGNOSTICIAN | fallback |

## 3. Retry budgets (deterministic policy)

| Role | Max retries before escalation |
|------|-------------------------------|
| CODER | 1 |
| BA | 2 |
| PLANNER | 2 |
| DIAGNOSTICIAN | 1 |
| ADVISOR | 1 |
| INFRASTRUCTURE | 3 |
| HUMAN | 0 (cannot auto-retry) |
<!-- factory-rule: retry-budgets begin -->
**Бюджеты ретраев (каноническая формулировка):** у каждой роли свой бюджет повторов — coder=1, ba=2, planner=2, diagnostician=1, advisor=1, infrastructure=3, reviewer=2; счётчики ведутся в `.code-factory/state/pipeline.yaml` (`retry_counters`). Исчерпанный бюджет не продлевается: прогон эскалируется по лестнице детерминированный regex → Diagnostician (LLM) → Advisor (LLM, secondary модель, контрастное семейство, бюджет 1) → Human (hitl) → FAILED с полным логом. Фабрика не зацикливается, не смягчает тесты ради зелёного прогона и не падает молча.
<!-- factory-rule: retry-budgets end -->

- Each retry increments the per-role counter in `.code-factory/state/pipeline.yaml`
  (`retry_counters.advisor` for the Advisor, §4.1).
- When a role's budget is exhausted → escalate to DIAGNOSTICIAN (append the attempt history);
  when the DIAGNOSTICIAN budget is exhausted and the fix still fails → escalate to the ADVISOR
  (§4.1), then to HUMAN.
- DIAGNOSTICIAN, after its analysis, RESETS the recommended role's counter to 0 and re-runs it
  with the diagnostic context (do NOT repeat the failed approach).

## 4. Diagnostician (LLM fallback)

When routing says DIAGNOSTICIAN (unknown errors, wrong business results, exhausted budgets):

1. Launch the `factory-diagnostician` subagent with:
   - the full error output (last ~3000 chars),
   - the failed role and attempt history,
   - the diagnostic pre-processing text (below).
2. The subagent returns a report: `root_cause`, `recommended_role` (coder | planner | ba |
   infrastructure | human), `recommended_action`, `context_for_retry`, `confidence`.
3. Main agent writes it to `.code-factory/logs/diagnostic.md`.
4. Route by `recommended_role`: coder → implement again; planner → re-plan; ba → re-analyze;
   human → ask the user; infrastructure → auto-fix.

### Diagnostic pre-processing (cheap, deterministic)
Before calling the LLM, run these cheap checks and include their results in the prompt:
- Was the command found? (BAD_COMMAND) — check `command not found`.
- Do referenced files exist? (MISSING_FILE) — check paths in the error.
- Did compilation succeed? (COMPILE_ERROR) — check for `error[E...]` / `cannot find`.
- Is the `.so`/binary present? (for compiled stacks) — `ls target/release/*.so`.
- Is it a wrong build order? (e.g. a later build overwrites the `.so` built with a feature flag).

This is the same trick the Python factory used; it makes the Diagnostician ~10x more reliable.

## 4.1 Advisor (second opinion, no edits)

When the DIAGNOSTICIAN has already spent its budget (1) and the recommended fix still fails — or
when the Diagnostician's own confidence is low / its recommendation contradicts the observed
behaviour — escalate once to the **Advisor**: a second, independent diagnosis before the user is
disturbed and before the run is allowed to fail.

- **Contrasting model family (P1.13).** The Advisor runs on a different model family from the one
  that produced the code/previous diagnosis (e.g. coder/diagnostician on Kimi K3 → advisor on
  `deepseek-flash`, and vice versa; see `references/providers.md` §5.1). A second opinion from the
  same family reproduces the same blind spots and is worth nothing.
- **No edits.** The Advisor is read-only: it never changes a file, never runs the fix and never
  re-runs the test suite. Its only output is an assessment.
- **Self-contained briefing** — the main agent hands it everything, because the Advisor has no run
  context of its own:
  1. the FULL error output (the archived log path plus the tail, `log_tail.py`), not a prose
     summary;
  2. the task goal and acceptance criteria that the run must satisfy;
  3. the attempt history — which roles ran, what each tried, what happened (from
     `.code-factory/logs/errors.md` and `diagnostic.md`);
  4. the Diagnostician's report as-is (`root_cause`, `recommended_role`, `recommended_action`,
     `confidence`), explicitly marked as a *claim to be checked*, not as a fact;
  5. the current diff / manifest, so it sees exactly what was changed.
- **Its verdict**: the machine-read `agreement` field (`agree | disagree` with the Diagnostician's
  route — `agree` = the same route still holds, `disagree` = the evidence points to another one;
  never implicit in the prose), `root_cause` (its own), `recommended_role`,
  `recommended_action`, `confidence`, plus a verbatim quote of the log fragment its reasoning rests
  on (the same quote discipline as `references/code-review.md` §2.1 — `verify_quotes.py` re-checks
  it). The main agent writes it to `.code-factory/logs/diagnostic.md` (appended, marked `advisor`)
  and then:
  - `agreement: agree` → run the recommended role once more with the combined context;
  - `agreement: disagree` → do NOT retry blindly: route to HUMAN (HITL) with both diagnoses side by
    side, or, in auto mode, stop the fix loop and record the disagreement in `report.md`.
- **Budget: advisor = 1 per root cause** (one escalation, never a loop of opinions), counted in
  `retry_counters.advisor` in `.code-factory/state/pipeline.yaml`.

## 5. Escalation ladder (never silent crash)

```
failure
   │
   ▼
1. Deterministic regex  ──────────────► ~90% of errors, 0 tokens
   │ (no pattern matched / role budget exhausted)
   ▼
2. Diagnostician (LLM, factory-diagnostician) ──► 1 LLM call, budget=1
   │ (fix still failing, or low confidence / contradictory recommendation)
   ▼
3. Advisor (second opinion, contrasting model family, no edits) ──► budget=1
   │ (agreement: agree → retry the recommended role once; disagree → next rung)
   ▼
4. HUMAN (HITL) ──► ask the user, show both diagnoses
   │
   ▼
5. FAILED ──► only when ALL budgets are exhausted; full report in
              .code-factory/logs/errors.md with the transition history
```

Budget guards: rung 1 costs nothing, rung 2 has budget 1, rung 3 has budget 1 (§4.1), rung 4 cannot
auto-retry, and rung 5 is reachable only when every budget above it is spent — so a stuck run
cannot loop, it escalates and finally fails loudly with a full log.
