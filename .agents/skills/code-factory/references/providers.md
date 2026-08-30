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
task.yaml `models.<role>` = <model alias>
        │  (the factory recognizes the vendor from the alias)
        ▼
~/.kimi-code/config.toml
  [providers.<vendor>]   → protocol type, base_url, api_key
  [models.<alias>]       → provider = <vendor>, model = <wire name>
        │
        ▼
sub-agent `.md` → `model_preference: primary|secondary`
        │  (resolved against default_model / [secondary_model].default_model)
        ▼
Kimi Code CLI sends the request to the vendor's API gateway
```

The factory never invents a vendor's endpoint; it relies on the documented `config.toml`
provider tables. When the `models` field names a Kimi or Qwen model, the factory must (a)
recognize the vendor, (b) point the user to the exact `config.toml` snippet below, and (c) route
any resulting errors per `references/error-routing.md` §1.1.

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

## 5. Binding roles to vendors

Roles are bound to models via `model_preference: primary|secondary` in each sub-agent `.md`,
resolved against `config.toml` (`default_model` + `[secondary_model].default_model`). To run a
specific role on Kimi K3 or Qwen, the user sets that alias in `default_model` /
`[secondary_model].default_model` (or lists it in the `[secondary_model].models` pool) and names
it in the task's `models` field. The factory records the actual model per role in
`.code-factory/state/pipeline.yaml` (`models_used`) for auditability.

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
