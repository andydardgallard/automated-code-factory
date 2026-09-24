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
        │   resolved against default_model / [secondary_model].default_model)
        ▼
Kimi Code CLI sends the request to the vendor's API gateway
```

The factory never invents a vendor's endpoint; it relies on the documented `config.toml`
provider tables. When the `models` field names a Kimi or Qwen model, the factory must (a)
recognize the vendor, (b) point the user to the exact `config.toml` snippet below, and (c) route
any resulting errors per `references/error-routing.md` §1.1. The model named in the task's matrix
is passed to the sub-agent explicitly (§5) — `model_preference` is only the fallback path.

## 2. Vendor detection (deterministic)

Match the model alias (case-insensitive) against these prefixes/patterns:

| Vendor | Provider `type` | Detection patterns |
|--------|-----------------|--------------------|
| Kimi / Moonshot | `kimi` | `kimi`, `k3`, `moonshot` |
| Qwen | `openai` | `qwen`, `qwq`, `dashscope` |

Any other alias (e.g. `deepseek-*`) is treated as an already-supported vendor and is untouched —
backward compatibility is preserved because the new rules only ADD rows, never rewrite existing
ones.

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

The task's `models` field IS the authoritative role → model matrix, and the main agent passes the
chosen model to each sub-agent **explicitly** — the current CLI supports an explicit model
parameter on the Agent tool:

```yaml
# task.yaml
models:
  coder: kimi-k3
  reviewer: deepseek-flash
  diagnostician: deepseek-flash
```

```
Agent(subagent_type: "factory-coder",        model: "kimi-k3",        ...)
Agent(subagent_type: "factory-code-reviewer", model: "deepseek-flash", ...)
```

- The explicit `model:` parameter is the primary mechanism. Any instruction stating "do NOT pass a
  concrete model name to the Agent tool (it is not supported)" is **outdated** and must be ignored:
  the CLI accepts the parameter, and without it every role silently falls back to the session
  defaults and the task's matrix is not honoured.
- `model_preference: primary|secondary` in each sub-agent `.md` is the **fallback** only — for
  roles the task's `models` matrix does not name. It resolves against `config.toml`
  (`default_model` + `[secondary_model].default_model`, or the `[secondary_model].models` pool),
  and it is never consulted for a role the matrix names.
- So running a specific role on Kimi K3 or Qwen is either a matrix entry (`models.<role>`) or, when
  the task has no matrix, an alias in `default_model` / `[secondary_model].default_model` (or the
  `[secondary_model].models` pool).
- The factory records the actual model per role in `.code-factory/state/pipeline.yaml`
  (`models_used`) for auditability.

### 5.1 Model diversity — generator ≠ judge (P1.13)

The coder and whoever judges the coder's work must not be the same model family. A reviewer running
on the generator's family shares its blind spots, so its `approve` is self-confirmation rather than
independent verification. "Family" = the vendor row detected in §2 (Kimi/Moonshot, Qwen,
DeepSeek, …); the `secondary_model` flag alone is not enough, since two aliases of one family are
still the same judge.

- Rule: `models.coder` family ≠ `models.reviewer` family; when the Diagnostician or the Advisor
  (`references/error-routing.md` §4/§4.1) is used, its family must likewise differ from the family
  that produced the code it diagnoses. A pairing verified on a real run: coder `kimi-k3` (Kimi),
  reviewer/advisor `deepseek-flash` (DeepSeek).
- **Pre-flight check (deterministic, zero LLM)**: before Phase 1 the main agent resolves the matrix
  (or the `model_preference` fallback when the task has no matrix) and compares the resolved
  families of coder vs reviewer/diagnostician. On a collision it records
  `models_warning: "coder and reviewer resolve to the same model family <family> (<aliases>)"` in
  `.code-factory/state/pipeline.yaml` and mirrors it in `report.md`.
- A collision is a **warning, not a blocker**: the run continues on the configured models, but the
  warning stays visible in `pipeline.yaml`/`report.md` so the task owner can widen the matrix. It
  is the same pre-flight slot that already reports a missing
  `KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1`.

### 5.2 Plan committee — the ONE exception to the task's matrix

The second planner of the plan committee (the `plan-committee` rule: hitl, double rejection of the
plan) is the ONLY role where the task's `models` matrix is NOT applied — the committee rule
OUTRANKS the matrix. Every other rule states "the role's model comes from the task's matrix" with
no exceptions; this is the single documented one, and it is narrower than it looks: only the
SECOND planner is affected, the first planner keeps its matrix value.

- The family is fixed by the rule, not by the matrix: the second planner always comes from a family
  CONTRASTING the first planner's (the same family test as §5.1), because the whole point of the
  committee is independent verification of a plan the user rejected twice. A matrix that puts both
  planners in one family is overridden — `models.planner: kimi-k3` (Kimi) ⇒ second planner
  `deepseek-flash` (DeepSeek), and vice versa.
- `model_preference` is NOT the answer either: the exception is resolved deterministically from the
  first planner's model alias (§2), never from `config.toml` defaults.
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
