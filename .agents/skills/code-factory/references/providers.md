# Model Providers (Kimi K3 / Qwen)

Goal: let the user choose models from different vendors per role through the task's `models`
field, while the factory routes each request to the correct vendor endpoint with the correct
authentication. Adding vendors is **strictly additive** — it must never break the routing of
already-configured models.

## 1. How routing actually works

The factory is instruction-driven and runs inside **Kimi Code CLI**. The CLI performs the real
HTTP calls; the factory's job is to map the `models` field to the correct provider configuration
and to surface the right vendor errors through the deterministic router.

The chain is:

```
task.yaml `models.<role>` = <model alias>     ← authoritative role→model matrix
        │  (the main agent passes it to the Agent tool as an explicit `model: <alias>`)
        │  (the factory recognizes the vendor from the alias)
        ▼
~/.kimi-code/config.toml
  [providers.<vendor>]   → protocol type, base_url, api_key
  [models.<alias>]       → provider = <vendor>, model = <wire name>
        │
        ▼
sub-agent `.md` → `model_preference: primary|secondary`    ← FALLBACK only
        │  (used when the task's `models` matrix does not name that role;
        │   the RESOLVER scripts/model_matrix.py picks that side's
        │   default_model / [secondary_model] default_model for the role)
        ▼
Kimi Code CLI sends the request to the vendor's API gateway
```

The factory never invents a vendor's endpoint; it relies on the documented `config.toml`
provider tables. When the `models` field names a Kimi or Qwen model, the factory must (a)
recognize the vendor, (b) point the user to the exact `config.toml` snippet below, and (c) route
any resulting errors per `references/error-routing.md` §1.1. The model named in the task's matrix
is passed to the sub-agent explicitly (§5) — `model_preference` is only the fallback path, and what it
falls back to is decided by the resolver `scripts/model_matrix.py`, never by prose.

## 2. Vendor detection (deterministic)

Match the model alias (case-insensitive) against these prefixes/patterns:

| Vendor | Provider `type` | Detection patterns |
|--------|-----------------|--------------------|
| Kimi / Moonshot | `kimi` | `kimi`, `moonshot`, `kimi-k3`, `kimi-code/k3`, `k3`, `kimi-k2` |
| DeepSeek | `deepseek` | `deepseek`, `deepseek-flash`, `deepseek-chat` |
| Qwen | `openai` | `qwen`, `qwq`, `dashscope`, `qwen-*`, `qwq-*`, `dashscope-*` |

Every alias the factory uses is claimed by one of these rows, so a family can be computed for every
role: `scripts/model_matrix.py family --model <alias>` is the implementation, and it fails loud on an
alias no row claims — there is no "other" bucket, because a bucket nobody can name would silently
accept a same-family pair. Routing for an alias outside these rows is untouched and backward
compatibility is preserved: the rows only ADD detection, they never rewrite an existing one.

## 3. Kimi (Kimi K3) — Moonshot AI

- Protocol: OpenAI-compatible, provider type `kimi`.
- Default base URL: `https://api.moonshot.ai/v1`
- Credential key names: `KIMI_API_KEY`, `KIMI_BASE_URL`
- Kimi K3 wire model name: `k3`

```toml
[providers.kimi]
type = "kimi"
base_url = "https://api.moonshot.ai/v1"
api_key = "sk-xxxxx"

[models."kimi-k3"]
provider = "kimi"
model = "k3"
max_context_size = 262144
capabilities = [ "thinking", "tool_use" ]
```

## 4. Qwen — Alibaba Cloud DashScope (OpenAI-compatible)

- Protocol: OpenAI Chat Completions, provider type `openai`.
- Base URL: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- Credential key names: `OPENAI_API_KEY`, `OPENAI_BASE_URL`
- Example wire model name: `qwen-max` (or any `qwen-*` alias in your ModelStudio plan)

```toml
[providers.qwen]
type = "openai"
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key = "sk-xxxxx"

[models."qwen-max"]
provider = "qwen"
model = "qwen-max"
max_context_size = 131072
capabilities = [ "thinking", "tool_use" ]
```

> Kimi Code CLI auto-handles the `reasoning_content` field and `reasoning_effort` injection for
> third-party reasoning models (DeepSeek, Qwen, etc.), so Qwen reasoning models work out of the
> box. If a gateway returns reasoning content under a non-standard field, set `reasoning_key` on
> the model alias.

## 5. Binding roles to vendors (explicit model per role)

The task's `models` field is the TASK MATRIX, and the model precedence has exactly two cases and no
third — `scripts/model_matrix.py` is the ONE implementation of it, pinned by
`scripts/test_model_precedence.py`. The main agent passes the chosen model to each sub-agent
**explicitly** — the current CLI supports an explicit model parameter on the Agent tool:

```yaml
# task.yaml
models:
  coder: kimi-k3
  gui_expert: kimi-k3       # generator-class: Web GUI implementation, same family as the coder
  reviewer: deepseek-flash
  diagnostician: deepseek-flash
```

```
Agent(subagent_type: "factory-coder",        model: "kimi-k3",        ...)
Agent(subagent_type: "factory-code-reviewer", model: "deepseek-flash", ...)
```

- **Case (a) — the task names the role**: that exact model is used, verbatim, and is NEVER
  substituted. A generator/judge family collision is a WARNING naming both roles and both models:
  the task is authoritative, so the run continues on the configured models.
- **Case (b) — the task does not name the role**: the model comes from the factory's DEFAULT
  MATRIX — `default_model` / `[secondary_model] default_model` in `config.toml`, selected by the
  role's `model_preference: primary|secondary` in `.agents/agents/sub-agents/<role>.md`. That lookup
  is performed by the RESOLVER (`scripts/model_matrix.py resolve`); `model_preference` selects a
  side, it resolves nothing by itself. On this path the generator≠judge rule IS enforced: a
  same-family coder/tester/gui_expert versus reviewer/diagnostician/advisor pair with either side
  taken from the default matrix is an ERROR naming the fix (widen `[secondary_model]` so the two
  families differ, or pin `models.<role>` in the task).
- **No third path**: the main agent never picks a model on its own, so an unnamed role goes to the
  default matrix and nowhere else. Omitting `model:` when launching a subagent is not a neutral
  choice — the Agent tool then runs the CLI's own default model, not the factory's choice — which is
  exactly why the resolver always passes an explicit model, for a task-matrix value AND for a
  default-matrix one.
- The factory records the actual model per role in `.code-factory/state/pipeline.yaml`
  (`models_used`) and confirms it from an ARTIFACT: `scripts/model_attribution.py` reads the CLI
  session wire and cross-checks the claim — a mismatch FAILS the run, a missing wire is DEGRADED.
- `models.gui_expert` (optional) names the model of the Web GUI specialist `factory-gui-expert`.
  Like `models.coder` it is GENERATOR-side (§5.1), so its family must differ from the
  reviewer/diagnostician/advisor family (§5.1 states where that is enforced and where it is only a
  warning); the model actually used is logged as `models_used.gui_expert`. A secondary-class model is
  enough for routine MCP-driven implementation when its MCP/media capabilities suffice.

### 5.1 Model diversity — generator ≠ judge (P1.13)

The coder and whoever judges the coder's work must not be the same model family. A reviewer running
on the generator's family shares its blind spots, so its `approve` is self-confirmation rather than
independent verification. "Family" = the vendor row detected in §2 (Kimi/Moonshot, Qwen,
DeepSeek, …); the `secondary_model` flag alone is not enough, since two aliases of one family are
still the same judge.

- Rule: `models.coder` family ≠ `models.reviewer` family — ENFORCED as an error on the default-matrix
  path and reported as the warning above on the task-matrix path; when the Diagnostician or the
  Advisor (`references/error-routing.md` §4/§4.1) is used, its family must likewise differ from the
  family that produced the code it diagnoses. A pairing verified on a real run: coder `kimi-k3`
  (Kimi), reviewer/advisor `deepseek-flash` (DeepSeek).
- `models.gui_expert` is GENERATOR-side, exactly like `models.coder`: the Web GUI specialist
  implements and the tester/reviewer judge its work, so the gui_expert family must differ from the
  reviewer/diagnostician/advisor family too. It does NOT need to differ from the coder family — both
  are generators. The pre-flight family check below therefore treats `coder` and `gui_expert` as one
  generator side.
- **The family check is one command (deterministic, zero LLM)**: `scripts/model_matrix.py` resolves
  every role and runs its `check_families` check over the resolved families of
  coder/tester/gui_expert versus reviewer/diagnostician/advisor. A same-family pair is a WARNING
  when both models come from the task's matrix — the task is authoritative, so the run continues on
  the configured models and the warning names both roles and both models — and an ERROR when either
  side comes from the default matrix, the message naming the fix. Either result is written to
  `.code-factory/state/pipeline.yaml` and mirrored in `report.md`; a missing
  `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1` is reported in the same pre-flight slot.
- **Who actually ran is proved by an artifact**: `scripts/model_attribution.py` reads the CLI session
  wire and compares it with `models_used` — `match` / `mismatch` / `degraded` per role, where a
  mismatch FAILS the run and a missing wire is DEGRADED (exit 3), never a silent green.

### 5.2 Plan committee — the ONE exception to the task's matrix

The second planner of the plan committee (the `plan-committee` rule: hitl, double rejection of the
plan) is the ONLY role where the task's `models` matrix is NOT applied — the committee rule
OUTRANKS the matrix. Every other role follows the two cases of §5 (the task matrix when it names the
role, the default matrix otherwise); this is the single documented exception, and it is narrower than
it looks: only the SECOND planner is affected, the first planner keeps its matrix value.

- The family is fixed by the rule, not by the matrix: the second planner always comes from a family
  CONTRASTING the first planner's (the same family test as §5.1), because the whole point of the
  committee is independent verification of a plan the user rejected twice. A matrix that puts both
  planners in one family is overridden — `models.planner: kimi-k3` (Kimi) ⇒ second planner
  `deepseek-flash` (DeepSeek), and vice versa.
- `model_preference` is NOT the answer either: the exception is resolved deterministically by
  `scripts/model_matrix.py committee_second_planner` from the first planner's model alias (§2) and a
  pool of candidates — never from `config.toml` defaults.
- As for every role, the model actually used is logged to `.code-factory/state/pipeline.yaml`
  (`models_used`) and `report.md`; the override is visible there, not silent.

## 6. Error handling

Provider-side failures (auth 401/403, rate limit 429, upstream 5xx, unknown model, malformed
request) are integrated into the deterministic router — see `references/error-routing.md` §1.1.
Auth/rate/upstream → INFRASTRUCTURE auto-fix (repair the provider config, no code rollback);
model/format → PLANNER (fix the alias → provider mapping). Budget: INFRASTRUCTURE=3.

## 7. Backward compatibility

- The existing `kimi` (managed OAuth) and `openai`/`deepseek` providers are untouched.
- New detection rows are additive; the factory only consults them when the alias matches a
  Kimi/Qwen pattern.
- Pre-existing `models` entries with deepseek/other aliases keep routing exactly as before.
- Passing the model explicitly to a sub-agent (§5) changes only HOW a role asks for its model; the
  alias → provider resolution in `config.toml` (`[providers.*]` / `[models.*]`) is unchanged, and
  a task without a `models` matrix keeps working through `model_preference` exactly as before.
